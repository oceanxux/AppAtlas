# -*- coding: utf-8 -*-
"""HTTP 集成:鉴权门拦截匿名请求,放行登录会话(不触网)。"""
import json
import threading
import urllib.error
import urllib.request

import pytest

from appatlas import store
from appatlas.server import Handler, ThreadingHTTPServer


@pytest.fixture
def server(tmp_data):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _get(base, path, headers=None):
    req = urllib.request.Request(base + path, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def _post(base, path, body, headers=None):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def _login(base):
    req = urllib.request.Request(
        base + "/api/login",
        data=json.dumps({"username": "admin", "password": "admin123"}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode())["token"]


def test_first_login_must_change_flag(server):
    # 首次创建的 admin 带 must_change 标记
    token = _login(server)
    status, me = _get(server, "/api/me", {"X-Auth-Token": token})
    assert status == 200 and me["must_change"] is True
    # 改密后解除
    status, d = _post(server, "/api/password",
                      {"old_password": "admin123", "new_password": "newpass1"},
                      {"X-Auth-Token": token})
    assert status == 200 and d["ok"] is True
    _, me2 = _get(server, "/api/me", {"X-Auth-Token": token})
    assert me2["must_change"] is False


def test_change_username(server):
    token = _login(server)
    status, d = _post(server, "/api/username",
                      {"username": "boss", "password": "admin123"},
                      {"X-Auth-Token": token})
    assert status == 200 and d["ok"] is True and d["username"] == "boss"
    # 旧 token 已失效(/api/me 始终 200 但 ok:false),新 token 可用
    _, me_old = _get(server, "/api/me", {"X-Auth-Token": token})
    assert me_old["ok"] is False
    _, me = _get(server, "/api/me", {"X-Auth-Token": d["token"]})
    assert me["ok"] is True and me["username"] == "boss"
    # 旧密码不配套 → 拒绝改名
    status, d2 = _post(server, "/api/username",
                       {"username": "boss2", "password": "wrong"},
                       {"X-Auth-Token": d["token"]})
    assert status == 401 and d2["error"] == "bad_credentials"


def test_gate_on_blocks_anonymous(server):
    users, meta = store.load_users()
    meta["require_api_key"] = True
    store.save_users(users, meta)
    status, body = _get(server, "/api/search?q=")
    assert status == 401 and body["error"] == "api_key_required"


def test_gate_on_allows_session(server):
    users, meta = store.load_users()
    meta["require_api_key"] = True
    store.save_users(users, meta)
    token = _login(server)
    status, body = _get(server, "/api/search?q=", {"X-Auth-Token": token})
    assert status == 200 and body == {"results": [], "resultCount": 0}


def test_gate_on_allows_web_app(server):
    users, meta = store.load_users()
    meta["require_api_key"] = True
    store.save_users(users, meta)
    # 网页请求带内部标记,即使鉴权门开启也放行查价
    status, body = _get(server, "/api/search?q=", {"X-Web-App": "1"})
    assert status == 200 and body == {"results": [], "resultCount": 0}


def test_gate_on_blocks_anonymous_without_marker(server):
    users, meta = store.load_users()
    meta["require_api_key"] = True
    store.save_users(users, meta)
    # 无标记、无会话、无密钥 → 仍被拦
    status, body = _get(server, "/api/search?q=")
    assert status == 401 and body["error"] == "api_key_required"


def test_health_always_open(server):
    status, body = _get(server, "/health")
    assert status == 200 and body["ok"] is True


def test_gate_off_open_by_default(server):
    status, _ = _get(server, "/api/search?q=")
    assert status == 200
