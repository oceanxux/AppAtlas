# -*- coding: utf-8 -*-
"""Telegram 查价机器人。

命令式交互 + 内联按钮点选:
  /s 名称/ID/链接 [区码]  搜索应用;结果带按钮,点选直达订阅最低价
  /b ID/链接 [区码]       本体买断价格(默认 8 区快查)
  /n ID/链接 [区码]       内购/订阅各区最低价(默认 8 区快查)
  /j ID/链接              应用简介
  /g ID/链接              版本更新说明
不带指令直接发:名称→搜索,ID/链接→订阅最低价。
所有结果下方附 App Store 跳转链接与续查按钮。
复用推送渠道里配置的 bot_token(保存后 ~30s 内自动生效);
只响应已绑定 chat_id 的会话,未配置 chat_id 时不限制。
"""
import hashlib
import html
import json
import re
import threading
import time
import urllib.parse
import urllib.request

from . import cache, config, fx, store
from .apple import build_offers_map, http_get_json

_bot_state = {"token": "", "gen": 0}

# apps.apple.com / itunes.apple.com 应用链接(区码可选)
LINK_RE = re.compile(r"(?:apps|itunes)\.apple\.com/(?:([a-z]{2})/)?app/\S*?id(\d{6,})", re.I)

USAGE = {
    "s": "用法：/s 关键词 · /s us 关键词 · /s AppID 或 App Store 链接",
    "b": "用法：/b AppID 或链接 · 可加区码，如 /b us 308111628",
    "n": "用法：/n AppID 或链接 · 可加区码，如 /n tr 6448311069",
    "j": "用法：/j AppID 或链接（也可回复应用链接消息并带 /j）",
    "g": "用法：/g AppID 或链接（也可回复应用链接消息并带 /g）",
}


def tg_call(token, method, payload=None, timeout=35):
    """调用 Bot API,返回解析后的 JSON(失败返回 None)。"""
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/{method}",
            data=json.dumps(payload or {}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"⚠️ TG {method} 失败: {e}")
        return None


def send_message(token, chat, text, kb=None):
    """发送 HTML 消息,可带内联键盘。"""
    payload = {"chat_id": chat, "text": text[:4000], "parse_mode": "HTML",
               "disable_web_page_preview": True}
    if kb:
        payload["reply_markup"] = {"inline_keyboard": kb}
    return tg_call(token, "sendMessage", payload) is not None


def tg_allowed_chat(users):
    """返回绑定的 chat_id;未配置则返回 ""(不限制)。"""
    for rec in users.values():
        tg = (rec.get("channels") or {}).get("tg") or {}
        if tg.get("bot_token") and tg.get("chat_id"):
            return str(tg["chat_id"])
    return ""


# ---------- 解析 ----------

def esc(s):
    return html.escape(str(s or ""))


def _trunc(s, n):
    s = (s or "").strip()
    return s if len(s) <= n else s[:n].rstrip() + "…"


def split_region(s):
    """剥离开头的两字母地区码 → (cc, rest)。码后必须还有内容;
    "id 123456" 视为 ID 查询而非印尼区码。"""
    s = (s or "").strip()
    m = re.match(r"([a-zA-Z]{2})(?=\s)", s)
    if m:
        rest = s[m.end():].strip()
        if m.group(1).lower() == "id" and re.fullmatch(r"(?:id)?\d{6,}", rest):
            return "", s
        return m.group(1).lower(), rest
    return "", s


def extract_target(s):
    """从指令参数提取 (App ID, 链接区码)。支持纯 ID / id 前缀 / App Store 链接。"""
    s = (s or "").strip()
    m = LINK_RE.search(s)
    if m:
        return m.group(2), (m.group(1) or "").lower()
    m = re.fullmatch(r"(?:id)?(\d{6,})", s)
    if m:
        return m.group(1), ""
    return None, ""


