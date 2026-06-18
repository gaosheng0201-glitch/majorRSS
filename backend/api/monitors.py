from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlmodel import Session, select
from typing import List
from db.database import get_session
from db.models import Subscription, SubscriptionUpdate
from backend.schemas import SubscriptionCreate, SubscriptionResponse, SubscriptionUpdateResponse, AdHocDiffTestRequest, DiffTestResponse, PipelineRunResponse, PipelineEventResponse
from worker_subscription import run_subscription_job

router = APIRouter(prefix="/monitors", tags=["monitors"])

@router.get("/", response_model=List[SubscriptionResponse])
def get_subscriptions(session: Session = Depends(get_session)):
    return session.exec(select(Subscription)).all()

@router.post("/", response_model=SubscriptionResponse)
def create_subscription(sub_in: SubscriptionCreate, session: Session = Depends(get_session)):
    from services.intent_normalizer import generate_subscription_normalized_intent
    data = sub_in.model_dump()
    data["normalized_intent"] = generate_subscription_normalized_intent(
        target_url=data["target_url"],
        fetch_interval_minutes=data["fetch_interval_minutes"],
        diff_policy=data["diff_policy"]
    )
    db_sub = Subscription(**data)
    session.add(db_sub)
    session.commit()
    session.refresh(db_sub)
    return db_sub

