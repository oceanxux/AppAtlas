# -*- coding: utf-8 -*-
"""HTTP 服务:路由、鉴权、启动。"""
import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

from . import applesvc, cache, config, fx, monitor, store, tgbot
from .apple import fetch_iap_data, http_get_json, search_apps


# ---------- 数据接口调用统计 ----------
STATS_LOCK = threading.Lock()
_stats = None


def record_api_call(cost_ms):
    """记一次数据接口调用(次数 + 耗时),保留近 30 天。"""
    global _stats
    d = time.strftime("%Y-%m-%d")
    with STATS_LOCK:
        if _stats is None:
            _stats = store.load_json_file(config.STATS_FILE, {})
        ent = _stats.setdefault(d, [0, 0.0])
        ent[0] += 1
        ent[1] += cost_ms
        cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - 30 * 86400))
        for k in [k for k in _stats if k < cutoff]:
            del _stats[k]
        store.save_json_file(config.STATS_FILE, _stats)


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
        # 允许任意页面访问(双击 file:// 也能用)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_html(self):
        if not config.HTML_FILE.exists():
            return self._send("<h1>缺少 AppPriceTracker.html</h1>", 500, "text/html")
        with open(config.HTML_FILE, "rb") as f:
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
        path = urllib.parse.urlparse(self.path).path
        t0 = time.time() if path in config.API_DATA_PATHS else None
        try:
            url = urllib.parse.urlparse(self.path)
            qs = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}

            # ---------- HTML 主页 ----------
            if path in ("/", "/index.html"):
                return self._send_html()

            # /atlas 根路径:API 入口说明(供程序调用者自省)
            if path in ("/atlas", "/atlas/"):
                return self._send({
                    "ok": True, "service": "App Atlas API",
                    "web": f"http://{self.headers.get('Host', '127.0.0.1:8765')}/",
                    "auth": "X-API-Key: <密钥>(网页「API」页创建) 或 X-Auth-Token: <登录token>",
                    "endpoints": [
                        "/atlas/search?q=<关键词>&country=<区码>",
                        "/atlas/lookup?id=<AppID>&country=<区码>",
                        "/atlas/iap?id=<AppID>&country=<区码>",
                        "/atlas/top", "/atlas/fx", "/atlas/me"]})

            if path == "/health":
                return self._send({"ok": True, "ts": int(time.time())})

            # ---------- 0. 登录状态 ----------
            if path == "/atlas/me":
                info = store.get_session(self.headers)
                if info:
                    users, _ = store.load_users()
                    rec = users.get(info["username"]) or {}
                    return self._send({"ok": True, "username": info["username"],
                                       "role": info["role"],
                                       "must_change": bool(rec.get("must_change"))})
                ak = store.get_apikey_user(self.headers)
                if ak:
                    return self._send({"ok": True, "username": ak,
                                       "role": "api_key", "via": "api_key"})
                return self._send({"ok": False})

            # ---------- 数据接口鉴权门 ----------
            # 「接口需密钥」开启时(或公网部署自动开启),数据接口要求登录会话或 X-API-Key。
            # 监控与 TG 机器人在进程内部调用,不经过这里,不受影响。
            if path in config.API_DATA_PATHS and store.api_gate_enabled():
                if not (self.headers.get("X-Web-App") == "1"
                        or store.get_session(self.headers)
                        or store.get_apikey_user(self.headers)):
                    return self._send({"ok": False, "error": "api_key_required"},
                                      status=401)

            # ---------- 0.2 登录用户的密钥 / 监控 / 通知 / 渠道 ----------
            if path == "/atlas/stats":
                info = store.get_session(self.headers)
                if not info:
                    return self._send({"ok": False, "error": "unauthorized"}, status=401)
                with STATS_LOCK:
                    snap = dict(_stats if _stats is not None
                                else store.load_json_file(config.STATS_FILE, {}))
                days = []
                for i in range(29, -1, -1):
                    d = time.strftime("%Y-%m-%d", time.localtime(time.time() - i * 86400))
                    c, total = snap.get(d, [0, 0.0])
                    days.append({"date": d, "count": c,
                                 "avg_ms": round(total / c) if c else 0})
                return self._send({"ok": True, "days": days})

            if path in ("/atlas/keys", "/atlas/watch", "/atlas/notifications", "/atlas/channels"):
                info = store.get_session(self.headers)
                if not info:
                    return self._send({"ok": False, "error": "unauthorized"}, status=401)
                users, meta = store.load_users()
                rec = users.get(info["username"]) or {}
                if path == "/atlas/keys":
                    return self._send({"ok": True, "keys": rec.get("api_keys", [])})
                if path == "/atlas/watch":
                    return self._send({"ok": True, "watches": rec.get("watches", [])})
                if path == "/atlas/notifications":
                    notifs = store.load_json_file(config.NOTIF_FILE, {})
                    return self._send({"ok": True,
                                       "events": notifs.get(info["username"], [])[:100]})
                return self._send({"ok": True, "channels": rec.get("channels", {})})

            # ---------- 0.5 用户管理(仅管理员) ----------
            if path == "/atlas/users":
                info = store.get_session(self.headers)
                if not info:
                    return self._send({"ok": False, "error": "unauthorized"}, status=401)
                users, meta = store.load_users()
                rec = users.get(info["username"])
                if not rec or rec.get("role") != "admin":
                    return self._send({"ok": False, "error": "forbidden"}, status=403)
                return self._send({"ok": True,
                                   "allow_register": meta.get("allow_register", True),
                                   "require_api_key": meta.get("require_api_key"),
                                   "require_api_key_effective": store.api_gate_enabled(meta),
                                   "users": [{"username": u, "role": r.get("role", "user"),
                                              "created_at": r.get("created_at")}
                                             for u, r in sorted(users.items())]})

            # ---------- 1. 搜索应用 ----------
            if path == "/atlas/search":
                term = qs.get("q", "").strip()
                cc = qs.get("country", "us").lower()
                if not term:
                    return self._send({"results": [], "resultCount": 0})
                data = search_apps(term, cc, limit=20)
                if data is not None:
                    return self._send(data)
                return self._err("search upstream error", 502)

            # ---------- 2. 应用详情 (lookup, 缓存 1 天,lang 本地化) ----------
            if path == "/atlas/lookup":
                aid = qs.get("id")
                cc = qs.get("country", "us").lower()
                lang = qs.get("lang", "").lower()
                if not re.fullmatch(r"[a-z]{2}(_[a-z]{2,4})?", lang):
                    lang = ""
                if not aid:
                    return self._err("missing id", 400)
                if aid in applesvc.SVC_APPS or aid.startswith("svc:"):
                    return self._send(applesvc.lookup_view(aid.replace("svc:", "")))
                key = f"lookup:{aid}:{cc}:{lang}"

                def _fetch_lookup():
                    u = (f"https://itunes.apple.com/lookup?id={aid}"
                         f"&country={cc}&entity=software"
                         + (f"&lang={lang}" if lang else ""))
                    try:
                        return http_get_json(u)
                    except Exception:
                        return None
                d = cache.cached_fetch(key, 86400, _fetch_lookup,
                                       ttl_fn=lambda x: 86400 if x.get("resultCount") else 600)
                if d is not None:
                    return self._send(d)
                return self._err("upstream error", 502)

            # ---------- 3. 内购订阅价格 (核心, 成功缓存 6 小时) ----------
            if path == "/atlas/iap":
                aid = qs.get("id")
                cc = qs.get("country", "us").lower()
                if not aid:
                    return self._err("missing id", 400)
                if aid in applesvc.SVC_APPS or aid.startswith("svc:"):
                    return self._send(applesvc.iap_view(aid.replace("svc:", ""), cc))
                data = fetch_iap_data(aid, cc)
                if data is not None:
                    return self._send(data)
                return self._err("HTTP error from apps.apple.com", 502)

            # ---------- 3.5 热门订阅 App（人工策划清单,元数据实时拉取,缓存 24h） ----------
            # Apple 官方没有"订阅榜",主流比价站均为人工策划;
            # 清单对齐 ChatGPT/Claude/Gemini/流媒体/社交等有订阅内购的头部 App
            if path == "/atlas/svc":
                name = qs.get("name", "").strip().lower()
                data = applesvc.get_service(name, force=qs.get("force") == "1")
                if data:
                    return self._send({"ok": True, "service": name, **data})
                return self._err("unknown service or upstream unavailable", 404)

            if path == "/atlas/top":
                ck = "top:subs10:v10"
                cached = cache.cache_get(ck)
                if cached is not None:
                    return self._send(cached)

                def _fetch_meta(aid):
                    if aid in applesvc.SVC_APPS or aid.startswith("svc:"):
                        meta = applesvc.SVC_APPS.get(aid.replace("svc:", "")) or {}
                        return {"id": aid.replace("svc:", ""), "name": meta.get("name", aid),
                                "artist": "Apple 官方服务", "icon": meta.get("icon", "")}
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
                    metas = list(ex.map(_fetch_meta, config.TOP_SUBSCRIPTION_APPS))
                apps = [m for m in metas if m]
                if apps:
                    resp = {"ok": True, "apps": apps,
                            "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                    cache.cache_put(ck, resp, 24 * 3600)
                    cache.cache_flush()
                    return self._send(resp)
                return self._err("top chart unavailable", 502)

            # ---------- 4. 实时汇率（USD 基准,TG 机器人共用 fx.get_fx_rates） ----------
            if path == "/atlas/fx":
                rates = fx.get_fx_rates()
                if rates:
                    return self._send({"base": "USD", "rates": rates})
                return self._err("FX unavailable", 502)

            return self._send({"error": "not found"}, 404)

        except urllib.error.HTTPError as e:
            self._err(f"upstream HTTP {e.code}: {e.reason}", code=502)
        except Exception as e:
            self._err(str(e), code=500)
        finally:
            # 只统计脚本/外部调用;网页自身的查询(X-Web-App)不计入
            if t0 is not None and self.headers.get("X-Web-App") != "1":
                record_api_call((time.time() - t0) * 1000)

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
        info = store.get_session(self.headers)
        if not info:
            return None, ({"ok": False, "error": "unauthorized"}, 401)
        users, meta = store.load_users()
        rec = users.get(info["username"])
        if not rec or rec.get("role") != "admin":
            return None, ({"ok": False, "error": "forbidden"}, 403)
        return info, None

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        body = self._read_json_body()

        if path == "/atlas/login":
            username = str(body.get("username", "")).strip()
            rec = store.check_login(username, str(body.get("password", "")))
            if rec:
                token = store.issue_token(username)
                # 顺手清理过期会话
                now = time.time()
                for tk in [k for k, v in store.SESSIONS.items()
                           if now - v["ts"] > config.SESSION_TTL]:
                    store.SESSIONS.pop(tk, None)
                return self._send({"ok": True, "token": token,
                                   "username": username, "role": rec.get("role", "user"),
                                   "must_change": bool(rec.get("must_change"))})
            return self._send({"ok": False, "error": "bad_credentials"}, status=401)

        if path == "/atlas/register":
            username = str(body.get("username", "")).strip()
            password = str(body.get("password", ""))
            err = self._validate_new_user(username, password)
            if err:
                return self._send({"ok": False, "error": err}, status=400)
            with store.USER_LOCK:
                users, meta = store.load_users()
                if not meta.get("allow_register", True):
                    return self._send({"ok": False, "error": "register_disabled"}, status=403)
                if username in users:
                    return self._send({"ok": False, "error": "user_exists"}, status=409)
                salt = secrets.token_hex(8)
                users[username] = {"salt": salt, "hash": store._hash_password(salt, password),
                                   "role": "user", "created_at": int(time.time())}
                store.save_users(users, meta)
            token = store.issue_token(username)
            return self._send({"ok": True, "token": token, "username": username, "role": "user"})

        if path == "/atlas/logout":
            store.SESSIONS.pop(self.headers.get("X-Auth-Token", ""), None)
            return self._send({"ok": True})

        if path == "/atlas/password":  # 修改自己的密码
            info = store.get_session(self.headers)
            if not info:
                return self._send({"ok": False, "error": "unauthorized"}, status=401)
            newpwd = str(body.get("new_password", ""))
            if len(newpwd) < 6:
                return self._send({"ok": False, "error": "password_short"}, status=400)
            with store.USER_LOCK:
                users, meta = store.load_users()
                if not store.check_login(info["username"], str(body.get("old_password", ""))):
                    return self._send({"ok": False, "error": "bad_credentials"}, status=401)
                rec = users.get(info["username"]) or {}
                salt = secrets.token_hex(8)
                rec["salt"], rec["hash"] = salt, store._hash_password(salt, newpwd)
                rec["must_change"] = 0  # 改密后解除首登强制
                store.save_users(users, meta)
            return self._send({"ok": True})

        if path == "/atlas/username":  # 修改自己的用户名
            info = store.get_session(self.headers)
            if not info:
                return self._send({"ok": False, "error": "unauthorized"}, status=401)
            newname = str(body.get("username", "")).strip()
            if not re.fullmatch(r"[\w\u4e00-\u9fa5\-]{2,32}", newname):
                return self._send({"ok": False, "error": "bad_username"}, status=400)
            with store.USER_LOCK:
                users, meta = store.load_users()
                rec = users.get(info["username"]) or {}
                if not store.check_login(info["username"], str(body.get("password", ""))):
                    return self._send({"ok": False, "error": "bad_credentials"}, status=401)
                if newname != info["username"] and newname in users:
                    return self._send({"ok": False, "error": "user_exists"}, status=409)
                users[newname] = users.pop(info["username"])
                store.save_users(users, meta)
                # 通知事件按用户名索引,一并迁移
                notifs = store.load_json_file(config.NOTIF_FILE, {})
                if info["username"] in notifs:
                    notifs[newname] = notifs.pop(info["username"])
                    store.save_json_file(config.NOTIF_FILE, notifs)
            role = rec.get("role", "user")
            # 旧会话按用户名失效,换发新 token 保持登录态
            store.SESSIONS.pop(self.headers.get("X-Auth-Token", ""), None)
            token = store.issue_token(newname)
            return self._send({"ok": True, "token": token,
                               "username": newname, "role": role})

        # ---- 以下需要管理员 ----
        if path in ("/atlas/users/create", "/atlas/users/set_role", "/atlas/users/delete",
                    "/atlas/users/set_password", "/atlas/config/set"):
            info, deny = self._require_admin()
            if deny:
                return self._send(*deny)

            if path == "/atlas/users/create":
                username = str(body.get("username", "")).strip()
                password = str(body.get("password", ""))
                role = body.get("role", "user")
                err = self._validate_new_user(username, password)
                if err:
                    return self._send({"ok": False, "error": err}, status=400)
                with store.USER_LOCK:
                    users, meta = store.load_users()
                    if username in users:
                        return self._send({"ok": False, "error": "user_exists"}, status=409)
                    salt = secrets.token_hex(8)
                    users[username] = {"salt": salt,
                                       "hash": store._hash_password(salt, password),
                                       "role": "admin" if role == "admin" else "user",
                                       "created_at": int(time.time())}
                    store.save_users(users, meta)
                return self._send({"ok": True})

            if path == "/atlas/users/set_role":
                username = str(body.get("username", ""))
                role = "admin" if body.get("role") == "admin" else "user"
                with store.USER_LOCK:
                    users, meta = store.load_users()
                    if username not in users:
                        return self._send({"ok": False, "error": "no_such_user"}, status=404)
                    if username == info["username"]:
                        return self._send({"ok": False, "error": "cannot_modify_self"}, status=400)
                    if users[username].get("role") == "admin" and role != "admin" \
                            and store.count_admins(users) <= 1:
                        return self._send({"ok": False, "error": "last_admin"}, status=400)
                    users[username]["role"] = role
                    store.save_users(users, meta)
                return self._send({"ok": True})

            if path == "/atlas/users/delete":
                username = str(body.get("username", ""))
                with store.USER_LOCK:
                    users, meta = store.load_users()
                    if username not in users:
                        return self._send({"ok": False, "error": "no_such_user"}, status=404)
                    if username == info["username"]:
                        return self._send({"ok": False, "error": "cannot_modify_self"}, status=400)
                    if users[username].get("role") == "admin" and store.count_admins(users) <= 1:
                        return self._send({"ok": False, "error": "last_admin"}, status=400)
                    users.pop(username)
                    store.save_users(users, meta)
                return self._send({"ok": True})

            if path == "/atlas/users/set_password":
                username = str(body.get("username", ""))
                newpwd = str(body.get("password", ""))
                if len(newpwd) < 6:
                    return self._send({"ok": False, "error": "password_short"}, status=400)
                with store.USER_LOCK:
                    users, meta = store.load_users()
                    if username not in users:
                        return self._send({"ok": False, "error": "no_such_user"}, status=404)
                    salt = secrets.token_hex(8)
                    users[username]["salt"] = salt
                    users[username]["hash"] = store._hash_password(salt, newpwd)
                    store.save_users(users, meta)
                return self._send({"ok": True})

            if path == "/atlas/config/set":
                # 全局配置开关:开放注册 / 接口需密钥(None=自动:本机开放,公网要求)
                with store.USER_LOCK:
                    users, meta = store.load_users()
                    if "allow_register" in body:
                        meta["allow_register"] = bool(body.get("allow_register"))
                    if "require_api_key" in body:
                        v = body.get("require_api_key")
                        meta["require_api_key"] = None if v in (None, "auto") else bool(v)
                    store.save_users(users, meta)
                return self._send({"ok": True,
                                   "allow_register": meta.get("allow_register", True),
                                   "require_api_key": meta.get("require_api_key"),
                                   "require_api_key_effective": store.api_gate_enabled(meta)})

        # ---- 登录用户的写操作:密钥 / 监控 / 渠道 ----
        if path in ("/atlas/keys/create", "/atlas/keys/delete", "/atlas/watch/save",
                    "/atlas/watch/delete", "/atlas/channels/save", "/atlas/channels/test"):
            info = store.get_session(self.headers)
            if not info:
                return self._send({"ok": False, "error": "unauthorized"}, status=401)
            with store.USER_LOCK:
                users, meta = store.load_users()
                rec = users.get(info["username"])
                if not rec:
                    return self._send({"ok": False, "error": "no_such_user"}, status=404)

                if path == "/atlas/keys/create":
                    name = str(body.get("name", "")).strip()[:32] or "key"
                    kid = secrets.token_hex(4)
                    key = "Atlas_" + secrets.token_urlsafe(24)
                    rec.setdefault("api_keys", []).append(
                        {"id": kid, "name": name, "key": key,
                         "created_at": int(time.time()), "last_used": 0})
                    store.save_users(users, meta)
                    return self._send({"ok": True,
                                       "key": {"id": kid, "name": name, "key": key}})

                if path == "/atlas/keys/delete":
                    kid = str(body.get("id", ""))
                    rec["api_keys"] = [k for k in rec.get("api_keys", [])
                                       if k.get("id") != kid]
                    store.save_users(users, meta)
                    return self._send({"ok": True})

                if path == "/atlas/watch/save":
                    aid = str(body.get("app_id", ""))
                    if not (aid.isdigit() or aid in applesvc.SVC_APPS
                            or aid.startswith("svc:")):
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
                    store.save_users(users, meta)
                    return self._send({"ok": True})

                if path == "/atlas/watch/delete":
                    aid = str(body.get("app_id", ""))
                    rec["watches"] = [x for x in rec.get("watches", [])
                                      if str(x.get("app_id")) != aid]
                    store.save_users(users, meta)
                    return self._send({"ok": True})

                if path == "/atlas/channels/save":
                    ctype = str(body.get("type", ""))
                    cfg = dict(body.get("config") or {})
                    ch_name = str(cfg.get("name", ""))[:40]
                    if ctype == "tg":
                        cfg = {"name": ch_name,
                               "bot_token": str(cfg.get("bot_token", ""))[:64],
                               "chat_id": str(cfg.get("chat_id", ""))[:32],
                               "group_id": str(cfg.get("group_id", ""))[:32]}
                    elif ctype == "bark":
                        device_key = str(cfg.get("device_key", ""))[:80]
                        server = str(cfg.get("server", ""))[:200]
                        if server and not server.startswith("http"):
                            return self._send({"ok": False, "error": "bad_server_url"}, status=400)
                        if not device_key:
                            return self._send({"ok": False, "error": "missing device_key"}, status=400)
                        cfg = {"name": ch_name, "device_key": device_key, "server": server}
                    elif ctype == "http":
                        url = str(cfg.get("url", ""))[:300]
                        if url and not url.startswith("http"):
                            return self._send({"ok": False, "error": "bad_webhook_url"}, status=400)
                        cfg = {"name": ch_name, "url": url}
                    else:
                        return self._send({"ok": False, "error": "bad_channel"}, status=400)
                    rec.setdefault("channels", {})[ctype] = cfg
                    store.save_users(users, meta)
                    return self._send({"ok": True})

                if path == "/atlas/channels/test":
                    ctype = str(body.get("type", ""))
                    cfg = (rec.get("channels") or {}).get(ctype) or {}
                    text = f"✅ App Atlas 测试消息：{config.TYPE_LABEL.get(ctype, ctype)} 渠道配置成功"
                    if ctype == "tg":
                        from .notify import tg_send
                        ok = tg_send(cfg.get("bot_token", ""), cfg.get("chat_id", ""), text)
                    elif ctype == "bark":
                        from .notify import bark_send
                        ok = bark_send(cfg, "✅ App Atlas", text)
                    elif ctype == "http":
                        from .notify import http_post_json
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
    if not config.HTML_FILE.exists():
        print(f"\n❌ 缺少前端文件: {config.HTML_FILE}")
        print(f"   请确认 AppPriceTracker.html 与 appatlas/ 包在同一目录\n")
        sys.exit(1)

    cache.cache_load()
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    server = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    url = f"http://{'127.0.0.1' if config.HOST == '0.0.0.0' else config.HOST}:{config.PORT}/"

    print()
    print("┌─────────────────────────────────────────────┐")
    print("│  🌍 App Store 价格全览 已启动               │")
    print("├─────────────────────────────────────────────┤")
    print(f"│  访问地址:  {url:<32s}│")
    print("│  关闭服务:  在此窗口按 Ctrl+C               │")
    print("└─────────────────────────────────────────────┘")
    print(f"  接口鉴权: {'需登录/密钥' if store.api_gate_enabled() else '开放(本机自用)'}")
    print()

    # 双击启动(有终端)时自动开浏览器;Docker/后台运行时不弹
    if sys.stdout.isatty() and os.environ.get("NO_BROWSER") != "1":
        import threading
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    # 价格监控定时任务(同时为监控中的 App 预热缓存)
    import threading
    threading.Thread(target=monitor.monitor_loop, daemon=True).start()
    # TG 查价机器人(用户在通知页保存 bot_token 后 ~30s 内自动上线)
    threading.Thread(target=tgbot.tg_bot_manager_loop, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 已停止。")
        cache.cache_flush(force=True)
        server.shutdown()


if __name__ == "__main__":
    main()
