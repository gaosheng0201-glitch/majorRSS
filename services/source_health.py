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

# --- Freshness assertion (B1) -------------------------------------------------
# HTTP 200 does NOT mean a source is alive. Field-verified failure modes that all
# look perfectly healthy to a status-code check:
#   • syndication.twitter.com — 200 + well-formed JSON whose newest item is 8
#     MONTHS old (the account posts daily). Fails silently-successfully.
#   • nitter.net — 200 + zero bytes for script user-agents, and 200-shaped
#     rate-limit responses. Indistinguishable from "no news today".
#   • Third-party generated feeds — repo still active, published XML frozen months ago.
# For a radar, a silently stale source is worse than a loudly broken one: it
# quietly removes a whole topic from view while the dashboard stays green. So
# health is judged on ITEM DATES, not on the HTTP status.
#
# A source is stale when its newest item is older than this, AND we have seen it
# deliver fresher items before (so a genuinely low-volume feed is not punished
# for being quiet — we only flag sources that USED to be fresher).
STALE_AFTER_DAYS = int(__import__("os").environ.get("SOURCE_STALE_AFTER_DAYS", "14"))
# An empty response is only suspicious when the source has delivered before.
EMPTY_STREAK_THRESHOLD = int(__import__("os").environ.get("SOURCE_EMPTY_STREAK", "5"))

# Consecutive empty responses per source key. In-process only and deliberately
# so: it is a heuristic for a live process, and losing it on restart just means
# a dark source gets a few more polls before being flagged.
_EMPTY_STREAKS: dict = {}


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


def record_fetch(key: str, items, latency_ms: int = 0, now: Optional[datetime] = None) -> Optional[str]:
    """Record a fetch that did not raise, judging LIVENESS BY ITEM DATES (B1).

    `items` are the fetched SourceItems (may be empty). Returns None when the
    source is healthy, or a reason string when it was recorded as a failure:
      • "empty_streak"  — repeatedly returns nothing after having delivered before
      • "stale_content" — newest item far older than STALE_AFTER_DAYS, and this
                          source has delivered fresher items in the past
    Both are recorded through record_failure, so a silently-dead source backs off
    and eventually quarantines exactly like a loudly-broken one, and surfaces in
    the Settings source-health view instead of masquerading as a quiet feed.

    A source with no delivery history is never punished: a genuinely new or
    low-volume feed must be allowed to be quiet.
    """
    from db.database import get_session
    now = now or _now()

    newest = None
    for it in (items or []):
        ts = getattr(it, "published_at", None)
        if ts is None:
            continue
        if ts.tzinfo is not None:
            ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
        if newest is None or ts > newest:
            newest = ts

    if not items:
        # Empty is normal once in a while; a STREAK of empties from a source that
        # used to deliver is the nitter / bird.makeup signature. Counted in its own
        # module-level tally, NOT in consecutive_failures (that one is for real
        # errors and is reset by every success, so a streak could never build).
        with _lock:
            with get_session() as session:
                rec = _get_or_create(session, key)
                had_history = (rec.total_success or 0) > 0
                rec.updated_at = now
                session.add(rec)
                session.commit()
        if not had_history:
            # A brand-new or genuinely low-volume feed is allowed to be quiet.
            return None
        streak = _EMPTY_STREAKS.get(key, 0) + 1
        _EMPTY_STREAKS[key] = streak
        if streak < EMPTY_STREAK_THRESHOLD:
            # Reachable but nothing to show — don't credit a success (that would
            # reset the streak), don't punish it yet.
            return None
        _EMPTY_STREAKS[key] = 0
        record_failure(key, error_type="EMPTY_RESPONSE", now=now)
        logger.warning(f"Source {key} returned nothing {streak}x in a row despite past deliveries — "
                       f"treating as FAILED, not as a quiet feed.")
        return "empty_streak"

    _EMPTY_STREAKS.pop(key, None)   # real content ends any building streak

    if newest is not None:
        age_days = (now - newest).total_seconds() / 86400.0
        if age_days > STALE_AFTER_DAYS:
            with _lock:
                with get_session() as session:
                    rec = _get_or_create(session, key)
                    prior_fresh = rec.last_success_at is not None
            if prior_fresh:
                record_failure(key, error_type="STALE_CONTENT", now=now)
                logger.warning(f"Source {key} returned items but the newest is {age_days:.0f} days old "
                               f"(> {STALE_AFTER_DAYS}d) — treating as FAILED (silently stale source).")
                return "stale_content"

    record_success(key, latency_ms=latency_ms, now=now)
    return None


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
