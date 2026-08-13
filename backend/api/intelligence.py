from fastapi import APIRouter, Depends
from sqlmodel import Session, select, func
from typing import List
import json
from db.database import get_session, get_api_session
from db.models import Tracker, RawArticle, IntelReport, TrendAlert, Subscription, TaskRequest
from backend.schemas import DashboardStats, IntelReportResponse, TrendAlertResponse, TrendAlertSource, RawArticleResponse

router = APIRouter(prefix="/intelligence", tags=["intelligence"])

def clean_summary_and_title(llm_summary: str, default_title: str):
    if llm_summary and llm_summary.startswith("[TITLE: "):
        parts = llm_summary.split("]\n\n", 1)
        if len(parts) == 2:
            title = parts[0][8:]
            clean_summary = parts[1]
            return clean_summary, title
    # Clean up extremely long default/scraped titles (e.g. social media wall-of-text posts)
    # Truncate to max 80 characters for a clean card header
    cleaned_default_title = default_title
    if len(cleaned_default_title) > 80:
        cleaned_default_title = cleaned_default_title[:77] + "..."
    return llm_summary, cleaned_default_title

def make_alert_response(a: TrendAlert, session: Session) -> TrendAlertResponse:
    # P2.1: related_article_ids now holds StoryThread ids (trends scan threads).
    from db.models import StoryThread
    rel_ids = [int(x.strip()) for x in a.related_article_ids.split(",") if x.strip()]
    sources_list = []
    if rel_ids:
        threads_db = session.exec(select(StoryThread).where(StoryThread.id.in_(rel_ids))).all()
        for th in threads_db:
            clean_summary, title = clean_summary_and_title(th.summary or "", th.title or "Untitled")

            desc = None
            if clean_summary:
                summary_lines = [line.strip() for line in clean_summary.split("\n") if line.strip()]
                if summary_lines:
                    desc = summary_lines[0]
                    if len(desc) > 200:
                        desc = desc[:197] + "..."
            sources_list.append(TrendAlertSource(title=title, url=th.source_url or "", description=desc))
    return TrendAlertResponse(
        id=a.id,
        entity_name=a.entity_name,
        alert_summary=a.alert_summary,
        related_article_ids=rel_ids,
        created_at=a.created_at,
        sources=sources_list
    )

@router.get("/stats", response_model=DashboardStats)
def get_dashboard_stats(session: Session = Depends(get_api_session)):
    pending_count = session.exec(select(func.count()).where(RawArticle.processed == False)).one()
    active_trackers = session.exec(select(func.count()).where(Tracker.is_active == True)).one()
    active_monitors = session.exec(select(func.count()).where(Subscription.is_active == True)).one()
    
    alerts = session.exec(select(TrendAlert).order_by(TrendAlert.created_at.desc()).limit(3)).all()
    
    alert_responses = [make_alert_response(a, session) for a in alerts]
        
    return DashboardStats(
        pending_count=pending_count,
        active_trackers_count=active_trackers,
        active_monitors_count=active_monitors,
        latest_alerts=alert_responses
    )

@router.get("/feed", response_model=List[IntelReportResponse])
def get_intelligence_feed(limit: int = 30, session: Session = Depends(get_api_session)):
    # P2.1: the feed is built from StoryThreads now — ONE card per event, with the
    # summary that lives on the thread — not from IntelReport blind batches. The
    # response shape is unchanged, so the frontend is untouched.
    from db.models import StoryThread
    threads = session.exec(
        select(StoryThread)
        .where(StoryThread.validity_category.in_(["[VALID_NEWS]", "VALID_NEWS"]))
        .where(StoryThread.summary.is_not(None))
        .order_by(StoryThread.summarized_at.desc())
        .limit(limit)
    ).all()

    feed = []
    for th in threads:
        tracker_name = "Unknown"
        if th.tracker_id:
            tracker = session.get(Tracker, th.tracker_id)
            if tracker:
                tracker_name = tracker.name

        try:
            entities = json.loads(th.key_entities or "[]")
            if not isinstance(entities, list):
                entities = []
        except Exception:
            entities = []

        clean_summary, clean_title = clean_summary_and_title(th.summary, th.title or "Untitled")
        feed.append(IntelReportResponse(
            id=th.id,
            raw_article_id=th.id,   # thread-based: no single lead article
            source_url=th.source_url or "",
            title=clean_title,
            validity_category=th.validity_category,
            radar_section=th.radar_section,
            tracker_name=tracker_name,
            llm_summary=clean_summary,
            importance_score=th.importance_score,
            created_at=th.summarized_at or th.last_update_at,
            event_timestamp=th.event_timestamp,
            key_entities=entities
        ))
    return feed

