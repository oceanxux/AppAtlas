# -*- coding: utf-8 -*-
"""Apple 官方/内部接口封装:搜索、详情、内购报价,以及全局节流。"""
import gzip
import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config
from .cache import cached_fetch

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15")

# apps.apple.com 全局限速:所有线程共享,避免突发触发 429
APPLE_LOCK = threading.Lock()
_apple_last = [0.0]


def apple_throttle():
    with APPLE_LOCK:
        wait = _apple_last[0] + config.APPLE_MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _apple_last[0] = time.monotonic()


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


def fetch_iap_data(aid, cc):
    """内购/订阅数据:per-key 锁防击穿,成功缓存 6 小时。网络错误返回 None。"""
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


def search_apps(term, cc="us", limit=20):
    """iTunes 搜索;term 为纯数字 ID 或含 id 前缀时自动走 lookup。
    与网页端 /api/search 同源同缓存。失败返回 None。"""
    m = re.search(r"id(\d{6,})|^(\d{6,})$", term)
    if m:
        aid = m.group(1) or m.group(2)
        u = (f"https://itunes.apple.com/lookup?id={aid}"
             f"&country={cc}&entity=software")
    else:
        u = (f"https://itunes.apple.com/search?"
             f"term={urllib.parse.quote(term)}"
             f"&country={cc}&entity=software&limit={limit}")
    key = f"search:{cc}:{hashlib.md5(term.lower().encode()).hexdigest()}"

    def _fetch():
        try:
            return http_get_json(u)
        except Exception:
            return None
    return cached_fetch(key, 86400, _fetch,
                        ttl_fn=lambda x: 86400 if x.get("resultCount") else 600)
