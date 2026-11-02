# 万能壁纸扒取器 · Wallpaper Harvester

> 所见即所得的壁纸抓取工具：url / render / carve / api / browser 五条路径，覆盖懒加载、登录墙、VIP 墙与本地缓存

![License](https://img.shields.io/badge/license-MIT-5a6b4f)
![Type](https://img.shields.io/badge/type-Agent%20Skill-4a6b7c)
![Platform](https://img.shields.io/badge/platform-WorkBuddy%20%7C%20Claude%20Code-b8935a)

## 它解决什么问题

网页上能看到的壁纸，右键却存不下来。原因通常是四种：懒加载没触发、内容由 JS 渲染、要登录或 VIP、图被画在 canvas 里。

这个 skill 用五条路径逐一覆盖，**核心路径零第三方依赖**（只用 Python 标准库），跑不动了才升级到下一条。

## 五条路径

| 模式 | 适用场景 | 原理 |
|---|---|---|
| `url` | 静态网页、可直接拿到图片地址 | 抓列表页 → 递归进详情页 → 取原图 |
| `render` | 懒加载、JS 渲染、登录/VIP 墙 | 调本机 Chrome/Edge 无头渲染，**带你的登录态** |
| `carve` | 图片只在软件缓存里（桌面壁纸软件） | 按文件魔数在目录里雕刻出 jpg/png/webp/mp4 |
| `api` | 站点有分页 JSON 接口 | 直接打接口批量拿，含内置元气壁纸库 |
| `browser` | 需要真实交互（滚动、点击解锁） | 交给浏览器控制，逐步触发 |

决策树在 `SKILL.md` 里：先问「右键能不能存」，能就 `url`，不能就往下走。

## 快速开始

```bash
# 1) 普通壁纸站
python scripts/harvest.py url --page "https://example.com/wallpaper" --out ./wall

# 2) 需要登录 / VIP（复用本机浏览器登录态）
python scripts/harvest.py render --page "https://example.com/vip" --out ./wall --scroll 8

# 3) 元气壁纸风景分类，批量 8 页
python scripts/harvest.py api --source yuanqi --category landscape --pages 8 --out ./wall

# 4) 从本地目录雕刻缓存图
python scripts/harvest.py carve --dir "C:/Users/xxx/AppData/Local/Wallpaper" --out ./wall

# 5) 离线自检（不联网，只验证环境）
python scripts/harvest.py selftest
```

## 几个实际会遇到的问题

- **抓到的是缩略图**：多半是列表页的 `src` 指向了 `_thumb` 变体，要回详情页找 `data-original` 或 `srcset` 里最大的那条。
- **webp 打不开**：不是文件坏了，是浏览器/看图软件不支持；`--format jpg` 会转码。
- **render 模式拿到登录页**：浏览器配置文件路径没指对，登录态没被复用。
- **carve 出很多碎图**：魔数匹配到的是缓存分片，加 `--min-size` 过滤。

## 目录结构

```
wallpaper-harvester/
├─ SKILL.md              模式决策树 · 五种模式详解 · 参数表
├─ scripts/              抓取与雕刻脚本（标准库优先）
└─ references/           站点适配笔记、常见失败原因
```

## 使用边界

只抓取你有权访问的公开内容。需要登录或付费才能看的内容，本工具复用你自己已付费的登录态，**不绕过任何付费机制**；请遵守目标站点的服务条款，不要用于批量转载。

## 许可

MIT © 2026 px-pangu


## 安装

把本仓库整个目录放进 Agent 的 skills 目录即可，目录名保持仓库名：

```bash
# WorkBuddy
git clone https://github.com/px-pangu/wallpaper-harvester.git ~/.workbuddy/skills/wallpaper-harvester

# Claude Code
git clone https://github.com/px-pangu/wallpaper-harvester.git ~/.claude/skills/wallpaper-harvester
```

装好后在对话里说一句相关的话就会自动触发，也可以用 `@wallpaper-harvester` 显式点名。

