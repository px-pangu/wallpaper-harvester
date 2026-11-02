# 排障与扩展指南

## 一、结果为空或数量过少时的排查顺序

按顺序检查，每一步都能排除一类原因：

1. **先加 `-v` 看日志**，确认是「抽取不到候选」「候选被过滤」还是「下载失败」。
2. **候选 0** → 页面是纯 JS 渲染，或请求被拦。改用 `render` 模式；确认 `--ua` / `--cookie` 是否需要。
3. **候选很多但全部「分辨率不足」** → 列表页只有缩略图，加 `--depth 1` 递归详情页；
   或确认该站原图需要特定参数，扩展升级规则（见第三节）。
4. **全部「非媒体」** → 站点返回的是 HTML 错误页（403/405/验证码）。加大 `--delay`、
   换 `--ua`、补 `--referer`（通常填站点首页）。
5. **全部「无法探测」** → 请求超时或被重置。加大 `--timeout`，降低 `--workers`。
6. **仍然拿不到** → `render --screenshot` 像素级截图兜底；若目标是本地软件，用 `carve`。

## 二、HTTP 状态码与限流对策

| 现象 | 含义 | 对策 |
|---|---|---|
| 403 | UA / Referer 被判机器，或需登录 | 换 `--ua`，补 `--referer <站点首页>`；需登录则 render 或 `--cookie` |
| 405 | WAF 对高频 GET 的拦截（如 pic.netbian.com 连续请求后出现） | `--delay 1.0 --workers 3` 降速；改用 render 模式走真实浏览器 |
| 429 | 速率限制 | 同上降速；必要时 `--pages 1` 分批跑 |
| 206 正常但魔数不匹配 | 加密流 / 混淆流 / 罕见封装 | 默认已按 Content-Type 兜底落盘；加 `--strict-magic` 可关闭该行为 |

脚本内置：403/429/503 会自动换 UA 并指数退避重试 3 次。

## 三、扩展新站点的高清升级规则

缩略图 → 原图的转换规则集中在脚本的 `UPGRADE_RULES`（`scripts/wallpaper_harvester.py`
中「4. Upgrader」一节）。每条规则是 `(正则, 替换函数)` 二元组，命中后生成一个候选 URL，
所有候选会用 Range 请求探测，取**字节数最大**的有效者。

新增站点规则的做法：

1. 用浏览器开发者工具对比缩略图 URL 与原图 URL 的差异。
2. 在 `UPGRADE_RULES` 末尾追加一条规则，例如：

```python
# 某站：/s512/xxx.jpg → /original/xxx.jpg
(re.compile(r"/s\d{2,4}/", re.I), lambda m: "/original/"),
# 某站：?x-oss-process=image/resize,w_400 → w_4096
(re.compile(r"resize,w_\d+", re.I), lambda m: "resize,w_4096"),
```

3. 用 `--dry-run -v` 验证变体是否被探测命中（日志会打印 `[升级] 旧URL → 新URL (大小)`）。
4. 若该站 URL 无尺寸规律，改用 `render` 模式：真浏览器加载出来的 DOM 里通常就是原图地址。

相关辅助函数：`Upgrader.variants()` 生成候选，`Upgrader.best()` 探测选优，
`prefilter()` 在探测前丢掉 css/js/html 等非媒体链接以节省请求。

## 四、登录态获取的三条路径

| 路径 | 命令 | 适用 |
|---|---|---|
| Firefox（零依赖） | `--cookies-from firefox` | cookies.sqlite 明文存储，标准库 sqlite3 直接读 |
| Chrome / Edge / 360 / QQ | `render` 模式 | 复制 Cookies + Local State 到临时 profile，由浏览器自己解密 |
| 手工注入 | `--cookie "k=v; k2=v2"` | 从开发者工具 Network 面板复制 Request Headers 里的 Cookie |

Chrome/Edge 若 profile 中不存在 Cookies 文件（未登录过），render 会以访客态运行，
日志会提示「无，将以访客态渲染」，此时改用另外两条路径。

## 五、视频壁纸与动态壁纸

- `api yuanqi --live` 抓到的是 MP4，落盘在 `video/`。
- 部分站点的动态壁纸是**客户端加密流**（前几字节不是 `ftyp`，例如元气壁纸 live 库）。
  这类文件能被完整下载，但需原客户端才能播放——这是站点侧加密，工具不应尝试破解。
  脚本通过「按 Content-Type 兜底」保证这类文件仍然落盘（加 `--strict-magic` 可关闭）。
- m3u8 流媒体当前未内置合并逻辑（需 ffmpeg）。如遇到，先用 url/render 拿到 `.m3u8` 地址，
  再自行用 ffmpeg 合并：`ffmpeg -i "xxx.m3u8" -c copy out.mp4`。

## 六、性能调优

| 场景 | 建议参数 |
|---|---|
| 大站批量抓（几百张） | `--workers 12 --delay 0.1 --depth 1 --max 500` |
| 站点限流严格 | `--workers 2 --delay 1.5 --timeout 30` |
| 只想快速看看有什么 | `--dry-run -v --max 20` |
| 只要原图、跳过探测省时间 | `--no-upgrade`（前提是 URL 本身已是原图） |
| 详情页特别多的站点 | `--depth 1`（每层最多抓 30 页，总页数上限 60，自动截断） |

## 七、已知站点备注

- **pic.netbian.com**：结构规整，列表页为 430×242 缩略图，必须 `--depth 1` 进详情页；
  连续请求后 WAF 会返回 405，需降速或改用 render。
- **元气壁纸（pcwallpaper.zhhainiao.com）**：接口免登录可用，静态库有频控（间隔 ≥0.35s），
  动态库视频为加密流；详见 `references/yuanqi-api.md`。
- **纯 canvas / WebGL 渲染的页面**：DOM 里没有图片 URL，只能 `render --screenshot` 截图。
