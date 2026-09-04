#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
App Store 全球比价工具 — 本地后端
========================================
功能:
  • 应用搜索 (iTunes Search API)
  • 应用本身价格跨地区对比 (iTunes Lookup API, JSONP)
  • 内购订阅价格跨地区对比 (apps.apple.com 内部 API)
  • 实时汇率换算

技术:
  • 仅使用 Python 标准库 (无需 pip install)
  • 本地 HTTP 服务，监听 127.0.0.1:8765
  • 启动后自动打开浏览器
  • 关闭：在终端窗口按 Ctrl+C
"""
import gzip
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import threading
import time
import webbrowser
import urllib.request
import urllib.parse
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from pathlib import Path

# HOST / PORT 可用环境变量覆盖（Docker 里 HOST=0.0.0.0 PORT=8765）
PORT = int(os.environ.get("PORT", "8765"))
HOST = os.environ.get("HOST", "127.0.0.1")
SCRIPT_DIR = Path(__file__).resolve().parent
HTML_FILE = SCRIPT_DIR / "AppPriceTracker.html"
# 账号与缓存数据目录（Docker 里挂卷用：APT_DATA_DIR=/app/data）
DATA_DIR = Path(os.environ.get("APT_DATA_DIR", SCRIPT_DIR))
USERS_FILE = DATA_DIR / "users.json"
CACHE_FILE = DATA_DIR / "cache.json"

# 登录会话（内存态，重启后需重新登录）
SESSIONS = {}          # token -> {"user": str, "ts": float}
SESSION_TTL = 7 * 86400
USER_LOCK = threading.Lock()

# 首页"热门订阅 App"策划清单（顺序即展示顺序；元数据每日自动刷新）
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

# ---------------- 内购数据拉取（Handler 与监控线程共用） ----------------
def fetch_iap_data(aid, cc):
    """内购/订阅数据：per-key 锁防击穿，成功缓存 6 小时。网络错误返回 None。"""
    key = f"iap:{aid}:{cc}"

    def _fetch():
        apple_throttle()
        u = (f"https://apps.apple.com/api/apps/v1/catalog/{cc}/apps/{aid}"
             f"?platform=web&views=top-in-app-purchasables&l=en-us")
        headers = {
            "Authorization": "Bearer",
            "Referer": f"https://apps.apple.com/{cc}/app/id{aid}",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "application/json",
        }
        try:
            raw = http_get_json(u, headers=headers, timeout=15)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"country": cc, "ok": False, "reason": "not_listed"}
            return None
        except Exception:
            return None
        try:
            app_data = raw["data"][0]
            name = app_data["attributes"].get("name", "")
            iaps_raw = (app_data.get("views", {}).get(
                "top-in-app-purchasables", {}) or {}).get("data", [])
            iaps = []
            for x in iaps_raw:
                a = x.get("attributes", {})
                for o in (a.get("offers") or []):
                    iaps.append({
                        "iapId": x.get("id"),
                        "name": a.get("name"),
                        "offerName": a.get("offerName"),
                        "isSubscription": a.get("isSubscription", False),
                        "groupId": a.get("subscriptionFamilyId"),
                        "groupName": a.get("subscriptionFamilyName"),
                        "groupRank": a.get("subscriptionFamilyRank"),
                        "currencyCode": o.get("currencyCode"),
                        "price": o.get("price"),
                        "priceFormatted": o.get("priceFormatted"),
                        "period": o.get("recurringSubscriptionPeriod"),
                    })
            return {"country": cc, "ok": True, "appName": name, "iaps": iaps}
        except Exception as e:
            print(f"⚠️ iap parse: {e}")
            return None

    return cached_fetch(key, 6 * 3600, _fetch)

# ---------------- 价格监控（定时任务 + 通知 + TG 推送） ----------------
MONITOR_HOURS = float(os.environ.get("MONITOR_HOURS", "6"))
MONITOR_FILE = DATA_DIR / "monitor.json"      # app_id → 最近一次报价快照
NOTIF_FILE = DATA_DIR / "notifications.json"  # username → [事件]
MON_LOCK = threading.Lock()
DEFAULT_MONITOR_REGIONS = ["US", "CN", "HK", "TW", "JP", "KR", "SG", "MY", "TH",
                           "VN", "PH", "ID", "IN", "PK", "TR", "AE", "SA", "GB",
                           "DE", "FR", "IT", "ES", "RU", "BR", "MX", "AR", "CA",
                           "AU", "NG", "ZA"]
TYPE_LABEL = {"drop": "📉 降价", "raise": "📈 涨价",
              "new": "🆕 新增套餐", "remove": "➖ 移除套餐"}


def _load_json_file(path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️ {path.name} 读取失败: {e}")
    return default


def _save_json_file(path, data):
    try:
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        print(f"⚠️ {path.name} 写入失败: {e}")


def build_offers_map(aid, regions):
    """当前报价快照: offerKey → {name, period, prices:{cc:price}, currency:{cc:cur}}"""
    offers = {}
    for cc in regions:
        data = fetch_iap_data(str(aid), cc.lower())
        if not data or not data.get("ok"):
            continue
        for i in data.get("iaps", []):
            key = f"{i.get('iapId')}::{i.get('period') or 'ONCE'}"
            o = offers.setdefault(key, {
                "name": i.get("name") or i.get("offerName") or key,
                "period": i.get("period") or "ONCE",
                "prices": {}, "currency": {}})
            o["prices"][cc.upper()] = i.get("price")
            o["currency"][cc.upper()] = i.get("currencyCode")
    return offers


def diff_watch(prev, current, watch):
    """对比上次快照，按 watch 的触发条件生成事件列表。首次只记基线不报事件。"""
    triggers = set(watch.get("triggers") or ["drop", "raise", "new", "remove"])
    offers_f = set(watch.get("offers") or [])
    regions_f = set(watch.get("regions") or [])
    events = []
    now = int(time.time())

    def ok_region(cc): return not regions_f or cc in regions_f
    def ok_offer(key): return not offers_f or key in offers_f

    if not prev:
        return events
    for key, cur in current.items():
        if not ok_offer(key):
            continue
        old = prev.get(key)
        if old is None:
            if "new" in triggers:
                events.append({"ts": now, "type": "new", "offer": cur["name"],
                               "period": cur["period"], "detail": "新增套餐"})
            continue
        for cc, price in cur["prices"].items():
            if price is None or not ok_region(cc):
                continue
            oldp = old["prices"].get(cc)
            if oldp in (None, 0) or price in (None, 0) or price == oldp:
                continue
            ev = {"ts": now, "offer": cur["name"], "period": cur["period"],
                  "region": cc, "old": oldp, "new": price,
                  "currency": cur["currency"].get(cc, "")}
            if price < oldp and "drop" in triggers:
                events.append({**ev, "type": "drop"})
            elif price > oldp and "raise" in triggers:
                events.append({**ev, "type": "raise"})
    if "remove" in triggers:
        for key, old in prev.items():
            if key not in current and ok_offer(key):
                events.append({"ts": now, "type": "remove",
                               "offer": old.get("name", key),
                               "period": old.get("period", ""),
                               "detail": "套餐已移除"})
    return events


def tg_send(bot_token, chat_id, text):
    if not bot_token or not chat_id:
        return False
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data=json.dumps({"chat_id": chat_id, "text": text,
                             "parse_mode": "HTML"}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=8)
        return True
    except Exception as e:
        print(f"⚠️ TG 推送失败: {e}")
        return False


def http_post_json(url, payload):
    if not url:
        return False
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=8)
        return True
    except Exception as e:
        print(f"⚠️ Webhook 推送失败: {e}")
        return False


def bark_send(cfg, title, body):
    """Bark (iOS) 推送：POST {server}/push，server 默认官方 api.day.app。"""
    key = (cfg or {}).get("device_key", "")
    if not key:
        return False
    server = ((cfg or {}).get("server") or "https://api.day.app").rstrip("/")
    try:
        req = urllib.request.Request(
            f"{server}/push",
            data=json.dumps({"device_key": key, "title": title[:64],
                             "body": body[:800], "group": "AppAtlas"}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=8)
        return True
    except Exception as e:
        print(f"⚠️ Bark 推送失败: {e}")
        return False


def push_events(rec, app_name, events):
    """把事件推送到用户配置的所有渠道（TG / Discord / HTTP Webhook）。"""
    ch = rec.get("channels") or {}
    first = TYPE_LABEL.get(events[0]["type"], "")
    html_lines = [f"<b>{first} {app_name}</b>"]
    plain_lines = [f"{first} {app_name}"]
    for e in events[:10]:
        if e["type"] in ("drop", "raise"):
            seg = f"• {e['offer']}({e['period']}) {e['region']}: {e['old']} → {e['new']} {e.get('currency','')}"
        else:
            seg = f"• {e['offer']} — {e.get('detail','')}"
        html_lines.append(seg)
        plain_lines.append(seg)
    if ch.get("tg", {}).get("bot_token") and ch["tg"].get("chat_id"):
        tg_send(ch["tg"]["bot_token"], ch["tg"]["chat_id"], "\n".join(html_lines))
    if ch.get("bark", {}).get("device_key"):
        bark_send(ch["bark"], f"{first} {app_name}", "\n".join(plain_lines[1:]) or "有新的价格变动")
    if ch.get("http", {}).get("url"):
        http_post_json(ch["http"]["url"], {"app": app_name, "events": events[:20]})


def run_monitor_pass():
    users, meta = load_users()
    jobs = {}
    for uname, rec in users.items():
        for w in rec.get("watches", []):
            jobs.setdefault(str(w.get("app_id")), []).append((uname, w))
    if not jobs:
        return
    monitor = _load_json_file(MONITOR_FILE, {})
    notifs = _load_json_file(NOTIF_FILE, {})
    changed = False
    for aid, watchers in jobs.items():
        regions = set()
        for _, w in watchers:
            regions.update(w.get("regions") or DEFAULT_MONITOR_REGIONS)
        current = build_offers_map(aid, sorted(regions))
        prev = (monitor.get(aid) or {}).get("offers")
        app_name = watchers[0][1].get("name") or aid
        for uname, w in watchers:
            events = diff_watch(prev, current, w)
            if not events:
                continue
            lst = notifs.setdefault(uname, [])
            for ev in events:
                ev.update({"app_id": aid, "app_name": app_name,
                           "icon": w.get("icon", "")})
            lst[:0] = events
            del lst[100:]
            changed = True
            push_events(users.get(uname) or {}, app_name, events)
        monitor[aid] = {"ts": time.time(), "offers": current}
        changed = True
        time.sleep(1)  # App 之间歇一下，配合全局节流
    if changed:
        _save_json_file(MONITOR_FILE, monitor)
        _save_json_file(NOTIF_FILE, notifs)


def monitor_loop():
    time.sleep(45)
    while True:
        try:
            run_monitor_pass()
        except Exception as e:
            print(f"⚠️ 监控任务异常: {e}")
        time.sleep(MONITOR_HOURS * 3600)


def get_apikey_user(headers):
    """X-API-Key → username。命中则顺带更新 last_used（每小时最多写一次盘）。"""
    key = headers.get("X-API-Key", "")
    if not key:
        return None
    users, meta = load_users()
    for uname, rec in users.items():
        for k in rec.get("api_keys", []):
            if k.get("key") == key:
                now = int(time.time())
                if now - (k.get("last_used") or 0) > 3600:
                    with USER_LOCK:
                        k["last_used"] = now
                        save_users(users, meta)
                return uname
    return None

# Apple API 结果缓存: key -> {"expires": ts, "data": obj}（内存 + 落盘，重启不丢）
CACHE = {}
CACHE_LOCK = threading.Lock()
CACHE_MAX = 2000
_cache_dirty = [False]
_cache_last_flush = [0.0]

# apps.apple.com 全局限速：所有线程共享，避免突发触发 429
APPLE_LOCK = threading.Lock()
_apple_last = [0.0]
APPLE_MIN_INTERVAL = 0.25


def apple_throttle():
    with APPLE_LOCK:
        wait = _apple_last[0] + APPLE_MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _apple_last[0] = time.monotonic()


def cache_get(key):
    with CACHE_LOCK:
        ent = CACHE.get(key)
        if not ent:
            return None
        if ent["expires"] < time.time():
            CACHE.pop(key, None)
            return None
        return ent["data"]


def cache_put(key, data, ttl):
    with CACHE_LOCK:
        if len(CACHE) >= CACHE_MAX:
            for k, _ in sorted(CACHE.items(), key=lambda kv: kv[1]["expires"])[:200]:
                CACHE.pop(k, None)
        CACHE[key] = {"expires": time.time() + ttl, "data": data}
        _cache_dirty[0] = True


def cache_flush(force=False):
    """落盘（最多每 20s 一次，避免频繁 IO）。"""
    now = time.time()
    with CACHE_LOCK:
        if not _cache_dirty[0] or (not force and now - _cache_last_flush[0] < 20):
            return
        _cache_dirty[0] = False
        _cache_last_flush[0] = now
        try:
            CACHE_FILE.write_text(json.dumps(CACHE), encoding="utf-8")
        except OSError as e:
            print(f"⚠️ cache.json 写入失败: {e}")


def cache_load():
    if CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            now = time.time()
            for k, v in data.items():
                if isinstance(v, dict) and v.get("expires", 0) > now:
                    CACHE[k] = v
            print(f"📦 已加载磁盘缓存 {len(CACHE)} 条")
        except Exception as e:
            print(f"⚠️ cache.json 读取失败: {e}")


def _hash_password(salt, password):
    return hashlib.sha256((salt + ":" + password).encode("utf-8")).hexdigest()


def load_users():
    """读取 users.json → (users, meta)。不存在则创建默认 admin 账号。

    格式: {"_meta": {"allow_register": true}, "users": {"名": {"salt","hash","role","created_at"}}}
    兼容旧版平铺格式（无 "users" 键），旧账号一律视为 admin。
    """
    if not USERS_FILE.exists():
        salt = secrets.token_hex(8)
        pw = os.environ.get("APT_ADMIN_PASSWORD", "admin123")
        users = {"admin": {"salt": salt, "hash": _hash_password(salt, pw),
                           "role": "admin", "created_at": int(time.time())}}
        save_users(users, {"allow_register": True})
        hint = "APT_ADMIN_PASSWORD 环境变量的值" if os.environ.get("APT_ADMIN_PASSWORD") \
            else "admin123（登录后请在「用户管理」中修改，或设置 APT_ADMIN_PASSWORD 后删除 users.json 重新生成）"
        print(f"\n👤 已创建管理员账号: admin / {hint}")
        print(f"   开放注册可在网页右上角「用户」面板中开关\n")
    try:
        data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️ users.json 解析失败: {e}")
        return {}, {"allow_register": True}
    if "users" not in data:  # 旧版平铺格式迁移
        data = {"_meta": data.get("_meta", {}),
                "users": {k: v for k, v in data.items() if k != "_meta"}}
    meta = data.get("_meta") or {}
    meta.setdefault("allow_register", True)
    users = data.get("users") or {}
    for name, rec in users.items():
        rec.setdefault("role", "admin" if name == "admin" else "user")
        rec.setdefault("api_keys", [])
        rec.setdefault("watches", [])
        rec.setdefault("channels", {})
        if rec.get("tg"):  # 旧版单 TG 配置迁移到 channels
            rec["channels"].setdefault("tg", rec.pop("tg"))
    return users, meta


def save_users(users, meta):
    USERS_FILE.write_text(json.dumps(
        {"_meta": meta, "users": users}, indent=2, ensure_ascii=False), encoding="utf-8")


def check_login(username, password):
    users, _ = load_users()
    rec = users.get(username)
    if not rec:
        hmac.compare_digest("x", "y")  # 用户不存在也做一次比较，避免时序侧信道
        return None
    if hmac.compare_digest(rec["hash"], _hash_password(rec.get("salt", ""), password)):
        return rec
    return None


def issue_token(username):
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = {"user": username, "ts": time.time()}
    return token


def get_session(headers):
    """校验 X-Auth-Token → {"username", "role"} | None。角色实时读 users.json。"""
    token = headers.get("X-Auth-Token", "")
    sess = SESSIONS.get(token)
    if not sess:
        return None
    if time.time() - sess["ts"] > SESSION_TTL:
        SESSIONS.pop(token, None)
        return None
    sess["ts"] = time.time()
    users, _ = load_users()
    rec = users.get(sess["user"])
    return {"username": sess["user"], "role": rec.get("role", "user")} if rec else None


def count_admins(users):
    return sum(1 for r in users.values() if r.get("role") == "admin")

# 细粒度 per-key 互斥锁：同一 key 的并发未命中只放一个线程回源，
# 其余线程等锁后直接读缓存（防击穿/防重复请求）。
_KEY_LOCKS = {}
_KEY_LOCKS_GUARD = threading.Lock()


class KeyLock:
    def __init__(self, key):
        with _KEY_LOCKS_GUARD:
            lock = _KEY_LOCKS.get(key)
            if lock is None:
                lock = threading.Lock()
                _KEY_LOCKS[key] = lock
            self.lock = lock

    def __enter__(self):
        self.lock.acquire()

    def __exit__(self, *exc):
        self.lock.release()


def cached_fetch(key, ttl, fetcher, ttl_fn=None):
    """读缓存 → 未命中则拿 per-key 锁回源（双检）→ 写缓存。
    fetcher 返回 None 表示上游失败，不缓存。ttl_fn(data) 可按结果定 TTL。"""
    hit = cache_get(key)
    if hit is not None:
        return hit
    with KeyLock(key):
        hit = cache_get(key)  # 等锁期间可能已被其他线程写入
        if hit is not None:
            return hit
        data = fetcher()
        if data is not None:
            cache_put(key, data, ttl_fn(data) if ttl_fn else ttl)
        return data


UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15")

# ---------------------------------------------------------------- #
def http_get_json(url, headers=None, timeout=15, retry_delays=(1.5, 3.5, 7)):
    """通用 GET → JSON。对 429/502/503 与网络抖动做多级退避重试。"""
    last_exc = None
    for attempt in range(len(retry_delays) + 1):
        try:
            h = {"User-Agent": UA, "Accept": "application/json"}
            if headers:
                h.update(headers)
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                # 可能 gzip
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503) and attempt < len(retry_delays):
                try:
                    delay = float(e.headers.get("Retry-After") or 0)
                except (TypeError, ValueError):
                    delay = 0
                time.sleep(min(max(delay, retry_delays[attempt]), 10.0))
                last_exc = e
                continue
            raise
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
            if attempt < len(retry_delays):
                time.sleep(min(retry_delays[attempt], 3.0))
                last_exc = e
                continue
            raise
    raise last_exc


# ---------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    """单文件路由处理。"""

    def log_message(self, fmt, *args):  # 静音访问日志
        pass

    # ---------- helpers ----------
    def _send(self, body, status=200, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # 允许任意页面访问（双击 file:// 也能用）
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_html(self):
        if not HTML_FILE.exists():
            return self._send("<h1>缺少 AppPriceTracker.html</h1>", 500, "text/html")
        with open(HTML_FILE, "rb") as f:
            self._send(f.read(), 200, "text/html; charset=utf-8")

    def _err(self, msg, code=500):
        self._send({"error": str(msg)}, status=code)

    # ---------- routing ----------
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        try:
            url = urllib.parse.urlparse(self.path)
            qs = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
            path = url.path

            # ---------- HTML 主页 ----------
            if path in ("/", "/index.html"):
                return self._send_html()

            if path == "/health":
                return self._send({"ok": True, "ts": int(time.time())})

            # ---------- 0. 登录状态 ----------
            if path == "/api/me":
                info = get_session(self.headers)
                if info:
                    return self._send({"ok": True, "username": info["username"],
                                       "role": info["role"]})
                ak = get_apikey_user(self.headers)
                if ak:
                    return self._send({"ok": True, "username": ak,
                                       "role": "api_key", "via": "api_key"})
                return self._send({"ok": False})

            # ---------- 0.2 登录用户的密钥 / 监控 / 通知 / TG ----------
            if path in ("/api/keys", "/api/watch", "/api/notifications", "/api/channels"):
                info = get_session(self.headers)
                if not info:
                    return self._send({"ok": False, "error": "unauthorized"}, status=401)
                users, meta = load_users()
                rec = users.get(info["username"]) or {}
                if path == "/api/keys":
                    return self._send({"ok": True, "keys": rec.get("api_keys", [])})
                if path == "/api/watch":
                    return self._send({"ok": True, "watches": rec.get("watches", [])})
                if path == "/api/notifications":
                    notifs = _load_json_file(NOTIF_FILE, {})
                    return self._send({"ok": True,
                                       "events": notifs.get(info["username"], [])[:100]})
                return self._send({"ok": True, "channels": rec.get("channels", {})})

            # ---------- 1. 搜索应用 ----------
            if path == "/api/users":
                info = get_session(self.headers)
                if not info:
                    return self._send({"ok": False, "error": "unauthorized"}, status=401)
                users, meta = load_users()
                rec = users.get(info["username"])
                if not rec or rec.get("role") != "admin":
                    return self._send({"ok": False, "error": "forbidden"}, status=403)
                return self._send({"ok": True, "allow_register": meta.get("allow_register", True),
                                   "users": [{"username": u, "role": r.get("role", "user"),
                                              "created_at": r.get("created_at")}
                                             for u, r in sorted(users.items())]})

            # ---------- 1. 搜索应用 ----------
            if path == "/api/search":
                term = qs.get("q", "").strip()
                cc = qs.get("country", "us").lower()
                if not term:
                    return self._send({"results": [], "resultCount": 0})
                # 如果 term 是数字 ID 或 URL，走 lookup
                m = re.search(r"id(\d{6,})|^(\d{6,})$", term)
                if m:
                    aid = m.group(1) or m.group(2)
                    u = (f"https://itunes.apple.com/lookup?id={aid}"
                         f"&country={cc}&entity=software")
                else:
                    u = (f"https://itunes.apple.com/search?"
                         f"term={urllib.parse.quote(term)}"
                         f"&country={cc}&entity=software&limit=20")
                key = f"search:{cc}:{hashlib.md5(term.lower().encode()).hexdigest()}"

                def _fetch_search():
                    try:
                        return http_get_json(u)
                    except Exception:
                        return None
                data = cached_fetch(key, 86400, _fetch_search,
                                    ttl_fn=lambda x: 86400 if x.get("resultCount") else 600)
                if data is not None:
                    return self._send(data)
                return self._err("search upstream error", 502)

            # ---------- 2. 应用本身价格 (lookup, 缓存 30 分钟) ----------
            if path == "/api/lookup":
                aid = qs.get("id")
                cc = qs.get("country", "us").lower()
                if not aid:
                    return self._err("missing id", 400)
                key = f"lookup:{aid}:{cc}"

                def _fetch_lookup():
                    u = (f"https://itunes.apple.com/lookup?id={aid}"
                         f"&country={cc}&entity=software")
                    try:
                        return http_get_json(u)
                    except Exception:
                        return None
                d = cached_fetch(key, 86400, _fetch_lookup,
                                 ttl_fn=lambda x: 86400 if x.get("resultCount") else 600)
                if d is not None:
                    return self._send(d)
                return self._err("upstream error", 502)

            # ---------- 3. 内购订阅价格 (核心, 成功缓存 6 小时) ----------
            if path == "/api/iap":
                aid = qs.get("id")
                cc = qs.get("country", "us").lower()
                if not aid:
                    return self._err("missing id", 400)
                data = fetch_iap_data(aid, cc)
                if data is not None:
                    return self._send(data)
                return self._err("HTTP error from apps.apple.com", 502)

            # ---------- 3.5 热门订阅 App（人工策划清单，元数据实时拉取，缓存 24h） ----------
            # Apple 官方没有"订阅榜"，主流比价站均为人工策划；
            # 清单对齐 ChatGPT/Claude/Gemini/流媒体/社交等有订阅内购的头部 App
            if path == "/api/top":
                ck = "top:subs10:v2"
                cached = cache_get(ck)
                if cached is not None:
                    return self._send(cached)

                def _fetch_meta(aid):
                    try:
                        d = http_get_json(
                            f"https://itunes.apple.com/lookup?id={aid}"
                            f"&country=us&entity=software", timeout=8)
                        if d.get("resultCount"):
                            r = d["results"][0]
                            return {"id": str(r["trackId"]),
                                    "name": r.get("trackName", ""),
                                    "artist": r.get("artistName", ""),
                                    "icon": r.get("artworkUrl100", "")}
                    except Exception:
                        pass
                    return None

                with ThreadPoolExecutor(max_workers=4) as ex:
                    metas = list(ex.map(_fetch_meta, TOP_SUBSCRIPTION_APPS))
                apps = [m for m in metas if m]
                if apps:
                    resp = {"ok": True, "apps": apps,
                            "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                    cache_put(ck, resp, 24 * 3600)
                    cache_flush()
                    return self._send(resp)
                return self._err("top chart unavailable", 502)

            # ---------- 4. 实时汇率（USD 基准） ----------
            if path == "/api/fx":
                # 优先 er-api (免 key 稳定), 兜底 currency-api 镜像
                try:
                    d = http_get_json(
                        "https://open.er-api.com/v6/latest/USD", timeout=8)
                    if d.get("result") == "success" and d.get("rates"):
                        return self._send({
                            "base": "USD", "rates": d["rates"],
                            "date": d.get("time_last_update_utc", ""),
                        })
                except Exception:
                    pass
                for u in [
                    "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest"
                    "/v1/currencies/usd.min.json",
                    "https://latest.currency-api.pages.dev/v1/currencies/usd.json",
                ]:
                    try:
                        d = http_get_json(u, timeout=8)
                        if d.get("usd"):
                            rates = {"USD": 1.0}
                            for k, v in d["usd"].items():
                                rates[k.upper()] = v
                            return self._send({"base": "USD", "rates": rates,
                                               "date": d.get("date")})
                    except Exception:
                        continue
                return self._err("FX unavailable", 502)

            return self._send({"error": "not found"}, 404)

        except urllib.error.HTTPError as e:
            self._err(f"upstream HTTP {e.code}: {e.reason}", code=502)
        except Exception as e:
            self._err(str(e), code=500)

    # ---------- 登录 / 注册 / 登出 / 用户管理 ----------
    def _read_json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 64 * 1024:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    @staticmethod
    def _validate_new_user(username, password):
        """返回错误信息或 None。"""
        if not re.fullmatch(r"[\w\u4e00-\u9fa5\-]{2,32}", username or ""):
            return "bad_username"
        if len(password or "") < 6:
            return "password_short"
        return None

    def _require_admin(self):
        """→ (session, None) 或 (None, (body, status))"""
        info = get_session(self.headers)
        if not info:
            return None, ({"ok": False, "error": "unauthorized"}, 401)
        users, meta = load_users()
        rec = users.get(info["username"])
        if not rec or rec.get("role") != "admin":
            return None, ({"ok": False, "error": "forbidden"}, 403)
        return info, None

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        body = self._read_json_body()

        if path == "/api/login":
            username = str(body.get("username", "")).strip()
            rec = check_login(username, str(body.get("password", "")))
            if rec:
                token = issue_token(username)
                # 顺手清理过期会话
                now = time.time()
                for tk in [k for k, v in SESSIONS.items() if now - v["ts"] > SESSION_TTL]:
                    SESSIONS.pop(tk, None)
                return self._send({"ok": True, "token": token,
                                   "username": username, "role": rec.get("role", "user")})
            return self._send({"ok": False, "error": "bad_credentials"}, status=401)

        if path == "/api/register":
            username = str(body.get("username", "")).strip()
            password = str(body.get("password", ""))
            err = self._validate_new_user(username, password)
            if err:
                return self._send({"ok": False, "error": err}, status=400)
            with USER_LOCK:
                users, meta = load_users()
                if not meta.get("allow_register", True):
                    return self._send({"ok": False, "error": "register_disabled"}, status=403)
                if username in users:
                    return self._send({"ok": False, "error": "user_exists"}, status=409)
                salt = secrets.token_hex(8)
                users[username] = {"salt": salt, "hash": _hash_password(salt, password),
                                   "role": "user", "created_at": int(time.time())}
                save_users(users, meta)
            token = issue_token(username)
            return self._send({"ok": True, "token": token, "username": username, "role": "user"})

        if path == "/api/logout":
            SESSIONS.pop(self.headers.get("X-Auth-Token", ""), None)
            return self._send({"ok": True})

        if path == "/api/password":  # 修改自己的密码
            info = get_session(self.headers)
            if not info:
                return self._send({"ok": False, "error": "unauthorized"}, status=401)
            newpwd = str(body.get("new_password", ""))
            if len(newpwd) < 6:
                return self._send({"ok": False, "error": "password_short"}, status=400)
            with USER_LOCK:
                users, meta = load_users()
                rec = check_login(info["username"], str(body.get("old_password", "")))
                if not rec:
                    return self._send({"ok": False, "error": "bad_credentials"}, status=401)
                salt = secrets.token_hex(8)
                rec["salt"], rec["hash"] = salt, _hash_password(salt, newpwd)
                save_users(users, meta)
            return self._send({"ok": True})

        # ---- 以下需要管理员 ----
        if path in ("/api/users", "/api/users/create", "/api/users/set_role",
                    "/api/users/delete", "/api/users/set_password", "/api/config/set"):
            info, deny = self._require_admin()
            if deny:
                return self._send(*deny)

            if path == "/api/users":
                users, meta = load_users()
                return self._send({"ok": True, "allow_register": meta.get("allow_register", True),
                                   "users": [{"username": u, "role": r.get("role", "user"),
                                              "created_at": r.get("created_at")}
                                             for u, r in sorted(users.items())]})

            if path == "/api/users/create":
                username = str(body.get("username", "")).strip()
                password = str(body.get("password", ""))
                role = body.get("role", "user")
                err = self._validate_new_user(username, password)
                if err:
                    return self._send({"ok": False, "error": err}, status=400)
                with USER_LOCK:
                    users, meta = load_users()
                    if username in users:
                        return self._send({"ok": False, "error": "user_exists"}, status=409)
                    salt = secrets.token_hex(8)
                    users[username] = {"salt": salt, "hash": _hash_password(salt, password),
                                       "role": "admin" if role == "admin" else "user",
                                       "created_at": int(time.time())}
                    save_users(users, meta)
                return self._send({"ok": True})

            if path == "/api/users/set_role":
                username = str(body.get("username", ""))
                role = "admin" if body.get("role") == "admin" else "user"
                with USER_LOCK:
                    users, meta = load_users()
                    if username not in users:
                        return self._send({"ok": False, "error": "no_such_user"}, status=404)
                    if username == info["username"]:
                        return self._send({"ok": False, "error": "cannot_modify_self"}, status=400)
                    if users[username].get("role") == "admin" and role != "admin" \
                            and count_admins(users) <= 1:
                        return self._send({"ok": False, "error": "last_admin"}, status=400)
                    users[username]["role"] = role
                    save_users(users, meta)
                return self._send({"ok": True})

            if path == "/api/users/delete":
                username = str(body.get("username", ""))
                with USER_LOCK:
                    users, meta = load_users()
                    if username not in users:
                        return self._send({"ok": False, "error": "no_such_user"}, status=404)
                    if username == info["username"]:
                        return self._send({"ok": False, "error": "cannot_modify_self"}, status=400)
                    if users[username].get("role") == "admin" and count_admins(users) <= 1:
                        return self._send({"ok": False, "error": "last_admin"}, status=400)
                    users.pop(username)
                    save_users(users, meta)
                return self._send({"ok": True})

            if path == "/api/users/set_password":
                username = str(body.get("username", ""))
                newpwd = str(body.get("password", ""))
                if len(newpwd) < 6:
                    return self._send({"ok": False, "error": "password_short"}, status=400)
                with USER_LOCK:
                    users, meta = load_users()
                    if username not in users:
                        return self._send({"ok": False, "error": "no_such_user"}, status=404)
                    salt = secrets.token_hex(8)
                    users[username]["salt"] = salt
                    users[username]["hash"] = _hash_password(salt, newpwd)
                    save_users(users, meta)
                return self._send({"ok": True})

                if path == "/api/config/set":
                    with USER_LOCK:
                        users, meta = load_users()
                        meta["allow_register"] = bool(body.get("allow_register"))
                        save_users(users, meta)
                    return self._send({"ok": True, "allow_register": meta["allow_register"]})

        # ---- 登录用户的写操作：密钥 / 监控 / TG ----
        if path in ("/api/keys/create", "/api/keys/delete", "/api/watch/save",
                    "/api/watch/delete", "/api/channels/save", "/api/channels/test"):
            info = get_session(self.headers)
            if not info:
                return self._send({"ok": False, "error": "unauthorized"}, status=401)
            with USER_LOCK:
                users, meta = load_users()
                rec = users.get(info["username"])
                if not rec:
                    return self._send({"ok": False, "error": "no_such_user"}, status=404)

                if path == "/api/keys/create":
                    name = str(body.get("name", "")).strip()[:32] or "key"
                    kid = secrets.token_hex(4)
                    key = "atlas_live_" + secrets.token_urlsafe(24)
                    rec.setdefault("api_keys", []).append(
                        {"id": kid, "name": name, "key": key,
                         "created_at": int(time.time()), "last_used": 0})
                    save_users(users, meta)
                    return self._send({"ok": True,
                                       "key": {"id": kid, "name": name, "key": key}})

                if path == "/api/keys/delete":
                    kid = str(body.get("id", ""))
                    rec["api_keys"] = [k for k in rec.get("api_keys", [])
                                       if k.get("id") != kid]
                    save_users(users, meta)
                    return self._send({"ok": True})

                if path == "/api/watch/save":
                    aid = str(body.get("app_id", ""))
                    if not aid.isdigit():
                        return self._send({"ok": False, "error": "missing app_id"},
                                          status=400)
                    w = {"app_id": aid,
                         "name": str(body.get("name", ""))[:80],
                         "icon": str(body.get("icon", ""))[:300],
                         "triggers": [t for t in (body.get("triggers") or [])
                                      if t in ("drop", "raise", "new", "remove")],
                         "offers": [str(x) for x in (body.get("offers") or [])][:60],
                         "regions": [str(x).upper()[:2] for x in (body.get("regions") or [])][:60],
                         "created_at": int(time.time())}
                    if not w["triggers"]:
                        w["triggers"] = ["drop", "raise", "new", "remove"]
                    watches = [x for x in rec.setdefault("watches", [])
                               if str(x.get("app_id")) != aid]
                    watches.insert(0, w)
                    rec["watches"] = watches[:30]
                    save_users(users, meta)
                    return self._send({"ok": True})

                if path == "/api/watch/delete":
                    aid = str(body.get("app_id", ""))
                    rec["watches"] = [x for x in rec.get("watches", [])
                                      if str(x.get("app_id")) != aid]
                    save_users(users, meta)
                    return self._send({"ok": True})

                if path == "/api/channels/save":
                    ctype = str(body.get("type", ""))
                    cfg = dict(body.get("config") or {})
                    if ctype == "tg":
                        cfg = {"bot_token": str(cfg.get("bot_token", ""))[:64],
                               "chat_id": str(cfg.get("chat_id", ""))[:32]}
                    elif ctype == "bark":
                        device_key = str(cfg.get("device_key", ""))[:80]
                        server = str(cfg.get("server", ""))[:200]
                        if server and not server.startswith("http"):
                            return self._send({"ok": False, "error": "bad_server_url"}, status=400)
                        if not device_key:
                            return self._send({"ok": False, "error": "missing device_key"}, status=400)
                        cfg = {"device_key": device_key, "server": server}
                    elif ctype == "http":
                        url = str(cfg.get("url", ""))[:300]
                        if url and not url.startswith("http"):
                            return self._send({"ok": False, "error": "bad_webhook_url"}, status=400)
                        cfg = {"url": url}
                    else:
                        return self._send({"ok": False, "error": "bad_channel"}, status=400)
                    rec.setdefault("channels", {})[ctype] = cfg
                    save_users(users, meta)
                    return self._send({"ok": True})

                if path == "/api/channels/test":
                    ctype = str(body.get("type", ""))
                    cfg = (rec.get("channels") or {}).get(ctype) or {}
                    text = f"✅ App Atlas 测试消息：{TYPE_LABEL.get(ctype, ctype)} 渠道配置成功"
                    if ctype == "tg":
                        ok = tg_send(cfg.get("bot_token", ""), cfg.get("chat_id", ""), text)
                    elif ctype == "bark":
                        ok = bark_send(cfg, "✅ App Atlas", text)
                    elif ctype == "http":
                        ok = http_post_json(cfg.get("url", ""),
                                            {"app": "App Atlas", "events": [{"type": "test", "text": text}]})
                    else:
                        ok = False
                    return self._send({"ok": ok})

        return self._send({"error": "not found"}, 404)


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


# ---------------------------------------------------------------- #
def main():
    if not HTML_FILE.exists():
        print(f"\n❌ 缺少前端文件: {HTML_FILE}")
        print(f"   请确认 AppPriceTracker.html 与本脚本在同一目录\n")
        sys.exit(1)

    cache_load()
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{'127.0.0.1' if HOST == '0.0.0.0' else HOST}:{PORT}/"

    print()
    print("┌─────────────────────────────────────────────┐")
    print("│  🌍 App Store 价格全览 已启动               │")
    print("├─────────────────────────────────────────────┤")
    print(f"│  访问地址:  {url:<32s}│")
    print("│  关闭服务:  在此窗口按 Ctrl+C               │")
    print("└─────────────────────────────────────────────┘")
    print()

    # 双击启动（有终端）时自动开浏览器；Docker/后台运行时不弹
    if sys.stdout.isatty() and os.environ.get("NO_BROWSER") != "1":
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    # 价格监控定时任务（同时为监控中的 App 预热缓存）
    threading.Thread(target=monitor_loop, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 已停止。")
        cache_flush(force=True)
        server.shutdown()


if __name__ == "__main__":
    main()