@router.get("/alerts", response_model=List[TrendAlertResponse])
def get_all_alerts(session: Session = Depends(get_api_session)):
    alerts = session.exec(select(TrendAlert).order_by(TrendAlert.created_at.desc())).all()
    alert_responses = [make_alert_response(a, session) for a in alerts]
    return alert_responses

@router.get("/threads")
def get_story_threads(limit: int = 40, tracker_id: int = None, view: str = None,
                      session: Session = Depends(get_api_session)):
    """Story threads for the Radar view — the aggregator→radar payoff. Each
    thread carries its lifecycle (LEAD/CORROBORATED/CONFIRMED), resonance,
    distinct-source count, member articles (citations), and any alert reasons
    ('why am I being interrupted?'). Resonant + recently-updated first.

    `view` splits the single radar surface into its two P6 faces:
      - "refined": threads that EARNED a summary — the daily reading feed, where
        the card IS the fused summary (愿景: feed 卡片 = 线索上的一段摘要).
      - "leads":   clustered but unsummarised threads. The client stratifies
        these by the intake stamps below — a tip-off from an account the user
        NAMED is the fast channel the design values, while an aggregator
        singleton is presumed noise and collapses by default.
    Omitted → all threads (previous behaviour).
    """
    from db.models import StoryThread, RadarAlert
    q = select(StoryThread)
    if tracker_id is not None:
        q = q.where(StoryThread.tracker_id == tracker_id)
    if view == "refined":
        q = q.where(StoryThread.summary.is_not(None))
    elif view == "leads":
        q = q.where(StoryThread.summary.is_(None))
    threads = session.exec(
        q.order_by(StoryThread.is_resonant.desc(), StoryThread.last_update_at.desc()).limit(limit)
    ).all()
    if not threads:
        return []

    # Batch member + alert loads (avoid N+1 across the thread list). The same
    # pass computes the lead-stratification flags — over ALL members, not just
    # the 8 kept for display, or a 9-member thread could misclassify.
    thread_ids = [th.id for th in threads]
    members_by_thread = {tid: [] for tid in thread_ids}
    # from_account: any member arrived via a route the user created by NAMING an
    # account (stamped at intake — provenance is never re-derived from URLs).
    # aggregated_only: no member outside the keyword firehose; NULL tier counts
    # as aggregated, matching the fusion gate's treatment of legacy rows.
    flags_by_thread = {tid: {"from_account": False, "aggregated_only": True} for tid in thread_ids}
    for art in session.exec(
        select(RawArticle).where(RawArticle.thread_id.in_(thread_ids))
        .order_by(RawArticle.created_at.desc())
    ).all():
        bucket = members_by_thread.get(art.thread_id)
        if bucket is not None and len(bucket) < 8:
            bucket.append({"title": art.title, "url": art.url})
        f = flags_by_thread.get(art.thread_id)
        if f is not None:
            if getattr(art, "from_account", False):
                f["from_account"] = True
            if art.source_tier is not None and art.source_tier != "aggregated":
                f["aggregated_only"] = False
    reasons_by_thread = {tid: set() for tid in thread_ids}
    for al in session.exec(select(RadarAlert).where(RadarAlert.thread_id.in_(thread_ids))).all():
        reasons_by_thread[al.thread_id].add(al.reason)

    out = []
    for th in threads:
        # The stored summary is "[TITLE: …]\n\n<body>\n\n---\n**:material/… 摘要引用
        # 来源:** …" — a machine annex the old Dashboard card parsed into tabs.
        # The radar card lists sources from the members instead, so the annex
        # would render as raw markup; serve the body, and prefer the fused title.
        clean_sum, display_title = clean_summary_and_title(th.summary or "", th.title or "")
        if clean_sum:
            clean_sum = clean_sum.split("\n---\n", 1)[0].strip()
        out.append({
            "id": th.id,
            "tracker_id": th.tracker_id,
            "title": display_title or th.title,
            "lifecycle": th.lifecycle,
            "distinct_source_count": th.distinct_source_count,
            "member_count": th.member_count,
            "is_resonant": th.is_resonant,
            "resonance_score": round(th.resonance_score, 2),
            "last_update_at": th.last_update_at.isoformat() if th.last_update_at else None,
            "first_seen_at": th.first_seen_at.isoformat() if th.first_seen_at else None,
            "alert_reasons": sorted(reasons_by_thread[th.id]),
            "sources": members_by_thread[th.id],
            "summary": clean_sum or None,
            "importance_score": th.importance_score,
            "validity_category": th.validity_category,
            "from_account": flags_by_thread[th.id]["from_account"],
            "aggregated_only": flags_by_thread[th.id]["aggregated_only"],
        })
    return out

