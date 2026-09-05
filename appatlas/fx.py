# -*- coding: utf-8 -*-
"""汇率:USD 基准,内存缓存 6 小时。/api/fx 与 TG 机器人共用。"""
from . import cache
from .apple import http_get_json

_FX_CACHE_KEY = "fx:usd:v1"
_FX_TTL = 6 * 3600


def get_fx_rates():
    """返回 { currency: per-USD-rate } 字典;全部上游失败时返回 None。"""
    hit = cache.cache_get(_FX_CACHE_KEY)
    if hit:
        return hit
    try:
        d = http_get_json("https://open.er-api.com/v6/latest/USD", timeout=8)
        if d.get("result") == "success" and d.get("rates"):
            cache.cache_put(_FX_CACHE_KEY, d["rates"], _FX_TTL)
            return d["rates"]
    except Exception:
        pass
    for u in ["https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest"
              "/v1/currencies/usd.min.json",
              "https://latest.currency-api.pages.dev/v1/currencies/usd.json"]:
        try:
            d = http_get_json(u, timeout=8)
            if d.get("usd"):
                rates = {"USD": 1.0}
                for k, v in d["usd"].items():
                    rates[k.upper()] = v
                cache.cache_put(_FX_CACHE_KEY, rates, _FX_TTL)
                return rates
        except Exception:
            continue
    return None
