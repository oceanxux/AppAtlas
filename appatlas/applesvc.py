# -*- coding: utf-8 -*-
"""Apple 官方服务(iCloud+ / Apple One)价格。

这两项是系统级订阅,App Store 接口查不到,价格取自 Apple 官网:
  iCloud+   → support.apple.com/zh-cn/108047 各国价格总表
  Apple One → apple.com/<区>/apple-one/ 方案页(plan-individual/family/premier 锚点)
按天缓存;上游失败时回退最近一次落盘数据。
"""
import re
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import config, store

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15")

ICLOUD_TIERS = ["50GB", "200GB", "2TB", "6TB", "12TB"]
APPLEONE_TIERS = ["Individual", "Family", "Premier"]

# apple.com 站点区域 → 官方货币码
REGION_CURRENCY = {
    "US":"USD","CN":"CNY","HK":"HKD","MO":"MOP","TW":"TWD","JP":"JPY","KR":"KRW",
    "SG":"SGD","MY":"MYR","TH":"THB","VN":"VND","ID":"IDR","PH":"PHP","IN":"INR",
    "PK":"PKR","AU":"AUD","NZ":"NZD","CA":"CAD","MX":"MXN","BR":"BRL","CL":"CLP",
    "CO":"COP","GB":"GBP","IE":"EUR","FR":"EUR","DE":"EUR","AT":"EUR","IT":"EUR",
    "ES":"EUR","PT":"EUR","NL":"EUR","BE":"EUR","SE":"SEK","DK":"DKK","NO":"NOK",
    "FI":"EUR","PL":"PLN","CZ":"CZK","HU":"HUF","RO":"RON","GR":"EUR","RU":"RUB",
    "TR":"TRY","IL":"ILS","SA":"SAR","AE":"AED","ZA":"ZAR","EG":"EGP","NG":"NGN",
    "KZ":"KZT","CH":"CHF","BH":"BHD","OM":"OMR","JO":"JOD",
}

SVC_APPS = {
    "icloud": {
        "name": "iCloud+", "icon": "https://www.icloud.com/icloud_logo/icloud_logo.png",
        "url": "https://www.icloud.com/", "genre": "Apple 官方服务",
        "desc": ("iCloud+ 是 Apple 的云存储订阅服务：在 iCloud 存储空间基础上增加 iCloud 专用代理、"
                 "隐藏邮件地址、HomeKit 安防视频等增强功能，可与家人共享。价格因国家/地区而异，"
                 "按月计费，数据来自 Apple 官网。"),
        "tiers": ["iCloud+ 50GB", "iCloud+ 200GB", "iCloud+ 2TB", "iCloud+ 6TB", "iCloud+ 12TB"],
        "group": "iCloud+",
    },
    "appleone": {
        "name": "Apple One", "icon": "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d6/Apple_One.svg/500px-Apple_One.svg.png",
        "url": "https://www.apple.com/apple-one/", "genre": "Apple 官方服务",
        "desc": ("Apple One 将多项 Apple 服务打包为一个订阅：含 iCloud+、Apple Music、Apple TV+、"
                 "Apple Arcade 等，分个人/家庭/尊享三档，比单独订阅更划算。部分国家/地区仅提供"
                 "个人与家庭两档，数据来自 Apple 官网。"),
        "tiers": ["Apple One 个人版", "Apple One 家庭版", "Apple One 尊享版"],
        "group": "Apple One",
    },
}


def parse_price(text):
    """"19,95 €" / "$21.95" / "1,350円" / "NT$390" → 数值。"""
    m = re.search(r"\d[\d.,\s]*\d|\d", (text or "").replace("\xa0", " "))
    if not m:
        return None
    num = re.sub(r"[^\d.,]", "", m.group(0)).strip(".,")
    if "," in num and "." in num:
        num = num.replace(",", "") if num.rfind(".") > num.rfind(",") else num.replace(".", "").replace(",", ".")
    elif "," in num:
        num = num.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", num) else num.replace(",", ".")
    elif "." in num:
        num = num.replace(".", "") if re.fullmatch(r"\d{1,3}(\.\d{3})+", num) else num
    try:
        v = float(num)
        return v if v > 0 else None
    except ValueError:
        return None
APPLEONE_TIERS = ["Individual", "Family", "Premier"]

# Apple One 方案页可用区(实测 200;us 在根路径,uk 用 /uk/;CN/HK/BE/IL/TR/CH 等无页面)
APPLE_ONE_REGIONS = ["JP", "TW", "KR", "SG", "MY", "VN", "ID", "IN", "AU", "CA",
                     "BR", "MX", "AE", "DE", "FR", "IT", "ES", "NL", "SE", "DK",
                     "NO", "FI", "PT", "IE", "AT", "GB", "US",
                     "SA", "EG", "TH", "PH", "PL", "CZ", "HU", "KZ", "NZ",
                     "CL", "CO", "RU", "BH", "OM", "JO"]