@router.get("/radar-stats")
def get_radar_stats_endpoint(since_hours: int = 168):
    """Noise-reduction / time-saved KPIs (盲区补全 #8): filtered N noise, merged
    M duplicates, tracked K events."""
    from services.radar_digest import get_radar_stats
    return get_radar_stats(since_hours)

@router.get("/catchup")
def get_catchup_endpoint(since: str = None, since_hours: int = 24):
    """'Since you last looked' increment digest (盲区补全 #7) — real thread
    increments, not a pile of unread items."""
    from services.radar_digest import get_catchup
    return get_catchup(since_iso=since, since_hours=since_hours)

@router.get("/radar-alerts")
def get_radar_alerts(limit: int = 50, unread_only: bool = False, session: Session = Depends(get_api_session)):
    """Thread-level alerts with their trigger reason (愿景 #2 — every alert can
    answer 'why am I being interrupted?')."""
    from db.models import RadarAlert
    q = select(RadarAlert)
    if unread_only:
        q = q.where(RadarAlert.is_read == False)
    return session.exec(q.order_by(RadarAlert.created_at.desc()).limit(limit)).all()

@router.get("/radar-alerts/undelivered")
def get_undelivered_radar_alerts(session: Session = Depends(get_api_session)):
    """Alerts not yet shown as OS notifications — the desktop delivery poll
    fetches these, shows a system notification, then marks them delivered."""
    from services.alert_engine import get_undelivered_alerts
    return get_undelivered_alerts()

@router.post("/radar-alerts/{alert_id}/delivered")
def mark_alert_delivered(alert_id: int, session: Session = Depends(get_api_session)):
    from db.models import RadarAlert
    a = session.get(RadarAlert, alert_id)
    if a:
        a.delivered = True
        session.add(a); session.commit()
    return {"ok": True}

@router.post("/radar-alerts/{alert_id}/read")
def mark_alert_read(alert_id: int, session: Session = Depends(get_api_session)):
    from db.models import RadarAlert
    a = session.get(RadarAlert, alert_id)
    if a:
        a.is_read = True
        session.add(a); session.commit()
    return {"ok": True}

@router.post("/scan-trends")
def trigger_trend_scan(session: Session = Depends(get_api_session)):
    from services.app_mode import is_pure_rss_mode
    if is_pure_rss_mode():
        return {"message": "Trend scan skipped in pure RSS mode"}

    scan_task = TaskRequest(
        job_type="TREND_SCAN",
        status="PENDING"
    )
    session.add(scan_task)
    session.commit()
    return {"message": "Trend scan task queued successfully"}

@router.get("/raw-feed", response_model=List[RawArticleResponse])
def get_raw_articles_feed(limit: int = 50, session: Session = Depends(get_api_session)):
    # Query raw articles order by created_at desc
    articles = session.exec(
        select(RawArticle)
        .order_by(RawArticle.created_at.desc())
        .limit(limit)
    ).all()
    
    feed = []
    for art in articles:
        tracker = session.get(Tracker, art.tracker_id)
        tracker_name = tracker.name if tracker else "Unknown"
        feed.append(RawArticleResponse(
            id=art.id,
            tracker_name=tracker_name,
            title=art.title,
            url=art.url,
            content=art.content,
            published_at=art.published_at,
            created_at=art.created_at,
            source_tier=art.source_tier,
        ))
    return feed
