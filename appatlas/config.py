# -*- coding: utf-8 -*-
"""环境变量与常量。所有可调参数集中在这里。"""
import os
from pathlib import Path

# 包目录的上一级 = 项目根(HTML 与默认数据目录所在)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
HTML_FILE = PROJECT_ROOT / "AppPriceTracker.html"

PORT = int(os.environ.get("PORT", "8765"))
HOST = os.environ.get("HOST", "127.0.0.1")

# 账号与缓存数据目录(Docker 里挂卷用:APT_DATA_DIR=/app/data)
DATA_DIR = Path(os.environ.get("APT_DATA_DIR", PROJECT_ROOT))
USERS_FILE = DATA_DIR / "users.json"
CACHE_FILE = DATA_DIR / "cache.json"
MONITOR_FILE = DATA_DIR / "monitor.json"      # app_id → 最近一次报价快照
NOTIF_FILE = DATA_DIR / "notifications.json"  # username → [事件]

# 登录会话有效期(内存态,重启后需重新登录)
SESSION_TTL = 7 * 86400

# 价格监控轮询间隔(小时)
MONITOR_HOURS = float(os.environ.get("MONITOR_HOURS", "6"))

# Apple 接口全局限速(秒/次),避免突发触发 429
APPLE_MIN_INTERVAL = 0.25

# Apple 结果缓存条目上限(超出时按过期时间淘汰)
CACHE_MAX = 2000

# 首页"热门订阅 App"策划清单(顺序即展示顺序;元数据每日自动刷新)
TOP_SUBSCRIPTION_APPS = [
    "6448311069",  # ChatGPT
    "6473753684",  # Claude by Anthropic
    "6477489729",  # Google Gemini
    "6670324846",  # Grok AI
    "324684580",   # Spotify
    "363590051",   # Netflix
    "544007664",   # YouTube
    "686449807",   # Telegram
    "414478124",   # WeChat
    "932747118",   # Shadowrocket
]

# 价格监控默认覆盖区(用户未勾选地区时)
DEFAULT_MONITOR_REGIONS = ["US", "CN", "HK", "TW", "JP", "KR", "SG", "MY", "TH",
                           "VN", "PH", "ID", "IN", "PK", "TR", "AE", "SA", "GB",
                           "DE", "FR", "IT", "ES", "RU", "BR", "MX", "AR", "CA",
                           "AU", "NG", "ZA"]

TYPE_LABEL = {"drop": "📉 降价", "raise": "📈 涨价",
              "new": "🆕 新增套餐", "remove": "➖ 移除套餐"}

# TG 查价机器人快查区(控制在 ~8 区,保证回复速度)
TG_QUICK_REGIONS = ["US", "CN", "TR", "IN", "AR", "PK", "NG", "BR"]
PERIOD_LABEL = {"ONCE": "买断", "P1W": "周付", "P1M": "月付", "P3M": "季付",
                "P6M": "半年付", "P1Y": "年付"}

# 同步到 Telegram 的命令菜单(输入 / 时弹出);描述 ≤256 字符
TG_COMMANDS = [
    {"command": "s", "description": "搜索应用 / 查看应用信息"},
    {"command": "n", "description": "各区订阅最低价"},
    {"command": "b", "description": "本体买断价格"},
    {"command": "j", "description": "应用简介"},
    {"command": "g", "description": "版本更新说明"},
    {"command": "help", "description": "使用说明"},
]
TG_HELP = (
    "📱 <b>App Atlas 查价机器人</b>\n\n"
    "<b>搜索应用</b>\n"
    "/s ChatGPT\n"
    "/s us ChatGPT（指定区码搜索）\n"
    "/s 6448311069 · /s https://apps.apple.com/app/id6448311069\n\n"
    "<b>查询指令</b>（支持 App ID 或 App Store 链接）\n"
    "/n 6448311069 — 💎 各区订阅最低价\n"
    "/b 6448311069 — 💰 本体价格\n"
    "/j 6448311069 — 📝 应用简介\n"
    "/g 6448311069 — 🆕 版本更新说明\n\n"
    "<b>快捷用法</b>\n"
    "• 指令可加区码：/n tr 6448311069（仅查土耳其）\n"
    "• 回复任意应用链接/ID 消息 + 指令，可直接调用：回复链接并发 /n\n"
    "• 直接发 <b>名称</b> 搜索、发 <b>ID/链接</b> 出订阅最低价\n"
    "• 搜索结果点下方按钮即可选择 App，无需手动输入 ID\n\n"
    "<i>数据来自本机 App Atlas 服务；订阅/本体默认 8 区快查，"
    "完整比价请用网页端</i>"
)

# 需要鉴权的数据接口(受"接口需密钥"开关控制)
API_DATA_PATHS = ("/api/search", "/api/lookup", "/api/iap", "/api/top", "/api/fx")
# 始终开放:页面本体、健康检查、登录态查询
API_OPEN_PATHS = ("/", "/index.html", "/health", "/api/me")
