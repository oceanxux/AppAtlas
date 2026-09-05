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
TG_HELP = ("🤖 <b>App Atlas 查价机器人</b>\n\n"
           "• 发送 <b>App 名称</b> → 搜索应用\n"
           "• 发送 <b>App ID</b>（纯数字或 id 开头）→ 各区订阅最低价\n"
           "• 数据来自本机 AppAtlas 服务，快查 8 区，结果为参考价")

# 需要鉴权的数据接口(受"接口需密钥"开关控制)
API_DATA_PATHS = ("/api/search", "/api/lookup", "/api/iap", "/api/top", "/api/fx")
# 始终开放:页面本体、健康检查、登录态查询
API_OPEN_PATHS = ("/", "/index.html", "/health", "/api/me")
