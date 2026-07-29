"""Host-level pacing and rate-limit cooldown — the other half of source health.

`source_health` keys backoff per ENDPOINT, deliberately: one dead Google News
keyword search must not silence every other tracker sharing news.google.com.
Its docstring has always noted that "domain-level politeness is a separate
concern". This module is that concern, and its absence was measurable.

Reddit succeeded on 511 of 2157 attempts — 24%, with 498 outright 429s. The
cause is structural, not incidental: a cycle generates ~23 reddit routes, each
with its own health key, fired back to back. Reddit rate-limits per IP per HOST,
so the first 429 taught the other 22 routes nothing; they kept firing, kept
being refused, and the endpoint backoff each one accrued was for a fault that
was never theirs. Two rules fix it, and neither belongs at endpoint scope:

  1. SPACING — requests to one host are serialised with a minimum gap, so we
     never present as a burst in the first place.
  2. COOLDOWN — a 429 (or a run of server errors) parks the whole HOST, because
     that is the scope at which the refusal was issued.

In-process and lock-guarded: the scrape runs in one process across a small
thread pool, and losing the state on restart merely costs one polite cycle.
"""
import threading
import time
import urllib.parse
from typing import Dict, Optional

from services.log_service import get_logger

logger = get_logger("host_politeness")

# Minimum seconds between requests to one host. The default is ordinary
# politeness; the overrides are hosts that have actually refused us.
DEFAULT_MIN_INTERVAL = 1.0
_MIN_INTERVAL: Dict[str, float] = {
    # Unauthenticated Reddit is roughly 10 requests/minute per IP.
    "reddit.com": 6.0,
    "old.reddit.com": 6.0,
    # HN's firebase/rss frontends 502 under bursts (416 measured in one window).
    "news.ycombinator.com": 2.0,
    "hnrss.org": 2.0,
    # Public instances run by volunteers — be a good guest.
    "nitter.net": 5.0,
    "rsshub.app": 5.0,
}

# Longest we will block a scrape worker waiting for a slot. Beyond this the
# route is skipped for this cycle rather than holding a worker hostage.
MAX_WAIT_SECONDS = 20.0

# Pacing means a busy host cannot serve all of its routes in one cycle: at 6s
# apart, reddit's ~23 routes would need over two minutes. Whoever asks first
# wins the slots — and route order is stable, so the SAME few routes would win
# every cycle and the rest would never run at all. Starving 20 sources is not an
# improvement on rate-limiting them. So each cycle starts serving where the last
# one stopped: over a few cycles every route on the host gets its turn.
# A host is considered to have begun a new cycle after this much quiet.
CYCLE_IDLE_GAP = 120.0

# Cooldown after a host refuses us, doubling while refusals continue.
COOLDOWN_START_SECONDS = 300.0
COOLDOWN_MAX_SECONDS = 3600.0
# One 5xx is noise; a run of them is the host asking for room.
SERVER_ERROR_STREAK = 3

_lock = threading.RLock()
_next_free: Dict[str, float] = {}          # host → monotonic time of next free slot
_cooldown_until: Dict[str, float] = {}     # host → monotonic time cooldown ends
_cooldown_len: Dict[str, float] = {}       # host → current cooldown length
_error_streak: Dict[str, int] = {}         # host → consecutive server errors
# Rotation state (see CYCLE_IDLE_GAP).
_last_seen: Dict[str, float] = {}          # host → monotonic time of last reserve
_seq: Dict[str, int] = {}                  # host → reserves so far this cycle
_served: Dict[str, int] = {}               # host → slots granted this cycle
_offset: Dict[str, int] = {}               # host → how many to yield before serving


def host_of(url: str) -> str:
    """Registrable-ish host key. Reddit serves the same limiter from www., old.
    and plain reddit.com, so the leading `www.` is dropped and known multi-
    subdomain hosts collapse to their apex — the scope the limiter actually uses."""
    try:
        net = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        net = (url or "").lower()
    if not net:
        return (url or "").lower()
    if net.startswith("www."):
        net = net[4:]
    for apex in ("reddit.com", "nitter.net", "rsshub.app"):
        if net == apex or net.endswith("." + apex):
            return apex
    return net


