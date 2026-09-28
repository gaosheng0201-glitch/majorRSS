"""Daily token budgets — one brake for all background spend (roadmap P1.2+).

LLM_DAILY_TOKEN_BUDGET (> 0 enables it) caps what the radar spends on its own
each UTC day: fusion, embeddings, the event arbiter, the merge pass, alert
synthesis and the daily maintenance calls (vocabulary refresh, planner
backfills). It used to stop fusion only — everything else kept spending past
it. Actions the user starts (plan a target, generate a briefing, investigate,
trend scan) are not blocked: the user is there and asked for them.

Per target: fetch_policy.daily_token_budget (> 0) caps that target's fusion
spend — the part of the bill that belongs to one target (billing attributes it
as "FactCheck: <name>"). Intake (embeddings, arbiter) is shared by all targets
and answers to the global budget only.

Checks read today's total at most every CACHE_SECONDS: the arbiter may ask
hundreds of times a cycle. The brake can therefore overshoot by what is spent
in that window.
"""
import os
import threading
import time
from datetime import datetime, timezone

from services.log_service import get_logger

logger = get_logger("budget")

CACHE_SECONDS = 30
_lock = threading.Lock()
_cache = {}          # key → (monotonic time, tokens, UTC day it counts)
_warned = set()      # (day, what) already logged


def _day_start():
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)


def _spent_today(action_type: str = None) -> int:
    key = action_type or "*"
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_SECONDS and hit[2] == _day_start():
            return hit[1]
    from sqlmodel import select, func
    from db.database import get_session
    from db.models import TokenUsage
    q = select(func.coalesce(func.sum(TokenUsage.total_tokens), 0)).where(TokenUsage.created_at >= _day_start())
    if action_type:
        q = q.where(TokenUsage.action_type == action_type)
    with get_session() as s:
        used = int(s.exec(q).one() or 0)
    with _lock:
        _cache[key] = (now, used, _day_start())
    return used


def reset_cache() -> None:
    with _lock:
        _cache.clear()


def daily_budget() -> int:
    try:
        return int(os.environ.get("LLM_DAILY_TOKEN_BUDGET", "0"))
    except ValueError:
        return 0


def todays_usage() -> int:
    """Tokens spent today (UTC), all models and actions — uncached."""
    reset_cache()
    return _spent_today()


def exhausted(what: str = "background spend") -> bool:
    """True when the global daily budget is set and used up. Logs once per day
    per `what`, so a stopped stage is visible without flooding the log."""
    budget = daily_budget()
    if budget <= 0:
        return False
    used = _spent_today()
    if used < budget:
        return False
    mark = (_day_start(), what)
    if mark not in _warned:
        _warned.add(mark)
        logger.warning(f"Daily LLM token budget exhausted ({used}/{budget}): {what} paused until 00:00 UTC.")
    return True


def target_budget(tracker) -> int:
    import json
    try:
        v = json.loads(tracker.fetch_policy or "{}").get("daily_token_budget")
        return int(v) if v else 0
    except Exception:
        return 0


def target_exhausted(tracker) -> bool:
    """True when this target has a daily cap and its fusion spend reached it."""
    cap = target_budget(tracker)
    if cap <= 0:
        return False
    used = _spent_today(f"FactCheck: {tracker.name}")
    if used < cap:
        return False
    mark = (_day_start(), f"target:{tracker.id}")
    if mark not in _warned:
        _warned.add(mark)
        logger.warning(f"Target '{tracker.name}' reached its daily token cap ({used}/{cap}); "
                       f"its summaries wait until 00:00 UTC.")
    return True
