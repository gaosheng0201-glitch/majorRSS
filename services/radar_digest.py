"""
Radar digest (R6 backend — 盲区补全 #7 追赶简报 + #8 省时间可视化).

Two views the dashboard consumes:
  - stats:   makes the KPI visible — "this week the radar filtered N noise,
             merged M duplicates, tracked K events." The product's promise is
             saved time; this is the proof, and also the demo material for the
             author's show.
  - catchup: after being away, "since you last looked, these threads had real
             increments" — the increment diff, not N unread items.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlmodel import select, func, or_

from services.log_service import get_logger

logger = get_logger("digest")


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_radar_stats(since_hours: int = 168) -> dict:
    """Time-saved / noise-reduction KPIs over a window (default 7 days)."""
    from db.database import get_session
    from db.models import RawArticle, ArticleEmbedding, StoryThread, RadarAlert

    since = _now() - timedelta(hours=since_hours)
    with get_session() as s:
        ingested = s.exec(select(func.count(RawArticle.id)).where(RawArticle.created_at >= since)).one() or 0
        gated = s.exec(select(func.count(RawArticle.id)).where(
            RawArticle.created_at >= since, RawArticle.relevance_gated == True)).one() or 0
        threads = s.exec(select(func.count(StoryThread.id)).where(StoryThread.first_seen_at >= since)).one() or 0
        # Duplicate/paraphrase reports merged into threads = members beyond the
        # first in each multi-member thread.
        multi = s.exec(select(StoryThread.member_count).where(
            StoryThread.first_seen_at >= since, StoryThread.member_count > 1)).all()
        merged = sum((m - 1) for m in multi)
        resonant = s.exec(select(func.count(StoryThread.id)).where(
            StoryThread.first_seen_at >= since, StoryThread.is_resonant == True)).one() or 0
        alerts = s.exec(select(func.count(RadarAlert.id)).where(RadarAlert.created_at >= since)).one() or 0
        # P2.1: "reports" = event summaries produced in the window (now on threads).
        reports = s.exec(select(func.count(StoryThread.id)).where(
            StoryThread.summarized_at >= since, StoryThread.summary.is_not(None))).one() or 0

    # "Items you didn't have to read": noise filtered + duplicates merged.
    noise_removed = int(gated) + int(merged)
    return {
        "window_hours": since_hours,
        "ingested": int(ingested),
        "noise_filtered": int(gated),
        "duplicates_merged": int(merged),
        "noise_removed_total": noise_removed,
        "events_tracked": int(threads),
        "resonant_events": int(resonant),
        "alerts": int(alerts),
        "reports": int(reports),
    }


def get_catchup(since_iso: Optional[str] = None, since_hours: int = 24) -> dict:
    """Threads that had a real increment since the user last looked. Returns the
    increment (new lifecycle / new sources), not a pile of unread items."""
    from db.database import get_session
    from db.models import StoryThread, RadarAlert

    if since_iso:
        try:
            since = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
            if since.tzinfo is not None:   # an offset is converted, not dropped
                since = since.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            since = _now() - timedelta(hours=since_hours)
    else:
        since = _now() - timedelta(hours=since_hours)

    with get_session() as s:
        threads = s.exec(
            select(StoryThread).where(StoryThread.last_update_at >= since)
            .order_by(StoryThread.resonance_score.desc(), StoryThread.distinct_source_count.desc())
        ).all()
        items = []
        for th in threads:
            alerts = s.exec(select(RadarAlert).where(RadarAlert.thread_id == th.id)).all()
            items.append({
                "thread_id": th.id,
                "tracker_id": th.tracker_id,
                "title": th.title,
                "lifecycle": th.lifecycle,
                "distinct_source_count": th.distinct_source_count,
                "is_resonant": th.is_resonant,
                "resonance_score": round(th.resonance_score, 2),
                "alert_reasons": [a.reason for a in alerts],
                "last_update_at": th.last_update_at.isoformat() if th.last_update_at else None,
            })

    # Headline: the human summary of "what you missed".
    resonant = [i for i in items if i["is_resonant"]]
    confirmed = [i for i in items if i["lifecycle"] == "CONFIRMED"]
    return {
        "since": since.isoformat(),
        "updated_threads": len(items),
        "resonant": len(resonant),
        "confirmed": len(confirmed),
        "threads": items,
    }


# ---- 醒来不漏: what you missed while away (2026-09-28) ----------------------
# The Mac slept 15:04–19:10 through the Sonnet 5.5 launch; the catch-up line
# said "N threads advanced" and nothing more, and "since you last looked" was
# the moment the page mounted — a tray app's page stays mounted for days. The
# desktop now tracks when you were actually looking and asks for this short
# list on return: alerts raised meanwhile, and NEW events that were confirmed
# or resonated, for your targets only. Keeping the machine awake is not an
# option we take (the user's device, the user's call); P8 is the always-on path.

_REASON_RANK = {"CONFIRMED_HIGH_ATTENTION": 0, "CORROBORATED_HIGH_ATTENTION": 1, "RESONANCE": 2}
AWAY_MAX_ITEMS = 8


def get_away_highlights(since_iso: str, limit: int = AWAY_MAX_ITEMS) -> dict:
    from db.database import get_session
    from db.models import RadarAlert, RawArticle, StoryThread, Tracker
    from services import thread_targets as tt

    since = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
    if since.tzinfo is not None:
        since = since.astimezone(timezone.utc).replace(tzinfo=None)

    with get_session() as s:
        reasons = {}
        for a in s.exec(select(RadarAlert).where(RadarAlert.created_at >= since)).all():
            reasons.setdefault(a.thread_id, []).append(a.reason)
        fresh = s.exec(select(StoryThread.id).where(
            StoryThread.first_seen_at >= since,
            or_(StoryThread.is_resonant == True, StoryThread.lifecycle == "CONFIRMED"),  # noqa: E712
        )).all()
        ids = set(reasons) | set(fresh)
        if not ids:
            return {"since": since.isoformat(), "count": 0, "highlights": []}
        threads = {t.id: t for t in s.exec(select(StoryThread).where(StoryThread.id.in_(list(ids)))).all()}
        rels = tt.rows_for(s, list(threads))
        names = {t.id: t.name for t in s.exec(select(Tracker)).all()}
        leads = dict(s.exec(select(RawArticle.thread_id, func.min(RawArticle.id))
                            .where(RawArticle.thread_id.in_(list(threads)))
                            .group_by(RawArticle.thread_id)).all())
        urls = dict(s.exec(select(RawArticle.id, RawArticle.url)
                           .where(RawArticle.id.in_(list(leads.values())))).all()) if leads else {}
        items = []
        for tid, th in threads.items():
            concerned = [r.tracker_id for r in rels.get(tid, []) if r.llm_verdict is not False]
            if not concerned:
                continue            # nobody's news is not news you missed
            rs = sorted(set(reasons.get(tid, [])), key=lambda r: _REASON_RANK.get(r, 9))
            items.append({
                "thread_id": tid,
                "title": th.title,
                "reasons": rs,
                "lifecycle": th.lifecycle,
                "is_resonant": bool(th.is_resonant),
                "distinct_source_count": th.distinct_source_count,
                "targets": sorted({names.get(i, "") for i in concerned} - {""}),
                "first_seen_at": th.first_seen_at.isoformat() if th.first_seen_at else None,
                "url": urls.get(leads.get(tid)),
                "_rank": (min((_REASON_RANK.get(r, 9) for r in rs), default=9),
                          0 if th.lifecycle == "CONFIRMED" else 1,
                          -(th.resonance_score or 0), -(th.distinct_source_count or 0)),
            })
    items.sort(key=lambda i: i["_rank"])
    for i in items:
        i.pop("_rank")
    return {"since": since.isoformat(), "count": len(items), "highlights": items[:limit]}
