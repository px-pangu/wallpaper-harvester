# 元气壁纸接口文档

接口免登录可直接调用，均为 POST + JSON（`Content-Type: application/json`）。
脚本已内置解析器，通过 `api yuanqi` 调用。

## 静态图片壁纸

```
POST https://pcwallpaper.zhhainiao.com/wallpaper/static/list
body: {"cate_id": 1, "sort_type": 2, "page": 1, "count": 24}
```

- `page` 从 1 起；`count` 参数无效，服务端固定每页 24 条；`total` 上限 800。
- `sort_type`：`2` = 热度降序，`4` = 使用量降序（服务端排序不严格，抓大池子后本地重排更好）。
- 返回 `data.list[]`，关键字段：
  - 图片直链（按优先级取）：`jpg_url` > `jpg_1920_url` > `mid_jpg_url`
  - 元信息：`id` / `wname` / `cid` / `cname` / `likes` / `download_cnt` / `view` / `hot` /
    `resolution` / `md5` / `price` / `ptype` / `size` / `author` / `tags`
- 脚本只取 `price == 0 且 ptype == 0` 的免费资源。

## 动态视频壁纸

```
POST https://pcwallpaper.zhhainiao.com/v20903/wplive/list
body: {"cate_id": 1, "sort_type": 2, "page": 1, "count": 24}
```

- 字段含 `video`（MP4 直链）、`download_count` / `likes` / `scan_cnt` / `md5_4k`；
  预览图 `preview_jpg_raw` 只有 960×540。
- 热度远高于静态库（百万级下载），但产物是视频，且**部分为客户端加密流**（需原客户端播放）。
- 备用路径：`/v20526/wplive/list`。

## 分类表（cate_id）

| id | 分类 | id | 分类 |
|---|---|---|---|
| 1 | 风景 | 7 | 动物 |
| 2 | 动漫 | 8 | 小清新 |
| 4 | 游戏 | 9 | 科幻 |
| 5 | 美女 | 10 | 汽车 |
| 6 | 明星 | 12 | 体育 |
|   |      | 13 | 其他 |

## 其他接口

| 用途 | 路径 |
|---|---|
| 静态分类导航 | `POST /wallpaper/static/cate_nav_v2` |
| 动态分类导航 | `POST /wallpaper/live/cate_nav_v2` |
| 壁纸详情（传 `wid`，不是 `id`） | `POST /wallpaper/static/detail` |
| 订阅列表（需登录，游客态返回 need login） | `POST /v1/subscribe/wplist/fetch` |

## 备用域名与图床

- API 备用域名：`https://360-wallpaper-api.yuanqidesk.com`、
  `https://api-multi-channel-2-wallpaper.yuanqidesk.com`
- 图床（内容相同）：`img-baofun.zhhainiao.com`、`cdn-img-wallpaper.yuanqidesk3.com`

## 频控

有频控，过快会返回业务码 `4001007 request frequency is too fast`。
脚本内置每页间隔 0.35s；手工调用时请保持 ≥0.35s 的请求间隔。

## 命令示例

```bash
# 风景分类，8 页（约 192 条候选），只要 4K
python scripts/wallpaper_harvester.py api yuanqi --cid 1 --pages 8 --sort 2 --min-width 3840

# 动漫分类按使用量排序
python scripts/wallpaper_harvester.py api yuanqi --cid 2 --sort 4 --pages 5

# 动态壁纸（MP4）
python scripts/wallpaper_harvester.py api yuanqi --live --cid 1 --pages 3
```
