"""The 2026-08-13 investigation fixes, pinned.

Two author complaints ("why didn't it catch the Brin/3.5-Pro story?" / "why not
the 3.7 Flash release?") traced to the SURFACING layer, not capture. Three
defects, one test file:

  A. RSS timestamps skewed +5h into the future (mktime read a UTC struct as
     local standard time), scrambling "who reported first".
  B. deepmind.google absent from the first-party floor, so the most
     authoritative source of the user's #1 tracker entered CURATED, started a
     muted singleton LEAD, and was never summarised.
  C. The event arbiter saw only the top-1 nearest thread; one wrong-but-closest
     sibling vetoed the right thread sitting in second place (measured: 80% of
     arbiter calls were splits, 88% of all threads singletons).
"""
import calendar
import time
from datetime import datetime, timezone

from scrapers.tier1_rss import entry_published_at
from services import semantic as sm
from services.provenance import Tier, is_first_party, tier_for_url


class _Entry:
    def __init__(self, parsed):
        self.published_parsed = parsed


# --- A. timestamp parse ------------------------------------------------------

def test_feed_utc_struct_stays_utc():
    # The DeepMind announcement's real pubDate: Thu, 13 Aug 2026 17:04:18 +0000.
    struct = time.struct_time((2026, 8, 13, 17, 4, 18, 3, 225, 0))
    got = entry_published_at(_Entry(struct))
    assert got == datetime(2026, 8, 13, 17, 4, 18, tzinfo=timezone.utc)


def test_the_old_bug_would_have_shifted_this_machine_5h():
    # Guard against regression to mktime: on any machine whose local offset is
    # not UTC, mktime and timegm disagree on a UTC struct. If this box IS UTC
    # the assertion is vacuous, which is fine — the bug only bit non-UTC boxes.
    struct = time.struct_time((2026, 8, 13, 17, 4, 18, 3, 225, 0))
    if time.timezone != 0:
        assert time.mktime(struct) != calendar.timegm(struct)


def test_missing_date_is_none_not_now():
    assert entry_published_at(_Entry(None)) is None


# --- B. first-party floor ----------------------------------------------------

def test_frontier_lab_own_channels_are_first_party():
    # The measured gap: blog.google was listed, DeepMind's own domain was not.
    for u in ("https://deepmind.google/blog/introducing-gemini-3-7-flash/",
              "https://x.ai/news/some-release", "https://mistral.ai/news/x",
              "https://status.claude.com/incidents/1"):
        assert is_first_party(u), u
        assert tier_for_url(u, Tier.CURATED) == Tier.PRIMARY, u


def test_press_is_not_first_party():
    # Media stays CURATED by design — an outlet's feed is official-of-the-feed,
    # not the subject's own channel.
    for u in ("https://feeds.bbci.co.uk/news/rss.xml",
              "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
              "https://www.bloomberg.com/markets"):
        assert not is_first_party(u), u


def test_portfolio_vendor_blogs_stay_curated():
    # The Cloudflare lesson: 5 of 5 summaries off-topic when its posts
    # auto-passed. Domain-level PRIMARY for portfolio blogs would resurrect
    # that; whether cloudflare.com is first-party depends on whose tracker it
    # is, which is the P4.0 planner's call.
    assert not is_first_party("https://blog.cloudflare.com/some-post/")


def test_gov_uk_suffix_now_matches():
    # ".gov" never matched ".gov.uk".
    assert is_first_party("https://www.gov.uk/government/news/x")


def test_code_host_guard_still_applies_to_huggingface():
    assert tier_for_url("https://huggingface.co/blog/some-release",
                        Tier.CURATED) == Tier.PRIMARY
    assert tier_for_url("https://huggingface.co/someuser/somemodel",
                        Tier.CURATED) == Tier.CURATED


def test_aggregated_still_never_upgrades():
    # A keyword-search hit pointing at deepmind.google is still a firehose catch.
    assert tier_for_url("https://deepmind.google/blog/x",
                        Tier.AGGREGATED) == Tier.AGGREGATED


# --- C. arbiter candidates ---------------------------------------------------

def _vec(i, n=8):
    v = [0.0] * n
    v[i] = 1.0
    return v


def test_candidates_are_ordered_best_first_and_floored():
    target = _vec(0)
    centroids = [
        (1, [0.9, 0.1, 0, 0, 0, 0, 0, 0]),   # close
        (2, [0.5, 0.5, 0, 0, 0, 0, 0, 0]),   # closer than 3
        (3, _vec(4)),                          # orthogonal — below floor
    ]
    got = sm.assign_thread_candidates(target, centroids, floor=0.1, k=3)
    assert [tid for tid, _ in got] == [1, 2]
    sims = [s for _, s in got]
    assert sims == sorted(sims, reverse=True)


def test_k_caps_the_list():
    target = _vec(0)
    centroids = [(i, [0.9 - 0.01 * i, 0.1, 0, 0, 0, 0, 0, 0]) for i in range(6)]
    got = sm.assign_thread_candidates(target, centroids, floor=0.1, k=3)
    assert len(got) == 3


