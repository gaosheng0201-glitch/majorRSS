"""目标即查询 — targets are queries over a global pool, not containers.

For three weeks every cross-target defect was the same defect in a new coat:
content was OWNED by whichever target's route fetched it, and ownership leaked
into clustering, visibility, relevance gating and finally the summariser's
point of view ("unrelated to the monitored target OpenAI" — about a DeepMind
post that gemini also watched). Each fix added a compensating mechanism:
also_tracker_ids, the tracker_ids lens, owner-aware passes, a lens briefing.

This module replaces them with one relation. Articles and threads are global
and ownerless. "Does this thread concern target X?" is a separate, symmetric
question with one answer stored in ThreadTarget:

  source='match'  the deterministic matcher says so (entities / the target's
                  own domains / ignore-veto) — evaluated against EVERY target,
                  no special case for whoever fetched it;
  source='route'  an AGGREGATED item exists only because it passed the
                  discovering target's keyword route and keep_keywords, so the
                  search engine already matched it to that target;
  llm_verdict     the summariser's separate judgement of involvement (None =
                  not judged; False = "a name collision, not this target") —
                  it never removes a row, it only lets the UI fold it.

RawArticle.tracker_id survives as "discovered via" (a diagnostic and the
context for intake filters); nothing reads it as ownership.
"""
from typing import Dict, Iterable, List, Optional, Set

from sqlmodel import select

from services import attribution

_BODY_CAP = 20000


def load_matchers(session=None):
    return attribution.load_profiles(session)


def targets_for_article(article, matchers) -> Dict[int, str]:
    """{tracker_id: source} for one article — symmetric over all targets."""
    out: Dict[int, str] = {}
    for tid in attribution.relevant_tracker_ids(
            article.title or "", (article.content or "")[:_BODY_CAP], article.url or "", matchers):
        out[tid] = "match"
    if (article.source_tier or "aggregated") == "aggregated" and article.tracker_id is not None:
        out.setdefault(article.tracker_id, "route")
    return out


def link(session, thread_id: int, targets: Dict[int, str]) -> int:
    """Upsert relation rows for a thread. Caller commits."""
    from db.models import ThreadTarget
    if not targets:
        return 0
    have = set(session.exec(select(ThreadTarget.tracker_id)
                            .where(ThreadTarget.thread_id == thread_id)).all())
    added = 0
    for tid, source in targets.items():
        if tid in have:
            continue
        session.add(ThreadTarget(thread_id=thread_id, tracker_id=tid, source=source))
        added += 1
    return added


def rows_for(session, thread_ids: Iterable[int]) -> Dict[int, list]:
    from db.models import ThreadTarget
    ids = list(thread_ids)
    out: Dict[int, list] = {i: [] for i in ids}
    if not ids:
        return out
    for r in session.exec(select(ThreadTarget).where(ThreadTarget.thread_id.in_(ids))).all():
        out.setdefault(r.thread_id, []).append(r)
    return out


def related_ids(session, thread_id: int, include_rejected: bool = False) -> Set[int]:
    rows = rows_for(session, [thread_id])[thread_id]
    return {r.tracker_id for r in rows if include_rejected or r.llm_verdict is not False}


def primary_target_id(rows: list, fallback: Optional[int] = None) -> Optional[int]:
    """A stable single target for the few places that need exactly one (section,
    alert row, publish topic): the lowest-id target the model did not reject."""
    ok = sorted(r.tracker_id for r in rows if r.llm_verdict is not False)
    return ok[0] if ok else fallback


def record_verdicts(session, thread_id: int, concerned_ids: Set[int], judged_ids: Set[int]) -> None:
    """Store the summariser's involvement judgement for the targets it was shown.
    A target it names that the matcher missed is ADDED (source='llm'); a target
    it was shown and did not name is marked False — folded in the UI, never
    deleted, because the model is sometimes the one that is wrong."""
    from db.models import ThreadTarget
    rows = {r.tracker_id: r for r in rows_for(session, [thread_id])[thread_id]}
    for tid in concerned_ids:
        r = rows.get(tid)
        if r is None:
            session.add(ThreadTarget(thread_id=thread_id, tracker_id=tid, source="llm", llm_verdict=True))
        else:
            r.llm_verdict = True
            session.add(r)
    for tid in judged_ids - concerned_ids:
        r = rows.get(tid)
        if r is not None:
            r.llm_verdict = False
            session.add(r)


def rebuild(session, thread_ids: Iterable[int], matchers=None) -> int:
    """Recompute relations from members (adds only; verdicts untouched)."""
    from db.models import RawArticle
    matchers = matchers if matchers is not None else load_matchers(session)
    added = 0
    for tid in thread_ids:
        targets: Dict[int, str] = {}
        for a in session.exec(select(RawArticle).where(RawArticle.thread_id == tid)).all():
            for k, v in targets_for_article(a, matchers).items():
                if targets.get(k) != "match":
                    targets[k] = v
        added += link(session, tid, targets)
    return added


def rebuild_recent(days: int = 30) -> dict:
    """Maintenance: after profiles change (new official domains, new targets),
    let the new knowledge reach recent threads. Deterministic, additive."""
    from datetime import datetime, timedelta
    from db.database import get_session
    from db.models import StoryThread
    with get_session() as session:
        cutoff = datetime.utcnow() - timedelta(days=days)
        ids = session.exec(select(StoryThread.id).where(StoryThread.last_update_at >= cutoff)).all()
        added = rebuild(session, ids)
        session.commit()
    return {"threads": len(ids), "relations_added": added}
