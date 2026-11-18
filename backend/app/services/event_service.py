from __future__ import annotations
from datetime import date, datetime
from typing import Any
from fastapi import HTTPException
from app.db import connect
from app.repositories import settings as settings_repo
from app.repositories import events as event_repo
from app.repositories import facts as fact_repo
from app.repositories import campaigns as camp_repo


def list_campaigns() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return camp_repo.list_all(conn)
    finally:
        conn.close()


def list_events(business_day: str | None = None) -> list[dict[str, Any]]:
    conn = connect()
    try:
        day = business_day or settings_repo.get(conn, "business_day")
        return event_repo.list_events(conn, day)
    finally:
        conn.close()


def _requested_day(conn, body: dict[str, Any]) -> str:
    """落库归属（三处同源的源头）：显式 business_day > occurred_at 当日 > 当前业务日。"""
    day = (body.get("business_day") or "").strip()
    if day:
        return day
    occurred = (body.get("occurred_at") or "").strip()
    if occurred:
        return occurred[:10]
    return settings_repo.get(conn, "business_day")


def _gate_redeem_day(conn, requested: str) -> tuple[str, str | None]:
    """日闸：目标日已钉则不写入该日，改挂到 [目标日, 当前业务日] 内最早开放日。

    返回 (落库日, retarget_from)；无开放日则 409，什么都不写。
    调用方须持有 BEGIN IMMEDIATE 事务，使检查与写入相对并发钉扎互斥。
    """
    if not fact_repo.day_is_sealed(conn, requested):
        return requested, None
    today = settings_repo.get(conn, "business_day")
    open_day = fact_repo.earliest_open_day(conn, requested, today)
    if open_day is None:
        raise HTTPException(
            409,
            f"业务日 {requested} 已钉扎，且至当前业务日 {today} 无开放日可改挂，核销未写入",
        )
    return open_day, requested


def add_event(body: dict[str, Any]) -> dict[str, Any]:
    conn = connect(immediate=True)
    try:
        et = body.get("event_type")
        if et not in {"issue", "redeem", "void"}:
            raise HTTPException(400, "event_type 须为 issue/redeem/void")
        code = (body.get("coupon_code") or "").strip()
        camp = (body.get("campaign_code") or "").strip()
        if not code or not camp:
            raise HTTPException(400, "coupon_code / campaign_code 必填")
        requested = _requested_day(conn, body)
        try:
            date.fromisoformat(requested)
        except ValueError:
            raise HTTPException(400, f"落库业务日格式非法（须 YYYY-MM-DD）: {requested!r}")
        retarget_from = None
        claim = None
        if et == "redeem":
            from app.services import day_claim
            occurred_hint = body.get("occurred_at") or ""
            claim = day_claim.place(conn, requested, occurred_hint)
            day = claim["event_day"]
            retarget_from = claim["retarget_from"]
        else:
            day = requested
        amount = float(body.get("amount") or 0)
        if et == "redeem" and amount <= 0:
            # default face value from campaign
            camps = {c["code"]: c for c in camp_repo.list_all(conn)}
            if camp in camps:
                amount = float(camps[camp]["face_value"])
        occurred = body.get("occurred_at") or datetime.now().replace(microsecond=0).isoformat()
        eid = event_repo.insert_event(
            conn,
            event_type=et,
            coupon_code=code,
            campaign_code=camp,
            amount=amount,
            business_day=day,
            occurred_at=occurred,
            note=body.get("note") or "",
            retarget_from=retarget_from,
        )
        fact_id = None
        receipt_day = day
        if et == "redeem" and claim is not None:
            receipt_day = claim["receipt_day"]
            if claim["half"] or claim["fact_day"] is None:
                conn.commit()
                return {
                    "event_id": eid,
                    "fact_id": None,
                    "business_day": receipt_day,
                    "occurred_at": occurred,
                    "retargeted": True,
                    "retarget_from": retarget_from,
                    "success": True,
                    "event_day": claim["event_day"],
                    "fact_day": None,
                }
            try:
                fact_id = fact_repo.insert_fact(
                    conn,
                    coupon_code=code,
                    campaign_code=camp,
                    amount=amount,
                    business_day=claim["fact_day"],
                    event_id=eid,
                    status="open",
                    retarget_from=retarget_from,
                )
            except Exception as e:
                raise HTTPException(409, f"核销事实写入失败（可能券码已核销）: {e}") from e
        conn.commit()
        return {
            "event_id": eid,
            "fact_id": fact_id,
            "business_day": receipt_day,
            "occurred_at": occurred,
            "retargeted": retarget_from is not None,
            "retarget_from": retarget_from,
            "event_day": claim["event_day"] if claim else day,
            "fact_day": claim["fact_day"] if claim else day,
            "success": True,
        }
    finally:
        conn.close()