# 108047 中文页国家名 → 区码
_CC_BY_COUNTRY = {
    "中国大陆": "CN", "香港": "HK", "澳门": "MO", "台湾": "TW", "日本": "JP",
    "韩国": "KR", "新加坡": "SG", "马来西亚": "MY", "泰国": "TH", "越南": "VN",
    "印度尼西亚": "ID", "菲律宾": "PH", "印度": "IN", "巴基斯坦": "PK",
    "澳大利亚": "AU", "新西兰": "NZ", "加拿大": "CA", "美国": "US", "墨西哥": "MX",
    "巴西": "BR", "智利": "CL", "哥伦比亚": "CO", "英国": "GB", "爱尔兰": "IE",
    "法国": "FR", "德国": "DE", "奥地利": "AT", "瑞士": "CH", "意大利": "IT",
    "西班牙": "ES", "葡萄牙": "PT", "荷兰": "NL", "比利时": "BE", "瑞典": "SE",
    "挪威": "NO", "丹麦": "DK", "芬兰": "FI", "波兰": "PL", "捷克": "CZ",
    "匈牙利": "HU", "罗马尼亚": "RO", "希腊": "GR", "俄罗斯": "RU", "土耳其": "TR",
    "以色列": "IL", "沙特阿拉伯": "SA", "阿联酋": "AE", "南非": "ZA", "埃及": "EG",
    "尼日利亚": "NG", "哈萨克斯坦": "KZ",
}

_lock = threading.Lock()
_data = None  # {"icloud": {...}, "appleone": {...}, "ts": ...}


