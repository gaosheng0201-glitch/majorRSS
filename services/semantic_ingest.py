"""
Semantic ingest job (R3): embed new articles and cluster them into story
threads. Runs between scrape and LLM fusion so that most items are organized
(and de-duplicated) by cheap vectors before any generation model is touched.

Uses get_embedder() — the fallback hashing embedder needs no key, so clustering
works in pure-RSS mode too. Deterministic and testable end-to-end without an
API key.
"""
import json
import urllib.parse
from datetime import datetime, timezone

from sqlmodel import select

from services.log_service import get_logger
from services import semantic as sm
# Provenance (first-party detection, domain, real publisher) is shared infra —
# one home, read by semantic_ingest + publish_service (docs/source_tiering.md).
from services.provenance import (
    domain as _domain,
    real_publisher,
)
from services.lifecycle import lifecycle_for
from services.target_profile import TargetProfile

logger = get_logger("semantic")

_MAX_TEXT_CHARS = 2000  # embedding input cap per article

# LLM event arbiter: embedding proposes a thread merge; when it's not a
# near-identical (high-confidence) match, an LLM confirms the two are the SAME
# news event rather than merely the same entity — this is what separates
# "Gemini 3.6 released" from "Gemini horoscope today", which collapse together in
# embedding space no matter the threshold (愿景: 事件线索, not entity buckets).
_EVENT_ARBITER_SYS = (
    "You judge whether two news headlines report the SAME specific news event. "
    "The same company or topic is NOT enough — it must be the same underlying "
    "event/announcement. Reply with exactly one word: yes or no."
)
_ARBITER_CALLS_PER_CYCLE = 300  # cost/latency cap; excess falls back to embedding
# How many nearest threads the arbiter may consult per article (top-1 was a
# measured failure: the closest neighbour vetoed the right answer behind it).
# Worst case multiplies calls by this factor; typical batches (~90 gray-zone
# merges) stay under the cycle cap.
_ARBITER_CANDIDATES = 3


# 故事线 arbiter (author ruling 2026-09-03): the same call now answers a
# three-way question. "story" = not the same event, but the same developing
# story ("internal testing" → "dropping today" → "released"); such threads are
# linked as kin, never merged. Measured motive: 91% of arbiter answers were
# splits, and one pre-release story was nine fragments, each too weak to earn
# attention alone.
_STORY_ARBITER_SYS = (
    "You judge how two news headlines relate. Reply with exactly one word:\n"
    "event — they report the SAME specific news event/announcement;\n"
    "story — different events, but the same developing storyline about the same "
    "specific subject (e.g. a rumor, then the leak, then the launch of ONE product);\n"
    "different — otherwise. The same company or topic alone is 'different'; research "
    "papers, reviews, tutorials or opinion pieces on a similar subject are 'different'."
)


def _llm_relation(provider, title_a, title_b):
    """Three-way arbitration: 'event' | 'story' | 'different', or None if the
    call failed (caller keeps the embedding decision)."""
    try:
        text, usage = provider.generate(
            f"Headline A: {title_a}\nHeadline B: {title_b}",
            system=_STORY_ARBITER_SYS, temperature=0.0)
        try:
            from llm.processor import _record_usage
            _record_usage(getattr(provider, "name", "unknown"), "EventArbiter", usage)
        except Exception:
            pass
        t = (text or "").strip().lower()
        if t.startswith("event") or t.startswith("yes"):
            return "event"
        if t.startswith("story"):
            return "story"
        return "different"
    except Exception as e:
        logger.warning(f"Event arbiter failed ({e}); keeping embedding decision.")
        return None


