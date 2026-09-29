"""Closing round (2026-09-28): fusion leftovers §G #7/#8/#12/#13, budgets,
grounding, task queue, auth, route budget — each pinned where it can regress."""
import json
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from db.database import get_session


@pytest.fixture(autouse=True)
def _leave_no_rows():
    """Every row a test here creates is removed after it: the suite shares one
    DB, and a stray un-embedded article is intake work for the next test."""
    from sqlmodel import select, func, delete
    from db.models import (ArticleEmbedding, RawArticle, StoryThread, ThreadTarget, Tracker,
                           TaskRequest, TokenUsage)
    tables = (ThreadTarget, ArticleEmbedding, RawArticle, StoryThread, TaskRequest, TokenUsage, Tracker)
    with get_session() as s:
        marks = {m: s.exec(select(func.max(m.id))).one() or 0 for m in tables}
    yield
    with get_session() as s:
        for m in tables:
            s.exec(delete(m).where(m.id > marks[m]))
        s.commit()


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _tracker(s, name, **kw):
    from db.models import Tracker
    t = Tracker(name=name, tracker_type="KEYWORD", target="[]", radar_section="AI",
                source_intent="KEYWORD_DISCOVERY", fetch_policy=json.dumps({"entities": [name]}), **kw)
    s.add(t); s.commit(); s.refresh(t)
    return t


# ---- §G #7: re-fusion updates the previous summary with only the new members

def test_previous_summary_is_the_model_written_part():
    from services.processor_service import _previous_summary
    stored = ("[TITLE: Launch day]\n\nThe model shipped.\n\n---\n"
              "**:material/menu_book: 摘要引用来源:**\n- [a](https://a.example)")
    assert _previous_summary(stored) == "Launch day\n\nThe model shipped."
    assert _previous_summary("free text") is None


def test_refusion_sends_previous_summary_and_only_new_members(monkeypatch):
    from db.models import RawArticle, StoryThread
    from llm.processor import FactCheckResult
    from services import processor_service as ps
    from services import thread_targets as tt

    seen = {}

    def fake(content, radar_section, **kw):
        seen["content"], seen["previous"] = content, kw.get("previous_summary")
        return FactCheckResult(validity_category="[VALID_NEWS]", importance_score=3,
                               title="Launch day, updated", llm_summary="Shipped; now priced.",
                               relevant_source_indices=[1], concerned_targets=None)
    monkeypatch.setattr(ps, "process_article", fake)

    with get_session() as s:
        t = _tracker(s, "refuse-t")
        th = StoryThread(tracker_id=t.id, title="Refusion unique event 7731", lifecycle="CORROBORATED",
                         member_count=4, distinct_source_count=4, fused_source_count=2,
                         fused_lifecycle="CORROBORATED", validity_category="[VALID_NEWS]",
                         source_url="Fused from 2 sources (a, b)",
                         summary="[TITLE: Launch day]\n\nThe model shipped.\n\n---\n**cited**",
                         first_seen_at=_now() - timedelta(hours=5), last_update_at=_now())
        s.add(th); s.commit(); s.refresh(th)
        old = []
        for i in range(2):
            a = RawArticle(tracker_id=t.id, thread_id=th.id, title=f"old {i}", url=f"https://old{i}.example/x",
                           content="OLD BODY", source_tier="primary", processed=True,
                           created_at=_now() - timedelta(hours=5 - i))
            s.add(a); s.commit(); s.refresh(a); old.append(a.id)
        new = []
        for i in range(2):
            a = RawArticle(tracker_id=t.id, thread_id=th.id, title=f"new {i}", url=f"https://new{i}.example/x",
                           content="NEW BODY", source_tier="primary", processed=False,
                           created_at=_now() - timedelta(minutes=10 - i))
            s.add(a); s.commit(); s.refresh(a); new.append(a.id)
        th.cited_article_ids = json.dumps([old[0]])
        s.add(th); s.commit()
        tt.link(s, th.id, {t.id: "route"}); s.commit()
        tid = th.id

    ps._fuse_thread(tid)

    assert seen["previous"] == "Launch day\n\nThe model shipped."
    assert "OLD BODY" not in seen["content"] and seen["content"].count("NEW BODY") == 2
    with get_session() as s:
        th = s.get(StoryThread, tid)
        cited = set(json.loads(th.cited_article_ids))
        assert old[0] in cited and len(cited & set(new)) == 1      # previous ∪ newly cited
        assert th.summary.startswith("[TITLE: Launch day, updated]")
        assert all(s.get(RawArticle, i).processed for i in new)


