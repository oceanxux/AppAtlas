# -*- coding: utf-8 -*-
"""TG 机器人回复构建(全部 mock 网络,不触网)。"""
from appatlas import tgbot


def test_search_reply_lists_ids_and_escapes(tmp_data, monkeypatch):
    fake = {"resultCount": 2, "results": [
        {"trackId": 6448311069, "trackName": "ChatGPT", "formattedPrice": "Free"},
        {"trackId": 123456, "trackName": "<b>X&D</b>", "formattedPrice": "$0.99"},
    ]}
    monkeypatch.setattr(tgbot, "_search_cached", lambda term: fake)
    out = tgbot.tg_build_search_reply("chatgpt")
    assert "6448311069" in out and "ChatGPT" in out
    assert "&lt;b&gt;X&amp;D&lt;/b&gt;" in out  # HTML 注入被转义


def test_search_reply_empty(tmp_data, monkeypatch):
    monkeypatch.setattr(tgbot, "_search_cached", lambda term: {"resultCount": 0, "results": []})
    out = tgbot.tg_build_search_reply("zzz")
    assert "没有找到" in out


def test_price_report_order_and_escape(tmp_data, monkeypatch):
    monkeypatch.setattr(tgbot, "http_get_json",
                        lambda url, **kw: {"resultCount": 1,
                                           "results": [{"trackName": "MyApp"}]})
    monkeypatch.setattr(tgbot, "build_offers_map", lambda aid, regions: {
        "b": {"name": "Pro", "period": "P1M",
              "prices": {"US": 99.0}, "currency": {"US": "USD"}},
        "a": {"name": "Plus", "period": "P1M",
              "prices": {"US": 9.99, "TR": 40.0},
              "currency": {"US": "USD", "TR": "TRY"}},
        "c": {"name": "Lifetime <x>", "period": "ONCE",
              "prices": {"US": 19.9}, "currency": {"US": "USD"}},
    })
    monkeypatch.setattr(tgbot.fx, "get_fx_rates",
                        lambda: {"USD": 1.0, "TRY": 40.0, "CNY": 7.0})
    out = tgbot.tg_build_price_report("123")
    assert "MyApp" in out
    # 订阅在前、按人民币估价升序:Plus(TR ¥7) → Pro(US ¥693) → 买断最后
    assert out.index("Plus") < out.index("Pro") < out.index("Lifetime")
    assert "40.0 TRY（TR）" in out and "≈ ¥7.0" in out
    assert "Lifetime &lt;x&gt;" in out


def test_price_report_no_offers(tmp_data, monkeypatch):
    monkeypatch.setattr(tgbot, "http_get_json",
                        lambda url, **kw: {"resultCount": 0, "results": []})
    monkeypatch.setattr(tgbot, "build_offers_map", lambda aid, regions: {})
    out = tgbot.tg_build_price_report("999")
    assert "未查到" in out


def test_allowed_chat(tmp_data):
    assert tgbot.tg_allowed_chat({}) == ""
    users = {"u": {"channels": {"tg": {"bot_token": "t", "chat_id": "42"}}}}
    assert tgbot.tg_allowed_chat(users) == "42"
