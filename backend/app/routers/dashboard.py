from __future__ import annotations
from fastapi import APIRouter
from app.services import catalog_service as svc

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
def dashboard():
    return svc.dashboard()


@router.get("/health")
def health():
    return {"ok": True, "service": "vouchpin"}
