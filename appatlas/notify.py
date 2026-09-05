# -*- coding: utf-8 -*-
"""推送渠道:Telegram / Bark(iOS) / HTTP Webhook。"""
import json
import urllib.request

from . import config


def tg_send(bot_token, chat_id, text):
    if not bot_token or not chat_id:
        return False
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data=json.dumps({"chat_id": chat_id, "text": text[:4000],
                             "parse_mode": "HTML",
                             "disable_web_page_preview": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=8)
        return True
    except Exception as e:
        print(f"⚠️ TG 推送失败: {e}")
        return False


def http_post_json(url, payload):
    if not url:
        return False
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=8)
        return True
    except Exception as e:
        print(f"⚠️ Webhook 推送失败: {e}")
        return False


def bark_send(cfg, title, body):
    """Bark (iOS) 推送:POST {server}/push,server 默认官方 api.day.app。"""
    key = (cfg or {}).get("device_key", "")
    if not key:
        return False
    server = ((cfg or {}).get("server") or "https://api.day.app").rstrip("/")
    try:
        req = urllib.request.Request(
            f"{server}/push",
            data=json.dumps({"device_key": key, "title": title[:64],
                             "body": body[:800], "group": "AppAtlas"}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=8)
        return True
    except Exception as e:
        print(f"⚠️ Bark 推送失败: {e}")
        return False


def push_events(rec, app_name, events):
    """把事件推送到用户配置的所有渠道(TG / Bark / HTTP Webhook)。"""
    ch = rec.get("channels") or {}
    first = config.TYPE_LABEL.get(events[0]["type"], "")
    html_lines = [f"<b>{first} {app_name}</b>"]
    plain_lines = [f"{first} {app_name}"]
    for e in events[:10]:
        if e["type"] in ("drop", "raise"):
            seg = f"• {e['offer']}({e['period']}) {e['region']}: {e['old']} → {e['new']} {e.get('currency','')}"
        else:
            seg = f"• {e['offer']} — {e.get('detail','')}"
        html_lines.append(seg)
        plain_lines.append(seg)
    if ch.get("tg", {}).get("bot_token") and ch["tg"].get("chat_id"):
        tg_send(ch["tg"]["bot_token"], ch["tg"]["chat_id"], "\n".join(html_lines))
    if ch.get("bark", {}).get("device_key"):
        bark_send(ch["bark"], f"{first} {app_name}", "\n".join(plain_lines[1:]) or "有新的价格变动")
    if ch.get("http", {}).get("url"):
        http_post_json(ch["http"]["url"], {"app": app_name, "events": events[:20]})
