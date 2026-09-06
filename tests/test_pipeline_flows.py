"""End-to-end-ish flows: semantic ingest -> alerts -> digest; portfolio planner."""
import json
from datetime import datetime, timezone


class _StubEmbedder:
    """On-topic (apple/siri/ajax) -> one vector; crypto -> another; else neutral.
    name != 'fallback' so the relevance gate is ENABLED."""
    name = "stub-real"

    def embed(self, texts):
        out = []
        for t in texts:
            tl = t.lower()
            if any(w in tl for w in ("apple", "siri", "ajax")):
                out.append([1.0, 0.05, 0, 0])
            elif any(w in tl for w in ("crypto", "bitcoin")):
                out.append([0.05, 1.0, 0, 0])
            else:
                out.append([0.4, 0.4, 0, 0])
        return out


def _seed_tracker_with_articles(name, keywords, articles, high_attention=False):
    from db.database import get_session
    from db.models import Tracker, RawArticle
    with get_session() as s:
        t = Tracker(name=name, tracker_type="KEYWORD", target=json.dumps(keywords),
                    source_intent="KEYWORD_DISCOVERY", radar_section="R", is_active=True,
                    is_high_attention=high_attention)
        s.add(t); s.commit(); s.refresh(t)
        # Every real row is stamped at intake (source_tiering §2; NULL is
        # impossible after migration 0020), so the seed stamps too: a 2-tuple
        # is an aggregated catch, a 3-tuple names its tier.
        for spec in articles:
            title, url = spec[0], spec[1]
            tier = spec[2] if len(spec) > 2 else "aggregated"
            s.add(RawArticle(tracker_id=t.id, title=title, url=url, content=title,
                             processed=False, source_tier=tier))
        s.commit()
        return t.id


def test_semantic_ingest_clusters_gates_and_promotes():
    from services.semantic_ingest import run_semantic_ingest
    from db.database import get_session
    from db.models import StoryThread, RawArticle
    from sqlmodel import select

    tid = _seed_tracker_with_articles(
        "Apple", ["apple siri", "ajax"],
        [("Apple rebuilds Siri on Ajax", "https://bloomberg.com/s1"),
         ("Apple Siri Ajax overhaul", "https://9to5mac.com/s2"),
         ("Apple Siri repo", "https://github.com/apple/siri", "primary"),   # first-party stamp -> CONFIRMED
         ("Bitcoin ETF inflows record", "https://coindesk.com/b1")], # off-topic -> gated
    )
    res = run_semantic_ingest(embedder=_StubEmbedder())
    assert res["embedded"] == 4
    with get_session() as s:
        # crypto article relevance-gated (real embedder enabled)
        crypto = s.exec(select(RawArticle).where(RawArticle.url == "https://coindesk.com/b1")).first()
        assert crypto.relevance_gated is True
        # apple thread confirmed (github first-party present)
        threads = s.exec(select(StoryThread).where(StoryThread.tracker_id == tid)).all()
        apple = [th for th in threads if th.lifecycle == "CONFIRMED"]
        assert len(apple) == 1
        assert apple[0].distinct_source_count == 3


def test_alerts_fire_idempotently_and_feed_digest():
    from services.semantic_ingest import run_semantic_ingest
    from services.alert_engine import evaluate_alerts
    from services.radar_digest import get_radar_stats, get_catchup

    _seed_tracker_with_articles(
        "AppleHA", ["apple siri"],
        [("Apple Siri Ajax A", "https://bloomberg.com/h1"),
         ("Apple Siri Ajax B", "https://reuters.com/h2"),
         ("Apple Siri Ajax C", "https://github.com/apple/siri2")],
        high_attention=True,
    )
    run_semantic_ingest(embedder=_StubEmbedder())
    r1 = evaluate_alerts(synthesize=False)
    assert r1["alerts_created"] >= 1
    r2 = evaluate_alerts(synthesize=False)
    assert r2["alerts_created"] == 0                       # idempotent
    stats = get_radar_stats(since_hours=168)
    assert stats["events_tracked"] >= 1
    cu = get_catchup(since_hours=168)
    assert cu["updated_threads"] >= 1


def test_portfolio_planner_fallback_selects_relevant_collection():
    # Seed preset collections so the planner has something to select from.
    from services.source_preset_service import upsert_source_presets_from_seed
    try:
        upsert_source_presets_from_seed()
    except Exception:
        pass
    from services.portfolio_planner import plan_portfolio
    p = plan_portfolio("bitcoin ethereum defi", "crypto market", use_llm=False)
    assert p["planner_used"] == "fallback"
    assert any("crypto" in c.lower() for c in p["selected_collections"])
    assert p["budget"]["max_sources_per_run"] == 8