# ---- §G #12: fusion never runs while the semantic job holds the thread lock

def test_fusion_waits_for_the_thread_write_lock(monkeypatch):
    from db.models import RawArticle, StoryThread
    from services import processor_service as ps
    from services.pipeline_lock import THREAD_WRITE_LOCK

    with get_session() as s:
        t = _tracker(s, "lock-t")
        th = StoryThread(tracker_id=t.id, title="lock thread", member_count=1, distinct_source_count=1)
        s.add(th); s.commit(); s.refresh(th)
        s.add(RawArticle(tracker_id=t.id, thread_id=th.id, title="x", url="https://lock.example/x",
                         content="x", processed=False)); s.commit()

    fused_at = []
    monkeypatch.setattr(ps, "_fuse_thread", lambda tid: fused_at.append(time.monotonic()))
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    released = {}
    holding = threading.Event()

    def semantic_job():
        with THREAD_WRITE_LOCK:
            holding.set()
            threading.Event().wait(0.3)       # a real wait; time.sleep is patched
            released["at"] = time.monotonic()

    th_job = threading.Thread(target=semantic_job)
    th_job.start(); holding.wait()
    ps.process_pending_threads()
    th_job.join()
    assert fused_at and min(fused_at) >= released["at"]


# ---- §G #8: a permanently failing embed is parked, not retried forever

def test_embed_failures_are_parked_so_intake_cannot_stall():
    from db.models import RawArticle
    from services import semantic_ingest as si

    with get_session() as s:
        t = _tracker(s, "poison-t")
        a = RawArticle(tracker_id=t.id, title="POISON-ITEM-4471", url="https://poison.example/x",
                       content="POISON")
        s.add(a); s.commit(); s.refresh(a)
        aid = a.id

    class Emb:
        name = "stub"
        seen = []
        def embed(self, texts):
            Emb.seen.append([x for x in texts if "POISON-ITEM-4471" in x])
            return [None if "POISON-ITEM-4471" in x else [1.0, 0.0, 0.0] for x in texts]

    try:
        for _ in range(si.EMBED_MAX_ATTEMPTS):
            si.run_semantic_ingest(limit=500, embedder=Emb())
        assert si._embed_failures.get(aid) == si.EMBED_MAX_ATTEMPTS
        Emb.seen.clear()
        si.run_semantic_ingest(limit=500, embedder=Emb())
        assert not any(Emb.seen)                      # parked: not sent again
    finally:
        si._embed_failures.pop(aid, None)
        with get_session() as s:
            s.delete(s.get(RawArticle, aid)); s.commit()


def test_pipeline_health_counts_articles_that_fell_out_of_intake():
    from db.models import ArticleEmbedding, RawArticle
    from services.db_cleanup_service import _pipeline_health

    with get_session() as s:
        before = _pipeline_health(s)
        t = _tracker(s, "health-t")
        a = RawArticle(tracker_id=t.id, title="lost", url="https://lost.example/x", content="x",
                       created_at=_now() - timedelta(hours=2))
        b = RawArticle(tracker_id=t.id, title="stuck", url="https://stuck.example/x", content="x",
                       created_at=_now() - timedelta(hours=2))
        s.add(a); s.add(b); s.commit(); s.refresh(a); s.refresh(b)
        s.add(ArticleEmbedding(article_id=a.id, model_name="t", dim=3, vector="[1, 0, 0]")); s.commit()
        after = _pipeline_health(s)
        assert after["unthreaded_recent"] == before["unthreaded_recent"] + 1
        assert after["unembedded_stale"] == before["unembedded_stale"] + 1


# ---- §G #13: /feed's raw_article_id is a RawArticle id (the lead), not the thread id

