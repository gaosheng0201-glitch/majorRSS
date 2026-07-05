"""
Humanized pacing for authorized fetches (R1, 愿景 #10).

Bots betray themselves by regularity: exact-interval polling, 24/7 activity, no
pauses. For routes that spend a real account's credit we add random jitter
between requests and honor a nightly quiet window (real people sleep). Anonymous
routes are exempt — this is specifically to keep authenticated sessions from
looking automated.

The quiet-window check is pure logic (testable with an injected clock); the
sleep is the only side effect and is skippable in tests.
"""
import os
import time
import hashlib
from datetime import datetime, time as dtime
from typing import Optional

from services.log_service import get_logger

logger = get_logger("humanized")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def in_quiet_window(now: datetime, start_hour: Optional[int] = None, end_hour: Optional[int] = None) -> bool:
    """True if `now` (local time) falls in the nightly quiet window during which
    authorized fetching pauses. Configurable via AUTH_QUIET_START/END (local
    hours); default 02:00–07:00. Set AUTH_QUIET_START == AUTH_QUIET_END to
    disable."""
    start_hour = _env_int("AUTH_QUIET_START", 2) if start_hour is None else start_hour
    end_hour = _env_int("AUTH_QUIET_END", 7) if end_hour is None else end_hour
    if start_hour == end_hour:
        return False
    h = now.hour
    if start_hour < end_hour:
        return start_hour <= h < end_hour
    # Wrap past midnight (e.g. 23 → 5).
    return h >= start_hour or h < end_hour


def _deterministic_jitter(seed_key: str, lo: float, hi: float) -> float:
    """A stable pseudo-random delay in [lo, hi] derived from seed_key. Avoids
    Math.random-style nondeterminism (varies per account/URL, not per call), so
    behavior is reproducible while still irregular across sources."""
    digest = hashlib.sha256(seed_key.encode("utf-8")).hexdigest()
    frac = int(digest[:8], 16) / 0xFFFFFFFF
    return lo + frac * (hi - lo)


def jitter_delay_seconds(seed_key: str) -> float:
    lo = _env_int("AUTH_JITTER_MIN_SECONDS", 3)
    hi = _env_int("AUTH_JITTER_MAX_SECONDS", 12)
    if hi <= lo:
        return float(lo)
    return _deterministic_jitter(seed_key, lo, hi)


def pace_authorized_request(seed_key: str, now: Optional[datetime] = None, sleep: bool = True) -> dict:
    """Apply humanized pacing before an authorized request.
    Returns {'skipped_quiet': bool, 'delay': float}. When in the quiet window,
    signals the caller to defer (skipped_quiet=True) rather than sleeping for
    hours."""
    now = now or datetime.now()
    if in_quiet_window(now):
        return {"skipped_quiet": True, "delay": 0.0}
    delay = jitter_delay_seconds(seed_key)
    if sleep and delay > 0:
        time.sleep(delay)
    return {"skipped_quiet": False, "delay": delay}