def test_the_brin_shape_second_candidate_reachable():
    # The exact failure: nearest = a sibling singleton (arbiter rightly says
    # no), second = the real story thread. Top-1 flow could never reach it;
    # the candidate list makes it reachable at all.
    article = [0.8, 0.6, 0, 0, 0, 0, 0, 0]
    sibling = (10, [0.9, 0.43, 0, 0, 0, 0, 0, 0])    # closest
    real_story = (20, [0.6, 0.8, 0, 0, 0, 0, 0, 0])  # second
    got = sm.assign_thread_candidates(article, [sibling, real_story],
                                      floor=0.1, k=3)
    assert [tid for tid, _ in got] == [10, 20]
    # A one-candidate flow stops here; the list carries the rescue target.
    assert got[1][0] == 20


# --- D. material-increment rule (2026-08-13 time-honesty ruling) -------------

def test_small_thread_growth_is_material():
    from services.processor_service import is_material_increment
    # 3→4 publishers genuinely changes a story's credibility (+33%).
    assert is_material_increment(3, "CORROBORATED", 4, "CORROBORATED")


def test_mega_thread_stragglers_are_not_material():
    from services.processor_service import is_material_increment
    # The measured case: a 3-week-old thread at 37 publishers gained two
    # straggler outlets (+5%), re-burned fusion twice and outranked that day's
    # real news. Outlet #40 is news about outlet #40.
    assert not is_material_increment(37, "CORROBORATED", 39, "CORROBORATED")


def test_promotion_is_material_at_any_size():
    from services.processor_service import is_material_increment
    assert is_material_increment(39, "CORROBORATED", 39, "CONFIRMED")


def test_no_growth_is_never_material():
    from services.processor_service import is_material_increment
    assert not is_material_increment(5, "CONFIRMED", 5, "CONFIRMED")
    assert not is_material_increment(5, "CONFIRMED", 4, "CONFIRMED")


def test_first_growth_from_nothing_is_material():
    from services.processor_service import is_material_increment
    assert is_material_increment(0, "", 1, "LEAD")


# --- 全局线索 (author ruling 2026-09-01) -------------------------------------------

def test_same_event_from_two_targets_becomes_one_thread_with_both_in_lens():
    """Two targets' routes find the same story. Per-target pools made two
    threads (measured: 3.7 Flash twice); the global pool makes one, and its
    lens names both targets so either filter chip shows it."""
    import json
    from db.database import get_session
    from db.models import Tracker, RawArticle, StoryThread, ArticleEmbedding
    from services.semantic_ingest import run_semantic_ingest
    from sqlmodel import select, delete

    with get_session() as s:
        s.exec(delete(ArticleEmbedding)); s.exec(delete(RawArticle)); s.exec(delete(StoryThread))
        s.commit()
        a = Tracker(name="claude-g", tracker_type="KEYWORD", target="[]", radar_section="AI",
                    source_intent="KEYWORD_DISCOVERY", fetch_policy=json.dumps({"entities": ["Claude"]}))
        b = Tracker(name="gemini-g", tracker_type="KEYWORD", target="[]", radar_section="AI",
                    source_intent="KEYWORD_DISCOVERY", fetch_policy=json.dumps({"entities": ["Gemini"]}))
        s.add(a); s.add(b); s.commit(); s.refresh(a); s.refresh(b)
        title = "Anthropic releases Claude Fable 5.1 with cheaper cache reads"
        s.add(RawArticle(tracker_id=a.id, title=title, url="https://one.example/fable",
                         content=title, source_tier="aggregated"))
        s.add(RawArticle(tracker_id=b.id, title=title + " - Outlet Two",
                         url="https://two.example/fable", content=title, source_tier="aggregated",
                         also_tracker_ids=json.dumps([a.id])))
        s.commit()

    out = run_semantic_ingest(limit=10)
    assert out["embedded"] == 2

    with get_session() as s:
        threads = s.exec(select(StoryThread)).all()
        assert len(threads) == 1, [t.title for t in threads]
        lens = set(json.loads(threads[0].tracker_ids))
        assert lens == {a.id, b.id}
        assert threads[0].member_count == 2


def test_ignore_keywords_veto_cross_target_visibility():
    from services.attribution import TrackerProfile, relevant_tracker_ids
    gemini = TrackerProfile(1, ["Gemini"], ["deepmind.google"], ignore_keywords=["exchange", "horoscope"])
    assert relevant_tracker_ids("Gemini exchange hacked for $30M", "", "https://coin.example/x",
                                [gemini], owner_id=9) == []
    assert relevant_tracker_ids("Gemini 3.8 Flash released", "", "https://press.example/y",
                                [gemini], owner_id=9) == [1]
    # An official-domain hit is never vetoed: the target's own channel is its own.
    assert relevant_tracker_ids("Exchange rate demo", "", "https://deepmind.google/blog/z",
                                [gemini], owner_id=9) == [1]