def _http(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            import gzip
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", errors="replace")


def _strip(text):
    import html as _h
    return re.sub(r"\s+", " ", _h.unescape(re.sub(r"<[^>]+>", "", text or ""))).strip()


_TAIL_WORDS = (r"(per\s*month|por\s*m[êe]s|pro\s*Monat|par\s*mois|al\s*mes|al\s*mese|"
               r"per\s*bulan|pr\s*m[åa]ned|na\s*m[ěe]s[íi]c|m[ée]sico|/mo\.?|/month|"
               r"/Monat|/m[êe]s|/м[еэ]с\.?|/kuukausi|/måned|每月|/月|/個月|/개월|/kuussa|/hónap|/mies\.?|za\s*mies\.?|/bulan|/เดือน|ต่อเดือน|/tháng|/mesec|/mjesec)+")


def _clean_plan(text):
    """'Individual AED 49.95/mo.per month' → 'Individual AED 49.95'。"""
    t = _strip(text)
    prev = None
    while prev != t:
        prev = t
        t = re.sub(_TAIL_WORDS + r"\s*$", "", t, flags=re.I).strip()
    return t


def _fetch_icloud():
    """108047 → 各区 iCloud+ 五档价格(原文,含货币)。"""
    html = _http("https://support.apple.com/zh-cn/108047")
    blocks = re.findall(
        r'<h4 class="gb-header">([^<]+?)(?:<sup>\d+</sup>)?（([^）]+)）</h4>\s*<ul[^>]*>(.*?)</ul>',
        html, re.S)
    regions = []
    for country, currency, block in blocks:
        cc = _CC_BY_COUNTRY.get(re.sub(r"\s+", "", country))
        if not cc:
            continue
        tiers = {_norm_tier(k): _strip(v) for k, v in
                 re.findall(r"<b>([^<]+)</b>[：:]\s*([^<]+)</p>", block)}
        regions.append({"cc": cc, "currency": REGION_CURRENCY.get(cc, "USD"),
                        "prices": [tiers.get(t) for t in ICLOUD_TIERS]})
    if not regions:
        raise RuntimeError("icloud price table empty")
    return {"tiers": ICLOUD_TIERS, "regions": regions}


def _norm_tier(k):
    return re.sub(r"\s+", "", k).upper().replace("TB", "TB")


def _fetch_appleone():
    """各区 apple-one 方案页 → Individual/Family/Premier 原文价格。"""
    def one(cc):
        slug = "apple-one/" if cc == "US" else f"{cc.lower()}/apple-one/"
        try:
            html = _http(f"https://www.apple.com/{slug}")
        except Exception:
            return None
        plans = []
        for key in ("individual", "family", "premier"):
            m = re.search(rf'plan-{key}[^>]*>(.*?)</p>', html, re.S)
            plans.append(_clean_plan(m.group(1)) if m else None)
        if not any(plans):
            return None
        cc2 = "GB" if cc == "UK" else cc
        return {"cc": cc2, "currency": REGION_CURRENCY.get(cc2, "USD"),
                "prices": plans}

    with ThreadPoolExecutor(max_workers=6) as ex:
        regions = [r for r in ex.map(one, APPLE_ONE_REGIONS) if r]
    if len(regions) < 5:
        raise RuntimeError("appleone regions too few")
    regions.sort(key=lambda r: r["cc"])
    return {"tiers": APPLEONE_TIERS, "regions": regions}


_FETCHERS = {"icloud": _fetch_icloud, "appleone": _fetch_appleone}


def _load_disk():
    return store.load_json_file(config.SVC_FILE, {})


def _save_disk(data):
    import time as _t
    data = dict(data)
    data["ts"] = int(_t.time())
    store.save_json_file(config.SVC_FILE, data)


SVC_TTL = 6 * 3600  # 与 /atlas/iap 缓存一致;过期后下次访问自动重抓官网


def get_service(name, force=False):
    """→ {"tiers":[...],"regions":[...]} | None(未知服务或无数据)。

    缓存 6 小时(与普通 App 的内购缓存一致);force=True 跳过缓存强制重抓。
    """
    global _data
    fetcher = _FETCHERS.get(name)
    if not fetcher:
        return None
    with _lock:
        if _data is None:
            _data = _load_disk()
        cached = _data.get(name)
        if not force and cached and _data.get("ts", 0) > _now() - SVC_TTL:
            return cached
        try:
            fresh = fetcher()
        except Exception as e:
            print(f"⚠️ Apple 服务价格抓取失败({name}): {e}")
            return cached
        if fresh:
            _data[name] = fresh
            _save_disk(_data)
            return fresh
        return cached


def _now():
    import time as _t
    return _t.time()


def lookup_view(name):
    """/atlas/lookup?id=svc:<name> → iTunes lookup 兼容结构(供详情页管线)。"""
    svc = SVC_APPS.get(name)
    if not svc:
        return {"resultCount": 0, "results": []}
    return {"resultCount": 1, "results": [{
        "trackId": name,
        "trackName": svc["name"],
        "artistName": "Apple",
        "artworkUrl100": svc["icon"],
        "artworkUrl60": svc["icon"],
        "description": svc["desc"],
        "primaryGenreName": svc["genre"],
        "formattedPrice": "按区定价",
        "price": 0,
        "trackViewUrl": svc["url"],
        "sellerUrl": svc["url"],
        "version": "",
        "releaseNotes": "",
        "screenshotUrls": [],
        "languageCodesISO2A": [],
    }]}


def iap_view(name, cc):
    """/atlas/iap?id=svc:<name>&country=<cc> → 内购兼容结构。

    详情页管线按国家逐个请求,把对应区的各档价格映射为 iap 条目;
    未覆盖区返回 not_listed(表格里显示「未上架」,与其他 App 一致)。
    """
    svc = SVC_APPS.get(name)
    data = get_service(name)
    if not svc or not data:
        return {"country": cc, "ok": False, "reason": "not_listed"}
    row = next((r for r in data["regions"]
                if r["cc"] == cc.upper() and any(r.get("prices"))), None)
    if not row:
        return {"country": cc, "ok": False, "reason": "not_listed"}
    iaps = []
    for i, tier in enumerate(data["tiers"]):
        text = (row.get("prices") or [None] * len(data["tiers"]))[i]
        price = parse_price(text)
        if text and price:
            iaps.append({
                "iapId": f"svc-{name}-{i}",
                "name": svc["tiers"][i] if i < len(svc["tiers"]) else tier,
                "isSubscription": True,
                "groupName": svc["group"],
                "currencyCode": row.get("currency") or REGION_CURRENCY.get(cc.upper(), "USD"),
                "price": price,
                "priceFormatted": text,
                "period": "P1M",
            })
    if not iaps:
        return {"country": cc, "ok": False, "reason": "not_listed"}
    return {"country": cc, "ok": True, "appName": svc["name"], "iaps": iaps}


def build_offers_map(name, regions):
    """监控管线用:与 apple.build_offers_map 同构的报价快照。

    offerKey → {name, period, prices:{cc:price}, currency:{cc:cur}}
    数据来自官网缓存,不触网。
    """
    data = get_service(name)
    svc = SVC_APPS.get(name)
    offers = {}
    if not data or not svc:
        return offers
    for i, tier in enumerate(data["tiers"]):
        prices, curs = {}, {}
        for r in data["regions"]:
            lst = r.get("prices") or []
            text = lst[i] if i < len(lst) else None
            p = parse_price(text)
            if p:
                cc = r["cc"]
                prices[cc] = p
                curs[cc] = r.get("currency") or REGION_CURRENCY.get(cc, "USD")
        if prices:
            offers[f"svc-{name}-{i}"] = {
                "name": svc["tiers"][i] if i < len(svc["tiers"]) else tier,
                "period": "P1M", "prices": prices, "currency": curs,
            }
    return offers
