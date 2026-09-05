# -*- coding: utf-8 -*-
"""用户 / 会话 / API 密钥持久化,以及数据接口鉴权门开关。"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

from . import config

USER_LOCK = threading.Lock()
# 登录会话(内存态,重启后需重新登录) token -> {"user": str, "ts": float}
SESSIONS = {}


def load_json_file(path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️ {path.name} 读取失败: {e}")
    return default


def save_json_file(path, data):
    try:
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        print(f"⚠️ {path.name} 写入失败: {e}")


def _hash_password(salt, password):
    return hashlib.sha256((salt + ":" + password).encode("utf-8")).hexdigest()


def load_users():
    """读取 users.json → (users, meta)。不存在则创建默认 admin 账号。

    格式: {"_meta": {"allow_register": true}, "users": {"名": {"salt","hash","role","created_at"}}}
    兼容旧版平铺格式(无 "users" 键),旧账号一律视为 admin。
    """
    if not config.USERS_FILE.exists():
        salt = secrets.token_hex(8)
        pw = os.environ.get("APT_ADMIN_PASSWORD", "admin123")
        users = {"admin": {"salt": salt, "hash": _hash_password(salt, pw),
                           "role": "admin", "created_at": int(time.time()),
                           "must_change": 1}}
        save_users(users, {"allow_register": True})
        hint = "APT_ADMIN_PASSWORD 环境变量的值" if os.environ.get("APT_ADMIN_PASSWORD") \
            else "admin123(登录后请在「用户管理」中修改,或设置 APT_ADMIN_PASSWORD 后删除 users.json 重新生成)"
        print(f"\n👤 已创建管理员账号: admin / {hint}")
        print(f"   开放注册可在网页右上角「用户」面板中开关\n")
    try:
        data = json.loads(config.USERS_FILE.read_text(encoding="utf-8"))
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
        rec.setdefault("channels", [])
        rec.setdefault("must_change", 0)
        if rec.get("tg"):  # 旧版单 TG 配置迁移到 channels
            rec["channels"].setdefault("tg", rec.pop("tg"))
    return users, meta


def save_users(users, meta):
    config.USERS_FILE.write_text(json.dumps(
        {"_meta": meta, "users": users}, indent=2, ensure_ascii=False), encoding="utf-8")


def check_login(username, password):
    users, _ = load_users()
    rec = users.get(username)
    if not rec:
        hmac.compare_digest("x", "y")  # 用户不存在也做一次比较,避免时序侧信道
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
    if time.time() - sess["ts"] > config.SESSION_TTL:
        SESSIONS.pop(token, None)
        return None
    sess["ts"] = time.time()
    users, _ = load_users()
    rec = users.get(sess["user"])
    return {"username": sess["user"], "role": rec.get("role", "user")} if rec else None


def get_apikey_user(headers):
    """X-API-Key → username。命中则顺带更新 last_used(每小时最多写一次盘)。"""
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


def count_admins(users):
    return sum(1 for r in users.values() if r.get("role") == "admin")


def api_gate_enabled(meta=None):
    """数据接口是否要求鉴权(登录会话或 X-API-Key)。

    面板显式开关(_meta.require_api_key = True/False)优先;
    未设置(None)时自动:监听回环地址(本机自用)开放,否则(公网/Docker)要求密钥。
    """
    if meta is None:
        _, meta = load_users()
    v = meta.get("require_api_key")
    if v is None or v == "auto":
        return config.HOST not in ("127.0.0.1", "localhost", "::1", "")
    return bool(v)
