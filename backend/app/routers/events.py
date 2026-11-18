from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Query
from app.services import event_service as svc

router = APIRouter(tags=["events"])


@router.get("/campaigns")
def campaigns():
    return svc.list_campaigns()


@router.get("/events")
def events(business_day: str | None = Query(None)):
    return svc.list_events(business_day)


@router.post("/events")
def create_event(body: dict[str, Any]):
    return svc.add_event(body)


@router.get("/days/watermark")
def watermark(business_day: str | None = Query(None)):
    from app.db import connect
    from app.repositories import settings as settings_repo
    from app.services import day_claim
    conn = connect()
    try:
        day = business_day or settings_repo.get(conn, "business_day")
        return day_claim.watermark(conn, day)
    finally:
        conn.close()
