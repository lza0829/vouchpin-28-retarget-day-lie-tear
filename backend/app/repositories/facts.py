from __future__ import annotations
import sqlite3
from datetime import date, timedelta
from typing import Any


def list_facts(conn: sqlite3.Connection, business_day: str | None = None) -> list[dict[str, Any]]:
    if business_day:
        rows = conn.execute(
            "SELECT * FROM redeem_facts WHERE business_day=? ORDER BY id",
            (business_day,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM redeem_facts ORDER BY id DESC LIMIT 200").fetchall()
    return [dict(r) for r in rows]


def insert_fact(conn: sqlite3.Connection, **fields: Any) -> int:
    cur = conn.execute(
        "INSERT INTO redeem_facts(coupon_code, campaign_code, amount, business_day, event_id, status, retarget_from) VALUES(?,?,?,?,?,?,?)",
        (
            fields["coupon_code"],
            fields["campaign_code"],
            float(fields["amount"]),
            fields["business_day"],
            int(fields["event_id"]),
            fields.get("status") or "open",
            fields.get("retarget_from"),
        ),
    )
    return int(cur.lastrowid)


def open_facts_for_day(conn: sqlite3.Connection, business_day: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM redeem_facts WHERE business_day=? AND status='open' ORDER BY id",
        (business_day,),
    ).fetchall()
    return [dict(r) for r in rows]


def mark_batched(conn: sqlite3.Connection, fact_ids: list[int], batch_id: int) -> None:
    for fid in fact_ids:
        conn.execute(
            "UPDATE redeem_facts SET status='sealed', batch_id=? WHERE id=?",
            (batch_id, fid),
        )


def day_is_sealed(conn: sqlite3.Connection, business_day: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM redeem_batches WHERE business_day=? AND status='sealed' LIMIT 1",
        (business_day,),
    ).fetchone()
    return row is not None


def earliest_open_day(conn: sqlite3.Connection, from_day: str, to_day: str) -> str | None:
    """日闸：在 [from_day, to_day] 内找最早一个无 sealed 批的业务日；没有则 None。"""
    day = date.fromisoformat(from_day)
    end = date.fromisoformat(to_day)
    while day <= end:
        iso = day.isoformat()
        if not day_is_sealed(conn, iso):
            return iso
        day += timedelta(days=1)
    return None


def retarget_stats(facts: list[dict[str, Any]]) -> tuple[int, float]:
    """给定一组事实，数出其中改挂笔数与金额（预览与批快照同源）。"""
    rt = [f for f in facts if f.get("retarget_from")]
    return len(rt), round(sum(float(f["amount"]) for f in rt), 2)
