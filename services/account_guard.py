"""
Authorized-session guard (R1, 愿景 #10 防封 + 保护/可用平衡).

The user's real social account is fragile borrowed credit. This module rations
its use so the account looks human and survives, WITHOUT protecting it into
uselessness. Three pillars + the balance mechanisms we designed:

- Per-ACCOUNT budget (not per-target): N targets sharing one login share one
  hourly allowance, so "follow more" never linearly amplifies account activity.
- Budget is a SAFE ALLOWANCE meant to be spent on the highest-value work, not a
  fear ceiling — the scheduler fills it by priority.
- AIMD calibration: clean days grow the allowance additively; a risk signal
  halves it (multiplicative) and trips the circuit → converges to each
  platform's real tolerance instead of sitting on the floor forever.
- Circuit breaker with half-open recovery: a risk signal opens the circuit for
  a cooldown; afterward one probe decides resume-or-extend. No silent death.
- Utilization is as visible as risk (see account_status): under-use + a queue is
  itself a signal.

Deterministic; clock is injectable for tests.
"""
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional

from services.log_service import get_logger

logger = get_logger("account_guard")

# MajorRSS runs a single backend process; all scrape/scheduler threads live
# here. This process-wide lock serializes read-modify-write on the guard state
# so "check budget then spend" and "admit exactly one half-open probe" are
# atomic — the DB session split alone (check in one txn, spend in another) has a
# TOCTOU that lets two threads sharing an account both pass and overshoot.
_lock = threading.RLock()

# AIMD parameters.
MIN_BUDGET = 6            # conservative first-week floor (requests/hour)
MAX_BUDGET = 120          # ceiling regardless of clean streak
PROBE_TIMEOUT_SECONDS = 300  # a half-open probe that never resolves self-heals
ADDITIVE_STEP = 4         # +N per clean day
BACKOFF_HOURS_ON_RISK = 6 # circuit-open cooldown after a risk signal
CLEAN_DAY_SECONDS = 86400


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _get_or_create(session, account_key: str):
    from db.models import AccountGuardState
    from sqlmodel import select
    rec = session.exec(select(AccountGuardState).where(AccountGuardState.account_key == account_key)).first()
    if not rec:
        rec = AccountGuardState(account_key=account_key, hourly_budget=MIN_BUDGET)
        session.add(rec)
        session.commit()
        session.refresh(rec)
    return rec