def _thread_is_rumor_grade(session, th) -> bool:
    """A thread with no curated/primary member — the only kind a storyline may
    be BORN from. Measured on the first live cycle: two arXiv papers on the
    same subject were judged 'same story' and became a labelled rumor line,
    which is the wrong word for research. Any tier may still JOIN an existing
    storyline, so the official launch post keeps its "rumored since" lineage."""
    from db.models import RawArticle
    from services.provenance import HIGH_WEIGHT
    tiers = session.exec(select(RawArticle.source_tier)
                         .where(RawArticle.thread_id == th.id)).all()
    return not any((t or "") in HIGH_WEIGHT for t in tiers)


def _link_storyline(session, new_th, sibling_th) -> int:
    """Make two event threads kin. The sibling's storyline is reused; if it has
    none, one is born from the pair."""
    from db.models import Storyline
    sid = sibling_th.storyline_id
    if sid is None:
        sl = Storyline(title=(sibling_th.title or "")[:120],
                       first_seen_at=sibling_th.first_seen_at or _now(), last_update_at=_now())
        session.add(sl)
        session.commit()
        session.refresh(sl)
        sid = sl.id
        sibling_th.storyline_id = sid
        session.add(sibling_th)
    new_th.storyline_id = sid
    session.add(new_th)
    session.commit()
    return sid


def _refresh_storyline(session, sid: int):
    """Recompute a storyline's aggregates from its threads and their members.
    distinct_source_count counts real publishers across everything — grouping
    must never manufacture corroboration."""
    from db.models import Storyline, StoryThread, RawArticle
    sl = session.get(Storyline, sid)
    if not sl:
        return
    threads = session.exec(select(StoryThread).where(StoryThread.storyline_id == sid)).all()
    if not threads:
        return
    rows = session.exec(select(RawArticle.url, RawArticle.title)
                        .where(RawArticle.thread_id.in_([t.id for t in threads]))).all()
    lens = set()
    for t in threads:
        lens |= _thread_lens(t)
    biggest = max(threads, key=lambda t: (t.member_count or 0, t.id))
    sl.title = (biggest.title or "")[:120]
    sl.thread_count = len(threads)
    sl.member_count = len(rows)
    sl.distinct_source_count = len({real_publisher(u, t) for (u, t) in rows})
    sl.first_seen_at = min(t.first_seen_at for t in threads if t.first_seen_at)
    sl.last_update_at = max(t.last_update_at for t in threads if t.last_update_at)
    sl.tracker_ids = json.dumps(sorted(lens))
    sl.has_refined = any(bool(t.summary) for t in threads)
    session.add(sl)
    session.commit()


def _llm_same_event(provider, title_a, title_b):
    """LLM arbitration: same news event? True/False, or None if the call failed
    (caller then keeps the embedding decision). Cheap — a one-word completion."""
    try:
        text, usage = provider.generate(
            f"Headline A: {title_a}\nHeadline B: {title_b}",
            system=_EVENT_ARBITER_SYS, temperature=0.0)
        try:
            from llm.processor import _record_usage
            _record_usage(getattr(provider, "name", "unknown"), "EventArbiter", usage)
        except Exception:
            pass
        return text.strip().lower().startswith("y")
    except Exception as e:
        logger.warning(f"Event arbiter failed ({e}); keeping embedding decision.")
        return None


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _embed_text(article) -> str:
    body = (article.content or "")[:_MAX_TEXT_CHARS]
    return f"{article.title or ''}\n{body}".strip()


def _profile_terms(tracker) -> list:
    """Topic profile terms for a tracker — one definition of the target
    (services/target_profile.py), viewed as embedding anchors."""
    return TargetProfile.from_tracker(tracker).terms()


_POOL_WINDOW_DAYS = 30   # a story older than this no longer accepts members


def _also_ids(article) -> list:
    try:
        ids = json.loads(getattr(article, "also_tracker_ids", None) or "[]")
        return [int(i) for i in ids if i is not None]
    except Exception:
        return []


def _thread_lens(th) -> set:
    ids = set()
    if th.tracker_id is not None:
        ids.add(th.tracker_id)
    try:
        ids.update(int(i) for i in json.loads(th.tracker_ids or "[]") if i is not None)
    except Exception:
        pass
    return ids