def extract_id_loose(s):
    """从被回复消息的全文中宽松提取 App ID(链接优先,id 前缀次之,裸数字兜底)。"""
    m = LINK_RE.search(s or "")
    if m:
        return m.group(2), (m.group(1) or "").lower()
    m = re.search(r"(?:^|\s)id(\d{6,})(?:\s|$)", s or "", re.I)
    if m:
        return m.group(1), ""
    m = re.search(r"(?:^|\s)(\d{6,})(?:\s|$)", s or "")
    if m:
        return m.group(1), ""
    return None, ""


# ---------- 数据获取(与网页端同缓存键) ----------

def lookup_cached(aid, cc):
    """iTunes lookup(与 /api/lookup 同缓存键,lang 为空)。"""
    cc = (cc or "us").lower()
    key = f"lookup:{aid}:{cc}:"

    def _fetch():
        try:
            return http_get_json(
                f"https://itunes.apple.com/lookup?id={aid}&country={cc}&entity=software")
        except Exception:
            return None
    return cache.cached_fetch(key, 86400, _fetch,
                              ttl_fn=lambda x: 86400 if x.get("resultCount") else 600)


def _search_cached(term, cc="us"):
    cc = (cc or "us").lower()

    def _fetch():
        try:
            return http_get_json(
                "https://itunes.apple.com/search?"
                f"term={urllib.parse.quote(term)}&country={cc}&entity=software&limit=8")
        except Exception:
            return None
    key = f"search:{cc}:{hashlib.md5(term.lower().encode()).hexdigest()}"
    return cache.cached_fetch(key, 86400, _fetch,
                              ttl_fn=lambda x: 86400 if x.get("resultCount") else 600)


def _lookup_first(aid, cc):
    d = lookup_cached(aid, cc)
    if d and d.get("resultCount"):
        return d["results"][0]
    return None


def _lookup_name(aid):
    rec = _lookup_first(aid, "us")
    return rec.get("trackName", aid) if rec else aid


def apple_link(aid, cc=""):
    return f"https://apps.apple.com/{(cc or 'us').lower()}/app/id{aid}"


# ---------- 回复构建 ----------

def tg_build_search_reply(term, cc="us", data=None):
    """名称 → 搜索结果文本(与 /api/search 同源同缓存)。"""
    if data is None:
        data = _search_cached(term, cc)
    results = (data or {}).get("results") or []
    if not results:
        return (f"🔍 没有找到「{esc(term[:40])}」，试试完整名称、"
                f"App ID 或直接发 App Store 链接")
    lines = [f"🔍 <b>「{esc(term[:40])}」</b>搜索结果："]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. <b>{esc(r.get('trackName', ''))}</b>"
                     f" — {esc(str(r.get('formattedPrice', '')))}\n"
                     f"    ID: <code>{r.get('trackId')}</code>")
    lines.append("\n👇 点下方按钮直达订阅最低价（也可回复 App ID / 链接）")
    return "\n".join(lines)


def tg_search_keyboard(data):
    """搜索结果 → 每行一个 App 的点选按钮(点选 = 查订阅最低价)。"""
    kb = []
    for r in ((data or {}).get("results") or [])[:8]:
        label = f"📱 {r.get('trackName', '')} · {r.get('formattedPrice', '')}"
        kb.append([{"text": label[:60], "callback_data": f"n:{r.get('trackId')}"}])
    return kb


def build_search_view(term, cc="us"):
    data = _search_cached(term, cc)
    return tg_build_search_reply(term, cc, data), tg_search_keyboard(data)


def app_kb(aid, cc=""):
    """结果下方的操作按钮:订阅/本体/简介/更新 + App Store 跳转。"""
    def cb(cmd):
        return f"{cmd}:{cc}:{aid}" if cc else f"{cmd}:{aid}"
    return [
        [{"text": "💎 订阅最低价", "callback_data": cb("n")}],
        [{"text": "💰 本体价", "callback_data": cb("b")},
         {"text": "📝 简介", "callback_data": cb("j")},
         {"text": "🆕 更新", "callback_data": cb("g")}],
        [{"text": "🔗 打开 App Store", "url": apple_link(aid, cc)}],
    ]