def _roll_window(rec, now):
    """Reset the hourly counter if the current window has elapsed, and credit a
    clean day (AIMD additive increase) if 24h passed with no risk signal.
    elapsed < 0 (system clock moved backwards) also starts a fresh window so a
    clock skew can never wedge the counter."""
    elapsed = (now - rec.window_started_at).total_seconds()
    if elapsed >= 3600 or elapsed < 0:
        rec.window_started_at = now
        rec.window_count = 0
    # Additive increase: each clean day (no risk signal) grows the allowance.
    # Anchored on last_budget_calibrated_at (a dedicated marker), NOT on the
    # hourly-rolling window_started_at — otherwise the 24h clock never elapses.
    anchor = rec.last_budget_calibrated_at or rec.last_risk_signal_at
    if anchor is None:
        # First observation: seed the anchor so day counting starts now.
        rec.last_budget_calibrated_at = now
        anchor = now
    if rec.last_used_at and (now - anchor).total_seconds() >= CLEAN_DAY_SECONDS:
        # Credit whole clean days elapsed (survives multi-day sleep).
        days = int((now - anchor).total_seconds() // CLEAN_DAY_SECONDS)
        if rec.hourly_budget < MAX_BUDGET:
            rec.hourly_budget = min(MAX_BUDGET, rec.hourly_budget + ADDITIVE_STEP * days)
            logger.info(f"{rec.account_key}: {days} clean day(s) → budget up to {rec.hourly_budget}/h")
        rec.consecutive_clean_days += days
        rec.last_budget_calibrated_at = anchor + timedelta(seconds=days * CLEAN_DAY_SECONDS)


def try_consume(account_key: str, now: Optional[datetime] = None) -> tuple:
    """ATOMIC check-and-consume: returns (allowed, reason) and, when allowed,
    has already spent the request. Use this instead of can_spend + record_spend
    to avoid the TOCTOU where two threads sharing an account both pass the check.
    Admits EXACTLY ONE half-open probe by transitioning the circuit to 'probing'
    under the lock."""
    from db.database import get_session
    now = now or _now()
    with _lock:
        with get_session() as session:
            rec = _get_or_create(session, account_key)

            if rec.circuit_state == "open":
                if rec.circuit_until and now >= rec.circuit_until:
                    rec.circuit_state = "half_open"
                    logger.info(f"{rec.account_key}: cooldown elapsed → half_open (one probe allowed)")
                else:
                    left = int((rec.circuit_until - now).total_seconds()) if rec.circuit_until else 0
                    session.add(rec); session.commit()
                    return False, f"circuit_open:{left}s"

            if rec.circuit_state == "half_open":
                # Admit exactly one probe: flip to 'probing' so concurrent
                # callers are denied until record_yield/record_risk resolves it.
                rec.circuit_state = "probing"
                rec.last_used_at = now
                rec.updated_at = now
                session.add(rec); session.commit()
                return True, "half_open_probe"

            if rec.circuit_state == "probing":
                # Self-heal: if the in-flight probe never resolved (its fetch
                # crashed before record_yield/record_risk_signal), reopen the
                # circuit after a timeout so the account isn't wedged forever.
                if rec.last_used_at and (now - rec.last_used_at).total_seconds() > PROBE_TIMEOUT_SECONDS:
                    rec.circuit_state = "open"
                    rec.circuit_until = now + timedelta(hours=BACKOFF_HOURS_ON_RISK)
                    session.add(rec); session.commit()
                    logger.warning(f"{rec.account_key}: stale probe timed out → circuit reopened")
                    return False, "probe_timeout_reopened"
                return False, "probe_in_flight"

            _roll_window(rec, now)
            if rec.window_count >= rec.hourly_budget:
                session.add(rec); session.commit()
                return False, f"budget_exhausted:{rec.window_count}/{rec.hourly_budget}"
            # Consume in the same locked transaction.
            rec.window_count += 1
            rec.last_used_at = now
            rec.updated_at = now
            session.add(rec); session.commit()
    return True, None


def can_spend(account_key: str, now: Optional[datetime] = None) -> tuple:
    """Deprecated: non-atomic gate kept for compatibility. Prefer try_consume.
    Serialized under the lock but still separate from record_spend."""
    from db.database import get_session
    now = now or _now()
    with _lock:
        with get_session() as session:
            rec = _get_or_create(session, account_key)
            if rec.circuit_state == "open":
                if rec.circuit_until and now >= rec.circuit_until:
                    rec.circuit_state = "half_open"
                    session.add(rec); session.commit()
                    logger.info(f"{rec.account_key}: cooldown elapsed → half_open (probe allowed)")
                else:
                    left = int((rec.circuit_until - now).total_seconds()) if rec.circuit_until else 0
                    return False, f"circuit_open:{left}s"
            if rec.circuit_state in ("half_open", "probing"):
                return True, "half_open_probe"
            _roll_window(rec, now)
            session.add(rec); session.commit()
            if rec.window_count >= rec.hourly_budget:
                return False, f"budget_exhausted:{rec.window_count}/{rec.hourly_budget}"
    return True, None


def record_spend(account_key: str, now: Optional[datetime] = None):
    """Account for one authorized request against the hourly window."""
    from db.database import get_session
    now = now or _now()
    with _lock:
        with get_session() as session:
            rec = _get_or_create(session, account_key)
            _roll_window(rec, now)
            rec.window_count += 1
            rec.last_used_at = now
            rec.updated_at = now
            session.add(rec); session.commit()


def record_yield(account_key: str, items: int = 0, now: Optional[datetime] = None):
    """A successful authorized fetch produced `items`. Closes a half-open
    circuit (probe succeeded) and updates the utilization sentinel."""
    from db.database import get_session
    now = now or _now()
    with _lock:
        with get_session() as session:
            rec = _get_or_create(session, account_key)
            # A successful probe (half_open or probing) closes the circuit.
            if rec.circuit_state in ("half_open", "probing"):
                rec.circuit_state = "closed"
                rec.circuit_until = None
                logger.info(f"{rec.account_key}: probe succeeded → circuit closed")
            rec.total_authorized_yield += items
            if items > 0:
                rec.last_yield_at = now
            rec.updated_at = now
            session.add(rec); session.commit()


def record_risk_signal(account_key: str, signal: str = "risk", now: Optional[datetime] = None):
    """Risk signal (captcha / 429 / limit page). Trips the circuit for the whole
    account and applies AIMD multiplicative decrease. This is the highest-
    priority path — call it the instant a risk signal is seen."""
    from db.database import get_session
    now = now or _now()
    with _lock:
        with get_session() as session:
            rec = _get_or_create(session, account_key)
            rec.circuit_state = "open"
            rec.circuit_until = now + timedelta(hours=BACKOFF_HOURS_ON_RISK)
            rec.last_risk_signal_at = now
            rec.last_budget_calibrated_at = now  # restart the clean-day clock
            rec.consecutive_clean_days = 0
            rec.hourly_budget = max(MIN_BUDGET, rec.hourly_budget // 2)  # multiplicative decrease
            rec.updated_at = now
            session.add(rec); session.commit()
            logger.warning(f"{rec.account_key}: RISK [{signal}] → circuit OPEN {BACKOFF_HOURS_ON_RISK}h, budget halved to {rec.hourly_budget}/h")


def account_status(account_key: str, now: Optional[datetime] = None) -> dict:
    """Snapshot for the diagnostics panel. Surfaces UNDER-utilization as loudly
    as risk: low usage + queued work means we are over-protecting."""
    from db.database import get_session
    now = now or _now()
    with _lock:
        with get_session() as session:
            rec = _get_or_create(session, account_key)
            _roll_window(rec, now)
            session.add(rec); session.commit()
        utilization = round(rec.window_count / rec.hourly_budget, 2) if rec.hourly_budget else 0.0
        stale_yield = bool(rec.last_used_at and (not rec.last_yield_at or (now - rec.last_yield_at).total_seconds() > 7 * CLEAN_DAY_SECONDS))
        return {
            "account_key": rec.account_key,
            "circuit_state": rec.circuit_state,
            "hourly_budget": rec.hourly_budget,
            "window_count": rec.window_count,
            "utilization": utilization,
            "consecutive_clean_days": rec.consecutive_clean_days,
            "total_authorized_yield": rec.total_authorized_yield,
            # Sentinel: authorized routes producing nothing for a week is itself
            # an alert (over-protection or broken auth), not silence.
            "underused_warning": utilization < 0.5 and rec.circuit_state == "closed",
            "stale_yield_warning": stale_yield,
        }
