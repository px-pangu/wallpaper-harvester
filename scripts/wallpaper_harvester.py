#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 wallpaper_harvester.py · 万能壁纸扒取器（所见即所得）
================================================================================
 单文件 / 核心路径零第三方依赖 / Windows + macOS + Linux 通用

 五种抓取路径，覆盖一切「肉眼可见」的壁纸：
   1. url     静态抽取：DOM 全属性 + CSS + JS + JSON + 整页正则兜底
   2. render  本机 Chrome/Edge 无头渲染：复用你已登录的账号态 → VIP/登录墙也能抓，还能像素级截图
   3. carve   缓存雕刻：对任意目录按魔数抠出图片/视频（桌面端壁纸软件缓存、浏览器 Cache 通吃）
   4. api     接口批量：内置元气壁纸公开接口 + 通用 JSON 分页接口
   5. browser 可选增强：装了 playwright 时可用（真浏览器滚动/拦截网络），没装自动降级为 render

 用法速查：
   python wallpaper_harvester.py url     https://example.com/wallpapers -o ./out
   python wallpaper_harvester.py render  https://vip.site.com/album --screenshot --depth 2
   python wallpaper_harvester.py carve   "D:\\元气壁纸缓存" -o ./out
   python wallpaper_harvester.py api     yuanqi --cid 1 --pages 8 --sort 2
   python wallpaper_harvester.py api     json --endpoint https://x/api/list --payload '{"page":{page}}' --json-path data.list
   python wallpaper_harvester.py selftest

 免责声明：本工具仅用于采集你本机已可正常浏览、拥有合法使用权的内容供个人使用。
           请勿用于抓取、传播他人付费内容或违反站点服务条款的行为。
================================================================================
"""

# ==============================================================================
# 0. 模块头 / 导入
# ==============================================================================
import argparse
import gzip
import hashlib
import html
import json
import os
import random
import re
import shutil
import sqlite3
import string
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
from html.parser import HTMLParser
from datetime import datetime

VERSION = "1.0.0"

# 终端编码兜底：避免 Windows GBK 控制台下中文日志炸掉
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

IMAGE_EXT = {"jpg", "jpeg", "png", "webp", "avif", "bmp", "gif", "tif", "tiff", "jfif"}
VIDEO_EXT = {"mp4", "webm", "mov", "m4v", "mkv", "flv", "avi", "ts", "m3u8"}
MEDIA_EXT = IMAGE_EXT | VIDEO_EXT

# 资源关键词：路径/查询里出现这些词，说明大概率是壁纸资源
RESOURCE_HINT = re.compile(
    r"(wallpaper|wall|photo|pic|image|img|banner|cover|orig|origin|raw|source|full|large|big|"
    r"hd|fhd|uhd|2k|4k|8k|\d{3,4}x\d{3,4}|1920|2560|3840|7680|1080|2160|4096|screen|bg|bgimg|"
    r"desktop|preview|thumb|show|view|file|attach|upload)", re.I)

# 垃圾关键词：命中即丢弃（配合尺寸过滤双保险）
GARBAGE_HINT = re.compile(
    r"(favicon|logo|icon|sprite|qrcode|qr_|avatar|headimg|placeholder|default_?img|"
    r"loading|spinner|emoji|badge|btn_|button|arrow|share_|wechat|weibo|qq_|alipay|"
    r"1x1|pixel\.|spacer|blank\.(gif|png)|advert|ad_|tracking|beacon)", re.I)

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
]

VERBOSE = False
_LOCK = threading.Lock()


# ==============================================================================
# 1. 基础设施：日志 / 文件工具
# ==============================================================================
def log(msg, tag="信息", force=False):
    if not VERBOSE and not force and tag in ("调试",):
        return
    prefix = {"信息": "[·]", "发现": "[发现]", "升级": "[升级]", "下载": "[下载]",
              "跳过": "[跳过]", "完成": "[完成]", "警告": "[警告]", "错误": "[错误]",
              "调试": "[调试]"}.get(tag, "[·]")
    with _LOCK:
        print(f"{prefix} {msg}", flush=True)


def ensure_dir(p):
    os.makedirs(p, exist_ok=True)
    return p


def human_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{int(n)}B"
        n /= 1024
    return f"{n:.1f}GB"


def safe_name(s, maxlen=90):
    s = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", s or "")
    s = re.sub(r"\s+", " ", s).strip().strip(".")
    return (s[:maxlen] or "unnamed")


def url_host(u):
    try:
        return urllib.parse.urlparse(u).netloc
    except Exception:
        return "unknown"


def sha1_bytes(b):
    return hashlib.sha1(b).hexdigest()


def now_stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def file_sha1(path, chunk=1 << 20):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def atomic_write(path, data_iter, total=0):
    """临时文件写入 + os.replace 原子落盘，绝不留下半截文件"""
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        for chunk in data_iter:
            f.write(chunk)
    os.replace(tmp, path)
    return os.path.getsize(path)


def resume_write(path, data_iter):
    """断点续传：已存在 .part 时接着写"""
    tmp = path + ".part"
    exist = os.path.getsize(tmp) if os.path.exists(tmp) else 0
    mode = "ab" if exist else "wb"
    with open(tmp, mode) as f:
        for chunk in data_iter:
            f.write(chunk)
    return os.path.getsize(tmp)


# ==============================================================================
# 2. Fetcher：urllib 封装（gzip/deflate、UA、Referer、重试、Range）
# ==============================================================================
def ascii_safe(v):
    """HTTP 头必须是 latin-1 可编码，中文 Referer 等会让 urllib 抛 UnicodeEncodeError"""
    if isinstance(v, bytes):
        return v.decode("latin-1", "ignore")
    try:
        v.encode("latin-1")
        return v
    except Exception:
        return v.encode("ascii", "ignore").decode("ascii")


class Fetcher:
    def __init__(self, timeout=20, delay=0.2, ua=None, cookie=None, headers=None, referer=None):
        self.timeout = timeout
        self.delay = delay
        self.ua = ua or random.choice(UA_POOL)
        self.cookie = cookie
        self.extra_headers = headers or {}
        self.referer = referer
        self._last = 0.0

    def _throttle(self):
        gap = time.time() - self._last
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self._last = time.time()

    def _build(self, url, extra=None, rng=None, method=None, body=None):
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("User-Agent", self.ua)
        req.add_header("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,"
                                 "image/avif,image/webp,image/apng,image/*,*/*;q=0.8")
        req.add_header("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8")
        req.add_header("Accept-Encoding", "gzip, deflate")
        req.add_header("Connection", "keep-alive")
        if self.cookie:
            req.add_header("Cookie", self.cookie)
        if self.referer:
            req.add_header("Referer", self.referer)
        for k, v in self.extra_headers.items():
            req.add_header(k, ascii_safe(v))
        if rng:
            req.add_header("Range", rng)
        for k, v in (extra or {}).items():
            req.add_header(k, ascii_safe(v))
        return req

    @staticmethod
    def _decode(resp, raw):
        enc = (resp.headers.get("Content-Encoding") or "").lower()
        if enc == "gzip":
            try:
                return gzip.decompress(raw)
            except Exception:
                return raw
        if enc == "deflate":
            try:
                return zlib.decompress(raw, -zlib.MAX_WBITS)
            except Exception:
                try:
                    return zlib.decompress(raw)
                except Exception:
                    return raw
        return raw

    def request(self, url, extra=None, rng=None, method=None, body=None,
                retries=3, referer=None, stream=False):
        """返回 (status, headers, body_bytes) 或 stream=True 时 (status, headers, resp_obj)"""
        last_err = None
        for attempt in range(retries):
            try:
                self._throttle()
                headers = dict(extra or {})
                if referer:
                    headers["Referer"] = referer
                req = self._build(url, headers, rng, method, body)
                resp = urllib.request.urlopen(req, timeout=self.timeout)
                if stream:
                    return resp.status, resp.headers, resp
                raw = resp.read()
                return resp.status, resp.headers, self._decode(resp, raw)
            except urllib.error.HTTPError as e:
                last_err = e
                # 403/429/503：换 UA 退避重试
                if e.code in (403, 429, 503) and attempt < retries - 1:
                    self.ua = random.choice(UA_POOL)
                    time.sleep(1.2 * (attempt + 1))
                    continue
                if stream:
                    return e.code, e.headers, None
                return e.code, e.headers, b""
            except Exception as e:
                last_err = e
                if attempt < retries - 1:
                    time.sleep(0.8 * (attempt + 1))
                    continue
        log(f"请求失败 {url[:110]} → {type(last_err).__name__}", "警告")
        return 0, {}, (None if stream else b"")

    def get(self, url, **kw):
        return self.request(url, **kw)

    def head_probe(self, url, referer=None):
        """Range 探测：只取前 64KB 判断尺寸与总大小，省流量"""
        st, hd, body = self.request(url, rng="bytes=0-65535", referer=referer, stream=True)
        if not body:
            return None
        try:
            data = body.read(65536)
        except Exception:
            return None
        finally:
            try:
                body.close()
            except Exception:
                pass
        total = None
        cr = hd.get("Content-Range") or ""
        m = re.search(r"/(\d+)\s*$", cr)
        if m:
            total = int(m.group(1))
        elif hd.get("Content-Length") and st == 200:
            total = int(hd.get("Content-Length"))
        return {"status": st, "type": hd.get("Content-Type", ""), "head": data,
                "size": total if total else len(data)}


# ==============================================================================
# 3. HTMLExtractor：DOM 全属性 + CSS + JS + JSON + 整页正则
# ==============================================================================
class _DomParser(HTMLParser):
    """收集所有标签的所有属性，以及 <style>/<script> 的文本内容"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.attrs = []          # [(tag, attr, value)]
        self.styles = []         # <style> 文本
        self.scripts = []        # <script> 文本
        self.links = []          # 所有 href / src
        self._cur = None

    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if v:
                self.attrs.append((tag, k, v))
        self._cur = tag

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self._cur = None

    def handle_data(self, data):
        if self._cur == "style" and data.strip():
            self.styles.append(data)
        if self._cur == "script" and data.strip():
            self.scripts.append(data)


