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
    is_first_party as _is_first_party,
    real_publisher,
)

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
    """Topic profile terms for a tracker: name + target keywords/entities +
    keep_keywords. Embedded once and reused as the relevance reference."""
    terms = []
    if getattr(tracker, "name", None):
        terms.append(tracker.name)
    for field in ("target", "normalized_intent", "fetch_policy"):
        raw = getattr(tracker, field, None)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            terms.append(str(raw))
            continue
        if isinstance(data, list):
            terms += [str(x) for x in data]
        elif isinstance(data, dict):
            for k in ("topic", "entities", "keep_keywords", "keywords"):
                v = data.get(k)
                if isinstance(v, list):
                    terms += [str(x) for x in v]
                elif isinstance(v, str):
                    terms.append(v)
            for sig in data.get("signals", []) or []:
                if isinstance(sig, dict) and sig.get("value"):
                    terms.append(str(sig["value"]))
    # Dedup, drop empties/URLs (URLs aren't good topic anchors).
    seen, out = set(), []
    for t in terms:
        t = t.strip()
        if not t or t.startswith("http") or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out[:20]


def run_semantic_ingest(limit: int = 100, embedder=None) -> dict:
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
            for (vjson,) in s.exec(select(ArticleEmbedding.vector)).all():
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
    arbiter = None
    if gating_enabled:
        try:
            from services.llm_provider import get_provider
            _prov = get_provider()
            if getattr(_prov, "supports_generation", False):
                arbiter = _prov
        except Exception:
            arbiter = None
    arb_budget = _ARBITER_CALLS_PER_CYCLE

    created = 0
    updated = 0
    gated = 0
    with get_session() as session:
        from db.models import RawArticle, ArticleEmbedding, StoryThread
        for article, vec in embedded:
            # Relevance vs the tracker's topic profile.
            profile = _profile_vecs(article.tracker_id)
            relevance = sm.relevance_score(vec, profile) if profile else None
            if gating_enabled and profile and relevance is not None and \
                    relevance < sm.DEFAULT_RELEVANCE_THRESHOLD:
                article.relevance_gated = True
                gated += 1
                session.add(article)
                session.add(ArticleEmbedding(article_id=article.id, model_name=model_name,
                                             dim=len(vec), vector=json.dumps(vec), relevance=relevance))
                session.commit()
                logger.info(f"Article {article.id} relevance-gated ({relevance:.2f} < {sm.DEFAULT_RELEVANCE_THRESHOLD}); kept in Raw Feed, skipped by fusion.")
                continue

            # Load this tracker's thread centroids.
            threads = session.exec(select(StoryThread).where(StoryThread.tracker_id == article.tracker_id)).all()
            centroids = []
            thread_by_id = {}
            for th in threads:
                if th.centroid:
                    try:
                        centroids.append((th.id, json.loads(th.centroid)))
                        thread_by_id[th.id] = th
                    except Exception:
                        pass

            # Candidate = nearest thread above the low floor (positive-ish in the
            # centered space); the arbiter judges it. The floor (not the old 0.18)
            # keeps cross-language same-event pairs as candidates.
            tid, sim = sm.assign_thread(vec, centroids, threshold=sm.THREAD_CANDIDATE_FLOOR)
            # Embedding proposes merging into `tid`. If it's not a high-confidence
            # (near-identical) match, ask the LLM whether it's really the same
            # event — embedding alone can't separate same-entity events. A "no"
            # forces a new thread. Only merges, only the gray zone, only while
            # budget remains; otherwise keep the embedding decision.
            if (tid is not None and arbiter is not None and arb_budget > 0
                    and sim < sm.THREAD_HIGH_CONFIDENCE):
                arb_budget -= 1
                rep_title = (thread_by_id[tid].title or "")
                same = _llm_same_event(arbiter, rep_title, article.title or "")
                if same is False:
                    logger.info(f"Arbiter split: '{(article.title or '')[:40]}' ≠ event of thread {tid}")
                    tid = None
            if tid is None:
                # A brand-new thread from a first-party source is CONFIRMED
                # outright (an official announcement); otherwise it starts LEAD.
                th = StoryThread(
                    tracker_id=article.tracker_id,
                    title=(article.title or "")[:120],
                    centroid=json.dumps(vec),
                    member_count=1,
                    distinct_source_count=1,
                    lifecycle="CONFIRMED" if _is_first_party(article.url) else "LEAD",
                    first_seen_at=_now(),
                    last_update_at=_now(),
                )
                session.add(th)
                session.commit()
                session.refresh(th)
                article.thread_id = th.id
                created += 1
            else:
                th = thread_by_id[tid]
                new_centroid = sm.update_centroid(json.loads(th.centroid), th.member_count, vec)
                th.centroid = json.dumps(new_centroid)
                th.member_count += 1
                th.last_update_at = _now()
                article.thread_id = th.id
                # Distinct-source count drives corroboration. Count unique real
                # PUBLISHERS, not URL domains: Google News links all share
                # news.google.com, so domain-counting made this ≡ 1 for every
                # gnews thread and nothing ever left LEAD (P0.4). real_publisher()
                # recovers the outlet from the title's " - Publisher" suffix.
                member_rows = session.exec(
                    select(RawArticle.url, RawArticle.title).where(RawArticle.thread_id == th.id)
                ).all()
                pubs = {real_publisher(u, t) for (u, t) in member_rows} | \
                       {real_publisher(article.url, article.title)}
                th.distinct_source_count = len(pubs)
                # Lifecycle: LEAD → CORROBORATED (≥2 independent sources) →
                # CONFIRMED (a first-party/authoritative source present). A
                # first-party source confirms directly, even with fewer sources.
                member_urls_list = [u for (u, _t) in member_rows] + [article.url]
                has_first_party = any(_is_first_party(u) for u in member_urls_list)
                if has_first_party and th.lifecycle != "CONFIRMED":
                    th.lifecycle = "CONFIRMED"
                    logger.info(f"Thread {th.id} promoted → CONFIRMED (first-party source present)")
                elif th.distinct_source_count >= 2 and th.lifecycle == "LEAD":
                    th.lifecycle = "CORROBORATED"
                    logger.info(f"Thread {th.id} promoted LEAD → CORROBORATED ({th.distinct_source_count} sources)")
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

    logger.info(f"Semantic ingest: embedded {len(embedded)}, threads +{created} ~{updated}, "
                f"gated {gated}, embed_skipped {embed_skipped}")
    return {"embedded": len(embedded), "threads_created": created,
            "threads_updated": updated, "relevance_gated": gated,
            "embed_skipped": embed_skipped}


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
