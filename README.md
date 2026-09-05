# 🌍 App Atlas — App Store 全球比价工具

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey.svg)]()

一键查看 **App Store 应用及内购订阅** 在全球 175 个国家的价格对比。实测可拿到 ChatGPT Plus / Pro、Spotify、Notion、Bumble 等任意 App 的实时订阅价格。

> 运行脚本或 Docker 部署 → 浏览器自动打开 → 搜索 App → 看各国订阅价格对比、历史走势、多 App 横评，还能让 Telegram 机器人帮你查价、价格变动主动推送通知。

## ✨ 功能特性

- 💎 **内购 / 订阅跨国比价**：自动并发查询 30 国（可改为 175 国），按订阅套餐分类，显示原币价、折算 CNY/USD、与最低价的百分比差
- 📱 **应用本身价格**：一次性买断价跨区对比（Minecraft、Procreate 等付费 App）
- 📈 **历史价格折线图**：180 天快照，多国多线 + 悬停 tooltip
- 📊 **家族大表**：一张表横向看同一 App 的多档订阅在所有国家/地区的价格
- ⚖️ **多 App 横评**：监控列表多选，跨 App 跨国大表（ChatGPT vs YouTube vs Notion）
- 🔔 **价格监控**：定时比对报价，降价/涨价/新增/移除套餐自动推送
- 🤖 **Telegram 查价机器人**：发名称出搜索、发 ID/链接出各区最低价，支持 `/s /b /n /j /g` 指令与内联按钮点选（见下方专节）
- 🔑 **账号系统**：注册 / 登录 / 管理员，支持 API 密钥与接口鉴权门
- 🌙 深色模式 + 中英双语 UI + CSV 导出 + 实时汇率

## 🚀 快速开始

### 前置要求