def tg_build_price_report(aid, cc=""):
    """App ID → 各区订阅最低价(与网页端同一套报价逻辑)。"""
    name = _lookup_name(aid)
    regions = [cc.upper()] if cc else config.TG_QUICK_REGIONS
    offers = build_offers_map(aid, regions)
    link_line = f"\n🔗 <a href=\"{apple_link(aid, cc)}\">id{aid} · 在 App Store 打开</a>"
    if not offers:
        return f"❌ 未查到 <b>{esc(name)}</b>（ID {aid}）的内购信息\n{link_line}"
    rates = fx.get_fx_rates()

    def to_cny(price, cur):
        try:
            if rates and rates.get(cur) and rates.get("CNY"):
                return price / rates[cur] * rates["CNY"]
        except (TypeError, ZeroDivisionError):
            pass
        return None

    rows = []
    for o in offers.values():
        priced = [(k, p) for k, p in o["prices"].items() if p]
        if not priced:
            continue
        est = [(to_cny(p, o["currency"].get(k, "USD")), k, p) for k, p in priced]
        best = min(est, key=lambda x: (x[0] if x[0] is not None else float("inf"),
                                       x[2]))
        rows.append((o, best))
    # 订阅在前,按人民币估价从低到高
    rows.sort(key=lambda x: (x[0]["period"] == "ONCE",
                             x[1][0] if x[1][0] is not None else float("inf")))
    scope = f"{regions[0]} 区" if cc else f"{len(config.TG_QUICK_REGIONS)} 区快查"
    lines = [f"💎 <b>{esc(name)}</b> 各区订阅最低价（{scope}）"]
    for o, (est, k, p) in rows[:8]:
        cur = o["currency"].get(k, "")
        seg = (f"• {esc(o['name'])}"
               f" [{config.PERIOD_LABEL.get(o['period'], o['period'])}]"
               f" — {p} {cur}（{k}）")
        if est is not None:
            seg += f" ≈ ¥{est:.1f}"
        lines.append(seg)
    lines.append(f"\n<i>共 {len(rows)} 项；完整比价请用网页端</i>")
    lines.append(link_line)
    return "\n".join(lines)


def tg_build_base_report(aid, cc=""):
    """App ID → 本体买断价(默认 8 区快查,可指定单区),按人民币估价升序。"""
    name = _lookup_name(aid)
    regions = [cc.upper()] if cc else config.TG_QUICK_REGIONS
    rates = fx.get_fx_rates()
    rows = []
    for rgn in regions:
        rec = _lookup_first(aid, rgn)
        if not rec:
            continue
        price = rec.get("trackPrice")
        cur = rec.get("currencyCode") or ""
        est = float("inf")
        if price not in (None, 0) and rates and rates.get(cur) and rates.get("CNY"):
            try:
                est = price / rates[cur] * rates["CNY"]
            except (TypeError, ZeroDivisionError):
                pass
        rows.append((est, rgn, rec.get("formattedPrice") or "—"))
    link_line = f"\n🔗 <a href=\"{apple_link(aid, cc)}\">id{aid} · 在 App Store 打开</a>"
    if not rows:
        return f"❌ 未查到 <b>{esc(name)}</b>（ID {aid}）的价格信息\n{link_line}"
    rows.sort(key=lambda x: x[0])
    scope = f"{regions[0]} 区" if cc else f"{len(config.TG_QUICK_REGIONS)} 区快查"
    lines = [f"💰 <b>{esc(name)}</b> 本体价格（{scope}）"]
    for est, rgn, fp in rows:
        seg = f"• {rgn} — {esc(fp)}"
        if est != float("inf"):
            seg += f" ≈ ¥{est:.1f}"
        lines.append(seg)
    lines.append(link_line)
    return "\n".join(lines)


def tg_build_desc_report(aid, cc=""):
    """App ID → 应用简介。"""
    rec = _lookup_first(aid, cc or "us")
    if not rec:
        return f"❌ 未查到 ID {aid} 的应用信息"
    lines = [f"📝 <b>{esc(rec.get('trackName', ''))}</b> 简介", "",
             esc(_trunc(rec.get("description") or "（无简介）", 1000)),
             f"\n🔗 <a href=\"{apple_link(aid, cc)}\">id{aid} · 在 App Store 打开</a>"]
    return "\n".join(lines)


