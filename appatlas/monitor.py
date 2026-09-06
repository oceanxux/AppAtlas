# -*- coding: utf-8 -*-
"""价格监控:定时拉取监控中的 App 报价,与上次快照对比生成事件并推送。"""
import time

from . import applesvc, config, notify, store
from .apple import build_offers_map


def diff_watch(prev, current, watch):
    """对比上次快照,按 watch 的触发条件生成事件列表。首次只记基线不报事件。"""
    triggers = set(watch.get("triggers") or ["drop", "raise", "new", "remove"])
    offers_f = set(watch.get("offers") or [])
    regions_f = set(watch.get("regions") or [])
    events = []
    now = int(time.time())

    def ok_region(cc): return not regions_f or cc in regions_f
    def ok_offer(key): return not offers_f or key in offers_f

    if not prev:
        return events
    for key, cur in current.items():
        if not ok_offer(key):
            continue
        old = prev.get(key)
        if old is None:
            if "new" in triggers:
                events.append({"ts": now, "type": "new", "offer": cur["name"],
                               "period": cur["period"], "detail": "新增套餐"})
            continue
        for cc, price in cur["prices"].items():
            if price is None or not ok_region(cc):
                continue
            oldp = old["prices"].get(cc)
            if oldp in (None, 0) or price in (None, 0) or price == oldp:
                continue
            ev = {"ts": now, "offer": cur["name"], "period": cur["period"],
                  "region": cc, "old": oldp, "new": price,
                  "currency": cur["currency"].get(cc, "")}
            if price < oldp and "drop" in triggers:
                events.append({**ev, "type": "drop"})
            elif price > oldp and "raise" in triggers:
                events.append({**ev, "type": "raise"})
    if "remove" in triggers:
        for key, old in prev.items():
            if key not in current and ok_offer(key):
                events.append({"ts": now, "type": "remove",
                               "offer": old.get("name", key),
                               "period": old.get("period", ""),
                               "detail": "套餐已移除"})
    return events


def run_monitor_pass():
    users, meta = store.load_users()
    jobs = {}
    for uname, rec in users.items():
        for w in rec.get("watches", []):
            jobs.setdefault(str(w.get("app_id")), []).append((uname, w))
    if not jobs:
        return
    monitor = store.load_json_file(config.MONITOR_FILE, {})
    notifs = store.load_json_file(config.NOTIF_FILE, {})
    changed = False
    for aid, watchers in jobs.items():
        regions = set()
        for _, w in watchers:
            regions.update(w.get("regions") or config.DEFAULT_MONITOR_REGIONS)
        if str(aid) in applesvc.SVC_APPS or str(aid).startswith("svc:"):
            current = applesvc.build_offers_map(str(aid).replace("svc:", ""), sorted(regions))
        else:
            current = build_offers_map(aid, sorted(regions))
        prev = (monitor.get(aid) or {}).get("offers")
        app_name = watchers[0][1].get("name") or aid
        for uname, w in watchers:
            events = diff_watch(prev, current, w)
            if not events:
                continue
            lst = notifs.setdefault(uname, [])
            for ev in events:
                ev.update({"app_id": aid, "app_name": app_name,
                           "icon": w.get("icon", "")})
            lst[:0] = events
            del lst[100:]
            changed = True
            notify.push_events(users.get(uname) or {}, app_name, events)
        monitor[aid] = {"ts": time.time(), "offers": current}
        changed = True
        time.sleep(1)  # App 之间歇一下,配合全局节流
    if changed:
        store.save_json_file(config.MONITOR_FILE, monitor)
        store.save_json_file(config.NOTIF_FILE, notifs)


def monitor_loop():
    time.sleep(45)
    while True:
        try:
            run_monitor_pass()
        except Exception as e:
            print(f"⚠️ 监控任务异常: {e}")
        time.sleep(config.MONITOR_HOURS * 3600)
