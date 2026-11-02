---
name: wallpaper-harvester
display_name: "万能壁纸扒取器"
display_name_en: "Wallpaper Harvester"
description: 万能壁纸扒取工具（所见即所得）。当用户要求「扒壁纸 / 下载网页上的壁纸 / 保存高清原图 / 抓取需要登录或 VIP 才能看到的壁纸 / 提取桌面壁纸软件缓存里的图片 / 批量下载 4K 壁纸 / 抓动态视频壁纸」时使用本技能。提供 url、render、carve、api、browser 五种抓取路径，覆盖静态网页、懒加载、JS 渲染、登录墙、VIP 墙、canvas/WebGL 绘制与本地缓存雕刻；内置元气壁纸接口。核心路径零第三方依赖。
agent_created: true
---

# Wallpaper Harvester · 万能壁纸扒取器

## Overview

把浏览器里肉眼能看到的壁纸落到本地磁盘。单文件 Python 3 脚本（`scripts/wallpaper_harvester.py`），
核心路径只用标准库（无需 pip 安装 requests / bs4 / lxml / PIL），支持五条互斥兜底的抓取路径、
缩略图自动升级为原图、按分辨率/体积过滤、SHA1 去重、断点续传、并产出可双击打开的画廊页面。

## 何时使用

- 「把这个网站的壁纸都扒下来」「帮我保存这页的高清图」
- 「这张图要 VIP / 要登录才能看，帮我弄下来」
- 「壁纸软件的缓存里有没有原图，给我抠出来」（元气桌面 / 必剪 / 浏览器 Cache）
- 「批量下载 4K 风景壁纸」「抓一批动态视频壁纸」
- 网页图片懒加载、由 JS 渲染、画在 canvas 里，普通右键另存拿不到原图

## 模式决策树

拿到需求后先判断走哪条路径，判断顺序自上而下：

```
页面是否需要登录 / VIP 才能看到原图？
├─ 是 → render 模式（复用本机浏览器登录态；必要时 --screenshot 像素级截图兜底）
└─ 否 → 页面上的图是直接写在 HTML 里，还是要滚动/点击才加载？
        ├─ 要滚动/点击/JS 渲染 → render 或 browser（装了 playwright 时）
        └─ 直接可见 → url 模式（--depth 1 递归详情页拿原图）

目标是批量图库而非网页？        → api 模式（元气壁纸内置 / 通用 JSON 分页接口）
目标是一个本地目录（缓存/软件目录）？ → carve 模式（按魔数雕刻）
以上都拿不到（canvas 绘制、加密客户端）？ → render --screenshot 截图兜底
```

一句话原则：**先 url，不行 render，再不行 screenshot，最后是 carve 抠缓存**。

## 快速开始

```bash
# 1) 普通壁纸站：抓列表页 + 递归详情页
python scripts/wallpaper_harvester.py url "https://example.com/wallpapers" --depth 1 --max 50

# 2) 需要登录 / VIP / 懒加载：本机 Chrome/Edge 无头渲染，带你的登录态
python scripts/wallpaper_harvester.py render "https://vip.site/album" --depth 1 --screenshot

# 3) 批量接口：元气壁纸风景分类，抓 8 页
python scripts/wallpaper_harvester.py api yuanqi --cid 1 --pages 8 --sort 2

# 4) 抠缓存：从任意目录按魔数雕刻图片/视频
python scripts/wallpaper_harvester.py carve "D:\元气壁纸缓存" --min-width 1920

# 5) 离线自检（不联网，验证环境可用）
python scripts/wallpaper_harvester.py selftest
```

Windows 下脚本路径含中文时请用引号包裹；Python 用 `python` 或 `py` 均可（实测 3.9+ 通过）。

## 各模式详解

### url — 静态网页抽取（默认首选）

解析 `<img>` 全部 data-* 属性、srcset、`<picture>/<source>`、`<video>`、
`meta[og:image]`、`<link rel=preload>`、内联 style 与 `<style>` 里的 `url()`、
`<script>` 内的 JSON 与转义字符串（`\/`、`\u002F`）、JSON-LD，最后整页正则兜底。
对抽到的缩略图生成高清变体并探测取最大者，再并发下载。

```bash
python scripts/wallpaper_harvester.py url <URL> --depth 1 --workers 8 --max 100
```

- `--depth N`：详情页递归层数。列表页通常只有缩略图，原图在详情页，**用 0 会大量被过滤**，默认给 1。
- 探测前会按 URL 预筛（丢弃 css/js/html），并对前 300 个候选做升级探测。

### render — 本机浏览器无头渲染（登录/VIP 突破）

