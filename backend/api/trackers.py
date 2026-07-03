from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from typing import List
from db.database import get_session
from db.models import Tracker, TaskRequest
from backend.schemas import TrackerCreate, TrackerResponse, AdHocRouteTestRequest, RouteTestResponse, PipelineRunResponse

router = APIRouter(prefix="/trackers", tags=["trackers"])

@router.get("/", response_model=List[TrackerResponse])
def get_trackers(session: Session = Depends(get_session)):
    return session.exec(select(Tracker)).all()

@router.post("/", response_model=TrackerResponse)
def create_tracker(tracker_in: TrackerCreate, session: Session = Depends(get_session)):
    from services.intent_normalizer import generate_tracker_normalized_intent
    data = tracker_in.model_dump()
    data["normalized_intent"] = generate_tracker_normalized_intent(
        name=data["name"],
        source_intent=data["source_intent"],
        target=data["target"],
        fetch_policy=data["fetch_policy"]
    )
    db_tracker = Tracker(**data)
    session.add(db_tracker)
    session.commit()
    session.refresh(db_tracker)
    return db_tracker

@router.delete("/{tracker_id}")
def delete_tracker(tracker_id: int, session: Session = Depends(get_session)):
    tracker = session.get(Tracker, tracker_id)
    if not tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")
    session.delete(tracker)
    session.commit()
    return {"message": f"Tracker {tracker_id} deleted successfully"}

@router.post("/{tracker_id}/toggle", response_model=TrackerResponse)
def toggle_tracker(tracker_id: int, session: Session = Depends(get_session)):
    tracker = session.get(Tracker, tracker_id)
    if not tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")
    tracker.is_active = not tracker.is_active
    session.add(tracker)
    session.commit()
    session.refresh(tracker)
    return tracker

@router.post("/{tracker_id}/run")
def trigger_tracker_scrape(tracker_id: int, session: Session = Depends(get_session)):
    tracker = session.get(Tracker, tracker_id)
    if not tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")

    from services.app_mode import is_pure_rss_mode
    
    # Create TaskRequest for Scrape
    scrape_task = TaskRequest(
        job_type="SCRAPE",
        target_type="TRACKER",
        target_id=str(tracker_id),
        status="PENDING"
    )
    session.add(scrape_task)

    if not is_pure_rss_mode():
        # Create TaskRequest for Process
        process_task = TaskRequest(
            job_type="PROCESS",
            target_type="TRACKER",
            target_id=str(tracker_id),
            status="PENDING"
        )
        session.add(process_task)

    session.commit()
    
    if is_pure_rss_mode():
        return {"message": "Scrape task queued successfully. AI processing skipped in pure RSS mode."}
    return {"message": "Scrape and AI process tasks queued successfully"}

@router.put("/{tracker_id}", response_model=TrackerResponse)
def update_tracker(tracker_id: int, tracker_in: TrackerCreate, session: Session = Depends(get_session)):
    tracker = session.get(Tracker, tracker_id)
    if not tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")
    
    from services.intent_normalizer import generate_tracker_normalized_intent
    data = tracker_in.model_dump()
    data["normalized_intent"] = generate_tracker_normalized_intent(
        name=data["name"],
        source_intent=data["source_intent"],
        target=data["target"],
        fetch_policy=data["fetch_policy"]
    )
    
    # Update fields
    for key, val in data.items():
        setattr(tracker, key, val)
        
    session.add(tracker)
    session.commit()
    session.refresh(tracker)
    return tracker

@router.post("/test-route", response_model=RouteTestResponse)
def test_ad_hoc_route(req: AdHocRouteTestRequest, session: Session = Depends(get_session)):
    from services.scraper_service import run_route_test
    try:
        return run_route_test(
            target=req.target,
            source_intent=req.source_intent,
            fetch_policy=req.fetch_policy,
            auth_profile_id=req.auth_profile_id,
            session=session
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{tracker_id}/test-route", response_model=RouteTestResponse)
def test_existing_tracker_route(tracker_id: int, session: Session = Depends(get_session)):
    tracker = session.get(Tracker, tracker_id)
    if not tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")
    
    from services.scraper_service import run_route_test
    try:
        return run_route_test(
            target=tracker.target,
            source_intent=tracker.source_intent,
            fetch_policy=tracker.fetch_policy,
            auth_profile_id=tracker.auth_profile_id,
            session=session
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/test-resolve-intent", response_model=RouteTestResponse)
def test_resolve_intent(req: AdHocRouteTestRequest, session: Session = Depends(get_session)):
    from services.scraper_service import run_route_test
    try:
        return run_route_test(
            target=req.target,
            source_intent=req.source_intent,
            fetch_policy=req.fetch_policy,
            auth_profile_id=req.auth_profile_id,
            session=session
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{tracker_id}/run-trace", response_model=PipelineRunResponse)
def run_tracker_trace(tracker_id: int, session: Session = Depends(get_session)):
    from db.models import PipelineRun, PipelineEvent
    tracker = session.get(Tracker, tracker_id)
    if not tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")
        
    from services.scraper_service import scrape_single_tracker
    try:
        # Run scraper synchronously
        scrape_single_tracker(tracker_id)
        
        # Get the latest run for this tracker
        run = session.exec(
            select(PipelineRun)
            .where(PipelineRun.tracker_id == tracker_id)
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

@router.get("/{tracker_id}/traces", response_model=List[PipelineRunResponse])
def get_tracker_traces(tracker_id: int, limit: int = 20, session: Session = Depends(get_session)):
    from db.models import PipelineRun, PipelineEvent
    runs = session.exec(
        select(PipelineRun)
        .where(PipelineRun.tracker_id == tracker_id)
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
def export_tracker_trace(run_id: int, session: Session = Depends(get_session)):
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