def test_feed_raw_article_id_is_the_threads_lead_article():
    from backend.api.intelligence import get_intelligence_feed
    from db.models import RawArticle, StoryThread

    with get_session() as s:
        t = _tracker(s, "feed-t")
        th = StoryThread(tracker_id=t.id, title="feed thread", summary="[TITLE: x]\n\ny", radar_section="AI",
                         validity_category="[VALID_NEWS]", summarized_at=_now() + timedelta(days=365))
        s.add(th); s.commit(); s.refresh(th)
        ids = []
        for i in range(2):
            a = RawArticle(tracker_id=t.id, thread_id=th.id, title=f"m{i}", url=f"https://feed{i}.example/x",
                           content="x")
            s.add(a); s.commit(); s.refresh(a); ids.append(a.id)
        feed = get_intelligence_feed(limit=5, session=s)
        card = next(c for c in feed if c.id == th.id)
        assert card.raw_article_id == min(ids)


# ---- P1.2+: one daily brake for all background spend; a per-target cap on fusion

def _spend(tokens, action="FactCheck"):
    from db.models import TokenUsage
    with get_session() as s:
        s.add(TokenUsage(model_name="m", action_type=action, prompt_tokens=tokens,
                         completion_tokens=0, total_tokens=tokens))
        s.commit()


def test_global_budget_pauses_background_spend(monkeypatch):
    from services import llm_budget
    from services import semantic_ingest as si
    from services import thread_merge as tm
    from services import alert_engine as ae
    llm_budget.reset_cache()
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", str(llm_budget.todays_usage() + 100))
    assert not llm_budget.exhausted("t")
    _spend(500)
    llm_budget.reset_cache()
    try:
        assert llm_budget.exhausted("t")
        with get_session() as s:
            t = _tracker(s, "budget-t")
            from db.models import RawArticle
            s.add(RawArticle(tracker_id=t.id, title="b", url="https://budget.example/x", content="x")); s.commit()

        class Emb:
            name = "real"
            called = False
            def embed(self, texts):
                Emb.called = True
                return [[1.0, 0.0] for _ in texts]
        assert si.run_semantic_ingest(limit=500, embedder=Emb()).get("budget") == "exhausted"
        assert not Emb.called

        class Arb:
            name = "stub"; supports_generation = True
            def generate(self, *a, **k):
                raise AssertionError("merge pass must not call the model over budget")
        assert tm.run_merge_pass(arbiter=Arb())["reason"] == "budget"

        class P:
            name = "stub"; supports_generation = True
            def generate(self, *a, **k):
                raise AssertionError("alert synthesis must fall back over budget")
        monkeypatch.setattr("services.llm_provider.get_provider", lambda: P())
        from types import SimpleNamespace as NS
        title, body = ae._synthesize(NS(title="T", distinct_source_count=2),
                                     [NS(title="a", url="https://a.example", content="x")])
        assert "Sources" in body
    finally:
        llm_budget.reset_cache()


def test_target_cap_defers_that_targets_summaries_only(monkeypatch):
    from db.models import RawArticle, StoryThread
    from services import llm_budget
    from services import processor_service as ps
    from services import thread_targets as tt

    monkeypatch.setattr(ps, "process_article",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("capped target reached the model")))
    llm_budget.reset_cache()
    with get_session() as s:
        t = _tracker(s, "capped-t")
        t.fetch_policy = json.dumps({"entities": ["capped-t"], "daily_token_budget": 1000}); s.add(t); s.commit()
        th = StoryThread(tracker_id=t.id, title="Capped target event 5521", lifecycle="CONFIRMED",
                         member_count=2, distinct_source_count=2)
        s.add(th); s.commit(); s.refresh(th)
        for i in range(2):
            s.add(RawArticle(tracker_id=t.id, thread_id=th.id, title=f"c{i}", url=f"https://cap{i}.example/x",
                             content="x", source_tier="primary"))
        s.commit()
        tt.link(s, th.id, {t.id: "route"}); s.commit()
        tid, name = th.id, t.name
    _spend(1500, f"FactCheck: {name}")
    try:
        ps._fuse_thread(tid)
        with get_session() as s:
            assert s.get(StoryThread, tid).summary is None
            members = s.exec(__import__("sqlmodel").select(RawArticle).where(RawArticle.thread_id == tid)).all()
            assert not any(m.processed for m in members)      # still pending, not dropped
    finally:
        llm_budget.reset_cache()