IMG_ATTRS = ("src", "data-src", "data-original", "data-lazy-src", "data-echo", "data-url",
             "data-bg", "data-image", "data-href", "data-full", "data-origin",
             "data-srcset", "srcset", "data-source", "data-img", "data-wallpaper",
             "data-preview", "poster", "background", "content", "url", "href")

DETAIL_HINT = re.compile(
    r"(detail|item|wallpaper|photo|pic|works?|post|view|show|desk|album|image|img|"
    r"/p/|/d/|/w/|topic|gallery)", re.I)


def normalize_url(u, page_url):
    """还原被转义/编码的 URL，并补全为绝对地址"""
    if not u:
        return None
    u = u.strip().strip("'\"").strip()
    u = u.replace("\\/", "/").replace("\\u002F", "/").replace("\\u002f", "/")
    u = u.replace("&amp;", "&")
    if u.startswith("data:") or u.startswith("javascript:") or u.startswith("about:"):
        return None
    if u.startswith("//"):
        u = "https:" + u
    try:
        u = urllib.parse.unquote(u, errors="ignore")
    except Exception:
        pass
    if u.startswith("http"):
        return u
    if u.startswith("/") or u.startswith("./") or u.startswith("../"):
        return urllib.parse.urljoin(page_url, u)
    if re.match(r"^[\w\-\.]+\.(jpg|jpeg|png|webp|gif|bmp|mp4|webm)", u, re.I):
        return urllib.parse.urljoin(page_url, u)
    return None


def clean_candidate(u):
    """清洗 URL 尾部的引号、转义、括号等脏字符"""
    if not u:
        return None
    u = re.split(r"[\s'\"<>()\[\]{}]+$", u)[0]
    u = u.rstrip("\\/,;")
    return u if len(u) > 12 else None


def looks_like_media(u):
    ext = ""
    m = re.search(r"\.(jpg|jpeg|png|webp|avif|bmp|gif|mp4|webm|mov|m4v|mkv)(?=[?#]|$)", u, re.I)
    if m:
        ext = m.group(1).lower()
        return ext in MEDIA_EXT
    return False


def is_probable_resource(u):
    """无明显扩展名时，靠关键词 + CDN 域名判断"""
    if looks_like_media(u):
        return True
    if RESOURCE_HINT.search(u):
        return True
    host = url_host(u).lower()
    if any(k in host for k in ("img", "pic", "cdn", "static", "wall", "photo", "image",
                               "oss", "cos.", "qiniu", "qbox", "aliyun", "upyun", "biliimg",
                               "hdslb", "baofun", "zhhainiao", "yuanqi", "sinaimg", "gtimg",
                               "bdimg", "bdstatic", "httppic", "douyin", "huaban", "pstatp")):
        return True
    return False


def is_garbage(u):
    return bool(GARBAGE_HINT.search(u))


class HTMLExtractor:
    """输入 HTML 原文 + 页面 URL，输出候选资源 URL 与详情页链接"""

    def __init__(self, page_url):
        self.page_url = page_url
        self.candidates = set()
        self.detail_links = set()

    def _add(self, u, source):
        u = normalize_url(u, self.page_url)
        u = clean_candidate(u)
        if not u or not u.startswith("http"):
            return
        if is_garbage(u):
            return
        if is_probable_resource(u):
            self.candidates.add(u)

    def _add_detail(self, u):
        u = normalize_url(u, self.page_url)
        if not u or not u.startswith("http"):
            return
        if url_host(u) != url_host(self.page_url):
            return
        if u.rstrip("/") == self.page_url.rstrip("/"):
            return
        if looks_like_media(u):
            return
        if DETAIL_HINT.search(u):
            self.detail_links.add(u.split("#")[0])

    def parse(self, text):
        # ---- 3.1 DOM 全属性 ----
        p = _DomParser()
        try:
            p.feed(text)
        except Exception:
            pass
        for tag, attr, val in p.attrs:
            low_attr = attr.lower()
            if low_attr in IMG_ATTRS or low_attr.endswith(("src", "url", "image", "href", "bg")) \
                    or low_attr.startswith("data-"):
                if attr.lower() in ("srcset", "data-srcset"):
                    # srcset: "url 1x, url 2x" / "url 400w"
                    for part in re.split(r",(?=\s*https?:|//|\./|/)", val):
                        self._add(part.split()[0] if part.split() else part, "srcset")
                else:
                    self._add(val, f"dom:{tag}.{attr}")
            if tag.lower() == "a" and attr.lower() == "href":
                self._add_detail(val)

        # ---- 3.2 <style> / 内联 style 中的 url() ----
        for css in p.styles + re.findall(r'style\s*=\s*"([^"]{0,4000})"', text, re.I):
            for m in re.finditer(r"url\((['\"]?)(.*?)\1\)", css, re.I | re.S):
                self._add(m.group(2), "css")

        # ---- 3.3 <script> 中的 JSON / 字符串 ----
        for js in p.scripts:
            for m in re.finditer(r"https?://[^\s'\"\\]+|//[a-z0-9\.\-]+\.[a-z]{2,}/[^\s'\"\\]+", js):
                self._add(m.group(0), "js")
            for m in re.finditer(r'["\']((?:https?:)?//[^"\']{10,400}\.(?:jpg|jpeg|png|webp|gif|bmp|mp4|webm|mov)[^"\']*)["\']', js, re.I):
                self._add(m.group(1), "js-string")

        # ---- 3.4 JSON-LD / 内嵌 JSON ----
        for m in re.finditer(r'<script[^>]*type=["\']application/(?:ld\+)?json["\'][^>]*>(.*?)</script>', text, re.I | re.S):
            self._walk_json(m.group(1))

        # ---- 3.5 整页正则兜底（含转义） ----
        raw = text.replace("\\/", "/").replace("\\u002F", "/")
        for m in re.finditer(r'(?:https?:)?//[^\s"\'<>\\\)\(]+?\.(?:jpg|jpeg|png|webp|avif|bmp|gif|mp4|webm|mov|m4v)(?:\?[^\s"\'<>\\]*)?', raw, re.I):
            self._add(m.group(0), "regex")
        for m in re.finditer(r'https?://[^\s"\'<>\\\)\(]{20,500}', raw):
            u = m.group(0)
            if is_probable_resource(u):
                self._add(u, "regex-hint")

        # ---- 3.6 详情页链接兜底 ----
        for m in re.finditer(r'href=["\']([^"\']{5,300})["\']', text, re.I):
            self._add_detail(m.group(1))

        return sorted(self.candidates), sorted(self.detail_links)

    def _walk_json(self, blob):
        try:
            data = json.loads(blob.strip())
        except Exception:
            for m in re.finditer(r'https?://[^"\']{10,400}\.(?:jpg|jpeg|png|webp|mp4|webm)', blob, re.I):
                self._add(m.group(0), "json-regex")
            return
        stack = [data]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                for v in cur.values():
                    stack.append(v)
            elif isinstance(cur, list):
                for v in cur:
                    stack.append(v)
            elif isinstance(cur, str) and 12 < len(cur) < 500:
                if re.match(r"^(https?:)?//", cur) or "/static/" in cur or "/upload" in cur:
                    self._add(cur, "json")


# ==============================================================================
# 4. Upgrader：生成高清变体并探测取最大
# ==============================================================================
UPGRADE_RULES = [
    (re.compile(r"([?&](?:w|width)=)(\d{2,4})", re.I), lambda m: m.group(1) + "3840"),
    (re.compile(r"([?&](?:h|height)=)(\d{2,4})", re.I), lambda m: m.group(1) + "2160"),
    (re.compile(r"(/w/)(\d{2,4})"), lambda m: m.group(1) + "3840"),
    (re.compile(r"/(\d{2,4})x(\d{2,4})(?=/|\.|$)"), lambda m: "/3840x2160"),
    (re.compile(r"imageView2/\d+/w/\d+/h/\d+", re.I), lambda m: "imageView2/0/w/3840/h/2160"),
    (re.compile(r"imageMogr2/thumbnail/\d+x\d*", re.I), lambda m: "imageMogr2/thumbnail/3840x"),
    (re.compile(r"image/resize,[^/]*w_\d+", re.I), lambda m: "image/resize,w_4096"),
    (re.compile(r"x-oss-process=[^&]*", re.I), lambda m: ""),
    (re.compile(r"_\d{2,4}x\d{2,4}(?=\.(jpg|jpeg|png|webp|gif|bmp))", re.I), lambda m: "_3840x2160"),
    (re.compile(r"[-_@](?:s|m|l|small|middle|thumb)?\d{2,4}(?=[._])"), lambda m: "_3840"),
    (re.compile(r"/(small|thumb|thumbnail|preview|middle|mid|mini|s\d{2,4}|w\d{2,4})/", re.I),
     lambda m: "/large/"),
    (re.compile(r"\.(webp)(\?|$)", re.I), lambda m: ".jpg" + (m.group(2) or "")),
    (re.compile(r"[!~]\w*\d{2,4}x?\d{0,4}$"), lambda m: ""),
    (re.compile(r"\?(?:.*&)?(?:w|width|h|height|q|quality|size|s)=\d+.*$", re.I), lambda m: ""),
]

