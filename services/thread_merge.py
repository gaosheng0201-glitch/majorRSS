"""事后合并 — the recoverable direction, completed.

Intake prefers a split over a wrong merge (a wrong merge poisons a summary
and cannot be undone; a split can). But the arbiter only consults the three
nearest threads, so one event still lands in two threads when a headline
leans toward a neighbouring story — measured 2026-09-22: "Claude Opus 5.5
matches Fable 5.1 performance" had three Fable-launch threads as its nearest
candidates and the Opus 5.5 launch thread, born three minutes earlier, in
fourth place; nobody asked, and the launch ended up as two refined cards.

This pass closes the loop: among recently updated threads, pairs whose
centroids sit above a high similarity are put to the same arbiter; "event"
merges them into the older thread (members, targets, alerts, kinship carried
over, counts recomputed, the summary kept and re-fused on the next pass as a
material increment); any other verdict is remembered so the pair is not asked
again. Bounded per cycle; no candidate limit hides a neighbour here because
the question is asked pair by pair.
"""
import json
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from sqlmodel import select

from services import semantic as sm
from services.log_service import get_logger
from services.provenance import real_publisher

logger = get_logger("merge")

WINDOW_HOURS = 48
MIN_SIMILARITY = 0.70     # centred cosine between centroids; the confident-merge line is 0.80
MAX_PAIRS_PER_RUN = 20
_LIFE_RANK = {"LEAD": 0, "CORROBORATED": 1, "CONFIRMED": 2}


def _pairs(session, cutoff) -> List[Tuple[int, int, float]]:
    from db.models import StoryThread, ThreadPairVerdict
    threads = [t for t in session.exec(select(StoryThread).where(StoryThread.last_update_at >= cutoff)).all()
               if t.centroid]
    vecs = {}
    for t in threads:
        try:
            vecs[t.id] = sm._center(json.loads(t.centroid))
        except Exception:
            pass
    judged = {(r.thread_a, r.thread_b) for r in session.exec(select(ThreadPairVerdict)).all()}
    out = []
    ids = sorted(vecs)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if (a, b) in judged:
                continue
            s = sm.cosine(vecs[a], vecs[b])
            if s >= MIN_SIMILARITY:
                out.append((a, b, s))
    out.sort(key=lambda x: -x[2])
    return out[:MAX_PAIRS_PER_RUN]


def _merge(session, keep, drop) -> None:
    from db.models import RawArticle, RadarAlert, StoryThread, ThreadTarget
    members_drop = session.exec(select(RawArticle).where(RawArticle.thread_id == drop.id)).all()
    for m in members_drop:
        m.thread_id = keep.id
        m.processed = False          # re-fuse: the merge is a material increment
        session.add(m)
    have = {r.tracker_id for r in session.exec(select(ThreadTarget).where(ThreadTarget.thread_id == keep.id)).all()}
    for r in session.exec(select(ThreadTarget).where(ThreadTarget.thread_id == drop.id)).all():
        if r.tracker_id in have:
            session.delete(r)
        else:
            r.thread_id = keep.id; session.add(r)
    for al in session.exec(select(RadarAlert).where(RadarAlert.thread_id == drop.id)).all():
        al.thread_id = keep.id; session.add(al)
    # counts and centroid from the union (flush first: the moved members are
    # already keep's in this session, so query once rather than add them twice)
    session.flush()
    members = session.exec(select(RawArticle.url, RawArticle.title).where(RawArticle.thread_id == keep.id)).all()
    keep.member_count = len(members)
    keep.distinct_source_count = len({real_publisher(u, t) for (u, t) in members})
    try:
        ca, cb = json.loads(keep.centroid), json.loads(drop.centroid)
        na, nb = max(keep.member_count - len(members_drop), 1), max(drop.member_count, 1)
        keep.centroid = json.dumps([(x * na + y * nb) / (na + nb) for x, y in zip(ca, cb)])
    except Exception:
        pass
    if _LIFE_RANK.get(drop.lifecycle, 0) > _LIFE_RANK.get(keep.lifecycle, 0):
        keep.lifecycle = drop.lifecycle
    if keep.storyline_id is None and drop.storyline_id is not None:
        keep.storyline_id = drop.storyline_id
    if not keep.summary and drop.summary:
        keep.summary, keep.summarized_at = drop.summary, drop.summarized_at
        keep.validity_category, keep.importance_score = drop.validity_category, drop.importance_score
        keep.fused_source_count, keep.fused_lifecycle = drop.fused_source_count, drop.fused_lifecycle
    keep.first_seen_at = min(keep.first_seen_at, drop.first_seen_at)
    keep.last_update_at = max(keep.last_update_at, drop.last_update_at)
    keep.is_resonant = keep.is_resonant or drop.is_resonant
    session.add(keep)
    session.delete(drop)


def run_merge_pass(arbiter=None, window_hours: int = WINDOW_HOURS) -> dict:
    from db.database import get_session
    from db.models import StoryThread, ThreadPairVerdict, ArticleEmbedding
    from services.semantic_ingest import _llm_relation
    if arbiter is None:
        try:
            from services.llm_provider import get_provider
            p = get_provider()
            arbiter = p if getattr(p, "supports_generation", False) else None
        except Exception:
            arbiter = None
    if arbiter is None:
        return {"pairs": 0, "merged": 0, "reason": "no arbiter"}
    merged = asked = 0
    with get_session() as session:
        # centred space, same correction as ingest
        stored = []
        for row in session.exec(select(ArticleEmbedding.vector)).all():
            try:
                stored.append(json.loads(row if isinstance(row, str) else row[0]))
            except Exception:
                pass
        if stored:
            dim = len(stored[0]); same = [v for v in stored if len(v) == dim]
            sm.set_corpus_mean([sum(v[i] for v in same) / len(same) for i in range(dim)])
        cutoff = datetime.utcnow() - timedelta(hours=window_hours)
        for a, b, sim in _pairs(session, cutoff):
            ta, tb = session.get(StoryThread, a), session.get(StoryThread, b)
            if ta is None or tb is None:
                continue
            rel = _llm_relation(arbiter, ta.title or "", tb.title or "")
            asked += 1
            if rel is None:
                continue                      # judge unavailable: ask again next time
            if rel == "event":
                keep, drop = (ta, tb) if (ta.first_seen_at or datetime.max) <= (tb.first_seen_at or datetime.max) else (tb, ta)
                logger.info(f"Merge (sim={sim:.2f}): thread {drop.id} '{(drop.title or '')[:40]}' → {keep.id} '{(keep.title or '')[:40]}'")
                _merge(session, keep, drop)
                session.add(ThreadPairVerdict(thread_a=a, thread_b=b, verdict="merged", similarity=sim))
                merged += 1
            else:
                session.add(ThreadPairVerdict(thread_a=a, thread_b=b, verdict=rel, similarity=sim))
            session.commit()
    if asked:
        logger.info(f"Merge pass: {asked} pairs judged, {merged} merged")
    return {"pairs": asked, "merged": merged}
