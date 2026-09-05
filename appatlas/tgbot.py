# -*- coding: utf-8 -*-
"""Telegram 查价机器人。

用户在 TG 里给机器人发 App 名称 → 返回搜索结果;发 App ID → 返回各区订阅最低价。
复用推送渠道里配置的 bot_token(保存后 ~30s 内自动生效);只响应已绑定
chat_id 的会话,未配置 chat_id 时不限制。
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
from .notify import tg_send

_bot_state = {"token": "", "gen": 0}


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


def tg_allowed_chat(users):
    """返回绑定的 chat_id;未配置则返回 ""(不限制)。"""
    for rec in users.values():
        tg = (rec.get("channels") or {}).get("tg") or {}
        if tg.get("bot_token") and tg.get("chat_id"):
            return str(tg["chat_id"])
    return ""


def tg_build_search_reply(term):
    """名称 → itunes 搜索前 8 条(与 /api/search 同源同缓存)。"""
    data = _search_cached(term)
    results = (data or {}).get("results") or []
    if not results:
        return f"🔍 没有找到「{html.escape(term[:40])}」，试试完整名称或直接发 App ID"
    lines = [f"🔍 <b>「{html.escape(term[:40])}」</b>搜索结果："]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. <b>{html.escape(r.get('trackName', ''))}</b>"
                     f" — {html.escape(str(r.get('formattedPrice', '')))}\n"
                     f"    ID: <code>{r.get('trackId')}</code>")
    lines.append("\n👇 回复 App ID 查看各区订阅最低价")
    return "\n".join(lines)


def _search_cached(term):
    def _fetch():
        try:
            return http_get_json(
                "https://itunes.apple.com/search?"
                f"term={urllib.parse.quote(term)}&country=us&entity=software&limit=8")
        except Exception:
            return None
    key = f"search:us:{hashlib.md5(term.lower().encode()).hexdigest()}"
    return cache.cached_fetch(key, 86400, _fetch,
                              ttl_fn=lambda x: 86400 if x.get("resultCount") else 600)


def tg_build_price_report(aid):
    """App ID → 快查 8 区订阅最低价(与网页端同一套报价逻辑)。"""
    name = aid
    try:
        d = http_get_json(
            f"https://itunes.apple.com/lookup?id={aid}&country=us&entity=software",
            timeout=8)
        if d.get("resultCount"):
            name = d["results"][0].get("trackName", aid)
    except Exception:
        pass
    offers = build_offers_map(aid, config.TG_QUICK_REGIONS)
    if not offers:
        return f"❌ 未查到 <b>{html.escape(str(name))}</b>（ID {aid}）的内购信息"
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
        priced = [(cc, p) for cc, p in o["prices"].items() if p]
        if not priced:
            continue
        est = [(to_cny(p, o["currency"].get(cc, "USD")), cc, p)
               for cc, p in priced]
        best = min(est, key=lambda x: (x[0] if x[0] is not None else float("inf"),
                                       x[2]))
        rows.append((o, best))
    # 订阅在前,按人民币估价从低到高
    rows.sort(key=lambda x: (x[0]["period"] == "ONCE",
                             x[1][0] if x[1][0] is not None else float("inf")))
    lines = [f"📊 <b>{html.escape(str(name))}</b> 各区最低价"]
    for o, (est, cc, p) in rows[:8]:
        cur = o["currency"].get(cc, "")
        seg = (f"• {html.escape(o['name'])}"
               f" [{config.PERIOD_LABEL.get(o['period'], o['period'])}]"
               f" — {p} {cur}（{cc}）")
        if est is not None:
            seg += f" ≈ ¥{est:.1f}"
        lines.append(seg)
    lines.append(f"\n<i>共 {len(rows)} 项，快查 {len(config.TG_QUICK_REGIONS)} 区；"
                 f"完整比价请用网页端</i>")
    return "\n".join(lines)


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
        cmd = text.split()[0].split("@")[0]
        if cmd in ("/start", "/help"):
            tg_send(token, chat, config.TG_HELP)
        return
    tg_call(token, "sendChatAction",
            {"chat_id": chat, "action": "typing"}, timeout=8)
    m = re.search(r"id(\d{6,})|^(\d{6,})$", text)
    if m:
        reply = tg_build_price_report(m.group(1) or m.group(2))
    elif len(text) <= 64:
        reply = tg_build_search_reply(text)
    else:
        reply = "⚠️ 查询词太长了，请发送 App 名称或 App ID"
    tg_send(token, chat, reply)


def tg_bot_loop(token, gen):
    """getUpdates 长轮询;token 更换/清除时由 manager 换代退出。"""
    tg_call(token, "deleteWebhook", {"drop_pending_updates": False}, timeout=8)
    print("🤖 TG 查价机器人已启动：发 App 名称出搜索，发 App ID 出各区最低价")
    offset = 0
    while _bot_state["gen"] == gen:
        data = tg_call(token, "getUpdates",
                       {"timeout": 25, "offset": offset,
                        "allowed_updates": ["message"]})
        if not data or not data.get("ok"):
            time.sleep(5)
            continue
        for upd in data.get("result") or []:
            offset = max(offset, upd.get("update_id", 0) + 1)
            try:
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
