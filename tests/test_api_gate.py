# -*- coding: utf-8 -*-
"""数据接口鉴权门:自动策略 + 显式覆盖。"""
from appatlas import config, store


def test_gate_auto_loopback_open(tmp_data):
    assert store.api_gate_enabled() is False


def test_gate_auto_public_requires_key(tmp_data, monkeypatch):
    monkeypatch.setattr(config, "HOST", "0.0.0.0")
    assert store.api_gate_enabled() is True


def test_gate_explicit_override(tmp_data):
    users, meta = store.load_users()

    meta["require_api_key"] = True
    store.save_users(users, meta)
    assert store.api_gate_enabled() is True

    users, meta = store.load_users()
    meta["require_api_key"] = False
    store.save_users(users, meta)
    assert store.api_gate_enabled() is False  # 公网也强制开放(面板手动关)

    users, meta = store.load_users()
    meta["require_api_key"] = None
    store.save_users(users, meta)
    assert store.api_gate_enabled() is False  # 恢复自动 → 本机开放
