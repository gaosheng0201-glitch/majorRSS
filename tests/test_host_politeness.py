"""Host-level pacing and cooldown (services/host_politeness).

These pin the behaviour that fixed reddit's 24% success rate: the refusal was
issued per HOST, but every one of its ~23 routes carried its own endpoint-scoped
health key, so the first 429 taught the other 22 nothing.
"""
import pytest

from services import host_politeness as hp


@pytest.fixture(autouse=True)
def clean():
    hp.reset()
    yield
    hp.reset()


def _cycle(n=23, url="https://www.reddit.com/search.rss?q=%d"):
    """One scrape cycle over n routes on one host; returns the indices served.
    Real cycles are minutes apart, so the pacing queue has drained between them."""
    hp._last_seen.clear()
    hp._next_free.clear()
    return [i for i in range(n) if hp.reserve(url % i)[1] is None]


def test_subdomains_share_one_limiter():
    # Reddit serves the same limiter from www., old. and the apex; treating them
    # as three hosts would triple the burst we present.
    keys = {hp.host_of(u) for u in (
        "https://www.reddit.com/r/a/.rss",
        "https://old.reddit.com/r/b/.rss",
        "https://reddit.com/search.rss?q=x",
    )}
    assert keys == {"reddit.com"}


def test_requests_to_one_host_are_spaced_not_bursted():
    waits = [hp.reserve("https://www.reddit.com/search.rss?q=%d" % i)[0] for i in range(3)]
    gap = hp.min_interval("reddit.com")
    assert waits[0] == 0
    assert waits[1] == pytest.approx(gap, abs=0.5)
    assert waits[2] == pytest.approx(gap * 2, abs=0.5)


def test_one_429_parks_every_route_on_the_host():
    # The bug, stated as a test: one route's refusal must inform the other 22.
    hp.record_failure("https://www.reddit.com/search.rss?q=1", "RATE_LIMITED")
    _, skip = hp.reserve("https://old.reddit.com/r/unrelated/.rss")
    assert skip and skip.startswith("host_cooldown")


def test_cooldown_is_scoped_to_the_host_that_refused_us():
    hp.record_failure("https://www.reddit.com/search.rss?q=1", "RATE_LIMITED")
    assert hp.reserve("https://news.google.com/rss/search?q=a")[1] is None


def test_a_lone_server_error_is_noise_a_streak_is_a_signal():
    for i in range(hp.SERVER_ERROR_STREAK - 1):
        hp.record_failure("https://hnrss.org/newest?q=%d" % i, "SOURCE_UNAVAILABLE")
    assert hp.reserve("https://hnrss.org/x")[1] is None
    hp.record_failure("https://hnrss.org/newest?q=last", "SOURCE_UNAVAILABLE")
    assert hp.reserve("https://hnrss.org/x")[1].startswith("host_cooldown")


def test_success_clears_the_cooldown():
    hp.record_failure("https://hnrss.org/a", "RATE_LIMITED")
    assert hp.reserve("https://hnrss.org/b")[1] is not None
    hp.record_success("https://hnrss.org/a")
    assert hp.reserve("https://hnrss.org/b")[1] is None


def test_repeated_refusal_lengthens_the_cooldown():
    hp.record_failure("https://reddit.com/a", "RATE_LIMITED")
    first = hp._cooldown_len["reddit.com"]
    hp.record_failure("https://reddit.com/a", "RATE_LIMITED")
    assert hp._cooldown_len["reddit.com"] == first * 2


def test_rotation_stops_the_same_routes_winning_every_cycle():
    # Pacing means a busy host cannot serve all its routes in one cycle. Route
    # order is stable, so without rotation the same few would win forever and
    # the rest would never run — starvation dressed up as politeness.
    cycles = [_cycle() for _ in range(4)]
    assert all(c for c in cycles), "every cycle must serve someone"
    assert len({tuple(c) for c in cycles}) == len(cycles), "winners must change"
    covered = set().union(*cycles)
    assert len(covered) > len(cycles[0]) * 2, "coverage must widen across cycles"


def test_rotation_eventually_reaches_every_route():
    seen = set()
    for _ in range(12):
        seen.update(_cycle())
    assert seen == set(range(23))


def test_a_skipped_route_does_not_consume_a_slot():
    # A route turned away must not advance the queue, or each denial would push
    # the host further out and the tail would never be reachable.
    for i in range(40):
        hp.reserve("https://www.reddit.com/search.rss?q=%d" % i)
    before = hp._next_free["reddit.com"]
    hp.reserve("https://www.reddit.com/search.rss?q=late")
    assert hp._next_free["reddit.com"] == before


def test_a_missing_browser_is_our_fault_not_the_endpoint_s():
    # The packaged app could not find a browser for days. Every x.com route
    # recorded the failure as its own — 7 failures, 0 successes, one short of
    # permanent quarantine — for a bug on our side. Classification is what keeps
    # that out of endpoint health (see NOT_ENDPOINT_FAULT in scraper_service).
    from services.error_classifier import classify_error, CAPABILITY_UNAVAILABLE
    from services.scraper_service import NOT_ENDPOINT_FAULT

    for exc in (RuntimeError("Playwright browsers are not installed at /x. "
                             "Run `playwright install chromium` once"),
                Exception("BrowserType.launch: Executable doesn't exist at "
                          "/Users/x/chromium_headless_shell-1217/headless_shell")):
        assert classify_error(exc) == CAPABILITY_UNAVAILABLE
        assert classify_error(exc) in NOT_ENDPOINT_FAULT


def test_a_real_source_failure_is_still_the_endpoint_s():
    from services.error_classifier import classify_error
    from services.scraper_service import NOT_ENDPOINT_FAULT

    for exc in (Exception("HTTP Error: 404 Client Error: Not Found"),
                Exception("HTTP Error: 502 Server Error: Bad Gateway"),
                Exception("RSS Parse Error: not well-formed")):
        assert classify_error(exc) not in NOT_ENDPOINT_FAULT