def tg_build_release_report(aid, cc=""):
    """App ID → 版本更新说明。"""
    rec = _lookup_first(aid, cc or "us")
    if not rec:
        return f"❌ 未查到 ID {aid} 的应用信息"
    lines = [f"🆕 <b>{esc(rec.get('trackName', ''))}</b> 更新说明"
             f"（v{esc(rec.get('version') or '?')}）", "",
             esc(_trunc(rec.get("releaseNotes") or "（本次更新未提供说明）", 1000)),
             f"\n🔗 <a href=\"{apple_link(aid, cc)}\">id{aid} · 在 App Store 打开</a>"]
    return "\n".join(lines)


def tg_build_info_card(aid, cc=""):
    """/s ID/链接 → 应用信息卡片。"""
    rec = _lookup_first(aid, cc or "us")
    if not rec:
        return f"❌ 未查到 ID {aid} 的应用信息"
    lines = [f"📱 <b>{esc(rec.get('trackName', ''))}</b>"]
    if rec.get("artistName"):
        lines.append(f"👨‍💻 {esc(rec['artistName'])}")
    meta = []
    if rec.get("primaryGenreName"):
        meta.append(f"🗂 {esc(rec['primaryGenreName'])}")
    if rec.get("version"):
        meta.append(f"🔧 v{esc(rec['version'])}")
    if meta:
        lines.append(" · ".join(meta))
    if rec.get("averageUserRating") is not None:
        lines.append(f"⭐ {rec['averageUserRating']:.1f}（{rec.get('userRatingCount') or 0:,}）")
    lines.append(f"💵 {esc(rec.get('formattedPrice') or '—')}（{(cc or 'us').upper()}）")
    lines.append(f"\n🔗 <a href=\"{apple_link(aid, cc)}\">id{aid} · 在 App Store 打开</a>")
    return "\n".join(lines)


BUILDERS = {"n": tg_build_price_report, "b": tg_build_base_report,
            "j": tg_build_desc_report, "g": tg_build_release_report}


def dispatch_view(cmd, aid, cc=""):
    """指令/按钮回调 → (回复文本, 内联键盘)。"""
    if cmd == "s":  # /s ID/链接 → 应用信息卡片
        return tg_build_info_card(aid, cc), app_kb(aid, cc)
    return BUILDERS[cmd](aid, cc), app_kb(aid, cc)


# ---------- 消息 / 回调处理 ----------

def tg_handle_command(token, chat, text, reply_text=""):
    parts = text.split(maxsplit=1)
    cmd = parts[0].split("@")[0].lower()
    rest = (parts[1] if len(parts) > 1 else "").strip()
    if cmd in ("/start", "/help"):
        return send_message(token, chat, config.TG_HELP)
    if cmd == "/s":
        if not rest:
            return send_message(token, chat, USAGE["s"])
        cc, term = split_region(rest)
        aid, linkcc = extract_target(term)
        tg_call(token, "sendChatAction", {"chat_id": chat, "action": "typing"}, timeout=8)
        if aid:
            return send_message(token, chat, *dispatch_view("s", aid, cc or linkcc))
        text_out, kb = build_search_view(term, cc or "us")
        return send_message(token, chat, text_out, kb)
    if cmd in ("/b", "/n", "/j", "/g"):
        cc, aid, linkcc = "", None, ""
        if rest:
            cc, rest2 = split_region(rest)
            aid, linkcc = extract_target(rest2)
        if not aid and reply_text:  # 无参数时,从被回复消息里取 ID/链接
            aid, linkcc = extract_id_loose(reply_text)
        if not aid:
            return send_message(token, chat, USAGE[cmd[1]])
        tg_call(token, "sendChatAction", {"chat_id": chat, "action": "typing"}, timeout=8)
        return send_message(token, chat, *dispatch_view(cmd[1], aid, cc or linkcc))
    return send_message(token, chat, "未知指令，发送 /help 查看用法")