SIZE_TOKEN = re.compile(r"(\d{3,4})[x*_](\d{3,4})")


class Upgrader:
    def __init__(self, fetcher, workers=6, enabled=True):
        self.f = fetcher
        self.workers = workers
        self.enabled = enabled

    @staticmethod
    def variants(u):
        """基于规则生成候选原图 URL（去重、保持原 URL 在最前）"""
        out, seen = [], {u}
        for pat, rep in UPGRADE_RULES:
            try:
                new = pat.sub(rep, u)
            except Exception:
                continue
            new = re.sub(r"(?<=[?&])$", "", new).rstrip("?&=")
            if new and new not in seen and len(new) > 12 and new != u:
                seen.add(new)
                out.append(new)
        # 去查询串版本（很多 CDN 去掉参数即为原图）
        base = u.split("?")[0]
        if base != u and base not in seen:
            seen.add(base)
            out.append(base)
        return out

    def _score(self, url):
        probe = self.f.head_probe(url)
        if not probe or not probe.get("head"):
            return None
        w, h = sniff_size(probe["head"])
        size = probe.get("size") or 0
        is_media = (probe.get("type", "").startswith(("image", "video"))) or w > 0
        if not is_media and size < 20000:
            return None
        return {"url": url, "size": size, "w": w or 0, "h": h or 0}

    def best(self, url):
        """返回 (best_url, info)；探测全部失败时回退原 URL"""
        if not self.enabled:
            return url, {"url": url, "size": 0, "w": 0, "h": 0}
        cands = [url] + self.variants(url)[:5]
        results = []
        with ThreadPoolExecutor(max_workers=min(6, len(cands))) as ex:
            futs = {ex.submit(self._score, c): c for c in cands}
            for fu in as_completed(futs):
                r = fu.result()
                if r:
                    results.append(r)
        if not results:
            return url, {"url": url, "size": 0, "w": 0, "h": 0}
        results.sort(key=lambda r: (r["size"], r["w"] * r["h"]), reverse=True)
        best = results[0]
        if best["url"] != url:
            log(f"{url[:80]} → {best['url'][:80]} ({human_size(best['size'])})", "升级")
        return best["url"], best


# ==============================================================================
# 5. Sniffer：纯标准库魔数识别 + 宽高解析（免 PIL）
# ==============================================================================
def sniff_format(head):
    if head[:3] == b"\xff\xd8\xff":
        return "jpg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:2] == b"BM":
        return "bmp"
    if head[4:8] == b"ftyp":
        return "mp4"
    if head[:4] == b"\x00\x00\x00\x18" and b"ftyp" in head[:32]:
        return "mp4"
    if head[:3] == b"ID3" or head[:2] in (b"\xff\xfb", b"\xff\xf3"):
        return "mp3"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    return None