def _load_thread_pool(session, StoryThread) -> dict:
    """Global candidate pool: every thread touched in the last window, with its
    centroid parsed once. Bounded by time, not by target."""
    from datetime import timedelta
    cutoff = _now() - timedelta(days=_POOL_WINDOW_DAYS)
    pool = {}
    for th in session.exec(select(StoryThread).where(StoryThread.last_update_at >= cutoff)).all():
        if not th.centroid:
            continue
        try:
            pool[th.id] = (th, json.loads(th.centroid))
        except Exception:
            pass
    return pool


def run_semantic_ingest(limit: int = 100, embedder=None, arbiter=None) -> dict:
    """Embed and thread-cluster up to `limit` not-yet-embedded articles.
    Returns a small summary dict.

    Clustering quality tracks embedding quality: a real multilingual model
    merges paraphrases and cross-language reports of one event into one thread.
    The no-key fallback embedder is bag-of-words, so with it threads are
    finer-grained (under-merge, never false-merge — the safe failure mode);
    dedup and relevance still work. `embedder` is injectable for testing."""
    from db.database import get_session
    from db.models import RawArticle, ArticleEmbedding, StoryThread
    from services.llm_provider import get_embedder

    if embedder is None:
        embedder = get_embedder()

    with get_session() as session:
        # Articles with no embedding yet.
        embedded_ids = set(session.exec(select(ArticleEmbedding.article_id)).all())
        articles = session.exec(select(RawArticle).order_by(RawArticle.id)).all()
        pending = [a for a in articles if a.id not in embedded_ids][:limit]

    if not pending:
        return {"embedded": 0, "threads_created": 0, "threads_updated": 0}

    model_name = getattr(embedder, "name", "unknown")

    # Embed the batch. embed() returns None for any item that permanently failed
    # (P0.3: one un-embeddable article or an exhausted-retry rate-limit must NOT
    # abort the whole batch — that froze the layer at 100/1101). Skip the Nones;
    # they carry no ArticleEmbedding row and are retried next cycle.
    raw_vectors = embedder.embed([_embed_text(a) for a in pending])
    embedded = [(a, v) for a, v in zip(pending, raw_vectors) if v is not None]
    embed_skipped = len(pending) - len(embedded)
    if embed_skipped:
        logger.warning(f"Semantic ingest: {embed_skipped}/{len(pending)} articles "
                       f"failed to embed this cycle; will retry next cycle.")
    if not embedded:
        return {"embedded": 0, "threads_created": 0, "threads_updated": 0,
                "embed_skipped": embed_skipped}
    vectors = [v for _, v in embedded]

    # Relevance gating acts (drops from LLM fusion) ONLY with a real embedder —
    # the fallback bag-of-words is too weak to safely reject content, so with it
    # we compute+store relevance but never gate.
    gating_enabled = model_name not in ("fallback", "unknown")

    # Topic profile vectors per tracker, embedded once and cached this run.
    from services import semantic as sm2  # alias to avoid shadowing in loop
    profile_cache = {}

    def _profile_vecs(tracker_id):
        if tracker_id in profile_cache:
            return profile_cache[tracker_id]
        from db.models import Tracker
        with get_session() as s:
            tr = s.get(Tracker, tracker_id)
        terms = _profile_terms(tr) if tr else []
        # embed() may return None per failed term (P0.3); drop them.
        vecs = [v for v in embedder.embed(terms) if v is not None] if terms else []
        profile_cache[tracker_id] = vecs
        return vecs

    # Anisotropy correction: set the corpus mean so thread clustering runs in a
    # mean-centered space (real embeddings collapse into a narrow cone otherwise;
    # see services/semantic.set_corpus_mean / assign_thread). Computed over all
    # stored embeddings + this batch. None for the bag-of-words fallback, where
    # centering doesn't apply and the raw threshold stays in effect.
    if gating_enabled:
        with get_session() as s:
            stored = []
            # SQLModel session.exec(select(single_column)) yields SCALARS (the
            # column value), not 1-tuples — so `for (vjson,) in ...` blew up with
            # "too many values to unpack" and aborted the whole semantic run once
            # ArticleEmbedding had rows (masked earlier while embedding was stalled
            # and this line was never reached). Handle scalar or Row defensively.
            for row in s.exec(select(ArticleEmbedding.vector)).all():
                vjson = row if isinstance(row, str) else row[0]
                try:
                    stored.append(json.loads(vjson))
                except Exception:
                    pass
        allvecs = stored + [list(v) for v in vectors]
        if allvecs:
            dim = len(allvecs[0])
            same = [v for v in allvecs if len(v) == dim]
            mean = [sum(v[i] for v in same) / len(same) for i in range(dim)]
            sm.set_corpus_mean(mean)
        else:
            sm.set_corpus_mean(None)
    else:
        sm.set_corpus_mean(None)

    # LLM event arbiter (see _llm_same_event): only when a generation model is
    # configured; no-key users fall back to embedding-only clustering.
    _arbiter_override = arbiter
    arbiter = None
    if gating_enabled:
        try:
            from services.llm_provider import get_provider
            _prov = get_provider()
            if getattr(_prov, "supports_generation", False):
                arbiter = _prov
        except Exception:
            arbiter = None
    if _arbiter_override is not None:
        arbiter = _arbiter_override      # injectable for tests
    arb_budget = _ARBITER_CALLS_PER_CYCLE

    created = 0
    updated = 0
    gated = 0
    # Arbiter accounting (author request 2026-07-29): the LLM event-arbiter is
    # the one generation call in the "cheap"半 of the pipeline, so its call
    # volume must be visible per cycle to judge whether raising
    # THREAD_HIGH_CONFIDENCE was worth it. Spend itself is billed under the
    # EventArbiter action in tokenusage → Billing 的「成本构成」卡.
    arb_calls = 0              # gray-zone candidates actually sent to the LLM
    arb_splits = 0             # …of which the LLM rejected as a different event
    arb_failed = 0             # …calls that errored (embedding decision kept)
    arb_rescued = 0            # merged into a candidate BEHIND a rejected top-1 —
                               # each of these is a thread the old flow would
                               # have wrongly started from scratch
    arb_skipped_confident = 0  # merges accepted on embedding confidence alone
    arb_skipped_budget = 0     # gray-zone merges that ran out of budget
    arb_story_links = 0        # new threads linked as kin of a same-story thread
    thread_pool = None         # global recent threads: id → (thread, centroid)
    with get_session() as session:
        from db.models import RawArticle, ArticleEmbedding, StoryThread
        for article, vec in embedded:
            # Relevance vs the tracker's topic profile. Both score and threshold
            # live in the ACTIVE space (mean-centered with a real embedder, raw
            # with the fallback) — in raw space the gate was dead: every article
            # scored 0.41+ against 0.35 and 0/1590 were ever gated. Stored
            # `relevance` values are therefore centered-space going forward
            # (historical rows are raw-space; scales differ).
            # 全局线索: an article concerns its fetcher AND every target its
            # intake stamp matched (also_tracker_ids). The junk floor used to
            # judge it by the fetcher's profile alone, so a Claude post that
            # gemini's route happened to fetch was scored against gemini's
            # profile — the best-matching target's profile is the honest one.
            lens_ids = [article.tracker_id] + _also_ids(article)
            relevance = None
            for lid in lens_ids:
                p = _profile_vecs(lid)
                if not p:
                    continue
                r = sm.relevance_score(vec, p)
                if relevance is None or r > relevance:
                    relevance = r
            profile = relevance is not None
            rel_threshold = sm.active_relevance_threshold()
            # Tier protection (same principle as the P1.1 fusion gate): sources
            # the user opted into (curated presets / tracked accounts / first
            # party) are NEVER junk-floored — only aggregator/legacy items are.
            from services.provenance import HIGH_WEIGHT
            tier_protected = (article.source_tier or "") in HIGH_WEIGHT
            if gating_enabled and profile and relevance is not None and \
                    not tier_protected and relevance < rel_threshold:
                article.relevance_gated = True
                # Also SETTLED, not pending: a junk-floored article is
                # deliberately excluded from fusion, so leaving processed=False
                # made the Dashboard's pending KPI grow forever (526 of 572
                # "pending" were floored items). Same bug class as the P1.1
                # gate-miss fix — that path was fixed, this one was missed.
                article.processed = True
                gated += 1
                session.add(article)
                session.add(ArticleEmbedding(article_id=article.id, model_name=model_name,
                                             dim=len(vec), vector=json.dumps(vec), relevance=relevance))
                session.commit()
                logger.info(f"Article {article.id} relevance-gated ({relevance:.2f} < {rel_threshold}); kept in Raw Feed, skipped by fusion.")
                continue

            # 全局线索: candidates come from the GLOBAL recent pool, not the
            # fetcher's own threads. Per-target pools were why one event lived
            # as two threads when two targets' routes both found it (measured:
            # 3.7 Flash twice; the author's Claude-under-grok cases). The pool
            # is loaded once per run and kept current in memory as threads are
            # created and joined below.
            if thread_pool is None:
                thread_pool = _load_thread_pool(session, StoryThread)
            centroids = [(tid, c) for tid, (_th, c) in thread_pool.items()]
            thread_by_id = {tid: th for tid, (th, _c) in thread_pool.items()}

            # Candidates = the k nearest threads above the low floor (positive-ish
            # in the centered space), best first. Top-1-only was a measured
            # failure mode: the nearest neighbour is often a sibling singleton
            # about the same entity, the arbiter (correctly) rejects it, and the
            # thread the article actually belongs to — sitting in second place —
            # is never consulted. 80% of arbiter calls ended in splits and 88% of
            # all threads were singletons. The arbiter now walks the list until a
            # "yes"; the judgement standard itself is unchanged.
            cands = sm.assign_thread_candidates(vec, centroids,
                                                floor=sm.THREAD_CANDIDATE_FLOOR,
                                                k=_ARBITER_CANDIDATES)
            tid = None
            story_sibling = None   # first candidate judged 'same story, different event'
            refresh_sid = None
            if cands:
                best_tid, best_sim = cands[0]
                if best_sim >= sm.THREAD_HIGH_CONFIDENCE:
                    # Near-identical: merged on embedding confidence alone.
                    # Counted so the share of unexamined merges stays visible.
                    tid = best_tid
                    arb_skipped_confident += 1
                elif arbiter is None:
                    # No arbiter configured: keep the embedding decision.
                    tid = best_tid
                elif arb_budget <= 0:
                    tid = best_tid
                    arb_skipped_budget += 1
                else:
                    for ctid, csim in cands:
                        if arb_budget <= 0:
                            # Ran dry mid-list. Do NOT fall back to a candidate
                            # the arbiter already rejected; a new thread is the
                            # conservative outcome here.
                            arb_skipped_budget += 1
                            break
                        arb_budget -= 1
                        arb_calls += 1
                        rel = _llm_relation(arbiter, (thread_by_id[ctid].title or ""),
                                            article.title or "")
                        same = (rel == "event") if rel is not None else None
                        if rel == "story" and story_sibling is None:
                            story_sibling = ctid
                        if same is True:
                            tid = ctid
                            if ctid != cands[0][0]:
                                # The fix earning its keep: merged into a thread
                                # the old top-1 flow could never have reached.
                                arb_rescued += 1
                                logger.info(f"Arbiter rescue (sim={csim:.2f}): "
                                            f"'{(article.title or '')[:40]}' → thread {ctid} "
                                            f"(top-1 {cands[0][0]} was rejected)")
                            break
                        if same is None:
                            # Call errored: keep the embedding decision for THIS
                            # candidate (the pre-arbiter behaviour) and stop.
                            arb_failed += 1
                            tid = ctid
                            break
                        arb_splits += 1
                        logger.info(f"Arbiter split (sim={csim:.2f}): '{(article.title or '')[:40]}' "
                                    f"≠ event of thread {ctid}")
            if tid is None:
                # A brand-new thread from a first-party source is CONFIRMED
                # outright (an official announcement); otherwise it starts LEAD.
                th = StoryThread(
                    tracker_id=article.tracker_id,
                    tracker_ids=json.dumps(sorted(set(lens_ids))),
                    title=(article.title or "")[:120],
                    centroid=json.dumps(vec),
                    member_count=1,
                    distinct_source_count=1,
                    # Lifecycle from the intake stamp, by the one rule
                    # (services/lifecycle.py). Consumption never derives
                    # provenance from a URL: legacy NULL stamps were written
                    # once by migration 0020, so no fallback remains.
                    lifecycle=lifecycle_for([article.source_tier], 1),
                    first_seen_at=_now(),
                    last_update_at=_now(),
                )
                session.add(th)
                session.commit()
                session.refresh(th)
                article.thread_id = th.id
                thread_pool[th.id] = (th, list(vec))
                created += 1
                _sib = thread_by_id.get(story_sibling) if story_sibling is not None else None
                if _sib is not None and (
                        _sib.storyline_id is not None
                        or ((article.source_tier or "aggregated") == "aggregated"
                            and _thread_is_rumor_grade(session, _sib))):
                    refresh_sid = _link_storyline(session, th, _sib)
                    arb_story_links += 1
                    logger.info(f"Storyline link: '{(article.title or '')[:40]}' ~ thread "
                                f"{story_sibling} (storyline {refresh_sid})")
            else:
                th = thread_by_id[tid]
                new_centroid = sm.update_centroid(json.loads(th.centroid), th.member_count, vec)
                th.centroid = json.dumps(new_centroid)
                thread_pool[th.id] = (th, new_centroid)
                th.member_count += 1
                th.last_update_at = _now()
                article.thread_id = th.id
                # The lens widens as members from other targets join.
                th.tracker_ids = json.dumps(sorted(_thread_lens(th) | set(lens_ids)))
                refresh_sid = th.storyline_id
                # Distinct-source count drives corroboration. Count unique real
                # PUBLISHERS, not URL domains: Google News links all share
                # news.google.com, so domain-counting made this ≡ 1 for every
                # gnews thread and nothing ever left LEAD (P0.4). real_publisher()
                # recovers the outlet from the title's " - Publisher" suffix.
                member_rows = session.exec(
                    select(RawArticle.url, RawArticle.title, RawArticle.source_tier)
                    .where(RawArticle.thread_id == th.id)
                ).all()
                pairs = [(u, t) for (u, t, _tier) in member_rows] + [(article.url, article.title)]
                pubs = {real_publisher(u, t) for (u, t) in pairs}
                # De-syndication: corroboration means INDEPENDENT reporting, not
                # reach. One press release syndicated to 10 outlets is 10
                # publishers but ONE title family — count the smaller of the two,
                # so syndication can't manufacture resonance/CORROBORATED (audit
                # 2026-07-23: "resonance comes from aggregator reposts of the
                # same pitch"). Reuses the P0.5 near-dup machinery.
                from services.dedup import is_near_duplicate
                families = []   # list of representative titles
                for (_u, t) in pairs:
                    if not any(is_near_duplicate(t, rep) for rep in families):
                        families.append(t)
                th.distinct_source_count = min(len(pubs), len(families))
                # Lifecycle by the one rule, from stamps only (never demotes
                # in the running pipeline; corrections are migrations).
                new_lc = lifecycle_for([tier for (_u, _t, tier) in member_rows] + [article.source_tier],
                                       th.distinct_source_count, current=th.lifecycle)
                if new_lc != th.lifecycle:
                    logger.info(f"Thread {th.id} {th.lifecycle} → {new_lc} ({th.distinct_source_count} sources)")
                    th.lifecycle = new_lc
                # Resonance: distinct sources per hour since the thread began.
                first_seen = th.first_seen_at
                if first_seen.tzinfo is not None:
                    first_seen = first_seen.replace(tzinfo=None)
                hours = max((_now() - first_seen).total_seconds() / 3600.0, 0.0)
                th.resonance_score = sm.resonance_score(th.distinct_source_count, hours)
                newly_resonant = sm.is_resonant(th.distinct_source_count, hours) and not th.is_resonant
                th.is_resonant = sm.is_resonant(th.distinct_source_count, hours)
                if newly_resonant:
                    logger.info(f"Thread {th.id} is RESONANT ({th.distinct_source_count} sources, score {th.resonance_score:.1f}/h) — cross-source signal")
                session.add(th)
                updated += 1

            session.add(article)
            session.add(ArticleEmbedding(
                article_id=article.id, model_name=model_name,
                dim=len(vec), vector=json.dumps(vec), relevance=relevance,
            ))
            session.commit()
            if refresh_sid:
                _refresh_storyline(session, refresh_sid)

    logger.info(f"Semantic ingest: embedded {len(embedded)}, threads +{created} ~{updated}, "
                f"gated {gated}, embed_skipped {embed_skipped} | "
                f"arbiter: {arb_calls} calls, {arb_splits} splits, {arb_rescued} rescued, "
                f"{arb_failed} failed, {arb_skipped_confident} skipped(confident), "
                f"{arb_skipped_budget} skipped(budget), {arb_story_links} story-links")
    return {"embedded": len(embedded), "threads_created": created,
            "threads_updated": updated, "relevance_gated": gated,
            "embed_skipped": embed_skipped,
            "arbiter_calls": arb_calls, "arbiter_splits": arb_splits,
            "arbiter_failed": arb_failed,
            "arbiter_skipped_confident": arb_skipped_confident,
            "arbiter_skipped_budget": arb_skipped_budget,
            "storyline_links": arb_story_links}


