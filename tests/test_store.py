# -*- coding: utf-8 -*-
"""用户存储 / 登录 / API 密钥。"""
from appatlas import store


def test_default_admin_created(tmp_data):
    users, meta = store.load_users()
    assert "admin" in users and users["admin"]["role"] == "admin"
    assert meta["allow_register"] is True


def test_login_ok_and_bad(tmp_data):
    assert store.check_login("admin", "admin123")
    assert store.check_login("admin", "wrong") is None
    assert store.check_login("ghost", "x") is None


def test_session_flow(tmp_data):
    token = store.issue_token("admin")
    headers = {"X-Auth-Token": token}
    info = store.get_session(headers)
    assert info and info["username"] == "admin"
    store.SESSIONS.pop(token)
    assert store.get_session(headers) is None


def test_apikey_lookup_updates_last_used(tmp_data):
    users, meta = store.load_users()
    users["admin"].setdefault("api_keys", []).append(
        {"id": "k1", "name": "t", "key": "atlas_live_abc",
         "created_at": 0, "last_used": 0})
    store.save_users(users, meta)
    assert store.get_apikey_user({"X-API-Key": "atlas_live_abc"}) == "admin"
    assert store.get_apikey_user({"X-API-Key": "nope"}) is None
    users, _ = store.load_users()
    assert users["admin"]["api_keys"][0]["last_used"] > 0