def _jpeg_size(data):
    i = 2
    n = len(data)
    while i < n - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0xD9, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seglen = struct.unpack(">H", data[i + 2:i + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        if seglen < 2:
            break
        i += 2 + seglen
    return 0, 0


def _png_size(data):
    if len(data) >= 24:
        w, h = struct.unpack(">II", data[16:24])
        return w, h
    return 0, 0


def _gif_size(data):
    if len(data) >= 10:
        w, h = struct.unpack("<HH", data[6:10])
        return w, h
    return 0, 0


def _webp_size(data):
    if len(data) < 30:
        return 0, 0
    fmt = data[12:16]
    if fmt == b"VP8X":
        # RIFF 容器内的 24-bit 画布宽高为小端存储，且存的是 (实际值 - 1)
        w = 1 + int.from_bytes(data[24:27], "little")
        h = 1 + int.from_bytes(data[27:30], "little")
        return w, h
    if fmt == b"VP8 ":
        i = data.find(b"\x9d\x01\x2a", 20)
        if i > 0 and i + 8 <= len(data):
            w = int.from_bytes(data[i + 3:i + 5], "little") & 0x3FFF
            h = int.from_bytes(data[i + 5:i + 7], "little") & 0x3FFF
            return w, h
    if fmt == b"VP8L":
        try:
            bits = int.from_bytes(data[21:25], "little")
            w = (bits & 0x3FFF) + 1
            h = ((bits >> 14) & 0x3FFF) + 1
            return w, h
        except Exception:
            return 0, 0
    return 0, 0


def _bmp_size(data):
    if len(data) >= 26:
        w, h = struct.unpack("<ii", data[18:26])
        return abs(w), abs(h)
    return 0, 0


def _mp4_size(data):
    """从 tkhd 里取最大宽高（需 moov 落在数据内）"""
    best = (0, 0)
    start = 0
    while True:
        i = data.find(b"tkhd", start)
        if i < 0 or i + 92 > len(data):
            break
        try:
            ver = data[i + 4]
            off = i + 4 + (20 if ver == 1 else 12) + 60
            w = struct.unpack(">I", data[off:off + 4])[0] >> 16
            h = struct.unpack(">I", data[off + 4:off + 8])[0] >> 16
            if w * h > best[0] * best[1]:
                best = (w, h)
        except Exception:
            pass
        start = i + 4
    return best


def sniff_size(data):
    fmt = sniff_format(data)
    if fmt == "jpg":
        return _jpeg_size(data)
    if fmt == "png":
        return _png_size(data)
    if fmt == "gif":
        return _gif_size(data)
    if fmt == "webp":
        return _webp_size(data)
    if fmt == "bmp":
        return _bmp_size(data)
    if fmt in ("mp4", "webm"):
        return _mp4_size(data)
    return 0, 0


EXT_BY_FMT = {"jpg": "jpg", "png": "png", "gif": "gif", "webp": "webp",
              "bmp": "bmp", "mp4": "mp4", "webm": "webm", "mp3": "mp3"}


# ==============================================================================
# 6. Downloader：并发 / 重试 / 续传 / 去重 / 过滤 / 落盘
# ==============================================================================
class Harvest:
    """全局产出上下文：目录、清单、去重集合"""

    def __init__(self, out_dir, min_w=1280, min_h=720, min_kb=80, max_files=200,
                 dry=False, gallery=True):
        self.out = ensure_dir(out_dir)
        self.img_dir = ensure_dir(os.path.join(self.out, "images"))
        self.vid_dir = ensure_dir(os.path.join(self.out, "video"))
        self.carve_dir = ensure_dir(os.path.join(self.out, "carve"))
        self.shot_dir = ensure_dir(os.path.join(self.out, "screenshots"))
        self.min_w, self.min_h = min_w, min_h
        self.min_bytes = int(min_kb * 1024)
        self.max_files = max_files
        self.dry = dry
        self.gallery = gallery
        self.rows = []
        self.seen_url = set()
        self.seen_sha = set()
        self.seen_file = os.path.join(self.out, "seen.txt")
        self.count = 0
        self.next_slot = 1
        self.stats = {"candidate": 0, "pass": 0, "ok": 0, "dup": 0, "skip": 0, "fail": 0,
                      "bytes": 0}
        if os.path.exists(self.seen_file):
            try:
                with open(self.seen_file, "r", encoding="utf-8") as f:
                    for line in f:
                        self.seen_sha.add(line.strip())
            except Exception:
                pass

    def _remember(self, sha):
        self.seen_sha.add(sha)
        try:
            with open(self.seen_file, "a", encoding="utf-8") as f:
                f.write(sha + "\n")
        except Exception:
            pass

    def _subdir(self, fmt):
        return self.vid_dir if fmt in ("mp4", "webm", "mp3", "m3u8") else self.img_dir

    def record(self, path, fmt, w, h, size, sha, src_url, page):
        self.rows.append({
            "file": os.path.relpath(path, self.out).replace("\\", "/"),
            "type": "video" if fmt in ("mp4", "webm") else "image",
            "w": w, "h": h, "size": size, "sha1": sha,
            "url": src_url, "page": page,
        })


class Downloader:
    def __init__(self, fetcher, harvest, workers=8, keep_video=True, strict_magic=False):
        self.f = fetcher
        self.h = harvest
        self.workers = workers
        self.keep_video = keep_video
        self.strict_magic = strict_magic

    def _fetch_one(self, url, page, slot=0):
        st = self.h.stats
        st["candidate"] += 1
        if url in self.h.seen_url:
            st["dup"] += 1
            return None
        self.h.seen_url.add(url)
        # 名额控制统一由 _task 的占位机制负责，此处不再重复判断

        # 阶段一：Range 探测前 256KB，先判格式与尺寸，不合格直接放弃（省流量）
        probe = self.f.head_probe(url, referer=page)
        if not probe or not probe.get("head"):
            st["fail"] += 1
            log(f"无法探测 {url[:90]}", "跳过")
            return None
        head = probe["head"]
        fmt = sniff_format(head)
        if (not fmt or fmt not in EXT_BY_FMT) and not self.strict_magic:
            # 兜底：服务器明确声明是媒体（可能是加密/混淆流、冷门封装），按 Content-Type 落盘
            ctype = (probe.get("type") or "").lower()
            if ctype.startswith(("image/", "video/")):
                sub = ctype.split("/")[1].split(";")[0].strip()
                sub = {"jpeg": "jpg", "jpg": "jpg", "png": "png", "webp": "webp",
                       "gif": "gif", "bmp": "bmp", "mp4": "mp4", "webm": "webm"}.get(sub)
                if sub in EXT_BY_FMT:
                    fmt = sub
                    log(f"按 Content-Type 落盘（魔数不匹配，可能是加密/混淆流）{url[:70]}", "警告")
        if not fmt or fmt not in EXT_BY_FMT:
            st["skip"] += 1
            log(f"非媒体 {url[:90]} ({probe.get('type', '?')})", "跳过")
            return None
        if fmt in ("mp4", "webm") and not self.keep_video:
            st["skip"] += 1
            return None
        w, hgt = sniff_size(head)
        total = probe.get("size") or 0
        is_video = fmt in ("mp4", "webm")
        if not is_video:
            if total and total < self.h.min_bytes:
                st["skip"] += 1
                log(f"过小 {human_size(total)} {url[:80]}", "跳过")
                return None
            if w and hgt and (w < self.h.min_w or hgt < self.h.min_h):
                st["skip"] += 1
                log(f"分辨率不足 {w}x{hgt} {url[:80]}", "跳过")
                return None
        st["pass"] += 1

        if self.h.dry:
            log(f"[DRY] {fmt} {w}x{hgt} {human_size(total)} {url[:90]}", "发现")
            st["ok"] += 1
            return {"dry": True}

        # 文件名编号（名额已在 _task 中占位，此处不再自增）
        name_seed = safe_name(os.path.splitext(urllib.parse.urlparse(url).path.split("/")[-1])[0])
        tag = f"{url_host(url).replace(':', '_')}_{slot or self.h.count:04d}"
        if not name_seed or len(name_seed) < 3 or name_seed.startswith("_"):
            name_seed = tag
        else:
            name_seed = f"{tag}_{name_seed}"[:100]
        tmp_path = os.path.join(self.h._subdir(fmt), f"{name_seed}.{EXT_BY_FMT[fmt]}")

        rng = f"bytes={os.path.getsize(tmp_path + '.part')}-" if os.path.exists(tmp_path + ".part") else None
        rstatus, rheaders, resp = self.f.request(url, referer=page, rng=rng, stream=True)
        if not resp:
            st["fail"] += 1
            log(f"下载失败 {url[:90]}", "错误")
            return None

        def chunks():
            while True:
                b = resp.read(65536)
                if not b:
                    break
                yield b

        try:
            if rstatus == 206 and os.path.exists(tmp_path + ".part"):
                resume_write(tmp_path, chunks())
            else:
                # 删除动作做容错：被占用/被安全策略拦截时直接用覆盖写，绝不中断主流程
                try:
                    if os.path.exists(tmp_path + ".part"):
                        os.remove(tmp_path + ".part")
                except Exception:
                    pass
                atomic_write(tmp_path, chunks())
        except Exception as e:
            st["fail"] += 1
            log(f"写盘失败 {type(e).__name__} {url[:80]}", "错误")
            return None
        finally:
            try:
                resp.close()
            except Exception:
                pass

        size = os.path.getsize(tmp_path)
        if size < 1024:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            st["fail"] += 1
            return None
        sha = file_sha1(tmp_path)
        if sha in self.h.seen_sha:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            st["dup"] += 1
            log(f"重复内容 {url[:80]}", "跳过")
            return None
        self.h._remember(sha)
        if w == 0 or hgt == 0:
            with open(tmp_path, "rb") as fp:
                w, hgt = sniff_size(fp.read(262144))
                if w == 0 and fmt in ("mp4", "webm"):
                    # moov 在文件尾的情况：读尾部再试一次
                    fp.seek(max(0, os.path.getsize(tmp_path) - 262144))
                    w, hgt = sniff_size(fp.read())
        final = os.path.join(self.h._subdir(fmt),
                             f"{tag}_{w}x{hgt}_{sha[:8]}.{EXT_BY_FMT[fmt]}")
        if final != tmp_path:
            try:
                os.replace(tmp_path, final)
            except Exception:
                final = tmp_path
        st["ok"] += 1
        st["bytes"] += size
        self.h.record(final, fmt, w, hgt, size, sha, url, page)
        log(f"{EXT_BY_FMT[fmt].upper()} {w}x{hgt} {human_size(size)} → {os.path.basename(final)}", "下载")
        return final

    def _task(self, url, page):
        """名额占位：进入探测前先占一个名额，失败/跳过时归还，保证 --max 精确生效"""
        global _LOCK
        with _LOCK:
            if self.h.count >= self.h.max_files:
                self.h.stats["skip"] += 1
                return None
            self.h.count += 1
            slot = self.h.next_slot
            self.h.next_slot += 1
        try:
            r = self._fetch_one(url, page, slot)
            if r is None:
                with _LOCK:
                    self.h.count -= 1
            return r
        except Exception:
            with _LOCK:
                self.h.count -= 1
            raise

    def run(self, urls, page="<direct>"):
        """urls: List[str] 或 List[(url, page)]；滑动窗口提交，失败自动补位，成功达上限即停"""
        jobs = []
        for item in urls:
            if isinstance(item, (tuple, list)):
                jobs.append((item[0], item[1]))
            else:
                jobs.append((item, page))
        it = iter(jobs)
        window = max(self.workers, 4)
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            pending = set()
            for _ in range(min(window, len(jobs))):
                try:
                    u, p = next(it)
                except StopIteration:
                    break
                pending.add(ex.submit(self._task, u, p))
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for fu in done:
                    try:
                        fu.result()
                    except Exception as e:
                        log(f"任务异常 {type(e).__name__}: {e}", "错误")
                        self.h.stats["fail"] += 1
                if self.h.stats["ok"] >= self.h.max_files:
                    for f2 in pending:
                        f2.cancel()
                    log(f"已达上限 {self.h.max_files} 个，停止采集", "完成")
                    break
                # 在途任务不足时继续补位（失败归还的名额会被复用）
                while len(pending) < window and self.h.count < self.h.max_files:
                    try:
                        u, p = next(it)
                    except StopIteration:
                        break
                    pending.add(ex.submit(self._task, u, p))
        return self.h


# ==============================================================================
# 7. ChromeRenderer：本机浏览器无头渲染（带登录态 + 截图）
# ==============================================================================
def find_browsers():
    cands = []
    home = os.path.expanduser("~")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    la = os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
    ra = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
    if sys.platform.startswith("win"):
        cands += [
            (os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
             os.path.join(la, "Google", "Chrome", "User Data"), "chrome"),
            (os.path.join(pf86, "Google", "Chrome", "Application", "chrome.exe"),
             os.path.join(la, "Google", "Chrome", "User Data"), "chrome"),
            (os.path.join(la, "Google", "Chrome", "Application", "chrome.exe"),
             os.path.join(la, "Google", "Chrome", "User Data"), "chrome"),
            (os.path.join(pf86, "Microsoft", "Edge", "Application", "msedge.exe"),
             os.path.join(la, "Microsoft", "Edge", "User Data"), "edge"),
            (os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
             os.path.join(la, "Microsoft", "Edge", "User Data"), "edge"),
            (os.path.join(la, "360Chrome", "Chrome", "Application", "360chrome.exe"),
             os.path.join(la, "360Chrome", "Chrome", "User Data"), "360chrome"),
            (os.path.join(pf86, "360", "360Chrome", "Chrome", "Application", "360chrome.exe"),
             os.path.join(la, "360Chrome", "Chrome", "User Data"), "360chrome"),
            (os.path.join(la, "360ChromeX", "Chrome", "Application", "360ChromeX.exe"),
             os.path.join(la, "360ChromeX", "Chrome", "User Data"), "360chromex"),
            (os.path.join(la, "Tencent", "QQBrowser", "Application", "QQBrowser.exe"),
             os.path.join(la, "Tencent", "QQBrowser", "User Data"), "qqbrowser"),
            (os.path.join(ra, "Tencent", "QQBrowser", "Application", "QQBrowser.exe"),
             os.path.join(ra, "Tencent", "QQBrowser", "User Data"), "qqbrowser"),
            (os.path.join(pf, "Mozilla Firefox", "firefox.exe"),
             os.path.join(ra, "Mozilla", "Firefox", "Profiles"), "firefox"),
        ]
    elif sys.platform == "darwin":
        cands += [
            ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
             os.path.join(home, "Library/Application Support/Google/Chrome"), "chrome"),
            ("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
             os.path.join(home, "Library/Application Support/Microsoft Edge"), "edge"),
            ("/Applications/Firefox.app/Contents/MacOS/firefox",
             os.path.join(home, "Library/Application Support/Firefox/Profiles"), "firefox"),
        ]
    else:
        cands += [
            ("google-chrome", os.path.join(home, ".config/google-chrome"), "chrome"),
            ("chromium-browser", os.path.join(home, ".config/chromium"), "chromium"),
            ("microsoft-edge", os.path.join(home, ".config/microsoft-edge"), "edge"),
            ("firefox", os.path.join(home, ".mozilla/firefox"), "firefox"),
        ]
    found = []
    for exe, profile, name in cands:
        if os.path.exists(exe) or shutil.which(exe):
            found.append({"exe": exe, "profile": profile, "name": name})
    # 有真实 profile（能拿到 Cookies）的浏览器优先
    found.sort(key=lambda b: 0 if pick_profile_dir(b["profile"]) else 1)
    return found


def pick_profile_dir(profile_root):
    """支持任意 profile 名：先试常见名，再扫描一级子目录找含 Cookies 的目录"""
    for name in ["Default", "Profile 1", "Profile 2", "Profile 3"]:
        p = os.path.join(profile_root, name)
        if os.path.exists(os.path.join(p, "Cookies")):
            return p
    try:
        for d in sorted(os.listdir(profile_root)):
            p = os.path.join(profile_root, d)
            if os.path.isdir(p) and os.path.exists(os.path.join(p, "Cookies")):
                return p
    except Exception:
        pass
    return None


def read_firefox_cookies(domain=None):
    """Firefox 的 cookies.sqlite 是明文存储，标准库 sqlite3 直接可读 → 零依赖拿登录态"""
    home = os.path.expanduser("~")
    roots = [os.path.join(os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming")),
                          "Mozilla", "Firefox", "Profiles"),
             os.path.join(home, ".mozilla", "firefox"),
             os.path.join(home, "Library/Application Support/Firefox/Profiles")]
    for root in roots:
        if not os.path.isdir(root):
            continue
        targets = []
        try:
            for d in os.listdir(root):
                p = os.path.join(root, d, "cookies.sqlite")
                if os.path.exists(p):
                    targets.append(p)
        except Exception:
            continue
        for db in targets:
            try:
                con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
                cur = con.cursor()
                if domain:
                    cur.execute("SELECT host, name, value FROM moz_cookies WHERE host LIKE ?",
                                (f"%{domain}%",))
                else:
                    cur.execute("SELECT host, name, value FROM moz_cookies")
                rows = cur.fetchall()
                con.close()
            except Exception:
                continue
            if rows:
                parts = [f"{name}={value or ''}" for _host, name, value in rows if name]
                log(f"从 Firefox 读取到 {len(rows)} 条 Cookie", "发现")
                return "; ".join(parts)
    log("未找到可用的 Firefox Cookie（若用 Chrome/Edge 请改用 render 模式复用登录态）", "警告")
    return ""


class ChromeRenderer:
    """复制登录态(Cookies + Local State)到临时 profile → headless 渲染"""

    def __init__(self, exe, profile_root, keep=False):
        self.exe = exe
        self.profile_root = profile_root
        self.keep = keep
        self.tmp = None

    def prepare(self):
        src = pick_profile_dir(self.profile_root)
        self.tmp = tempfile.mkdtemp(prefix="wpharvest_profile_")
        dst_default = os.path.join(self.tmp, "Default")
        os.makedirs(dst_default, exist_ok=True)
        copied = []
        if src:
            for fn in ("Cookies", "Local State", "Preferences", "Web Data", "Login Data"):
                s = os.path.join(src, fn) if fn != "Local State" else os.path.join(self.profile_root, "Local State")
                if os.path.exists(s):
                    try:
                        shutil.copy2(s, os.path.join(dst_default if fn != "Local State" else self.tmp, fn))
                        copied.append(fn)
                    except Exception:
                        pass
        # 有些 profile 的 Local State 在 Default 下
        if "Local State" not in copied and os.path.exists(os.path.join(src or "", "Local State")):
            try:
                shutil.copy2(os.path.join(src, "Local State"), os.path.join(self.tmp, "Local State"))
                copied.append("Local State")
            except Exception:
                pass
        log(f"临时登录态已就绪（复制: {', '.join(copied) or '无，将以访客态渲染'}）", "信息")
        return self.tmp

    def _base_args(self, window="1920,1080", wait=6):
        return [
            self.exe,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-sync",
            "--disable-background-networking",
            "--disable-component-update",
            "--no-sandbox",
            "--hide-scrollbars",
            "--window-size=" + window,
            f"--virtual-time-budget={int(wait * 1000)}",
            "--run-all-compositor-stages-before-draw",
            f"--user-data-dir={self.tmp}",
        ]

    def dump_dom(self, url, window="1920,1080", wait=6, timeout=90):
        args = self._base_args(window, wait) + ["--dump-dom", url]
        try:
            cp = subprocess.run(args, capture_output=True, timeout=timeout)
            out = cp.stdout.decode("utf-8", "replace")
            if len(out) < 200 and cp.stderr:
                err = cp.stderr.decode("utf-8", "replace")[:400]
                log(f"渲染返回异常：{err}", "警告")
            return out
        except subprocess.TimeoutExpired:
            log("渲染超时", "警告")
            return ""
        except Exception as e:
            log(f"渲染失败 {type(e).__name__}: {e}", "错误")
            return ""

    def screenshot(self, url, dest, window="1920,1080", wait=6, timeout=90):
        args = self._base_args(window, wait) + [f"--screenshot={dest}", url]
        try:
            subprocess.run(args, capture_output=True, timeout=timeout)
            return os.path.exists(dest) and os.path.getsize(dest) > 1024
        except Exception as e:
            log(f"截图失败 {type(e).__name__}", "警告")
            return False

    def cleanup(self):
        if self.tmp and not self.keep and os.path.isdir(self.tmp):
            try:
                shutil.rmtree(self.tmp, ignore_errors=True)
            except Exception:
                pass


# ==============================================================================
# 8. Carver：目录魔数雕刻（缓存 / 无扩展名文件终极兜底）
# ==============================================================================
MAGIC = [
    (b"\xff\xd8\xff", "jpg", b"\xff\xd9"),
    (b"\x89PNG\r\n\x1a\n", "png", b"IEND\xaeB`\x82"),
    (b"GIF87a", "gif", b"\x00\x3b"),
    (b"GIF89a", "gif", b"\x00\x3b"),
]


def bmp_at(data, i):
    """BMP 魔数 'BM' 太短、误报率高，必须结合文件头字段做上下文校验"""
    if i + 30 > len(data) or data[i:i + 2] != b"BM":
        return False
    try:
        off = struct.unpack("<I", data[i + 10:i + 14])[0]
        dib = struct.unpack("<I", data[i + 14:i + 18])[0]
    except Exception:
        return False
    return 12 <= off <= 4096 and dib in (12, 40, 52, 56, 108, 124)


def validate_blob(blob, declared):
    """雕刻结果的真实性校验：魔数复检 + 尺寸合理性 + 体积/像素比合理性。
    返回 (ok, real_fmt, w, h) —— 挡掉一切误判产物。"""
    fmt = sniff_format(blob)
    if not fmt:
        return False, None, 0, 0
    w, h = sniff_size(blob[:262144])
    if fmt in ("mp4", "webm"):
        return True, fmt, w, h           # 视频尺寸常不在头部，放宽
    if not (16 <= w <= 30000 and 16 <= h <= 30000):
        return False, fmt, w, h          # 荒谬尺寸 → 误判
    px = w * h
    n = len(blob)
    floor_ratio = {"bmp": 1.0, "png": 0.02, "jpg": 0.02, "gif": 0.02, "webp": 0.02}.get(fmt, 0.02)
    if n < px * floor_ratio:
        return False, fmt, w, h          # 体积远小于像素数 → 头部伪造/起点错误
    if n > px * 12 + (2 << 20):
        return False, fmt, w, h          # 体积远超合理上限 → 刻多了
    return True, fmt, w, h


def _webp_end(data, start):
    """RIFF 容器：按头部声明的长度截断"""
    if start + 8 > len(data):
        return -1
    size = struct.unpack("<I", data[start + 4:start + 8])[0]
    end = start + 8 + size
    return end if end <= len(data) else len(data)


def _mp4_end(data, start):
    """mp4/mov：连续 box 累加长度直到非法"""
    i = start
    n = len(data)
    while i + 8 <= n:
        try:
            sz = struct.unpack(">I", data[i:i + 4])[0]
            typ = data[i + 4:i + 8]
        except Exception:
            break
        if sz == 0:
            return n
        if sz < 8 or not re.match(rb"^[a-zA-Z0-9_\-]{4}$", typ or b""):
            return i
        i += sz
        if i > n:
            return n
    return n if i > start else -1


def carve_buffer(data, out_dir, prefix, min_bytes, emit):
    """从一个字节块中雕刻出所有媒体文件"""
    n = len(data)
    results = []
    for magic, fmt, endmark in MAGIC:
        start = 0
        while True:
            i = data.find(magic, start)
            if i < 0:
                break
            if fmt == "bmp" and not (i + 26 <= n and data[18:20] != b"" and
                                     struct.unpack("<I", data[i + 10:i + 14])[0] in (6, 12, 14, 26, 40, 122, 124)):
                pass
            if endmark:
                j = data.find(endmark, i + 8)
                end = j + len(endmark) if j >= 0 else -1
            else:
                end = -1
            if end < 0:
                end = n
            blob = data[i:end]
            start = end
            if len(blob) < min_bytes:
                continue
            results.append(emit(blob, fmt))
    # BMP（带上下文校验，避免随机字节误命中）
    start = 0
    while True:
        i = data.find(b"BM", start)
        if i < 0:
            break
        if bmp_at(data, i):
            try:
                fsize = struct.unpack("<I", data[i + 2:i + 6])[0]
            except Exception:
                fsize = 0
            end = i + fsize if 12 <= fsize <= n else n
            start = end
            if end - i < min_bytes:
                continue
            results.append(emit(data[i:end], "bmp"))
        else:
            start = i + 2
    # WebP
    start = 0
    while True:
        i = data.find(b"RIFF", start)
        if i < 0:
            break
        if data[i + 8:i + 12] != b"WEBP":
            start = i + 4
            continue
        end = _webp_end(data, i)
        start = max(end, i + 12)
        if end < 0 or end - i < min_bytes:
            continue
        results.append(emit(data[i:end], "webp"))
    # MP4 / MOV（ftyp）
    start = 0
    while True:
        i = data.find(b"ftyp", start)
        if i < 4:
            break
        s = i - 4
        if s < 0 or s + 12 > n:
            break
        try:
            sz0 = struct.unpack(">I", data[s:s + 4])[0]
        except Exception:
            start = i + 4
            continue
        if sz0 < 8 or sz0 > n:
            start = i + 4
            continue
        end = _mp4_end(data, s)
        start = max(end, i + 4)
        if end < 0 or end - s < min_bytes:
            continue
        results.append(emit(data[s:end], "mp4"))
    return [r for r in results if r]


class Carver:
    def __init__(self, harvest, min_bytes, max_files):
        self.h = harvest
        self.min_bytes = min_bytes
        self.max_files = max_files

    def scan(self, root):
        files = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ("System Volume Information", "$RECYCLE.BIN")]
            for fn in filenames:
                fp = os.path.join(dirpath, fn)
                try:
                    if os.path.getsize(fp) >= self.min_bytes:
                        files.append(fp)
                except Exception:
                    pass
        log(f"待扫描文件 {len(files)} 个（来自 {root}）", "发现")
        return files

    def carve_file(self, path):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except Exception:
            return []

        def emit(blob, fmt):
            if self.h.count >= self.max_files:
                return None
            self.h.stats["candidate"] += 1
            # 真实性校验：剔除误判产物（如随机字节命中的假 BMP）
            ok, real_fmt, w, h = validate_blob(blob, fmt)
            if not ok:
                self.h.stats["skip"] += 1
                return None
            fmt = real_fmt
            if fmt not in ("mp4", "webm"):
                if len(blob) < self.min_bytes:
                    self.h.stats["skip"] += 1
                    return None
                if w and h and (w < self.h.min_w or h < self.h.min_h):
                    self.h.stats["skip"] += 1
                    return None
            sha = sha1_bytes(blob)
            if sha in self.h.seen_sha:
                self.h.stats["dup"] += 1
                return None
            if self.h.dry:
                self.h.stats["ok"] += 1
                log(f"[DRY] carve {fmt} {w}x{h} {human_size(len(blob))}", "发现")
                return None
            self.h._remember(sha)
            self.h.count += 1
            sub = self.h._subdir(fmt)
            dest = os.path.join(sub, f"carve_{self.h.count:04d}_{w}x{h}_{sha[:8]}.{EXT_BY_FMT.get(fmt, fmt)}")
            with open(dest, "wb") as fo:
                fo.write(blob)
            self.h.stats["ok"] += 1
            self.h.stats["bytes"] += len(blob)
            self.h.record(dest, fmt, w, h, len(blob), sha, "file://" + path, path)
            log(f"雕刻 {fmt.upper()} {w}x{h} {human_size(len(blob))} ← {os.path.basename(path)[:50]}", "下载")
            return dest

        out = carve_buffer(data, self.h.carve_dir, "carve", self.min_bytes, emit)
        return [o for o in out if o]

    def run(self, root):
        files = self.scan(root)
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = [ex.submit(self.carve_file, p) for p in files]
            for fu in as_completed(futs):
                try:
                    fu.result()
                except Exception as e:
                    log(f"雕刻异常 {type(e).__name__}", "调试")
        return self.h