# ---- editing a target merges its policy instead of erasing what no form shows

def test_update_tracker_merges_policy_and_keeps_unsent_fields():
    from backend.api.trackers import create_tracker, update_tracker
    from backend.schemas import TrackerCreate

    with get_session() as s:
        created = create_tracker(TrackerCreate(
            name="merge-edit-t", target=json.dumps({"topic": "x", "signals": [{"type": "keyword", "value": "x"}]}),
            radar_section="AI", source_intent="HYBRID",
            fetch_policy=json.dumps({"entities": ["x"], "source_scope": ["ai"], "intent_plan": {"k": 1}})), session=s)
        assert created.tracker_type == "HYBRID"            # derived, not required
        created.auth_profile_id = 7; s.add(created); s.commit()
        updated = update_tracker(created.id, TrackerCreate(
            name="merge-edit-t", tracker_type="HYBRID", target=created.target, radar_section="AI",
            source_intent="HYBRID", fetch_policy=json.dumps({"max_days": 3, "keep_keywords": []})), session=s)
        policy = json.loads(updated.fetch_policy)
        assert policy["intent_plan"] == {"k": 1} and policy["source_scope"] == ["ai"]
        assert policy["max_days"] == 3 and policy["keep_keywords"] == []
        assert updated.auth_profile_id == 7


# ---- P2.2: the briefing reports what the summaries say; inference is marked

def test_briefing_prompt_is_grounded(monkeypatch):
    from db.models import StoryThread
    import llm.processor as lp

    seen = {}

    class P:
        name = "stub"; supports_generation = True
        def generate(self, prompt, system=None, temperature=None, **kw):
            seen.update(system=system, temperature=temperature)
            return "briefing", {}
    monkeypatch.setattr(lp, "get_provider", lambda: P())
    with get_session() as s:
        s.add(StoryThread(title="g", summary="[TITLE: g]\n\nbody", validity_category="[VALID_NEWS]",
                          radar_section="AI", summarized_at=_now())); s.commit()
    lp.generate_daily_briefing()
    assert "〔分析〕" in seen["system"] and "own knowledge" in seen["system"]
    assert "podcast" not in seen["system"] and seen["temperature"] <= 0.2


# ---- user runs are background tasks with an id to poll

def test_task_runner_records_result_and_failure():
    from services import task_runner as tr

    def wait(tid):
        for _ in range(100):
            t = tr.get(tid)
            if t["status"] != "RUNNING":
                return t
            threading.Event().wait(0.05)
        raise AssertionError("task did not finish")

    ok = wait(tr.submit("TEST", lambda: {"answer": 42, "at": _now()}))
    assert ok["status"] == "COMPLETED" and ok["result"]["answer"] == 42 and ok["job_type"] == "USER_TEST"

    def boom():
        raise ValueError("no route resolved")
    bad = wait(tr.submit("TEST", boom))
    assert bad["status"] == "FAILED" and "no route resolved" in bad["error"]


def test_poller_marks_pure_rss_skips_as_skipped_and_restart_interrupts_user_runs(monkeypatch):
    import scheduler
    from db.models import TaskRequest
    from services import task_runner as tr

    monkeypatch.setattr(scheduler, "is_pure_rss_mode", lambda: True)
    with get_session() as s:
        skip = TaskRequest(job_type="PROCESS", target_type="TRACKER", target_id="1", status="PENDING")
        odd = TaskRequest(job_type="NO_SUCH_JOB", target_type="X", target_id="1", status="PENDING")
        cut = TaskRequest(job_type="USER_RUN_TRACE", target_type="TRACKER", target_id="1", status="RUNNING",
                          started_at=tr.PROCESS_STARTED - timedelta(minutes=1))
        s.add(skip); s.add(odd); s.add(cut); s.commit()
        ids = (skip.id, odd.id, cut.id)
    scheduler.process_task_requests()
    with get_session() as s:
        a, b, c = (s.get(TaskRequest, i) for i in ids)
        assert a.status == "SKIPPED" and a.finished_at is not None      # not "COMPLETED"
        assert b.status == "FAILED" and "Unknown job type" in b.error
        assert c.status == "FAILED" and "restarted" in c.error