def refresh_resonance(window_days: int = 14) -> int:
    """Resonance is distinct-sources-per-hour and DECAYS as a thread ages, but
    it's only computed when a new member is added — a burst that fell quiet
    stays flagged 'resonant' forever, skewing /threads ordering and stats.
    Recompute it for recent + currently-flagged threads so the stored value
    stays honest. Returns the number of threads whose flag changed."""
    from datetime import timedelta
    from db.database import get_session
    from db.models import StoryThread
    from sqlalchemy import or_

    cutoff = _now() - timedelta(days=window_days)
    changed = 0
    with get_session() as session:
        threads = session.exec(
            select(StoryThread).where(or_(StoryThread.last_update_at >= cutoff,
                                          StoryThread.is_resonant == True))
        ).all()
        for th in threads:
            first_seen = th.first_seen_at.replace(tzinfo=None) if th.first_seen_at and th.first_seen_at.tzinfo else th.first_seen_at
            hours = max((_now() - first_seen).total_seconds() / 3600.0, 0.0) if first_seen else 0.0
            new_score = sm.resonance_score(th.distinct_source_count, hours)
            new_flag = sm.is_resonant(th.distinct_source_count, hours)
            if new_flag != th.is_resonant or abs(new_score - th.resonance_score) > 0.01:
                th.resonance_score = new_score
                th.is_resonant = new_flag
                session.add(th)
                changed += 1
        session.commit()
    if changed:
        logger.info(f"Resonance refresh: {changed} thread(s) updated (decay).")
    return changed
