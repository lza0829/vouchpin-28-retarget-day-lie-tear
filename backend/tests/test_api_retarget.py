"""HTTP 层：回执字段与 409 失败体端到端核对（绕开 app.main 的 seed 副作用，直接挂路由）。"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import events, redeem, dashboard


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(events.router, prefix="/api")
    app.include_router(redeem.router, prefix="/api")
    app.include_router(dashboard.router, prefix="/api")
    return TestClient(app)


def test_receipt_marks_retarget_and_never_claims_sealed_day(db):
    today = db
    yday = "2026-11-17"
    c = make_client()
    assert c.post("/api/events", json={"event_type": "redeem", "coupon_code": "C-1", "campaign_code": "NEW10", "business_day": yday}).status_code == 200
    assert c.post("/api/redeem/seal", json={"business_day": yday}).status_code == 200

    r = c.post("/api/events", json={
        "event_type": "redeem", "coupon_code": "C-2", "campaign_code": "NEW10",
        "business_day": yday, "occurred_at": f"{yday}T22:00:00",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["business_day"] == today          # 回执写落库日，不写已钉日
    assert body["retargeted"] is True
    assert body["retarget_from"] == yday
    assert body["occurred_at"] == f"{yday}T22:00:00"

    # 预览 / 事实列表 / 回执三处同源
    pv = c.get(f"/api/redeem/preview?business_day={today}").json()
    assert pv["open_count"] == 1 and pv["retarget_open_count"] == 1
    facts = c.get(f"/api/facts?business_day={today}").json()
    assert facts[0]["coupon_code"] == "C-2" and facts[0]["retarget_from"] == yday
    assert c.get(f"/api/facts?business_day={yday}").json()[0]["coupon_code"] == "C-1"


def test_no_open_day_returns_409_and_writes_nothing(db):
    today = db
    c = make_client()
    c.post("/api/events", json={"event_type": "redeem", "coupon_code": "C-1", "campaign_code": "NEW10", "business_day": today})
    assert c.post("/api/redeem/seal", json={"business_day": today}).status_code == 200

    r = c.post("/api/events", json={"event_type": "redeem", "coupon_code": "C-2", "campaign_code": "NEW10", "business_day": today})
    assert r.status_code == 409
    assert "无开放日" in r.json()["detail"]

    events = c.get(f"/api/events?business_day={today}").json()
    assert [e["coupon_code"] for e in events] == ["C-1"]
    dash = c.get("/api/dashboard").json()
    assert dash["fact_count"] == 1 and dash["day_sealed"] is True
