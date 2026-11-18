import os
import tempfile

# 必须在任何 app.* 导入之前指向隔离数据目录（config 在 import 时定型 DB_PATH）
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="vouchpin-test-")

import pytest

from app.config import DB_PATH
from app.db import init_db, connect

TODAY = "2026-11-18"


@pytest.fixture()
def db():
    """每用例一个全新库：只有 settings 业务日与一个活动，无样例事件。"""
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()
    conn = connect()
    try:
        conn.execute("INSERT INTO settings(key, value) VALUES('business_day', ?)", (TODAY,))
        conn.execute(
            "INSERT INTO campaigns(code, title, face_value, min_spend) VALUES('NEW10', '新人立减10', 10, 30)"
        )
        conn.commit()
    finally:
        conn.close()
    yield TODAY


def set_day(day: str) -> None:
    conn = connect()
    try:
        conn.execute("UPDATE settings SET value=? WHERE key='business_day'", (day,))
        conn.commit()
    finally:
        conn.close()
