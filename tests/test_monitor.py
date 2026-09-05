# -*- coding: utf-8 -*-
"""监控差分逻辑 diff_watch。"""
from appatlas.monitor import diff_watch


def offer(name="Plus", period="P1M", prices=None, currency=None):
    return {"name": name, "period": period,
            "prices": prices or {"US": 9.99},
            "currency": currency or {"US": "USD"}}


BASE = {"k1": offer()}


def test_first_run_baseline_only():
    assert diff_watch(None, BASE, {}) == []


def test_drop_event():
    ev = diff_watch(BASE, {"k1": offer(prices={"US": 7.99})}, {"triggers": ["drop"]})
    assert [e["type"] for e in ev] == ["drop"]
    assert ev[0]["old"] == 9.99 and ev[0]["new"] == 7.99


def test_raise_event():
    ev = diff_watch(BASE, {"k1": offer(prices={"US": 12.99})}, {"triggers": ["raise"]})
    assert [e["type"] for e in ev] == ["raise"]


def test_no_change_no_event():
    assert diff_watch(BASE, {"k1": offer()}, {}) == []


def test_new_and_remove():
    ev = diff_watch(BASE, {"k2": offer("Pro")}, {"triggers": ["new", "remove"]})
    assert sorted(e["type"] for e in ev) == ["new", "remove"]


def test_region_filter():
    prev = {"k1": offer(prices={"US": 9.99, "TR": 40})}
    cur = {"k1": offer(prices={"US": 9.99, "TR": 30})}
    ev = diff_watch(prev, cur, {"triggers": ["drop"], "regions": ["US"]})
    assert ev == []