# ---- an Expired profile is not walked into the login wall

def test_expired_profile_routes_are_skipped_or_anonymous():
    from db.models import AuthProfile
    from services.source_resolver import SourceResolver, SourceRoute

    with get_session() as s:
        p = AuthProfile(platform="twitter", display_name="expired-p", storage_ref="x", status="Expired")
        s.add(p); s.commit(); s.refresh(p)
        pid = p.id
    try:
        r = SourceResolver(fetch_policy=None, auth_profile_id=pid)
        routes = [SourceRoute(route_id="agentic_twitter_0", adapter="AgenticAdapter", platform="twitter",
                              url_or_command="https://x.com/someone", purpose="discovery",
                              requires_auth=False, priority=3),
                  SourceRoute(route_id="agentic_snapshot_0", adapter="AgenticAdapter", platform="web",
                              url_or_command="https://vendor.example/news", purpose="snapshot",
                              requires_auth=False, priority=1)]
        r._enrich_routes_with_auth(routes)
        assert routes[0].auth_status == "expired" and routes[0].auth_profile_id is None
        assert routes[1].auth_status == "expired_anonymous" and routes[1].auth_profile_id is None
    finally:
        with get_session() as s:
            s.delete(s.get(AuthProfile, pid)); s.commit()


# ---- the per-run source cap keeps what the user opted into

def test_source_cap_counts_sources_and_prefers_opted_in_ones():
    from services.provenance import Tier
    from services.source_resolver import SourceResolver, SourceRoute

    def route(rid, tier, prio):
        return SourceRoute(route_id=rid, adapter="RssAdapter", platform="web", purpose="discovery",
                           requires_auth=False, url_or_command=f"https://{rid}.example",
                           priority=prio, tier=tier)
    routes = ([route(f"gnews_{i}", Tier.AGGREGATED, 1) for i in range(3)]
              + [route(f"hn_{i}", Tier.AGGREGATED, 1) for i in range(3)]
              + [route("rss_feed_0", Tier.CURATED, 1), route("rss_alternate_0", Tier.CURATED, 2),
                 route("preset_openai_news", Tier.CURATED, 5), route("sugg_rss_0", Tier.CURATED, 4)])
    r = SourceResolver(fetch_policy=json.dumps({"max_sources_per_run": 4}))
    kept = [x.route_id for x in r._apply_budget(routes)]
    # the three opted-in sources survive (the feed with its fallback), then one firehose
    assert {"rss_feed_0", "rss_alternate_0", "preset_openai_news", "sugg_rss_0"} <= set(kept)
    assert sum(1 for k in kept if k.startswith(("gnews_", "hn_"))) == 1
    assert kept == [x.route_id for x in routes if x.route_id in kept]    # order kept


# ---- 2026-09-28 Sonnet 5.5: a templated launch for a different product is not "the same event"