# ==============================================================================
# 9. ApiMode：元气壁纸内置 + 通用 JSON 分页接口
# ==============================================================================
YUANQI_API = "https://pcwallpaper.zhhainiao.com/wallpaper/static/list"
YUANQI_LIVE_API = "https://pcwallpaper.zhhainiao.com/v20903/wplive/list"
YUANQI_CATE = {1: "风景", 2: "动漫", 4: "游戏", 5: "美女", 6: "明星", 7: "动物",
               8: "小清新", 9: "科幻", 10: "汽车", 12: "体育", 13: "其他"}


def api_yuanqi(fetcher, cid=1, sort_type=2, pages=5, delay=0.35, live=False):
    """元气壁纸：static=静态图片库；live=动态视频壁纸库（MP4）"""
    endpoint = YUANQI_LIVE_API if live else YUANQI_API
    kind = "live" if live else "static"
    items = []
    for p in range(1, pages + 1):
        payload = json.dumps({"cate_id": cid, "sort_type": sort_type, "page": p,
                              "count": 24}, ensure_ascii=False).encode("utf-8")
        st, hd, body = fetcher.request(endpoint, method="POST", body=payload,
                                       extra={"Content-Type": "application/json"},
                                       retries=3)
        try:
            js = json.loads(body.decode("utf-8", "replace"))
        except Exception:
            log(f"第 {p} 页解析失败", "警告")
            time.sleep(delay)
            continue
        data = (js.get("data") or {})
        lst = data.get("list") or data.get("data") or []
        if not lst:
            break
        for it in lst:
            if live:
                u = it.get("video")
            else:
                if str(it.get("price", 0)) != "0" or str(it.get("ptype", 0)) != "0":
                    continue  # 静态库只取免费资源
                u = it.get("jpg_url") or it.get("jpg_1920_url") or it.get("mid_jpg_url")
            if u:
                items.append((u, f"yuanqi-{kind}://cid={cid}/page={p}"))
        log(f"元气 {kind} 第 {p} 页 → 累计 {len(items)} 条", "发现")
        time.sleep(delay)
    return items


