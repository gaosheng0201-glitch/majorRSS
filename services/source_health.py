"""
Per-source health, backoff and quarantine (R1).

A failing source must not be re-hit at full cadence forever (愿景/差距地图).
This records success/failure per key (usually the domain), applies exponential
backoff after failures via `next_eligible_at`, and quarantines chronically dead
sources. `should_skip` is the gate the scrape loop checks before spending a
request; `record_success` / `record_failure` update the record afterward.

Pure DB state + deterministic math — unit-testable with an injected clock.
"""
import threading
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Optional

from services.log_service import get_logger

logger = get_logger("source_health")

# Single-process: serialize check-then-act so concurrent scrapes can't both
# bypass a backoff window or clobber consecutive_failures.
_lock = threading.RLock()

# Backoff schedule (minutes) indexed by consecutive-failure count.
BACKOFF_MINUTES = [0, 2, 5, 15, 60, 180, 360]
QUARANTINE_THRESHOLD = 8   # consecutive failures → quarantined
DEGRADED_THRESHOLD = 2     # consecutive failures → degraded


def domain_key(url: str) -> str:
    try:
        net = urllib.parse.urlparse(url).netloc.lower()
        return net or url.lower()
    except Exception:
        return url.lower()


def route_key(url_or_command: str) -> str:
    """Per-endpoint health key. Backoff/quarantine must be scoped to the exact
    URL, not the domain — otherwise one failing Google News search
    (news.google.com/rss/search?q=A) would back off EVERY keyword tracker that
    shares that domain. Domain-level politeness is a separate concern."""
    try:
        p = urllib.parse.urlparse(url_or_command)
        if p.scheme and p.netloc:
            # domain + path + query — distinguishes per-keyword search endpoints.
            key = f"{p.netloc.lower()}{p.path}"
            if p.query:
                key += "?" + p.query
            return key[:400]
    except Exception:
        pass
    return url_or_command.lower()[:400]


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _get_or_create(session, key: str):
    from db.models import SourceHealth
    from sqlmodel import select
    rec = session.exec(select(SourceHealth).where(SourceHealth.key == key)).first()
    if not rec:
        rec = SourceHealth(key=key)
        session.add(rec)
        session.commit()
        session.refresh(rec)
    return rec


def should_skip(key: str, now: Optional[datetime] = None) -> tuple:
    """Return (skip: bool, reason: str|None). Skips while inside a backoff
    window or while quarantined."""
    from db.database import get_session
    now = now or _now()
    with _lock:
        with get_session() as session:
            rec = _get_or_create(session, key)
            if rec.state == "quarantined":
                # Quarantine still honors next_eligible_at as a periodic retry probe.
                if rec.next_eligible_at and now >= rec.next_eligible_at:
                    return False, None
                return True, "quarantined"
            if rec.next_eligible_at and now < rec.next_eligible_at:
                wait = int((rec.next_eligible_at - now).total_seconds())
                return True, f"backoff:{wait}s"
    return False, None


def record_success(key: str, latency_ms: int = 0, now: Optional[datetime] = None):
    from db.database import get_session
    now = now or _now()
    with _lock:
        with get_session() as session:
            rec = _get_or_create(session, key)
            rec.consecutive_failures = 0
            rec.total_success += 1
            rec.last_success_at = now
            rec.next_eligible_at = None
            rec.state = "healthy"
            rec.last_error_type = None
            # Exponential moving average latency.
            rec.avg_latency_ms = latency_ms if rec.avg_latency_ms == 0 else int(rec.avg_latency_ms * 0.7 + latency_ms * 0.3)
            rec.updated_at = now
            session.add(rec)
            session.commit()


def record_failure(key: str, error_type: str = "UNKNOWN_ERROR", now: Optional[datetime] = None):
    from db.database import get_session
    now = now or _now()
    with _lock:
        with get_session() as session:
            rec = _get_or_create(session, key)
            rec.consecutive_failures += 1
            rec.total_failure += 1
            rec.last_failure_at = now
            rec.last_error_type = error_type

            n = rec.consecutive_failures
            idx = min(n, len(BACKOFF_MINUTES) - 1)
            rec.next_eligible_at = now + timedelta(minutes=BACKOFF_MINUTES[idx])

            if n >= QUARANTINE_THRESHOLD:
                rec.state = "quarantined"
            elif n >= DEGRADED_THRESHOLD:
                rec.state = "degraded"
            rec.updated_at = now
            session.add(rec)
            session.commit()
            logger.info(f"Source {key} failure #{n} [{error_type}] → state={rec.state}, next eligible in {BACKOFF_MINUTES[idx]}m")
