"""Account guard — atomic consume, circuit breaker, AIMD, probe semantics."""
from datetime import datetime, timedelta

from services import account_guard as ag


def _k(name):
    # Unique key per test so state doesn't bleed across tests in one session DB.
    return f"test:{name}:{datetime(2026,7,6).timestamp()}"


def test_try_consume_budget_and_window():
    k = _k("budget"); b0 = datetime(2026, 7, 6, 0, 0, 0)
    for _ in range(ag.MIN_BUDGET):
        allowed, _r = ag.try_consume(k, now=b0)
        assert allowed
    allowed, reason = ag.try_consume(k, now=b0)
    assert not allowed and reason.startswith("budget_exhausted")
    # A new hour window frees the budget again.
    allowed, _ = ag.try_consume(k, now=b0 + timedelta(hours=1, minutes=1))
    assert allowed


def test_circuit_and_single_probe():
    k = _k("circuit"); b0 = datetime(2026, 7, 6, 0, 0, 0)
    ag.record_risk_signal(k, "429", now=b0)
    allowed, reason = ag.try_consume(k, now=b0 + timedelta(minutes=1))
    assert not allowed and reason.startswith("circuit_open")
    after = b0 + timedelta(hours=ag.BACKOFF_HOURS_ON_RISK, minutes=1)
    a1, r1 = ag.try_consume(k, now=after)
    assert a1 and r1 == "half_open_probe"
    # A concurrent second caller is denied — exactly one probe.
    a2, r2 = ag.try_consume(k, now=after)
    assert not a2 and r2 == "probe_in_flight"
    # A successful probe closes the circuit.
    ag.record_yield(k, items=3, now=after)
    assert ag.account_status(k, now=after)["circuit_state"] == "closed"


def test_stale_probe_self_heals():
    k = _k("staleprobe"); b0 = datetime(2026, 7, 6, 0, 0, 0)
    ag.record_risk_signal(k, "429", now=b0)
    after = b0 + timedelta(hours=ag.BACKOFF_HOURS_ON_RISK, minutes=1)
    ag.try_consume(k, now=after)  # admit probe -> probing
    # Probe never resolves; a later call self-heals by reopening the circuit.
    a, r = ag.try_consume(k, now=after + timedelta(seconds=ag.PROBE_TIMEOUT_SECONDS + 10))
    assert not a and r == "probe_timeout_reopened"


def test_aimd_additive_increase():
    k = _k("aimd"); d0 = datetime(2026, 7, 6, 0, 0, 0)
    ag.record_spend(k, now=d0)
    ag.try_consume(k, now=d0 + timedelta(days=1, minutes=1))  # one clean day
    st = ag.account_status(k, now=d0 + timedelta(days=1, minutes=2))
    assert st["hourly_budget"] > ag.MIN_BUDGET
