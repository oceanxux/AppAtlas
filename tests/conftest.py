# -*- coding: utf-8 -*-
"""公共夹具:把数据目录/监听地址隔离到临时目录,避免污染真实数据。"""
import tempfile
from pathlib import Path

import pytest

from appatlas import cache as cache_mod, config, store


@pytest.fixture
def tmp_data(monkeypatch):
    d = Path(tempfile.mkdtemp(prefix="appatlas_test_"))
    monkeypatch.setattr(config, "DATA_DIR", d)
    monkeypatch.setattr(config, "USERS_FILE", d / "users.json")
    monkeypatch.setattr(config, "CACHE_FILE", d / "cache.json")
    monkeypatch.setattr(config, "MONITOR_FILE", d / "monitor.json")
    monkeypatch.setattr(config, "NOTIF_FILE", d / "notifications.json")
    monkeypatch.setattr(config, "HOST", "127.0.0.1")
    store.SESSIONS.clear()
    with cache_mod.CACHE_LOCK:
        cache_mod.CACHE.clear()
    return d
