from fastapi import APIRouter, Depends
from sqlmodel import Session, select, func
from typing import List
import json
from db.database import get_session
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
    rel_ids = [int(x.strip()) for x in a.related_article_ids.split(",") if x.strip()]
    sources_list = []
    if rel_ids:
        reports_db = session.exec(select(IntelReport).where(IntelReport.id.in_(rel_ids))).all()
        for r in reports_db:
            raw = session.get(RawArticle, r.raw_article_id)
            raw_title = raw.title if raw else "Untitled"
            
            clean_summary, title = clean_summary_and_title(r.llm_summary, raw_title)
            
            desc = None
            if clean_summary:
                summary_lines = [line.strip() for line in clean_summary.split("\n") if line.strip()]
                if summary_lines:
                    desc = summary_lines[0]
                    if len(desc) > 200:
                        desc = desc[:197] + "..."
            sources_list.append(TrendAlertSource(title=title, url=r.source_url, description=desc))
    return TrendAlertResponse(
        id=a.id,
        entity_name=a.entity_name,
        alert_summary=a.alert_summary,
        related_article_ids=rel_ids,
        created_at=a.created_at,
        sources=sources_list
    )

@router.get("/stats", response_model=DashboardStats)
def get_dashboard_stats(session: Session = Depends(get_session)):
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
def get_intelligence_feed(limit: int = 30, session: Session = Depends(get_session)):
    # Query reports and join raw article for the title
    reports = session.exec(
        select(IntelReport)
        .where(IntelReport.validity_category.in_(["[VALID_NEWS]", "VALID_NEWS"]))
        .order_by(IntelReport.created_at.desc())
        .limit(limit)
    ).all()
    
    feed = []
    for r in reports:
        raw = session.get(RawArticle, r.raw_article_id)
        title = raw.title if raw else "Untitled"
        tracker_name = "Unknown"
        if raw:
            tracker = session.get(Tracker, raw.tracker_id)
            if tracker:
                tracker_name = tracker.name
        
        try:
            entities = json.loads(r.key_entities)
            if not isinstance(entities, list):
                entities = []
        except Exception:
            entities = []
            
        clean_summary, clean_title = clean_summary_and_title(r.llm_summary, title)
        feed.append(IntelReportResponse(
            id=r.id,
            raw_article_id=r.raw_article_id,
            source_url=r.source_url,
            title=clean_title,
            validity_category=r.validity_category,
            radar_section=r.radar_section,
            tracker_name=tracker_name,
            llm_summary=clean_summary,
            importance_score=r.importance_score,
            created_at=r.created_at,
            event_timestamp=r.event_timestamp,
            key_entities=entities
        ))
    return feed

@router.get("/alerts", response_model=List[TrendAlertResponse])
def get_all_alerts(session: Session = Depends(get_session)):
    alerts = session.exec(select(TrendAlert).order_by(TrendAlert.created_at.desc())).all()
    alert_responses = [make_alert_response(a, session) for a in alerts]
    return alert_responses

@router.post("/scan-trends")
def trigger_trend_scan(session: Session = Depends(get_session)):
    scan_task = TaskRequest(
        job_type="TREND_SCAN",
        status="PENDING"
    )
    session.add(scan_task)
    session.commit()
    return {"message": "Trend scan task queued successfully"}

@router.get("/raw-feed", response_model=List[RawArticleResponse])
def get_raw_articles_feed(limit: int = 50, session: Session = Depends(get_session)):
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
            created_at=art.created_at
        ))
    return feed