def dig_path(obj, path):
    cur = obj
    for key in path.split("."):
        if not key:
            continue
        if isinstance(cur, dict):
            cur = cur.get(key)
        elif isinstance(cur, list) and key.isdigit():
            cur = cur[int(key)]
        else:
            return None
        if cur is None:
            return None
    return cur


def api_json(fetcher, endpoint, payload_tpl, json_path, pages=5, method="POST"):
    items = []
    for p in range(1, pages + 1):
        payload = payload_tpl.replace("{page}", str(p))
        body = payload.encode("utf-8") if method == "POST" else None
        url = endpoint if method == "POST" else endpoint.replace("{page}", str(p))
        st, hd, resp_body = fetcher.request(url, method=method, body=body,
                                            extra={"Content-Type": "application/json"})
        try:
            js = json.loads(resp_body.decode("utf-8", "replace"))
        except Exception:
            break
        lst = dig_path(js, json_path) if json_path else js
        if not isinstance(lst, list):
            break
        for it in lst:
            if isinstance(it, str) and it.startswith("http"):
                items.append((it, f"{endpoint}#page{p}"))
            elif isinstance(it, dict):
                for v in it.values():
                    if isinstance(v, str) and re.search(r"\.(jpg|jpeg|png|webp|mp4|webm)(\?|$)", v, re.I):
                        items.append((v, f"{endpoint}#page{p}"))
                        break
        log(f"接口 第 {p} 页 → 累计 {len(items)} 条", "发现")
    return items


