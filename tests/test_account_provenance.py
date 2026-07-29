"""Account provenance is stamped at intake, not re-derived at consumption.

The fusion gate used to ask `is_tracked_account(item.url)` — a host allow-list
(x.com, nitter, weibo…) consulted long after the fact. That answers "is this
link on a social platform", which is not the question the gate is asking. Both
directions were wrong, and both are pinned below.
"""
from services.adapters import SourceItem
from services.provenance import Tier
from services.source_resolver import SourceResolver


def _routes(target):
    return SourceResolver()._resolve_account_routes(target)


def test_every_account_route_is_stamped_whatever_platform_it_lands_on():
    routes = _routes("twitter:elonmusk\nweibo:12345\nbilibili:999")
    assert {r.platform for r in routes} == {"twitter", "weibo", "bilibili"}
    assert all(r.is_account for r in routes)


def test_a_keyword_firehose_is_not_the_people_radar():
    assert not [r for r in SourceResolver()._resolve_keyword_routes("xAI") if r.is_account]


def test_a_topic_feed_linking_to_a_social_host_is_not_an_account():
    # Failure mode A: the host allow-list matched any item whose URL happened to
    # be on x.com, handing the people-radar bypass to ordinary feed items.
    item = SourceItem(source_id="g1", platform="gnews", route="gnews",
                      title="Report on Musk", url="https://x.com/someone/status/1",
                      content="...", tier=Tier.CURATED)
    assert item.from_account is False


def test_an_account_read_through_an_unlisted_host_is_still_an_account():
    # Failure mode B: the same account via rsshub: or a new nitter mirror has no
    # listed host in its URL, so the allow-list denied it the bypass it had earned.
    weibo = [r for r in _routes("weibo:12345") if r.platform == "weibo"]
    assert weibo and all(r.is_account for r in weibo)
    assert not any(h in weibo[0].url_or_command for h in ("weibo.com", "x.com", "nitter"))


def test_the_gate_reads_the_stamp():
    from services.processor_service import _thread_worth_summary

    class _M:
        def __init__(self, **kw): self.__dict__.update(kw)

    thread = _M(lifecycle="EMERGING", is_resonant=False, distinct_source_count=1)
    tracker = _M(is_high_attention=False)

    stamped = [_M(source_tier=Tier.CURATED, url="https://rsshub.app/weibo/user/1",
                  from_account=True)]
    worth, reason = _thread_worth_summary(thread, stamped, tracker)
    assert worth and "tracked account" in reason

    linked = [_M(source_tier=Tier.CURATED, url="https://x.com/someone/status/1",
                 from_account=False)]
    worth, _ = _thread_worth_summary(thread, linked, tracker)
    assert not worth, "a link to x.com must not buy the people-radar bypass"
