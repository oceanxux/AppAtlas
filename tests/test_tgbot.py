# -*- coding: utf-8 -*-
"""TG 机器人回复构建与交互解析(全部 mock 网络,不触网)。"""
from appatlas import tgbot


# ---------- 解析 ----------

def test_split_region():
    assert tgbot.split_region("us 308111628") == ("us", "308111628")
    assert tgbot.split_region("308111628") == ("", "308111628")
    # "id 123456" 是 ID 查询,不是印尼区码
    assert tgbot.split_region("id 123456") == ("", "id 123456")


def test_extract_target():
    assert tgbot.extract_target("308111628") == ("308111628", "")
    assert tgbot.extract_target("id308111628") == ("308111628", "")
    assert tgbot.extract_target("https://apps.apple.com/us/app/id308111628") \
        == ("308111628", "us")
    assert tgbot.extract_target("https://itunes.apple.com/app/id6448311069") \
        == ("6448311069", "")
    assert tgbot.extract_target("chatgpt") == (None, "")


def test_extract_id_loose():
    assert tgbot.extract_id_loose("🔍 「1」搜索结果：\n1. App\n    ID: 1423538627") \
        == ("1423538627", "")
    assert tgbot.extract_id_loose("... id6448311069 ...") == ("6448311069", "")
    assert tgbot.extract_id_loose("no id here") == (None, "")


# ---------- 搜索结果 ----------

def test_search_reply_only_header(tmp_data):
    fake = {"resultCount": 2, "results": [
        {"trackId": 6448311069, "trackName": "ChatGPT", "formattedPrice": "Free"},
        {"trackId": 123456, "trackName": "<b>X&D</b>", "formattedPrice": "$0.99"},
    ]}
    out = tgbot.tg_build_search_reply("chatgpt", "us", fake)
    # 只输出标题提示;结果列表由内联按钮呈现
    assert "共 2 个结果" in out and "点下方按钮选择" in out
    assert "ChatGPT" not in out and "X&amp;D" not in out


def test_search_reply_empty(tmp_data):
    out = tgbot.tg_build_search_reply("zzz", "us", {"resultCount": 0, "results": []})
    assert "没有找到" in out


def test_search_keyboard(tmp_data):
    fake = {"resultCount": 2, "results": [
        {"trackId": 6448311069, "trackName": "ChatGPT", "formattedPrice": "Free"},
        {"trackId": 123456, "trackName": "X", "formattedPrice": "$0.99"},
    ]}
    kb = tgbot.tg_search_keyboard(fake)
    row0 = kb[0][0]
    assert row0["callback_data"] == "n:6448311069"
    assert "ChatGPT" in row0["text"]


# ---------- 价格报告 ----------

def test_price_report_order_and_escape(tmp_data, monkeypatch):
    monkeypatch.setattr(tgbot, "_lookup_name", lambda aid: "MyApp")
    monkeypatch.setattr(tgbot, "_lookup_first", lambda aid, cc: None)
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
    monkeypatch.setattr(tgbot, "_lookup_name", lambda aid: "MyApp")
    monkeypatch.setattr(tgbot, "_lookup_first", lambda aid, cc: None)
    monkeypatch.setattr(tgbot, "build_offers_map", lambda aid, regions: {})
    out = tgbot.tg_build_price_report("999")
    assert "未查到" in out


def test_app_kb_button(tmp_data):
    kb = tgbot.app_kb("6448311069")
    flat = [b for row in kb for b in row]
    url_btn = [b for b in flat if "url" in b]
    assert url_btn, "应有跳转按钮"
    assert url_btn[0]["text"] == "id6448311069 · 在 App Store 打开"
    assert "apps.apple.com" in url_btn[0]["url"]


# ---------- 本体 / 简介 / 更新 / 信息卡 ----------

def test_base_report(tmp_data, monkeypatch):
    monkeypatch.setattr(tgbot, "_lookup_name", lambda aid: "MyApp")
    monkeypatch.setattr(tgbot, "_lookup_first",
                        lambda aid, cc: {"trackPrice": 9.99, "currencyCode": "USD",
                                         "formattedPrice": "$9.99"})
    monkeypatch.setattr(tgbot.fx, "get_fx_rates",
                        lambda: {"USD": 1.0, "CNY": 7.0})
    out = tgbot.tg_build_base_report("123")
    assert "MyApp" in out and "本体价格" in out
    assert "$9.99" in out and "≈ ¥69.9" in out


def test_desc_and_release_escape(tmp_data, monkeypatch):
    monkeypatch.setattr(tgbot, "_lookup_first",
                        lambda aid, cc: {"trackName": "A<b>", "version": "1.0",
                                         "description": "d<b>", "releaseNotes": "r<b>"})
    d = tgbot.tg_build_desc_report("123")
    assert "A&lt;b&gt;" in d and "d&lt;b&gt;" in d
    r = tgbot.tg_build_release_report("123")
    assert "A&lt;b&gt;" in r and "r&lt;b&gt;" in r and "v1.0" in r


def test_info_card_empty_fields(tmp_data, monkeypatch):
    monkeypatch.setattr(tgbot, "_lookup_first", lambda aid, cc: {"trackName": "X"})
    out = tgbot.tg_build_info_card("123")
    assert "<b>X</b>" in out


# ---------- 权限 ----------

def test_allowed_chat():
    assert tgbot.tg_allowed_chat({}) == ""
    users = {"u": {"channels": {"tg": {"bot_token": "t", "chat_id": "42"}}}}
    assert tgbot.tg_allowed_chat(users) == "42"


# ---------- 指令分发 ----------

def test_handle_commands(tmp_data, monkeypatch):
    sent = []
    monkeypatch.setattr(tgbot, "send_message",
                        lambda token, chat, text, kb=None: sent.append((text, kb)))
    monkeypatch.setattr(tgbot, "build_search_view",
                        lambda term, cc="us": ("search:" + term, None))
    monkeypatch.setattr(tgbot, "tg_build_info_card",
                        lambda aid, cc="": "card:" + aid)

    tgbot.tg_handle_command("t", "1", "/s chatgpt")
    assert sent[-1] == ("search:chatgpt", None)

    tgbot.tg_handle_command("t", "1", "/s 6448311069")
    assert sent[-1][0] == "card:6448311069"
    assert "url" in sent[-1][1][0][0] or any(
        row and row[0].get("url") for row in sent[-1][1])

    # 无参数时报用法
    tgbot.tg_handle_command("t", "1", "/b")
    assert "用法" in sent[-1][0]