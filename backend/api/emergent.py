"""P4.2 涌现源发现 endpoints — see services/emergent_sources.py."""
from typing import Optional

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/emergent", tags=["emergent"])


@router.get("/")
def list_emergent(tracker_id: Optional[int] = None, status: str = "pending", limit: int = 20):
    from services.emergent_sources import list_emergent_sources
    return list_emergent_sources(tracker_id=tracker_id, status=status, limit=limit)


@router.post("/scan")
def scan_emergent(window_days: int = 14, min_threads: int = 3):
    from services.emergent_sources import scan_emergent_sources
    return scan_emergent_sources(window_days=window_days, min_threads=min_threads)


@router.post("/{emergent_id}/accept")
def accept_emergent(emergent_id: int):
    from services.emergent_sources import accept_emergent_source
    out = accept_emergent_source(emergent_id)
    if not out.get("ok") and out.get("reason") == "not found":
        raise HTTPException(status_code=404, detail="not found")
    return out


@router.post("/{emergent_id}/dismiss")
def dismiss_emergent(emergent_id: int):
    from services.emergent_sources import dismiss_emergent_source
    out = dismiss_emergent_source(emergent_id)
    if not out.get("ok"):
        raise HTTPException(status_code=404, detail="not found")
    return out