def min_interval(host: str) -> float:
    return _MIN_INTERVAL.get(host, DEFAULT_MIN_INTERVAL)


def reserve(url: str) -> tuple:
    """Claim the next slot for this URL's host.

    Returns (wait_seconds, skip_reason). On success wait_seconds is how long the
    caller must sleep before issuing the request and the slot is CONSUMED — the
    reservation happens under the lock so two scrape threads can never claim the
    same slot. When the host is cooling down, or the queue is longer than a
    worker should wait, nothing is consumed and skip_reason says why.
    """
    host = host_of(url)
    now = time.monotonic()
    with _lock:
        until = _cooldown_until.get(host)
        if until and now < until:
            return 0.0, f"host_cooldown:{int(until - now)}s"

        # New cycle? Resume serving where the previous one ran out of slots.
        last = _last_seen.get(host)
        if last is None or (now - last) > CYCLE_IDLE_GAP:
            served = _served.get(host, 0)
            seen = _seq.get(host, 0)
            if seen > 0:
                _offset[host] = (_offset.get(host, 0) + served) % seen
            _seq[host] = 0
            _served[host] = 0
        _last_seen[host] = now

        pos = _seq.get(host, 0)
        _seq[host] = pos + 1
        if pos < _offset.get(host, 0):
            # Served in an earlier cycle; stand aside so the tail gets its turn.
            return 0.0, "host_rotation"

        gap = min_interval(host)
        slot = max(now, _next_free.get(host, 0.0))
        wait = slot - now
        if wait > MAX_WAIT_SECONDS:
            return 0.0, f"host_busy:{int(wait)}s"
        _next_free[host] = slot + gap
        _served[host] = _served.get(host, 0) + 1
        return wait, None


def wait_for_slot(url: str) -> Optional[str]:
    """reserve() + sleep. Returns None when the caller may proceed, or a skip
    reason. Sleeping happens OUTSIDE the lock so other hosts keep flowing."""
    wait, skip = reserve(url)
    if skip:
        return skip
    if wait > 0:
        time.sleep(wait)
    return None


def record_success(url: str):
    host = host_of(url)
    with _lock:
        _error_streak.pop(host, None)
        if host in _cooldown_until:
            _cooldown_until.pop(host, None)
            _cooldown_len.pop(host, None)


def record_failure(url: str, error_type: str):
    """Park the host when the failure is one the host is asking us to respect.

    A 429 is unambiguous and takes effect immediately. Server errors need a
    streak — a lone 502 is noise, three in a row is the host under load.
    Everything else (a parse error, one dead endpoint) is the endpoint's own
    problem and stays with source_health, where it belongs."""
    host = host_of(url)
    if error_type == "RATE_LIMITED":
        _enter_cooldown(host, error_type)
        return
    if error_type in ("SOURCE_UNAVAILABLE", "NETWORK_ERROR"):
        with _lock:
            streak = _error_streak.get(host, 0) + 1
            _error_streak[host] = streak
        if streak >= SERVER_ERROR_STREAK:
            _enter_cooldown(host, f"{error_type}x{streak}")


def _enter_cooldown(host: str, reason: str):
    with _lock:
        length = min(_cooldown_len.get(host, 0.0) * 2 or COOLDOWN_START_SECONDS,
                     COOLDOWN_MAX_SECONDS)
        _cooldown_len[host] = length
        _cooldown_until[host] = time.monotonic() + length
        _error_streak.pop(host, None)
    logger.warning(f"Host {host} cooling down for {int(length/60)}m [{reason}] — "
                   f"every route on this host waits, because the refusal was host-wide.")


def snapshot() -> dict:
    """Current pacing state, for diagnostics and the source-health view."""
    now = time.monotonic()
    with _lock:
        return {
            "cooldowns": {h: int(t - now) for h, t in _cooldown_until.items() if t > now},
            "error_streaks": dict(_error_streak),
            "rotation": {h: {"offset": o, "served": _served.get(h, 0), "seen": _seq.get(h, 0)}
                         for h, o in _offset.items()},
        }


def reset():
    """Test hook — drop all pacing state."""
    with _lock:
        for d in (_next_free, _cooldown_until, _cooldown_len, _error_streak,
                  _last_seen, _seq, _served, _offset):
            d.clear()