- **Python 3.9+**（仅用标准库，无需 `pip install` 任何东西）
  - macOS：终端 `python3 --version`（系统通常自带）
  - Windows：[python.org](https://www.python.org/downloads/) 下载安装，务必勾选 ✅ **Add Python to PATH**

### macOS

1. 下载本仓库 ZIP（`Code` → `Download ZIP`），解压
2. 进入文件夹，终端运行：
   ```bash
   python3 AppPriceTracker.py
   ```
3. 浏览器自动打开 `http://localhost:8765`
4. 关闭：在终端窗口按 **Ctrl+C**

### Windows

1. 下载并解压本仓库 ZIP
2. 在文件夹里打开 cmd，运行：
   ```bat
   python AppPriceTracker.py
   ```
3. 浏览器自动打开
4. 关闭：直接关掉 cmd 窗口

> 想要双击启动可自建 `.command` / `.bat` 脚本（各 3 行，调用上面的命令即可），此类本地工具不入库。

## 🐳 Docker 部署

镜像由 GitHub Actions 自动构建并发布：`ghcr.io/oceanxux/appatlas:latest`（amd64 + arm64 双架构），服务器部署**无需克隆仓库**：

```bash
# 1. 只取 compose 文件
mkdir app-atlas && cd app-atlas
curl -O https://raw.githubusercontent.com/oceanxux/AppAtlas/main/docker-compose.yml

# 2. 启动
docker compose up -d

# 3. 更新到最新版
docker compose pull && docker compose up -d

# 日志 / 停止
docker compose logs -f
docker compose down
```

- 访问 `http://服务器IP:8765`（端口在 compose 的 `ports` 里改）
- 账号（users.json）与缓存（cache.json）持久化在 `./data` 目录，重建容器不丢失
- 默认管理员 `admin / admin123`，**公网部署请立即在右上角「用户」面板改密码**
- 若 Packages 未设为 Public，先在服务器 `docker login ghcr.io -u oceanxux`（密码用带 `read:packages` 权限的 PAT）

本地构建（开发调试）：

```bash
git clone https://github.com/oceanxux/AppAtlas.git && cd AppAtlas
# 编辑 docker-compose.yml：注释 image 行、取消 build: . 行注释
docker compose up -d --build
```

## 👤 账号系统

- **注册 / 登录**：默认开放注册；登录后解锁监控列表、家族大表、多 App 对比、历史走势与 CSV 导出
- **默认管理员** `admin / admin123`（首次启动自动创建 `users.json`，可用环境变量 `APT_ADMIN_PASSWORD` 覆盖）
- **管理员**可在右上角「用户」面板：授管理员、重置密码、删号、开关注册、配置接口鉴权门

## 🤖 Telegram 机器人使用

App Atlas 内置两个 Telegram 能力，**共用同一个 Bot Token**：

1. **价格监控推送** —— 监控的 App 价格变动时，主动推消息给你
2. **查价机器人** —— 你主动给机器人发 App 名称 / ID，它回你价格

### 第 1 步：创建机器人（拿 Token）

1. 打开 Telegram，搜索并打开 **[@BotFather](https://t.me/BotFather)**
2. 发送 `/newbot`
3. 按提示输入**显示名称**（如 `App Atlas 查价`），再输入**用户名**（必须以 `bot` 结尾，如 `my_app_atlas_bot`）
4. BotFather 回复一条消息，其中 `Use this token to access the HTTP API:` 后面的那串就是 Token，形如：
   ```
   123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```

### 第 2 步：获取你的 Chat ID

机器人和推送都需要知道往哪个会话发。二选一即可：

- **方法 A（推荐，消息可见）**：先给刚创建的机器人随便发一条消息（`/start`），然后用浏览器打开：
  ```
  https://api.telegram.org/bot<你的TOKEN>/getUpdates
  ```
  返回的 JSON 里，`result[].message.chat.id` 就是你的 Chat ID（数字，如 `987654321`）。

- **方法 B（拿自己的 user ID）**：在 Telegram 搜 [@userinfobot](https://t.me/userinfobot)，给它发 `/start`，它直接回你的 `Id:`。

### 第 3 步：在 App Atlas 里配置

1. 登录后，点击右上角 **「监控通知」** 页
2. 在 **Telegram** 渠道中填入 **Bot Token** 与 **Chat ID**
3. 点 **保存**，再点 **测试**，收到测试消息即配置成功

保存后约 **30 秒**，查价机器人自动上线。

### 第 4 步：使用查价机器人

**搜索应用** —— 发 App 名称即可，结果带的按钮**直接点选**，无需手动输入 ID：

```
/s ChatGPT             搜索应用（可加区码：/s us ChatGPT）
```

**查询指令**（均支持 App ID 或 App Store 链接，可加区码查单地区）：

| 指令 | 作用 | 示例 |
|---|---|---|
| `/n` | 💎 各区订阅最低价（默认 8 区快查） | `/n 6448311069` · `/n tr 6448311069` |
| `/b` | 💰 本体买断价格 | `/b 308111628` · `/b us 308111628` |
| `/j` | 📝 应用简介 | `/j 6448311069` |
| `/g` | 🆕 版本更新说明 | `/g 6448311069` |
| `/s` | 📱 搜索 /（对 ID、链接时）显示应用信息卡 | `/s ChatGPT` · `/s 6448311069` |

**快捷用法**：

- 直接发 **App 名称** → 搜索；发 **App ID 或 App Store 链接** → 订阅最低价
- **回复**任意含应用链接/ID 的消息并带指令，可直接调用：回复链接并发 `/n`
- 搜索结果点下方按钮选择 App（点选 = 查订阅最低价）
- 所有查询结果末尾附带 **「🔗 打开 App Store」跳转链接**，以及订阅/本体/简介/更新四个后续操作按钮

### 会话权限（重要）

- 配置了 **Chat ID** 时：机器人**只响应那个 Chat** 的消息，其他人发消息会被忽略（推荐）；绑定成功后会收到一条使用说明
- 未配置 Chat ID 时：任何给这个机器人发消息的人都能查价。**公网部署且在意消耗时，务必填 Chat ID**

### 会话权限（重要）

- 配置了 **Chat ID** 时：机器人**只响应那个 Chat** 的消息，其他人发消息会被忽略（推荐）
- 未配置 Chat ID 时：任何给这个机器人发消息的人都能查价。**公网部署且在意消耗时，务必填 Chat ID**

## 🔔 价格监控与推送渠道

详情页点「监控」配置通知：

- **触发条件**：降价 / 涨价 / 新增套餐 / 移除套餐（可限定套餐与区域）
- **轮询间隔**：`MONITOR_HOURS` 环境变量，默认 6 小时
- **推送渠道**（「监控通知」页配置，可同时启用多个）：
  - **Telegram** —— `bot_token` + `chat_id`（与查价机器人共用）
  - **Bark（iOS）** —— `device_key`（+ 可选自建 `server`，默认官方 `api.day.app`）
  - **HTTP Webhook** —— 任意 `url`，收到 `{"app","events":[...]}` JSON POST

## 🔌 API 接口

Base URL：`http://127.0.0.1:8765`。登录后调用受保护接口带请求头 `X-Auth-Token: <token>`；数据类接口也可改用 `X-API-Key`（网页「API」页创建，形如 `atlas_live_...`）。

### 数据接口

| 方法 | 路径 | 参数 | 说明 |
|---|---|---|---|
| GET | `/api/search` | `q` 关键词/App ID/链接；`country` 区码（默认 us） | 搜索应用（含 `description` 简介）|
| GET | `/api/lookup` | `id` App ID；`country` 区码 | 应用信息与买断价 |
| GET | `/api/iap` | `id` App ID；`country` 区码 | 内购/订阅价格（未上架返回 `{"ok":false,"reason":"not_listed"}`）|
| GET | `/api/top` | 无 | 首页「热门订阅 App」清单 |
| GET | `/api/fx` | 无 | 实时汇率（USD 基准）|
| GET | `/health` | 无 | 健康检查 `{"ok":true,"ts":...}` |

`/api/iap` 返回结构（节选）：

```json
{
  "country": "tr", "ok": true, "appName": "ChatGPT",
  "iaps": [{
    "iapId": "6448311597", "name": "ChatGPT Plus", "isSubscription": true,
    "groupName": "ChatGPT Plan", "currencyCode": "TRY",
    "price": 499.0, "priceFormatted": "₺499,00", "period": "P1M"
  }]
}
```

### 登录相关

| 方法 | 路径 | Body (JSON) | 说明 |
|---|---|---|---|
| POST | `/api/login` | `{"username","password"}` | 登录，返回 `token`、`role` |
| POST | `/api/register` | `{"username","password"}` | 注册并自动登录（用户名 2-32 位，密码 ≥6 位）|
| POST | `/api/logout` | - | 登出（服务端销毁会话）|
| POST | `/api/password` | `{"old_password","new_password"}` | 修改自己的密码 |
| GET | `/api/me` | - | 当前登录态 |

token 有效期 7 天（内存态，服务重启后需重新登录）。

### 监控 / 渠道 / 密钥（需登录）

| 方法 | 路径 | Body (JSON) | 说明 |
|---|---|---|---|
| GET / POST | `/api/watch` / `/api/watch/save` / `/api/watch/delete` | `{"app_id","name","icon","triggers","offers","regions"}` | 监控列表增删查 |
| GET | `/api/notifications` | - | 最近 100 条价格变动事件 |
| GET / POST | `/api/channels` / `/api/channels/save` / `/api/channels/test` | `{"type","config"}` | 推送渠道：`tg`→`{"bot_token","chat_id"}`；`bark`→`{"device_key","server"}`；`http`→`{"url"}` |
| GET / POST | `/api/keys` / `/api/keys/create` / `/api/keys/delete` | `{"name"}` / `{"id"}` | API 密钥管理 |

### 管理员接口（请求头需管理员 token）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/users` | 用户列表 + 注册/鉴权门开关状态 |
| POST | `/api/users/create` / `set_role` / `delete` / `set_password` | 用户管理 |
| POST | `/api/config/set` | `{"allow_register":true}` 开放注册；`{"require_api_key":true\|false\|"auto"}` 接口鉴权门 |

### 接口鉴权门

数据接口（search / lookup / iap / top / fx）的开放程度由「用户」面板的『接口需密钥』开关控制：

- **自动（默认）**：监听 `127.0.0.1` 时开放（本机自用零门槛）；`HOST=0.0.0.0` 或 Docker 公网部署时自动要求登录会话或 `X-API-Key`
- **手动覆盖**：面板勾选 = 强制要求，取消 = 强制开放，「自动」恢复默认
- 被拦截时返回 `401 {"ok":false,"error":"api_key_required"}`

### 调用示例

```bash
BASE=http://127.0.0.1:8765

# 搜索应用
curl "$BASE/api/search?q=chatgpt&country=us"

# 查询 ChatGPT 在土耳其的内购价格
curl "$BASE/api/iap?id=6448311069&country=tr"

# 登录拿 token
TOKEN=$(curl -s -X POST $BASE/api/login -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")

# 带 token 查用户列表（管理员）
curl "$BASE/api/users" -H "X-Auth-Token: $TOKEN"

# 或改用 API 密钥（网页「API」页创建，适合长期脚本）
curl "$BASE/api/iap?id=6448311069&country=us" -H "X-API-Key: atlas_live_xxx"
```

错误格式统一为 `{"ok":false,"error":"<code>"}`，常见 code：`bad_credentials`、`user_exists`、`password_short`、`register_disabled`、`cannot_modify_self`、`last_admin`、`api_key_required`。

## ⚙️ 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `PORT` | `8765` | 监听端口 |
| `HOST` | `127.0.0.1` | 监听地址（Docker 内 `0.0.0.0`；非回环地址会自动开启鉴权门）|
| `APT_DATA_DIR` | 脚本所在目录 | 账号 / 缓存 / 监控数据目录（Docker 挂卷用）|
| `APT_ADMIN_PASSWORD` | 无 | 首次创建 users.json 时 admin 的密码 |
| `NO_BROWSER` | 无 | 设为 `1` 不自动打开浏览器 |
| `MONITOR_HOURS` | `6` | 价格监控轮询间隔（小时）|

## 🔧 技术原理

### 数据源

1. **iTunes Search API** — 应用搜索 + 应用本身价格（公开免费）
2. **`apps.apple.com/api/apps/v1/...`** — App Store 网页内部 API，取内购/订阅价格。有 same-origin 限制，所以**必须有本地后端转发**（不需要 token、不被 IP 区域重定向）
3. **汇率** — 主用 `open.er-api.com`（ECB 数据、免 key），兜底 `@fawazahmed0/currency-api` CDN 镜像，缓存 6 小时

### 架构

```
浏览器 (UI) ←→ http://localhost:8765 (Python 后端) ←→ Apple APIs
                    │
                    ├─ monitor：定时比对监控 App 报价 → TG/Bark/Webhook 推送
                    └─ tgbot：Telegram 查价机器人（发名称出搜索，发 ID 出各区最低价）
```

后端为 `appatlas/` 包（`server` 路由 · `store` 用户/鉴权 · `apple` 苹果接口 · `monitor` 监控 · `tgbot` 机器人 · `fx` 汇率 · `notify` 推送 · `cache` 缓存 · `config` 配置），全部标准库；前端为单文件 HTML + JS（无外部库依赖）。

## 📦 文件清单

| 文件 | 说明 |
|---|---|
| `AppPriceTracker.py` | 一键启动入口（薄封装，调用 `appatlas.server.main`）|
| `appatlas/` | 后端包（9 个模块，纯标准库）|
| `AppPriceTracker.html` | 前端（单文件 HTML+JS，深色模式自适应）|
| `tests/` | pytest 测试（鉴权门 / 用户存储 / 监控差分 / TG 回复）|
| `requirements.txt` | 运行时零依赖；仅列出开发用 pytest |
| `Dockerfile` / `docker-compose.yml` | Docker 部署（含日志轮转上限）|
| `.github/workflows/docker.yml` | GitHub Actions 自动构建镜像（amd64 + arm64）|

开发 & 测试：

```bash
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest tests/ -q
```

## ⚠️ 注意事项

- **同时只能跑一个实例**（端口 8765 占用）
- **iTunes API 限速 ~20 calls/min**：默认并发 5，30 国查询约 10 秒
- **某些地区显示「未上架」是真实情况**（如 ChatGPT Pro 在中国大陆/香港未上架）
- **数据精确到原币种**，跨国比价用实时汇率换算（每 6 小时刷新一次）

## 🐛 常见问题

**Q: 端口被占用？** 设环境变量 `PORT=8766`，或改 `AppPriceTracker.py` 顶部的默认值。

**Q: 公司网络拦截了某个 API？** 看启动窗口报错。若 `apps.apple.com` 被拦，订阅查询会失败但应用本身价格仍可用。

**Q: macOS 提示"未签名"？** 右键文件 → 打开 → 安全提示里点"打开"。本项目本地运行，请放心。

**Q: 换 App 之后查询很慢？** 正常。30 国 × 1 次 API 调用，并发 5 路约 8-15 秒。

**Q: Telegram 机器人不回复？** 确认 Bot Token 填对、已保存，保存后等 ~30 秒；填了 Chat ID 的话，确认发消息的就是那个 Chat。

## 🎯 推荐试用

| 应用 | App ID | 看点 |
|---|---|---|
| ChatGPT | 6448311069 | Plus / Go / Pro 多档订阅 |
| Spotify | 324684580 | 全球 Premium 价差 |
| Notion | 1232780281 | Personal Pro 订阅 |
| Bumble | 930441707 | Boost / Premium |
| YouTube | 544007664 | YT Premium 订阅 |

## 📜 License

[MIT](LICENSE) © 2026 paradossio

## 🙏 致谢

- [fork 大佬](https://github.com/paradossio/AppPriceTracker-iOS)
- [Apple iTunes Search API](https://performance-partners.apple.com/search-api)
- [@fawazahmed0/currency-api](https://github.com/fawazahmed0/exchange-api) — 免费汇率 CDN
- [BestLemoon/ApplePriceTracker](https://github.com/BestLemoon/ApplePriceTracker) — App Store IAP 解析思路启发

发现 bug 或想加新功能？欢迎 [开 issue](../../issues) 或 PR。