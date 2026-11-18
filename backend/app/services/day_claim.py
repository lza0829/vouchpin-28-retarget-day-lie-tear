"""日闸的唯一口径源：落库归属日 = 事件折日 = 对外回执日。

已钉日的核销不硬拒、不暗写：改挂到 [目标日, 当前业务日] 内最早开放日，
事件与事实同事务落在该日，回执回写同一日；无开放日则抛 409，整笔不写。
写入口、事件入湖、事实归属、水位扫描、预览与批附注全部以此处为唯一事实源。
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.repositories import facts as fact_repo
from app.repositories import settings as settings_repo


def place(conn, requested: str) -> dict[str, Any]:
    """决定一笔核销的唯一落库日。

    返回 (day, retarget_from)：
    - 目标日开放：原样落目标日，retarget_from=None；
    - 目标日已钉：改挂到最早开放日，retarget_from=目标日；
    - 范围内无开放日：409，调用方事务回滚，事件与事实都不落库。
    不存在第二套回执日/事件折日/事实归属日，三日永远同一日。
    """
    if not fact_repo.day_is_sealed(conn, requested):
        return {"day": requested, "retarget_from": None}
    today = settings_repo.get(conn, "business_day")
    open_day = fact_repo.earliest_open_day(conn, requested, today)
    if open_day is None:
        raise HTTPException(
            409,
            f"业务日 {requested} 已钉扎，且至当前业务日 {today} 无开放日可改挂，核销未写入",
        )
    return {"day": open_day, "retarget_from": requested}


def watermark(conn, business_day: str) -> dict[str, Any]:
    """可写水位与批头同源：该日存在 sealed 批即不可写，否则可写。

    水位不得声称可写而批头已钉，也不得在已钉日仍保留可写落点。
    """
    sealed = fact_repo.day_is_sealed(conn, business_day)
    return {
        "business_day": business_day,
        "write_open": not sealed,
        "open_watermark": None if sealed else business_day,
        "watermark_sealed": sealed,
        "stored_sealed": sealed,
    }