# ==============================================================================
# 10. Gallery：manifest.csv + index.html
# ==============================================================================
def write_manifest(harvest):
    import csv
    path = os.path.join(harvest.out, "manifest.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["file", "type", "w", "h", "size", "sha1", "url", "page"])
        w.writeheader()
        for r in harvest.rows:
            w.writerow(r)
    return path


GALLERY_TPL = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>壁纸采集画廊 · {ts}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{{--bg:#f7f6f3;--card:#fff;--ink:#2b2a27;--soft:#6b6862;--line:#e6e2da;--acc:#5a6b4f}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--ink);font-family:"PingFang SC","Microsoft YaHei",sans-serif;padding:28px}}
h1{{font-size:22px;margin-bottom:6px}}
.sub{{color:var(--soft);font-size:13px;margin-bottom:20px}}
.stats{{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:22px}}
.stat{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 16px;font-size:13px}}
.stat b{{color:var(--acc);font-size:16px;margin-right:6px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;
box-shadow:0 4px 16px rgba(60,55,45,.06);transition:.2s}}
.card:hover{{transform:translateY(-3px);box-shadow:0 10px 26px rgba(60,55,45,.13)}}
.card img{{width:100%;display:block;background:#eee;aspect-ratio:16/9;object-fit:cover}}
.card video{{width:100%;display:block;background:#000;aspect-ratio:16/9;object-fit:cover}}
.meta{{padding:10px 12px;font-size:12px;color:var(--soft);line-height:1.7}}
.meta .t{{color:var(--ink);font-weight:600;display:block;margin-bottom:2px;
white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.badge{{display:inline-block;background:#eef1ea;color:#3e4a37;border-radius:6px;padding:1px 7px;margin-right:6px}}
a{{color:var(--acc);text-decoration:none}}
</style></head><body>
<h1>壁纸采集画廊</h1>
<div class="sub">生成时间 {ts} · 共 {n} 个文件 · {total}</div>
<div class="stats">
<div class="stat"><b>{n}</b>文件</div>
<div class="stat"><b>{imgs}</b>图片</div>
<div class="stat"><b>{vids}</b>视频</div>
<div class="stat"><b>{total}</b>总体积</div>
</div>
<div class="grid">
{items}
</div></body></html>
"""


def write_gallery(harvest):
    items = []
    for r in harvest.rows:
        rel = r["file"]
        if r["type"] == "video":
            media = f'<video src="{rel}" muted loop autoplay playsinline></video>'
        else:
            media = f'<img loading="lazy" src="{rel}" alt="">'
        items.append(
            f'<div class="card">{media}<div class="meta">'
            f'<span class="t">{os.path.basename(rel)}</span>'
            f'<span class="badge">{r["w"]}×{r["h"]}</span>'
            f'<span class="badge">{human_size(r["size"])}</span>'
            f'<span class="badge">{r["type"]}</span><br>'
            f'<a href="{html.escape(r["url"])}" target="_blank" rel="noreferrer">原始地址</a>'
            f'</div></div>')
    imgs = sum(1 for r in harvest.rows if r["type"] == "image")
    vids = sum(1 for r in harvest.rows if r["type"] == "video")
    out = GALLERY_TPL.format(
        ts=datetime.now().strftime("%Y-%m-%d %H:%M"), n=len(harvest.rows),
        imgs=imgs, vids=vids, total=human_size(harvest.stats["bytes"]),
        items="\n".join(items))
    path = os.path.join(harvest.out, "index.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)
    return path


# ==============================================================================
# 11. CLI
# ==============================================================================
def build_parser():
    ap = argparse.ArgumentParser(
        prog="wallpaper_harvester.py",
        description="万能壁纸扒取器 · 所见即所得（url / render / carve / api / browser / selftest）",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""示例：
  python wallpaper_harvester.py url    https://example.com/wallpapers --depth 2
  python wallpaper_harvester.py render https://vip.site/album --screenshot --wait 10
  python wallpaper_harvester.py carve  "D:\\元气壁纸缓存" --min-width 1920
  python wallpaper_harvester.py api    yuanqi --cid 1 --pages 8 --sort 2
  python wallpaper_harvester.py selftest
""")
    ap.add_argument("mode", choices=["url", "render", "carve", "api", "browser", "selftest"])
    ap.add_argument("target", nargs="?", default="", help="URL / 目录 / api 类型")

    ap.add_argument("-o", "--out", default="", help="输出目录，默认 ./harvest/<host>_<时间戳>")
    ap.add_argument("--min-width", type=int, default=1280)
    ap.add_argument("--min-height", type=int, default=720)
    ap.add_argument("--min-size", type=int, default=80, help="最小体积 KB")
    ap.add_argument("--max", type=int, default=200, help="最多保存文件数")
    ap.add_argument("--depth", type=int, default=1, help="详情页递归层数")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--delay", type=float, default=0.2)
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--cookie", default="")
    ap.add_argument("--cookies-from", default="", choices=["", "firefox", "chrome", "edge"],
                    help="从本机浏览器读取登录态（firefox 零依赖；chrome/edge 走 render 模式复用）")
    ap.add_argument("--header", action="append", default=[], help="自定义请求头，可重复：'K: V'")
    ap.add_argument("--ua", default="")
    ap.add_argument("--referer", default="")
    ap.add_argument("--no-upgrade", action="store_true", help="关闭高清变体探测")
    ap.add_argument("--strict-magic", action="store_true",
                    help="只认文件魔数，不按 Content-Type 兜底（更严格，更少误存）")
    ap.add_argument("--screenshot", action="store_true", help="render 模式额外截图")
    ap.add_argument("--window", default="1920,1080")
    ap.add_argument("--wait", type=float, default=6.0)
    ap.add_argument("--keep-profile", action="store_true")
    ap.add_argument("--endpoint", default="")
    ap.add_argument("--payload", default="")
    ap.add_argument("--json-path", default="")
    ap.add_argument("--cid", type=int, default=1)
    ap.add_argument("--sort", type=int, default=2)
    ap.add_argument("--pages", type=int, default=5)
    ap.add_argument("--live", action="store_true", help="api yuanqi：抓动态视频壁纸（MP4）而非静态图")
    ap.add_argument("--no-gallery", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap


# ==============================================================================
# 12. main：分发 + 汇总报告
# ==============================================================================
def parse_headers(pairs):
    d = {}
    for p in pairs:
        if ":" in p:
            k, v = p.split(":", 1)
            d[k.strip()] = v.strip()
    return d


def prefilter(u):
    """探测前的 URL 预筛：明显不是媒体的直接丢掉，省下大量无效请求"""
    low = u.split("?")[0].lower()
    if re.search(r"\.(css|js|json|xml|txt|html?|php|asp|aspx|jsp|svg|ico|woff2?|ttf)$", low):
        return False
    if re.search(r"\.(jpg|jpeg|png|webp|avif|bmp|gif|mp4|webm|mov|m4v)(\?|$)", low, re.I):
        return True
    # 无扩展名但有强资源信号：路径含 upload/allimg/img/pic/photo/original 等
    return bool(re.search(r"/(upload|uploads|allimg|images?|img|pic|photo|original|orig|"
                          r"wallpaper|attach|file|media|static)/", low, re.I))


def fetch_page(fetcher, url):
    st, hd, body = fetcher.request(url)
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else ""
    if not text:
        return url, [], []
    ex = HTMLExtractor(url)
    cands, details = ex.parse(text)
    return url, cands, details


def crawl(fetcher, harvest, upgrader, downloader, page_url, depth, max_pages=60, per_level=30):
    """抓取页面 → 抽取 → 预筛 → 升级 → 返回下载任务；按 depth 逐层并发递归详情页"""
    visited = set()
    level = [(page_url, depth)]
    all_urls = []

    while level and len(visited) < max_pages:
        level = [x for x in level if x[0] not in visited][:per_level]
        if not level:
            break
        for u, _ in level:
            visited.add(u)
        log(f"并发抓取 {len(level)} 个页面（层级剩余深度 {level[0][1]}）", "信息")
        next_level = []
        with ThreadPoolExecutor(max_workers=min(6, len(level))) as ex:
            futs = [ex.submit(fetch_page, fetcher, u) for u, d in level]
            depth_map = {u: d for u, d in level}
            for fu in as_completed(futs):
                try:
                    u, cands, details = fu.result()
                except Exception as e:
                    log(f"页面异常 {type(e).__name__}", "调试")
                    continue
                d = depth_map.get(u, 0)
                good = [c for c in cands if prefilter(c)]
                log(f"  {u[:70]} → 候选 {len(cands)}（预筛后 {len(good)}）/ 详情 {len(details)}", "发现")
                for c in good:
                    all_urls.append((c, u))
                if d > 0:
                    for dl in details[:20]:
                        if dl not in visited:
                            next_level.append((dl, d - 1))
        level = next_level

    if not all_urls:
        return []

    uniq, seen = [], set()
    for u, p in all_urls:
        if u in seen:
            continue
        seen.add(u)
        uniq.append((u, p))
    uniq = uniq[:300]   # 探测上限，防止超大站点拖死
    log(f"去重后 {len(uniq)} 个候选，开始高清升级探测…", "信息")
    upgraded = []
    with ThreadPoolExecutor(max_workers=min(16, max(downloader.workers, 8))) as ex:
        futs = {ex.submit(upgrader.best, u): (u, p) for u, p in uniq}
        for fu in as_completed(futs):
            u, p = futs[fu]
            try:
                best_url, info = fu.result()
            except Exception:
                best_url, info = u, None
            upgraded.append((best_url, p))
    return upgraded


def run_url_mode(args, fetcher, harvest, upgrader, downloader):
    target = args.target
    jobs = crawl(fetcher, harvest, upgrader, downloader, target, args.depth)
    if not jobs:
        log("未抽取到任何资源，尝试放宽条件（--min-width 0 --min-size 0）或改用 render 模式", "警告")
    downloader.run(jobs)
    return harvest


def run_render_mode(args, fetcher, harvest, upgrader, downloader):
    browsers = find_browsers()
    if not browsers:
        log("未检测到 Chrome/Edge，自动降级为 url 静态模式", "警告")
        return run_url_mode(args, fetcher, harvest, upgrader, downloader)
    b = browsers[0]
    log(f"使用浏览器：{b['name']} → {b['exe']}", "信息")
    r = ChromeRenderer(b["exe"], b["profile"], keep=args.keep_profile)
    r.prepare()
    try:
        dom = r.dump_dom(args.target, window=args.window, wait=args.wait)
        if dom:
            log(f"渲染 DOM 长度 {len(dom)}", "发现")
            # 渲染后的 DOM 直接喂给抽取器（此时含懒加载与登录后内容）
            ex = HTMLExtractor(args.target)
            cands, details = ex.parse(dom)
            log(f"渲染后抽取 {len(cands)} 个候选 / {len(details)} 个详情链接", "发现")
            jobs = []
            seen = set()
            for c in cands:
                if c in seen:
                    continue
                seen.add(c)
                jobs.append((c, args.target))
            if args.depth > 0 and details:
                for dl in details[:15]:
                    sub = r.dump_dom(dl, window=args.window, wait=max(3.0, args.wait * 0.6))
                    if not sub:
                        continue
                    ex2 = HTMLExtractor(dl)
                    c2, _ = ex2.parse(sub)
                    for c in c2:
                        if c not in seen:
                            seen.add(c)
                            jobs.append((c, dl))
            if not args.no_upgrade:
                with ThreadPoolExecutor(max_workers=8) as exx:
                    futs = {exx.submit(upgrader.best, u): (u, p) for u, p in jobs}
                    jobs = []
                    for fu in as_completed(futs):
                        u, p = futs[fu]
                        try:
                            bu, _ = fu.result()
                        except Exception:
                            bu = u
                        jobs.append((bu, p))
            downloader.run(jobs)
        else:
            log("渲染无输出，降级为 url 静态模式", "警告")
            return run_url_mode(args, fetcher, harvest, upgrader, downloader)

        if args.screenshot:
            shot = os.path.join(harvest.shot_dir, f"shot_{now_stamp()}.png")
            ok = r.screenshot(args.target, shot, window=args.window, wait=args.wait)
            if ok:
                with open(shot, "rb") as f:
                    head = f.read(64)
                w, h = _png_size(head)
                size = os.path.getsize(shot)
                harvest.record(shot, "png", w, h, size, file_sha1(shot),
                               args.target, args.target)
                harvest.stats["ok"] += 1
                harvest.stats["bytes"] += size
                log(f"截图已保存 {w}x{h} {human_size(size)}", "完成")
    finally:
        r.cleanup()
    return harvest


def run_carve_mode(args, harvest):
    root = args.target
    if not os.path.isdir(root):
        log(f"目录不存在：{root}", "错误")
        return harvest
    carver = Carver(harvest, max(harvest.min_bytes, 20 * 1024), args.max)
    carver.run(root)
    return harvest


def run_api_mode(args, fetcher, harvest, downloader):
    kind = (args.target or "yuanqi").lower()
    if kind == "yuanqi":
        items = api_yuanqi(fetcher, cid=args.cid, sort_type=args.sort, pages=args.pages,
                           live=args.live)
    elif kind == "json":
        if not args.endpoint:
            log("api json 模式需要 --endpoint", "错误")
            return harvest
        items = api_json(fetcher, args.endpoint, args.payload or '{"page":{page}}',
                         args.json_path, pages=args.pages)
    else:
        log(f"未知 api 类型：{kind}", "错误")
        return harvest
    log(f"接口共返回 {len(items)} 条资源", "发现")
    downloader.run(items)
    return harvest


def run_browser_mode(args, fetcher, harvest, upgrader, downloader):
    """可选增强：装了 playwright 则用真浏览器；未装自动降级 render"""
    try:
        from playwright.sync_api import sync_playwright  # noqa
    except Exception:
        log("未安装 playwright → 自动降级为 render 模式（如需增强：pip install playwright && playwright install chromium）", "警告")
        return run_render_mode(args, fetcher, harvest, upgrader, downloader)

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            br = pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
            ctx = br.new_context(viewport={"width": 1920, "height": 1080})
            if args.cookie:
                ctx.add_cookies([
                    {"name": kv.split("=", 1)[0].strip(), "value": kv.split("=", 1)[1].strip(),
                     "url": args.target}
                    for kv in args.cookie.split(";") if "=" in kv])
            page = ctx.new_page()
            caught = []
            page.on("response", lambda r: caught.append(r.url)
                    if (("image" in (r.headers.get("content-type") or "")
                         or re.search(r"\.(jpg|jpeg|png|webp|mp4|webm)(\?|$)", r.url, re.I))
                        and r.status == 200) else None)
            page.goto(args.target, timeout=args.timeout * 1000, wait_until="networkidle")
            for _ in range(6):
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(700)
            html_text = page.content()
            if args.screenshot:
                shot = os.path.join(harvest.shot_dir, f"shot_{now_stamp()}.png")
                page.screenshot(path=shot, full_page=True)
                harvest.record(shot, "png", 0, 0, os.path.getsize(shot),
                               file_sha1(shot), args.target, args.target)
            br.close()
        ex = HTMLExtractor(args.target)
        cands, _ = ex.parse(html_text)
        jobs = list({*cands, *caught})
        log(f"真浏览器捕获 {len(jobs)} 个资源（DOM {len(cands)} + 网络 {len(caught)}）", "发现")
        downloader.run([(u, args.target) for u in jobs])
    except Exception as e:
        log(f"playwright 执行失败（{type(e).__name__}），降级 render", "警告")
        return run_render_mode(args, fetcher, harvest, upgrader, downloader)
    return harvest


def selftest():
    """离线自检：不联网，验证抽取 / 升级规则 / 尺寸嗅探 / 雕刻"""
    ok = True

    # 1) 抽取
    sample = """<html><head>
      <meta property="og:image" content="https://cdn.test.com/w/300/a_big_wallpaper.jpg?w=400">
      <link rel="preload" href="//cdn.test.com/cover_400x300.webp" as="image">
      <style>.x{background-image:url('/static/bg/thumb/1.jpg')}</style>
      <script>var a={"list":[{"url":"https:\\/\\/cdn.test.com\\/orig\\/2_1920x1080.jpg"}]};</script>
      </head><body>
      <img src="/img/logo.png" data-src="https://cdn.test.com/photo/a_400x300.jpg" srcset="https://cdn.test.com/x.jpg 1x, https://cdn.test.com/x@2x.jpg 2x">
      <a href="/wallpaper/detail/12345">详情页</a>
      <a href="/about">关于我们</a>
      </body></html>"""
    ex = HTMLExtractor("https://www.test.com/wallpapers/")
    cands, details = ex.parse(sample)
    print(f"[selftest] 抽取候选 {len(cands)}：")
    for c in cands:
        print("   -", c)
    print(f"[selftest] 详情链接 {details}")
    checks = {
        "og:image 抽取": any("a_big_wallpaper.jpg" in c for c in cands),
        "srcset 抽取": any("x@2x.jpg" in c for c in cands),
        "CSS url() 抽取": any("/static/bg/thumb/1.jpg" in c for c in cands),
        "JS 转义 URL 抽取": any("2_1920x1080.jpg" in c for c in cands),
        "logo 被过滤": not any("logo.png" in c for c in cands),
        "详情页识别": any("detail/12345" in d for d in details),
        "无关链接不误判": not any("about" in d.split("/")[-1] for d in details),
    }
    for k, v in checks.items():
        print(f"   {'PASS' if v else 'FAIL'}  {k}")
        ok &= v

    # 2) 升级规则
    u = "https://cdn.test.com/w/300/a_400x300.jpg?w=400"
    vs = Upgrader.variants(u)
    print(f"[selftest] 升级候选 {len(vs)}：")
    for v in vs:
        print("   -", v)
    up_ok = any("3840" in v for v in vs)
    print(f"   {'PASS' if up_ok else 'FAIL'}  高清变体生成")
    ok &= up_ok

    # 3) 尺寸嗅探（构造最小 PNG / JPEG / GIF / WEBP）
    def mk_png(w, h):
        raw = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00" + b"\x00" * 20
        return raw
    def mk_gif(w, h):
        return b"GIF89a" + struct.pack("<HH", w, h) + b"\x00" * 10
    def mk_jpg(w, h):
        # SOI(FFD8) + SOF0(FFC0) + len(2) + precision(1) + height(2) + width(2)
        return b"\xff\xd8" + b"\xff\xc0" + struct.pack(">H", 17) + b"\x08" + \
            struct.pack(">HH", h, w) + b"\x03" + b"\x00" * 30
    def mk_webp(w, h):
        # RIFF + size + WEBP + VP8X + chunkLen(4) + flags(1) + reserved(3) + w-1(3) + h-1(3)
        return b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"VP8X" + struct.pack("<I", 10) + \
            b"\x00" + b"\x00\x00\x00" + (w - 1).to_bytes(3, "little") + \
            (h - 1).to_bytes(3, "little") + b"\x00" * 8
    tests = [(mk_png(1920, 1080), (1920, 1080), "PNG"),
             (mk_gif(800, 600), (800, 600), "GIF"),
             (mk_jpg(3840, 2160), (3840, 2160), "JPEG"),
             (mk_webp(2560, 1440), (2560, 1440), "WebP")]
    print("[selftest] 尺寸嗅探：")
    for data, expect, name in tests:
        got = sniff_size(data)
        good = got == expect
        print(f"   {'PASS' if good else 'FAIL'}  {name} 期望{expect} 实测{got}")
        ok &= good

    # 4) 雕刻
    blob = b"JUNKJUNK" + mk_jpg(1920, 1080) + b"XX" + mk_png(2560, 1440) + b"IEND\xaeB`\x82" + b"TAIL"
    found = []
    carve_buffer(blob, "", "t", 10, lambda b, fmt: found.append((fmt, len(b))) or "")
    carve_ok = len(found) >= 2
    print(f"[selftest] 雕刻：找到 {found} → {'PASS' if carve_ok else 'FAIL'}")
    ok &= carve_ok

    print("\n[selftest] 总体结果：" + ("全部通过 ✅" if ok else "存在失败项 ❌"))
    return 0 if ok else 1


def report(harvest, t0):
    s = harvest.stats
    dur = time.time() - t0
    print("\n" + "=" * 68)
    print(f" 采集完成 · 耗时 {dur:.1f}s")
    print(f"   候选 {s['candidate']}   通过过滤 {s['pass']}   成功 {s['ok']}   "
          f"去重 {s['dup']}   跳过 {s['skip']}   失败 {s['fail']}")
    print(f"   总体积 {human_size(s['bytes'])}   输出目录 {harvest.out}")
    print("=" * 68)
    if harvest.rows:
        mp = write_manifest(harvest)
        print(f" 清单：{mp}")
        if harvest.gallery:
            gp = write_gallery(harvest)
            print(f" 画廊：{gp}（双击打开）")
    return 0


def main():
    global VERBOSE
    ap = build_parser()
    args = ap.parse_args()
    VERBOSE = args.verbose

    if args.mode == "selftest":
        return selftest()

    if not args.target:
        ap.error("缺少 target")

    out = args.out
    if not out:
        key = safe_name(args.target if args.mode != "api" else f"api_{args.target}", 40)
        out = os.path.join("harvest", f"{key}_{now_stamp()}")
    out = os.path.abspath(out)

    headers = parse_headers(args.header)
    cookie = args.cookie
    if args.cookies_from == "firefox":
        domain = url_host(args.target) if args.mode in ("url", "render", "browser") else ""
        got = read_firefox_cookies(domain)
        if got:
            cookie = (cookie + "; " + got).strip("; ") if cookie else got
    fetcher = Fetcher(timeout=args.timeout, delay=args.delay, ua=args.ua or None,
                      cookie=cookie or None, headers=headers,
                      referer=args.referer or None)
    harvest = Harvest(out, min_w=args.min_width, min_h=args.min_height,
                      min_kb=args.min_size, max_files=args.max,
                      dry=args.dry_run, gallery=not args.no_gallery)
    upgrader = Upgrader(fetcher, workers=min(8, args.workers), enabled=not args.no_upgrade)
    downloader = Downloader(fetcher, harvest, workers=args.workers,
                            strict_magic=args.strict_magic)

    log(f"输出目录 {out}", "信息")
    t0 = time.time()
    try:
        if args.mode == "url":
            run_url_mode(args, fetcher, harvest, upgrader, downloader)
        elif args.mode == "render":
            run_render_mode(args, fetcher, harvest, upgrader, downloader)
        elif args.mode == "carve":
            run_carve_mode(args, harvest)
        elif args.mode == "api":
            run_api_mode(args, fetcher, harvest, downloader)
        elif args.mode == "browser":
            run_browser_mode(args, fetcher, harvest, upgrader, downloader)
    except KeyboardInterrupt:
        log("用户中断，已保留已下载内容", "警告")
    return report(harvest, t0)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已中断")
        sys.exit(130)
