"""
In-process scheduler health state.

The APScheduler instance runs in a daemon thread inside the FastAPI process.
This module holds a small shared snapshot of its lifecycle so the /health
endpoint (and the desktop UI) can answer: "is the scraping engine running?"
"""
import threading
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

_lock = threading.Lock()

_state: Dict[str, Any] = {
    "started_at": None,        # datetime | None
    "last_heartbeat_at": None, # datetime | None
    "error": None,             # str | None — fatal startup/runtime error
    "jobs": [],                # [{name, next_run_time}]
}

# If the heartbeat is older than this, the scheduler is considered stalled.
HEARTBEAT_STALE_SECONDS = 120


def mark_started():
    with _lock:
        _state["started_at"] = datetime.now(timezone.utc)
        _state["last_heartbeat_at"] = _state["started_at"]
        _state["error"] = None


def mark_error(message: str):
    with _lock:
        _state["error"] = message


def heartbeat(jobs: Optional[List[Dict[str, Any]]] = None):
    with _lock:
        _state["last_heartbeat_at"] = datetime.now(timezone.utc)
        if jobs is not None:
            _state["jobs"] = jobs


def get_state() -> Dict[str, Any]:
    with _lock:
        started_at = _state["started_at"]
        last_hb = _state["last_heartbeat_at"]
        error = _state["error"]
        jobs = list(_state["jobs"])

    if error:
        status = "error"
    elif started_at is None:
        status = "starting"
    elif last_hb and (datetime.now(timezone.utc) - last_hb).total_seconds() > HEARTBEAT_STALE_SECONDS:
        status = "stalled"
    else:
        status = "running"

    return {
        "status": status,
        "started_at": started_at.isoformat() if started_at else None,
        "last_heartbeat_at": last_hb.isoformat() if last_hb else None,
        "error": error,
        "jobs": jobs,
    }
