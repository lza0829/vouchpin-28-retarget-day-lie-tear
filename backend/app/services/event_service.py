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
    """目标归属日（唯一口径的源头）：显式 business_day > occurred_at 当日 > 当前业务日。"""
    day = (body.get("business_day") or "").strip()
    if day:
        return day
    occurred = (body.get("occurred_at") or "").strip()
    if occurred:
        return occurred[:10]
    return settings_repo.get(conn, "business_day")


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
        if et == "redeem":
            # 日闸唯一入口：已钉则改挂最早开放日，无开放日在此抛 409，
            # 下面任何 INSERT 都不会发生，事务随连接关闭回滚——无半写。
            from app.services import day_claim
            claim = day_claim.place(conn, requested)
            day = claim["day"]
            retarget_from = claim["retarget_from"]
        else:
            # issue/void 不产生核销事实，不受日闸限制
            day = requested

        amount = float(body.get("amount") or 0)
        if et == "redeem" and amount <= 0:
            # default face value from campaign
            camps = {c["code"]: c for c in camp_repo.list_all(conn)}
            if camp in camps:
                amount = float(camps[camp]["face_value"])
        occurred = body.get("occurred_at") or datetime.now().replace(microsecond=0).isoformat()

        # 事件入湖与事实归属同一 business_day，同事务提交
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
        if et == "redeem":
            try:
                fact_id = fact_repo.insert_fact(
                    conn,
                    coupon_code=code,
                    campaign_code=camp,
                    amount=amount,
                    business_day=day,
                    event_id=eid,
                    status="open",
                    retarget_from=retarget_from,
                )
            except Exception as e:
                # 事实落不下（如券码已核销）：事件一并回滚，禁止事件无事实的半写
                conn.rollback()
                raise HTTPException(409, f"核销事实写入失败（可能券码已核销）: {e}") from e
        conn.commit()
        # 对外回执 = 落库日：回执日、事件折日、事实归属日三者同一日
        return {
            "event_id": eid,
            "fact_id": fact_id,
            "business_day": day,
            "occurred_at": occurred,
            "retargeted": retarget_from is not None,
            "retarget_from": retarget_from,
            "success": True,
        }
    finally:
        conn.close()
