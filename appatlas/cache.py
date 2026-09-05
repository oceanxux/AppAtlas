# -*- coding: utf-8 -*-
"""内存 + 磁盘二级缓存与 per-key 防击穿锁。"""
import json
import threading
import time

from . import config

CACHE = {}
CACHE_LOCK = threading.Lock()
_cache_dirty = [False]
_cache_last_flush = [0.0]

# 细粒度 per-key 互斥锁:同一 key 的并发未命中只放一个线程回源,
# 其余线程等锁后直接读缓存(防击穿/防重复请求)。
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
        if len(CACHE) >= config.CACHE_MAX:
            for k, _ in sorted(CACHE.items(), key=lambda kv: kv[1]["expires"])[:200]:
                CACHE.pop(k, None)
        CACHE[key] = {"expires": time.time() + ttl, "data": data}
        _cache_dirty[0] = True


def cache_flush(force=False):
    """落盘(最多每 20s 一次,避免频繁 IO)。"""
    now = time.time()
    with CACHE_LOCK:
        if not _cache_dirty[0] or (not force and now - _cache_last_flush[0] < 20):
            return
        _cache_dirty[0] = False
        _cache_last_flush[0] = now
        try:
            config.CACHE_FILE.write_text(json.dumps(CACHE), encoding="utf-8")
        except OSError as e:
            print(f"⚠️ cache.json 写入失败: {e}")


def cache_load():
    if config.CACHE_FILE.exists():
        try:
            data = json.loads(config.CACHE_FILE.read_text(encoding="utf-8"))
            now = time.time()
            for k, v in data.items():
                if isinstance(v, dict) and v.get("expires", 0) > now:
                    CACHE[k] = v
            print(f"📦 已加载磁盘缓存 {len(CACHE)} 条")
        except Exception as e:
            print(f"⚠️ cache.json 读取失败: {e}")


def cached_fetch(key, ttl, fetcher, ttl_fn=None):
    """读缓存 → 未命中则拿 per-key 锁回源(双检)→ 写缓存。
    fetcher 返回 None 表示上游失败,不缓存。ttl_fn(data) 可按结果定 TTL。"""
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
