"""五本日历账同口径的跨账本不变量。

打穿四类谎言：
1. 回执可写日行在不可写日 / 三日互不一致 —— 回执日=事件折日=事实归属日=落库日；
2. 不可写日残留迁出成功行 —— 已钉日事实行不暗增、无 retarget 行；
3. 附注 0 —— 目标批附注计数与真实改挂事实行严格相等；
4. 无可用日半写 —— 409 时事件与事实都不存在；外加事实写入失败整笔回滚。
另核水位与批头同源、预览/批快照/回执三处同源。
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.db import connect
from app.services import event_service, redeem_service, catalog_service
from app.services import day_claim
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


def events_of(day: str):
    return event_service.list_events(day)


def test_receipt_event_fact_three_days_are_one_landing_day(db):
    today, yday = db, "2026-11-17"
    redeem("C-1", day=yday, occurred=f"{yday}T12:00:00")
    redeem_service.seal({"business_day": yday})

    r = redeem("C-2", day=yday, occurred=f"{yday}T22:00:00")

    # 对外回执日 = 落库日（可写日），绝不可指向已钉的不可写日
    assert r["business_day"] == today
    assert r["retarget_from"] == yday
    # 事件折日
    ev = [e for e in events_of(today) if e["coupon_code"] == "C-2"]
    assert len(ev) == 1 and ev[0]["business_day"] == today and ev[0]["retarget_from"] == yday
    # 库内事实归属日
    ft = [f for f in facts_of(today) if f["coupon_code"] == "C-2"]
    assert len(ft) == 1 and ft[0]["business_day"] == today and ft[0]["retarget_from"] == yday
    # 三日同口径，且事件与事实互指
    assert r["business_day"] == ev[0]["business_day"] == ft[0]["business_day"] == today
    assert ev[0]["id"] == r["event_id"] and ft[0]["event_id"] == r["event_id"]
    # 回执里不得再出现第二套分叉日字段
    assert "event_day" not in r and "fact_day" not in r and "half" not in r


def test_sealed_day_keeps_no_retarget_success_rows(db):
    today, yday = db, "2026-11-17"
    redeem("C-1", day=yday)
    redeem_service.seal({"business_day": yday})
    redeem("C-2", day=yday, occurred=f"{yday}T22:00:00")
    redeem("C-3", day=yday, occurred=f"{yday}T23:00:00")

    # 不可写日上不得残留任何迁出成功行：事实仍是钉扎前那一笔，且无改挂标记
    sealed_facts = facts_of(yday)
    assert [f["coupon_code"] for f in sealed_facts] == ["C-1"]
    assert all(f["retarget_from"] is None for f in sealed_facts)
    # 已钉日事件湖中也不得折入改挂事件
    assert all(e["retarget_from"] is None for e in events_of(yday))

    # 改挂行全部在可写日落库
    landed = facts_of(today)
    assert {f["coupon_code"] for f in landed} == {"C-2", "C-3"}
    assert all(f["business_day"] == today and f["retarget_from"] == yday for f in landed)


def test_batch_annotation_equals_real_retarget_rows_never_zero(db):
    today, yday = db, "2026-11-17"
    redeem("C-0", day=yday)
    redeem_service.seal({"business_day": yday})
    redeem("C-1", day=yday, amount=10)
    redeem("C-2", day=yday, amount=10)
    redeem("C-3", day=today, amount=10)

    pv = redeem_service.preview(today)
    seal_r = redeem_service.seal({"business_day": today})

    # 批附注按真实迁出事实行重算：与预览、与事实行计数三方相等，禁止附注 0
    real_rows = [f for f in facts_of(today) if f["retarget_from"] == yday]
    batch = [b for b in redeem_service.list_batches() if b["business_day"] == today][0]
    assert seal_r["retarget_count"] == pv["retarget_open_count"] == len(real_rows) == 2
    assert seal_r["retarget_amount"] == pv["retarget_open_total"] == 20.0
    assert batch["retarget_count"] == len(real_rows)
    assert batch["retarget_amount"] == round(sum(float(f["amount"]) for f in real_rows), 2)
    assert batch["fact_count"] == len(facts_of(today))


def test_no_open_day_409_writes_neither_event_nor_fact(db):
    today, yday = db, "2026-11-17"
    redeem("C-0", day=yday)
    redeem_service.seal({"business_day": yday})
    redeem("C-1", day=today)
    redeem_service.seal({"business_day": today})

    with pytest.raises(HTTPException) as ei:
        redeem("C-2", day=yday, occurred=f"{yday}T23:00:00")
    assert ei.value.status_code == 409 and "无开放日" in ei.value.detail

    # 半写防线：事实、事件两个湖中都没有 C-2
    assert all(f["coupon_code"] != "C-2" for f in facts_of(today) + facts_of(yday))
    conn = connect()
    try:
        n_event = conn.execute("SELECT COUNT(*) c FROM coupon_events WHERE coupon_code='C-2'").fetchone()["c"]
        n_fact = conn.execute("SELECT COUNT(*) c FROM redeem_facts WHERE coupon_code='C-2'").fetchone()["c"]
    finally:
        conn.close()
    assert (n_event, n_fact) == (0, 0)


def test_fact_insert_failure_rolls_back_event_too(db):
    today = db
    # 同一券码二次核销：事实 UNIQUE 约束失败，事件必须随之一笔回滚，不得事件无事实
    redeem("DUP", day=today)
    with pytest.raises(HTTPException) as ei:
        redeem("DUP", day=today)
    assert ei.value.status_code == 409

    conn = connect()
    try:
        n_event = conn.execute("SELECT COUNT(*) c FROM coupon_events WHERE coupon_code='DUP'").fetchone()["c"]
        n_fact = conn.execute("SELECT COUNT(*) c FROM redeem_facts WHERE coupon_code='DUP'").fetchone()["c"]
    finally:
        conn.close()
    assert (n_event, n_fact) == (1, 1)


def test_watermark_and_batch_header_share_one_source(db):
    today, yday = db, "2026-11-17"
    conn = connect()
    try:
        # 开放日：水位可写，且无批头
        w = day_claim.watermark(conn, yday)
        assert w["write_open"] is True and w["watermark_sealed"] is False
        assert w["open_watermark"] == yday and w["stored_sealed"] is False
    finally:
        conn.close()

    redeem("C-1", day=yday)
    redeem_service.seal({"business_day": yday})

    conn = connect()
    try:
        # 钉后：水位必须改口不可写，与批头同源——不得“水位称可写，批头已钉”
        w = day_claim.watermark(conn, yday)
        assert w["write_open"] is False and w["watermark_sealed"] is True
        assert w["open_watermark"] is None and w["stored_sealed"] is True
    finally:
        conn.close()

    # 仪表盘扫的是当前业务日 today：钉扎前后水位与批头同样同源改口
    d_before = catalog_service.dashboard()
    assert d_before["business_day"] == today
    assert d_before["day_sealed"] is False and d_before["write_open"] is True
    redeem("C-2", day=today)
    redeem_service.seal({"business_day": today})
    d_after = catalog_service.dashboard()
    assert d_after["day_sealed"] is True and d_after["write_open"] is False


def test_run_of_sealed_days_lands_on_first_open_and_books_align(db):
    set_day("2026-11-19")
    redeem("C-1", day="2026-11-17")
    redeem_service.seal({"business_day": "2026-11-17"})
    redeem("C-2", day="2026-11-18")
    redeem_service.seal({"business_day": "2026-11-18"})

    r = redeem("C-3", day="2026-11-17", occurred="2026-11-17T09:30:00")
    assert r["business_day"] == "2026-11-19" and r["retarget_from"] == "2026-11-17"

    # 两个不可写日都无迁出残留，落库日事件与事实同口径
    assert [f["coupon_code"] for f in facts_of("2026-11-17")] == ["C-1"]
    assert [f["coupon_code"] for f in facts_of("2026-11-18")] == ["C-2"]
    landed = facts_of("2026-11-19")
    ev = events_of("2026-11-19")
    assert len(landed) == 1 and landed[0]["coupon_code"] == "C-3"
    assert len(ev) == 1 and ev[0]["business_day"] == landed[0]["business_day"] == "2026-11-19"