def test_confident_merge_needs_a_copied_headline_not_just_a_close_vector():
    from sqlmodel import select
    from db.models import RawArticle, StoryThread
    from services import semantic_ingest as si

    V = [0.3, 0.1, 0.9, 0.2, 0.4, 0.7, 0.5]          # 7-dim: no other test's vectors share the pool

    class Emb:
        name = "fallback"                             # raw space: identical vectors → cosine 1.0
        def embed(self, texts):
            return [list(V) for _ in texts]

    class Arb:
        name = "stub"; supports_generation = True
        calls = []
        def generate(self, prompt, **kw):
            Arb.calls.append(prompt)
            return ("event" if "Reuters" in prompt else "different"), {}

    with get_session() as s:
        t = _tracker(s, "launch-t")
        near = [x + (0.05 if i == 0 else 0.0) for i, x in enumerate(V)]   # cosine ≈ 0.99 to V
        old = StoryThread(tracker_id=t.id, title="Claude Opus 5.5 now available on AI Gateway",
                          centroid=json.dumps(near), member_count=1, distinct_source_count=1,
                          first_seen_at=_now() - timedelta(days=6), last_update_at=_now())
        s.add(old); s.commit(); s.refresh(old)
        launch = RawArticle(tracker_id=t.id, title="Claude Sonnet 5.5 now available on AI Gateway",
                            url="https://gw.example/sonnet", content="x", source_tier="curated")
        s.add(launch); s.commit(); s.refresh(launch)
        old_id, launch_id = old.id, launch.id

    si.run_semantic_ingest(limit=500, embedder=Emb(), arbiter=Arb())
    with get_session() as s:
        a = s.get(RawArticle, launch_id)
        assert a.thread_id is not None and a.thread_id != old_id     # its own thread
        assert any("Sonnet 5.5" in p for p in Arb.calls)             # the arbiter was asked

    # a syndicated copy of the same headline still merges without a call
    Arb.calls.clear()
    with get_session() as s:
        new_tid = s.get(RawArticle, launch_id).thread_id
        copy = RawArticle(tracker_id=s.exec(select(StoryThread.tracker_id).where(StoryThread.id == new_tid)).one(),
                          title="Claude Sonnet 5.5 now available on AI Gateway", url="https://mirror.example/s",
                          content="x", source_tier="aggregated")
        s.add(copy); s.commit(); s.refresh(copy)
        copy_id = copy.id
    si.run_semantic_ingest(limit=500, embedder=Emb(), arbiter=Arb())
    with get_session() as s:
        assert s.get(RawArticle, copy_id).thread_id == new_tid
    assert not Arb.calls


# ---- 醒来不漏: what you missed while away

def test_away_highlights_list_alerts_and_new_events_for_your_targets_only():
    from db.models import RadarAlert, StoryThread, ThreadTarget
    from services.radar_digest import get_away_highlights
    from services import thread_targets as tt

    since = _now() - timedelta(hours=3)
    with get_session() as s:
        t = _tracker(s, "away-t")
        launch = StoryThread(tracker_id=t.id, title="Away: model launched", lifecycle="CONFIRMED",
                             distinct_source_count=1, first_seen_at=_now() - timedelta(hours=1), last_update_at=_now())
        wave = StoryThread(tracker_id=t.id, title="Away: everyone reports it", lifecycle="CORROBORATED",
                           distinct_source_count=9, is_resonant=True, resonance_score=4.0,
                           first_seen_at=_now() - timedelta(days=2), last_update_at=_now())
        nobody = StoryThread(tracker_id=t.id, title="Away: concerns no target", lifecycle="CONFIRMED",
                             first_seen_at=_now() - timedelta(hours=1), last_update_at=_now())
        vetoed = StoryThread(tracker_id=t.id, title="Away: name collision", lifecycle="CONFIRMED",
                             first_seen_at=_now() - timedelta(hours=1), last_update_at=_now())
        old = StoryThread(tracker_id=t.id, title="Away: before you left", lifecycle="CONFIRMED",
                          first_seen_at=_now() - timedelta(days=3), last_update_at=_now())
        for th in (launch, wave, nobody, vetoed, old):
            s.add(th)
        s.commit()
        for th in (launch, wave, old):
            tt.link(s, th.id, {t.id: "route"})
        s.add(ThreadTarget(thread_id=vetoed.id, tracker_id=t.id, source="match", llm_verdict=False))
        s.add(RadarAlert(thread_id=wave.id, tracker_id=t.id, reason="RESONANCE", title=wave.title,
                         summary="s", distinct_source_count=9, lifecycle="CORROBORATED"))
        s.commit()
        ids = {"launch": launch.id, "wave": wave.id}
        others = {nobody.id, vetoed.id, old.id}
    try:
        r = get_away_highlights(since.isoformat() + "Z")
        got = [h["thread_id"] for h in r["highlights"]]
        assert got[:2] == [ids["wave"], ids["launch"]]          # the alert first, then the new confirmation
        assert not others & set(got)
        assert r["highlights"][0]["reasons"] == ["RESONANCE"] and r["highlights"][0]["targets"] == ["away-t"]
    finally:
        with get_session() as s:
            from sqlmodel import delete
            s.exec(delete(RadarAlert).where(RadarAlert.thread_id == ids["wave"])); s.commit()
