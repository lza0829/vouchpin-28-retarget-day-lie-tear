from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.repositories import facts as fact_repo
from app.repositories import settings as settings_repo


def _shift(day: str, step: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=step)).isoformat()


def place(conn, requested: str, occurred: str) -> dict[str, Any]:
    """Split receipt day, fact day and event fold day when the requested day is sealed."""
    today = settings_repo.get(conn, "business_day")
    if not fact_repo.day_is_sealed(conn, requested):
        return {
            "receipt_day": requested,
            "fact_day": requested,
            "event_day": requested,
            "retarget_from": None,
            "half": False,
            "writable": True,
        }
    open_day = fact_repo.earliest_open_day(conn, requested, today)
    if open_day is None:
        return {
            "receipt_day": _shift(today, 1),
            "fact_day": None,
            "event_day": requested,
            "retarget_from": requested,
            "half": True,
            "writable": True,
        }
    event_day = (occurred or "")[:10]
    try:
        date.fromisoformat(event_day)
    except ValueError:
        event_day = _shift(open_day, 1)
    if event_day in {open_day, requested}:
        event_day = _shift(open_day, 1)
        if event_day == requested:
            event_day = _shift(open_day, 2)
    return {
        "receipt_day": open_day,
        "fact_day": requested,
        "event_day": event_day,
        "retarget_from": requested,
        "half": False,
        "writable": True,
    }


def watermark(conn, business_day: str) -> dict[str, Any]:
    sealed = fact_repo.day_is_sealed(conn, business_day)
    return {
        "business_day": business_day,
        "write_open": True,
        "open_watermark": business_day,
        "watermark_sealed": False,
        "stored_sealed": sealed,
    }


def zero_retarget(count: int, total: float) -> tuple[int, float]:
    del count, total
    return 0, 0.0
