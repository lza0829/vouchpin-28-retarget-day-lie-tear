from __future__ import annotations
from datetime import date, datetime, timedelta
from app.db import connect, init_db


def seed_if_empty() -> None:
    init_db()
    conn = connect()
    try:
        n = conn.execute("SELECT COUNT(*) c FROM campaigns").fetchone()["c"]
        if n:
            return
        today = date.today().isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES('business_day', ?)",
            (today,),
        )
        campaigns = [
            ("NEW10", "新人立减10", 10.0, 30.0),
            ("VIP20", "会员满减20", 20.0, 100.0),
            ("TEA5", "茶饮立减5", 5.0, 15.0),
        ]
        for code, title, face, mn in campaigns:
            conn.execute(
                "INSERT INTO campaigns(code, title, face_value, min_spend) VALUES(?,?,?,?)",
                (code, title, face, mn),
            )
        # issue + redeem events for today and yesterday
        yday = (date.today() - timedelta(days=1)).isoformat()
        rows = [
            ("issue", "C-1001", "NEW10", 0, today, f"{today}T09:00:00"),
            ("issue", "C-1002", "VIP20", 0, today, f"{today}T09:10:00"),
            ("issue", "C-1003", "TEA5", 0, today, f"{today}T09:20:00"),
            ("redeem", "C-1001", "NEW10", 10, today, f"{today}T12:00:00"),
            ("redeem", "C-1002", "VIP20", 20, today, f"{today}T12:30:00"),
            ("issue", "C-0901", "NEW10", 0, yday, f"{yday}T10:00:00"),
            ("redeem", "C-0901", "NEW10", 10, yday, f"{yday}T18:00:00"),
        ]
        for et, cc, camp, amt, day, at in rows:
            cur = conn.execute(
                "INSERT INTO coupon_events(event_type, coupon_code, campaign_code, amount, business_day, occurred_at) VALUES(?,?,?,?,?,?)",
                (et, cc, camp, amt, day, at),
            )
            if et == "redeem":
                conn.execute(
                    "INSERT INTO redeem_facts(coupon_code, campaign_code, amount, business_day, event_id, status) VALUES(?,?,?,?,?, 'open')",
                    (cc, camp, amt, day, cur.lastrowid),
                )
        conn.commit()
    finally:
        conn.close()