def tg_handle_message(token, msg):
    text = (msg.get("text") or "").strip()
    chat = str((msg.get("chat") or {}).get("id", ""))
    if not text or not chat:
        return
    users, _ = store.load_users()
    allow = tg_allowed_chat(users)
    if allow and chat != allow:
        return  # 未绑定的会话,忽略
    if text.startswith("/"):
        reply = ((msg.get("reply_to_message") or {}).get("text") or "").strip()
        return tg_handle_command(token, chat, text, reply)
    tg_call(token, "sendChatAction", {"chat_id": chat, "action": "typing"}, timeout=8)
    aid, linkcc = extract_target(text)
    if aid:
        send_message(token, chat, *dispatch_view("n", aid, linkcc))
    elif len(text) <= 64:
        text_out, kb = build_search_view(text)
        send_message(token, chat, text_out, kb)
    else:
        send_message(token, chat, "⚠️ 查询词太长了，请发送 App 名称、ID 或 App Store 链接")


def tg_handle_callback(token, cbq):
    """内联按钮回调 → 按回调数据派发对应查询。"""
    data = (cbq.get("data") or "").strip()
    msg = cbq.get("message") or {}
    chat = str((msg.get("chat") or {}).get("id", ""))
    if not data or not chat:
        return
    users, _ = store.load_users()
    allow = tg_allowed_chat(users)
    if allow and chat != allow:
        return
    tg_call(token, "answerCallbackQuery", {"callback_query_id": cbq.get("id")}, timeout=8)
    parts = data.split(":")
    if parts[0] not in BUILDERS or not parts[-1].isdigit():
        return
    cc = parts[1] if len(parts) == 3 else ""
    tg_call(token, "sendChatAction", {"chat_id": chat, "action": "typing"}, timeout=8)
    send_message(token, chat, *dispatch_view(parts[0], parts[-1], cc))


# ---------- 轮询 ----------

def tg_bot_loop(token, gen):
    """getUpdates 长轮询;token 更换/清除时由 manager 换代退出。"""
    tg_call(token, "deleteWebhook", {"drop_pending_updates": False}, timeout=8)
    print("🤖 TG 查价机器人已上线：/help 看指令；发名称出搜索（点按钮选择），发 ID/链接出订阅最低价")
    users, _ = store.load_users()
    allow = tg_allowed_chat(users)
    if allow:  # 绑定成功提醒:推送使用说明到配置的会话
        send_message(token, allow, config.TG_HELP)
    offset = 0
    while _bot_state["gen"] == gen:
        data = tg_call(token, "getUpdates",
                       {"timeout": 25, "offset": offset,
                        "allowed_updates": ["message", "callback_query"]})
        if not data or not data.get("ok"):
            time.sleep(5)
            continue
        for upd in data.get("result") or []:
            offset = max(offset, upd.get("update_id", 0) + 1)
            try:
                if upd.get("callback_query"):
                    tg_handle_callback(token, upd["callback_query"])
                else:
                    tg_handle_message(token, upd.get("message") or {})
            except Exception as e:
                print(f"⚠️ TG 消息处理失败: {e}")
    print("🤖 TG 查价机器人已停止")


def tg_bot_manager_loop():
    """每 30s 扫描用户配置的 bot_token,变化时重启轮询线程。"""
    while True:
        try:
            users, _ = store.load_users()
            token = ""
            for rec in users.values():
                tg = (rec.get("channels") or {}).get("tg") or {}
                if tg.get("bot_token"):
                    token = tg["bot_token"]
                    break
            if token != _bot_state["token"]:
                _bot_state["gen"] += 1
                _bot_state["token"] = token
                if token:
                    threading.Thread(target=tg_bot_loop,
                                     args=(token, _bot_state["gen"]),
                                     daemon=True).start()
        except Exception as e:
            print(f"⚠️ TG 机器人管理异常: {e}")
        time.sleep(30)
