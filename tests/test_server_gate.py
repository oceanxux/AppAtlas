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


def _login(base):
    req = urllib.request.Request(
        base + "/api/login",
        data=json.dumps({"username": "admin", "password": "admin123"}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode())["token"]


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


def test_health_always_open(server):
    status, body = _get(server, "/health")
    assert status == 200 and body["ok"] is True


def test_gate_off_open_by_default(server):
    status, _ = _get(server, "/api/search?q=")
    assert status == 200
