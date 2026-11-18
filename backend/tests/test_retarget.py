"""已钉日核销写入 → 改挂到最早开放日（全局互斥语义：改挂，不硬拒、不暗写）。"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.db import connect
from app.services import event_service, redeem_service, catalog_service
from tests.conftest import set_day


def redeem(coupon: str, day: str | None = None, occurred: str | None = None, amount: float | None = None):
    body = {"event_type": "redeem", "coupon_code": coupon, "campaign_code": "NEW10"}
    if day:
        body["business_day"] = day
    if occurred:
        body["occurred_at"] = occurred
    if amount is not None:
        body["amount"] = amount
    return event_service.add_event(body)


def facts_of(day: str):
    return redeem_service.list_facts(day)


def test_write_to_sealed_day_retargets_to_open_day(db):
    today = db
    yday = "2026-11-17"
    # 11-17 有一笔原生核销并被钉扎
    redeem("C-1", day=yday, occurred=f"{yday}T12:00:00")
    redeem_service.seal({"business_day": yday})

    # 已钉日写入：带着 11-17 的 occurred_at 与 business_day
    r = redeem("C-2", day=yday, occurred=f"{yday}T22:00:00")

    # 回执不撒谎：业务日是落库日，且标明改挂来源与原始 occurred_at
    assert r["business_day"] == today
    assert r["retargeted"] is True
    assert r["retarget_from"] == yday
    assert r["occurred_at"] == f"{yday}T22:00:00"

    # 已钉日事实不暗增
    sealed_day_facts = facts_of(yday)
    assert [f["coupon_code"] for f in sealed_day_facts] == ["C-1"]

    # 事件与事实同改挂、同事务落库，均打 retarget_from
    landed = facts_of(today)
    assert len(landed) == 1
    assert landed[0]["coupon_code"] == "C-2"
    assert landed[0]["retarget_from"] == yday
    ev = [e for e in event_service.list_events(today) if e["coupon_code"] == "C-2"]
    assert len(ev) == 1
    assert ev[0]["business_day"] == today
    assert ev[0]["retarget_from"] == yday
    assert ev[0]["occurred_at"] == f"{yday}T22:00:00"
    assert ev[0]["id"] == r["event_id"] and landed[0]["event_id"] == r["event_id"]


def test_retarget_skips_run_of_consecutive_sealed_days(db):
    # 当前业务日推到 11-19，连续钉死 11-17、11-18
    set_day("2026-11-19")
    redeem("C-1", day="2026-11-17")
    redeem_service.seal({"business_day": "2026-11-17"})
    redeem("C-2", day="2026-11-18")
    redeem_service.seal({"business_day": "2026-11-18"})

    r = redeem("C-3", day="2026-11-17", occurred="2026-11-17T09:30:00")

    assert r["business_day"] == "2026-11-19"
    assert r["retarget_from"] == "2026-11-17"
    assert facts_of("2026-11-17")[0]["coupon_code"] == "C-1"
    assert facts_of("2026-11-18")[0]["coupon_code"] == "C-2"
    landed = facts_of("2026-11-19")
    assert [f["coupon_code"] for f in landed] == ["C-3"]
    assert landed[0]["retarget_from"] == "2026-11-17"


def test_no_open_day_fails_without_partial_write(db):
    today = db
    yday = "2026-11-17"
    # 钉死 11-17 与当前日 11-18 → 目标 11-17 时 [11-17, 11-18] 无开放日
    redeem("C-0", day=yday)
    redeem_service.seal({"business_day": yday})
    redeem("C-1", day=today)
    redeem_service.seal({"business_day": today})

    with pytest.raises(HTTPException) as ei:
        redeem("C-2", day=yday, occurred=f"{yday}T23:00:00")
    assert ei.value.status_code == 409

    # 不得半写：事件与事实都没有 C-2
    assert all(f["coupon_code"] != "C-2" for f in facts_of(today))
    assert all(f["coupon_code"] != "C-2" for f in facts_of(yday))
    conn = connect()
    try:
        n = conn.execute("SELECT COUNT(*) c FROM coupon_events WHERE coupon_code='C-2'").fetchone()["c"]
    finally:
        conn.close()
    assert n == 0


def test_sealed_current_day_without_target_also_fails(db):
    today = db
    redeem("C-1", day=today)
    redeem_service.seal({"business_day": today})
    # 不带 business_day/occurred_at → 目标即当前业务日（已钉），范围内唯一候选已钉 → 失败
    with pytest.raises(HTTPException) as ei:
        redeem("C-2")
    assert ei.value.status_code == 409


def test_sealing_retarget_day_snapshots_retarget_totals(db):
    today = db
    yday = "2026-11-17"
    redeem("C-0", day=yday)
    redeem_service.seal({"business_day": yday})

    # 两笔改挂进 11-18，一笔原生
    redeem("C-1", day=yday, amount=10)
    redeem("C-2", day=yday, amount=10)
    redeem("C-3", day=today, amount=10)

    # 预览与批快照同源
    pv = redeem_service.preview(today)
    assert pv["open_count"] == 3
    assert pv["retarget_open_count"] == 2
    assert pv["retarget_open_total"] == 20.0

    r = redeem_service.seal({"business_day": today})
    assert r["fact_count"] == 3
    assert r["total_amount"] == 30.0
    assert r["retarget_count"] == pv["retarget_open_count"] == 2
    assert r["retarget_amount"] == pv["retarget_open_total"] == 20.0

    batch = [b for b in redeem_service.list_batches() if b["business_day"] == today][0]
    assert batch["retarget_count"] == 2
    assert batch["retarget_amount"] == 20.0
    # 事实列表同源：改挂笔在事实行上可核对
    rt = [f for f in facts_of(today) if f["retarget_from"]]
    assert len(rt) == 2 and all(f["retarget_from"] == yday for f in rt)
    assert all(f["status"] == "sealed" and f["batch_id"] == r["batch_id"] for f in facts_of(today))


def test_occurred_at_drives_attribution_and_is_preserved(db):
    today = db
    yday = "2026-11-17"
    redeem("C-0", day=yday)
    redeem_service.seal({"business_day": yday})

    # 不带 business_day，只带已钉日的 occurred_at → 目标日由 occurred_at 决定
    r = redeem("C-9", occurred=f"{yday}T23:10:00")
    assert r["retargeted"] is True
    assert r["retarget_from"] == yday
    assert r["business_day"] == today
    assert r["occurred_at"] == f"{yday}T23:10:00"


def test_open_day_write_untouched_and_issue_void_not_gated(db):
    today = db
    yday = "2026-11-17"
    redeem("C-0", day=yday)
    redeem_service.seal({"business_day": yday})

    # 开放日正常写：无改挂标记
    r = redeem("C-1", day=today)
    assert r["business_day"] == today and r["retargeted"] is False and r["retarget_from"] is None

    # issue/void 不产生核销事实，不受日闸限制
    e = event_service.add_event({"event_type": "issue", "coupon_code": "C-7", "campaign_code": "NEW10", "business_day": yday})
    assert e["business_day"] == yday and e["fact_id"] is None


def test_dashboard_counts_retargeted_events_on_landing_day(db):
    today = db
    yday = "2026-11-17"
    redeem("C-0", day=yday)
    redeem_service.seal({"business_day": yday})
    redeem("C-1", day=yday)  # 改挂进今天

    d = catalog_service.dashboard()
    assert d["business_day"] == today
    assert d["event_count"] == 1
    assert d["retarget_event_count"] == 1
    assert d["fact_count"] == 1
    assert d["open_fact_count"] == 1