调用本机 Chrome / Edge / 360 / QQ 浏览器，复制 `Default/Cookies` + `Local State`
到临时 user-data-dir，用 `--headless=new --dump-dom` 渲染出**带登录态的完整 DOM**，
后续抽取流程与 url 模式一致。支持 `--screenshot` 输出像素级截图（canvas/WebGL 同样吃到）。

```bash
python scripts/wallpaper_harvester.py render <URL> --screenshot --window 1920,1080 --wait 8
```

- 未检测到浏览器时自动降级为 url 模式，不会中断。
- 若该浏览器 profile 里没有 Cookies（未登录过），会以访客态渲染，此时改用 `--cookie` 手工注入。
- `--keep-profile` 保留临时 profile 便于排查。

### carve — 本地缓存雕刻（终极兜底）

对任意目录按文件魔数（JPEG / PNG / GIF / WebP / BMP / MP4 ftyp）雕刻出内嵌媒体，
按结束标记或容器长度截断落盘，适合壁纸客户端缓存、浏览器 Cache、无扩展名的临时文件。

```bash
python scripts/wallpaper_harvester.py carve "D:\某缓存目录" --min-width 1920 --max 200
```

雕刻结果会做真实性校验（魔数复检 + 尺寸合理性 + 体积/像素比），避免随机字节误判。

### api — 接口批量

```bash
# 元气壁纸静态库（内置，已验证）
python scripts/wallpaper_harvester.py api yuanqi --cid 1 --pages 8 --sort 2
# 元气壁纸动态视频壁纸（MP4）
python scripts/wallpaper_harvester.py api yuanqi --live --cid 1 --pages 3
# 任意 JSON 分页接口
python scripts/wallpaper_harvester.py api json --endpoint https://x/api/list \
       --payload '{"page":{page},"size":24}' --json-path data.list --pages 5
```

接口细节、分类表与字段说明见 `references/yuanqi-api.md`。

### browser — 可选增强（需 playwright）

装了 playwright 时用真浏览器滚动加载 + 拦截网络响应（能抓到不在 DOM 里的原图）；
未安装则自动降级为 render 模式，并提示安装命令。

## 常用参数速查

| 参数 | 默认 | 说明 |
|---|---|---|
| `-o, --out` | `./harvest/<域名>_<时间戳>` | 输出根目录 |
| `--min-width` / `--min-height` | 1280 / 720 | 分辨率下限，过滤缩略图与图标 |
| `--min-size` | 80 (KB) | 体积下限 |
| `--max` | 200 | 最多保存文件数（名额占位机制，精确生效） |
| `--depth` | 1 | 详情页递归层数 |
| `--workers` / `--delay` | 8 / 0.2s | 并发数与请求间隔（被限流时调大 delay） |
| `--cookie` / `--header` / `--ua` / `--referer` | — | 手工注入请求头 |
| `--cookies-from firefox` | — | 零依赖读取 Firefox 明文 Cookie 注入登录态 |
| `--no-upgrade` | 关 | 关闭高清变体探测（省时间） |
| `--strict-magic` | 关 | 只认魔数，不按 Content-Type 兜底 |
| `--dry-run` | 关 | 只列出将下载的内容，不落盘 |
| `-v, --verbose` | 关 | 详细日志 |

## 输出结构

```
<out>/
├── images/        图片（域名_序号_宽x高_sha1前8.jpg）
├── video/         视频壁纸
├── carve/         carve 模式预留
├── screenshots/   render --screenshot 产物
├── manifest.csv   清单：文件、类型、宽高、字节、sha1、原始URL、来源页
├── index.html     画廊（浅色主题 / CSS Grid / 懒加载 / 点击打开原图）
└── seen.txt       历史 SHA1，跨次运行去重
```

运行结束会打印汇总：候选 / 通过过滤 / 成功 / 去重 / 跳过 / 失败 / 总体积 / 耗时。

## 关键注意事项

- **列表页缩略图会被过滤**，这是预期行为；要原图请 `--depth 1` 进详情页，或用 render 模式。
- **不要对同一输出目录重复跑**：`seen.txt` 会按内容 SHA1 去重，重复文件自动跳过。
- **尊重版权**：仅采集本机已可正常浏览、拥有合法使用权的个人用途内容。
- Ctrl+C 可随时中断，已下载文件完整保留。
- 需要扩展新站点的高清规则或排查失败原因 → 见 `references/troubleshooting.md`。

## Resources

- `scripts/wallpaper_harvester.py` — 主程序，单文件、零第三方依赖，可直接执行
- `references/troubleshooting.md` — 失败排查流程、反爬对策、如何扩展高清升级规则
- `references/yuanqi-api.md` — 元气壁纸接口文档（静态/动态）、分类表、字段与频控说明