@router.delete("/{sub_id}")
def delete_subscription(sub_id: int, session: Session = Depends(get_session)):
    sub = session.get(Subscription, sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    session.delete(sub)
    session.commit()
    return {"message": f"Subscription {sub_id} deleted successfully"}

@router.post("/{sub_id}/toggle", response_model=SubscriptionResponse)
def toggle_subscription(sub_id: int, session: Session = Depends(get_session)):
    sub = session.get(Subscription, sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    sub.is_active = not sub.is_active
    session.add(sub)
    session.commit()
    session.refresh(sub)
    return sub

@router.get("/updates", response_model=List[SubscriptionUpdateResponse])
def get_subscription_updates(limit: int = 50, session: Session = Depends(get_session)):
    updates = session.exec(
        select(SubscriptionUpdate)
        .order_by(SubscriptionUpdate.created_at.desc())
        .limit(limit)
    ).all()
    
    response = []
    for u in updates:
        sub = session.get(Subscription, u.subscription_id)
        sub_name = sub.name if sub else "Unknown"
        response.append(SubscriptionUpdateResponse(
            id=u.id,
            subscription_id=u.subscription_id,
            subscription_name=sub_name,
            diff_text=u.diff_text,
            is_read=u.is_read,
            llm_summary=u.llm_summary,
            created_at=u.created_at
        ))
    return response

@router.post("/updates/{update_id}/read")
def mark_update_as_read(update_id: int, session: Session = Depends(get_session)):
    update = session.get(SubscriptionUpdate, update_id)
    if not update:
        raise HTTPException(status_code=404, detail="Update not found")
    update.is_read = True
    session.add(update)
    session.commit()
    return {"message": "Update marked as read"}

@router.post("/run")
def force_run_subscription_check(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_subscription_job)
    return {"message": "Web page monitor change detection triggered"}

@router.post("/test-diff-route", response_model=DiffTestResponse)
def test_diff_route(req: AdHocDiffTestRequest):
    import json
    import hashlib
    from scrapers.tier3_agentic import AgenticScraper
    from worker_subscription import clean_html_for_diff
    
    policy = {}
    if req.diff_policy:
        try:
            policy = json.loads(req.diff_policy)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON in diff_policy: {e}")
            
    js_rendering = policy.get("js_rendering", False)
    extract_sel = policy.get("extract_selector")
    ignore_sel = policy.get("ignore_selector")
    
    from scrapers.url_normalizer import is_rss_url
    if is_rss_url(req.target_url):
        import feedparser
        import requests
        try:
            headers = {'User-Agent': 'Mozilla/5.0 MajorRSS/1.0'}
            res = requests.get(req.target_url, headers=headers, timeout=15)
            feed = feedparser.parse(res.content)
            items = []
            for entry in feed.entries[:5]:
                title = entry.get('title', '')
                link = entry.get('link', '')
                items.append(f"TEXT: {title}")
                if link:
                    items.append(f"LINK: {title} ({link})")
            clean_text = "\n".join(items)
            if not clean_text.strip():
                clean_text = "TEXT: No items found in feed."
                
            text_hash = hashlib.sha256(clean_text.encode('utf-8')).hexdigest()
            return DiffTestResponse(
                ok=True,
                extracted_text_length=len(clean_text),
                sample_text=clean_text[:500],
                ignored_nodes_count=0,
                snapshot_hash=text_hash
            )
        except Exception as e:
            return DiffTestResponse(
                ok=False,
                extracted_text_length=0,
                sample_text="",
                ignored_nodes_count=0,
                snapshot_hash="",
                error_message=str(e)
            )
            
    try:
        html_content = ""
        if js_rendering:
            scraper = AgenticScraper(req.target_url)
            html_content = scraper.fetch_text_snapshot(return_html=True)
        else:
            import requests
            headers = {'User-Agent': 'Mozilla/5.0 MajorRSS/1.0'}
            res = requests.get(req.target_url, headers=headers, timeout=15)
            html_content = res.text
            
        if not html_content:
            return DiffTestResponse(
                ok=False,
                extracted_text_length=0,
                sample_text="",
                ignored_nodes_count=0,
                snapshot_hash="",
                error_message="Failed to retrieve HTML content."
            )
            
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, 'html.parser')
        ignored_count = 0
        if ignore_sel:
            try:
                ignored_count = len(soup.select(ignore_sel))
            except:
                pass
            
        clean_text = clean_html_for_diff(html_content, extract_selector=extract_sel, ignore_selector=ignore_sel)
        if not clean_text.strip():
            return DiffTestResponse(
                ok=False,
                extracted_text_length=0,
                sample_text="",
                ignored_nodes_count=ignored_count,
                snapshot_hash="",
                error_message="Extracted text is empty. Try refining your extract selector."
            )
            
        text_hash = hashlib.sha256(clean_text.encode('utf-8')).hexdigest()
        return DiffTestResponse(
            ok=True,
            extracted_text_length=len(clean_text),
            sample_text=clean_text[:500],
            ignored_nodes_count=ignored_count,
            snapshot_hash=text_hash
        )
    except Exception as e:
        return DiffTestResponse(
            ok=False,
            extracted_text_length=0,
            sample_text="",
            ignored_nodes_count=0,
            snapshot_hash="",
            error_message=str(e)
        )

@router.post("/test-diff-route-trace", response_model=PipelineRunResponse)
def test_diff_route_trace(req: AdHocDiffTestRequest):
    import time
    import hashlib
    import json
    from datetime import datetime, timezone
    from scrapers.tier3_agentic import AgenticScraper
    from worker_subscription import clean_html_for_diff, desensitize_url
    from backend.schemas import PipelineRunResponse, PipelineEventResponse
    
    # We build the mock pipeline run response
    start_time = datetime.now(timezone.utc).replace(tzinfo=None)
    run_resp = PipelineRunResponse(
        id=0,
        status="RUNNING",
        started_at=start_time,
        total_routes=1,
        total_items=0,
        accepted_items=0,
        cost_flag_browser=False,
        cost_flag_llm=False
    )
    
    events = []
    step_counter = 1
    
    policy = {}
    if req.diff_policy:
        try:
            policy = json.loads(req.diff_policy)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON in diff_policy: {e}")
            
    js_rendering = policy.get("js_rendering", False)
    extract_sel = policy.get("extract_selector")
    ignore_sel = policy.get("ignore_selector")
    
    # RESOLVE Event
    from scrapers.url_normalizer import is_rss_url
    is_rss = is_rss_url(req.target_url)
    strategy_desc = "RSS feed parsing" if is_rss else "Webpage monitoring"
    events.append(PipelineEventResponse(
        id=0,
        run_id=0,
        step_index=step_counter,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        stage="RESOLVE",
        status="SUCCESS",
        output_summary=f"Resolved target strategy: {strategy_desc}",
        duration_ms=0
    ))
    step_counter += 1
    
    fetch_start = time.time()
    html_content = ""
    clean_text = ""
    cost_browser = False
    
    try:
        if is_rss:
            import feedparser
            import requests
            headers = {'User-Agent': 'Mozilla/5.0 MajorRSS/1.0'}
            res = requests.get(req.target_url, headers=headers, timeout=15)
            feed = feedparser.parse(res.content)
            items = []
            for entry in feed.entries[:5]:
                title = entry.get('title', '')
                link = entry.get('link', '')
                items.append(f"TEXT: {title}")
                if link:
                    items.append(f"LINK: {title} ({link})")
            clean_text = "\n".join(items)
            if not clean_text.strip():
                clean_text = "TEXT: No items found in feed."
                
            fetch_duration = int((time.time() - fetch_start) * 1000)
            events.append(PipelineEventResponse(
                id=0,
                run_id=0,
                step_index=step_counter,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                stage="FETCH",
                input_data=desensitize_url(req.target_url),
                output_summary=f"Parsed RSS feed. Extracted {len(items)} items",
                status="SUCCESS",
                duration_ms=fetch_duration
            ))
            step_counter += 1
        else:
            if js_rendering:
                cost_browser = True
                scraper = AgenticScraper(req.target_url)
                html_content = scraper.fetch_text_snapshot(return_html=True)
            else:
                import requests
                headers = {'User-Agent': 'Mozilla/5.0 MajorRSS/1.0'}
                res = requests.get(req.target_url, headers=headers, timeout=15)
                html_content = res.text
                
            if not html_content:
                raise Exception("Failed to fetch HTML content (returned empty)")
                
            fetch_duration = int((time.time() - fetch_start) * 1000)
            events.append(PipelineEventResponse(
                id=0,
                run_id=0,
                step_index=step_counter,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                stage="FETCH",
                adapter="AgenticAdapter" if js_rendering else "StaticAdapter",
                input_data=desensitize_url(req.target_url),
                output_summary=f"Fetched HTML (length: {len(html_content)} bytes)",
                status="SUCCESS",
                duration_ms=fetch_duration
            ))
            step_counter += 1
            
            # CLEAN Event
            clean_start = time.time()
            clean_text = clean_html_for_diff(html_content, extract_selector=extract_sel, ignore_selector=ignore_sel)
            clean_duration = int((time.time() - clean_start) * 1000)
            
            if not clean_text.strip():
                raise Exception("Extracted text is empty after filtering")
                
            events.append(PipelineEventResponse(
                id=0,
                run_id=0,
                step_index=step_counter,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                stage="CLEAN",
                output_summary=f"Cleaned HTML. Text length: {len(clean_text)} characters",
                status="SUCCESS",
                duration_ms=clean_duration
            ))
            step_counter += 1
            
        # DIFF Event (Mock)
        diff_duration = 0
        events.append(PipelineEventResponse(
            id=0,
            run_id=0,
            step_index=step_counter,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            stage="DIFF",
            output_summary="Diff completed (Dry run). Sample text snippet size: " + str(min(100, len(clean_text))) + " chars",
            status="SUCCESS",
            duration_ms=diff_duration
        ))
        
        run_resp.status = "SUCCESS"
        run_resp.total_items = 1
        
    except Exception as e:
        run_resp.status = "FAILED"
        run_resp.error_summary = str(e)
        events.append(PipelineEventResponse(
            id=0,
            run_id=0,
            step_index=step_counter,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            stage="FETCH" if not html_content else "CLEAN",
            status="FAILED",
            error=str(e)[:100],
            duration_ms=int((time.time() - fetch_start) * 1000)
        ))
        
    run_resp.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
    run_resp.cost_flag_browser = cost_browser
    run_resp.events = events
    return run_resp

@router.post("/{sub_id}/run-trace", response_model=PipelineRunResponse)
def run_monitor_trace(sub_id: int, session: Session = Depends(get_session)):
    from db.models import PipelineRun, PipelineEvent
    from backend.schemas import PipelineRunResponse
    sub = session.get(Subscription, sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
        
    from worker_subscription import process_subscription
    from datetime import datetime, timezone
    try:
        now = datetime.now(timezone.utc)
        process_subscription(session, sub, now)
        
        # Get the latest run for this subscription
        run = session.exec(
            select(PipelineRun)
            .where(PipelineRun.subscription_id == sub_id)
            .order_by(PipelineRun.started_at.desc())
        ).first()
        
        if not run:
            raise HTTPException(status_code=500, detail="Pipeline run failed to create trace")
            
        events = session.exec(
            select(PipelineEvent)
            .where(PipelineEvent.run_id == run.id)
            .order_by(PipelineEvent.step_index.asc())
        ).all()
        
        run_dict = run.model_dump()
        run_dict["events"] = events
        return PipelineRunResponse(**run_dict)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{sub_id}/traces", response_model=List[PipelineRunResponse])
def get_monitor_traces(sub_id: int, limit: int = 20, session: Session = Depends(get_session)):
    from db.models import PipelineRun, PipelineEvent
    from backend.schemas import PipelineRunResponse
    runs = session.exec(
        select(PipelineRun)
        .where(PipelineRun.subscription_id == sub_id)
        .order_by(PipelineRun.started_at.desc())
        .limit(limit)
    ).all()
    
    results = []
    for r in runs:
        events = session.exec(
            select(PipelineEvent)
            .where(PipelineEvent.run_id == r.id)
            .order_by(PipelineEvent.step_index.asc())
        ).all()
        r_dict = r.model_dump()
        r_dict["events"] = events
        results.append(PipelineRunResponse(**r_dict))
    return results

@router.get("/traces/{run_id}/export")
def export_monitor_trace(run_id: int, session: Session = Depends(get_session)):
    from db.models import PipelineRun, PipelineEvent
    from datetime import datetime, timezone
    run = session.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Trace run not found")
        
    events = session.exec(
        select(PipelineEvent)
        .where(PipelineEvent.run_id == run_id)
        .order_by(PipelineEvent.step_index.asc())
    ).all()
    
    export_data = {
        "export_metadata": {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "privacy_standard": "desensitized_strict_v1"
        },
        "pipeline_run": run.model_dump(),
        "events": [ev.model_dump() for ev in events]
    }
    return export_data
