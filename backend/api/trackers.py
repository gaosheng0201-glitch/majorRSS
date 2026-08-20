from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from typing import List, Optional
from pydantic import BaseModel
from db.database import get_session, get_api_session
from db.models import Tracker, TaskRequest
from backend.schemas import TrackerCreate, TrackerResponse, AdHocRouteTestRequest, RouteTestResponse, PipelineRunResponse

router = APIRouter(prefix="/trackers", tags=["trackers"])

@router.get("/", response_model=List[TrackerResponse])
def get_trackers(session: Session = Depends(get_api_session)):
    return session.exec(select(Tracker)).all()


class PlanRequest(BaseModel):
    name: str
    intent_text: Optional[str] = ""
    use_llm: bool = True

@router.post("/plan")
def plan_watch_target(req: PlanRequest):
    """Propose a source portfolio for a watch target BEFORE creating it, so the
    user sees which sources will be watched and why (愿景: 选源可解释). The
    returned fetch_policy can be passed straight into tracker creation."""
    from services.portfolio_planner import plan_portfolio
    return plan_portfolio(req.name, req.intent_text or "", use_llm=req.use_llm)


class IntentPlanRequest(BaseModel):
    intent_text: str
    name: Optional[str] = ""
    use_llm: bool = True


@router.post("/plan-intent")
def plan_intent_endpoint(req: IntentPlanRequest):
    """P4.0: one natural-language sentence → structured IntentPlan (lane,
    language-aware entity profile, per-target official domains, collections,
    keywords, cadence). A PROPOSAL: the client shows it for editing and only a
    confirmed plan is stored — 可解释 > 自动化 (docs/p4_intent_design.md)."""
    from services.portfolio_planner import plan_intent
    return plan_intent(req.intent_text, req.name or "", use_llm=req.use_llm)

def _ensure_source_scope(name: str, target: str, fetch_policy_json: Optional[str]) -> Optional[str]:
    """Guarantee a target watches curated first-party sources, not just a keyword
    meta-search. If the client didn't attach a source_scope (chosen preset
    collections), plan one now so the resolver pulls real vendor RSS / changelogs
    / papers — otherwise a keyword target collapses into a Google-News-only feed.
    No-op (returns input) when a scope is already present or planning fails."""
    import json
    try:
        policy = json.loads(fetch_policy_json) if fetch_policy_json else {}
    except Exception:
        return fetch_policy_json
    if policy.get("source_scope"):
        return fetch_policy_json  # user/preview already chose sources

    # Build intent text from the target's keyword signals so the planner has
    # something richer than the bare name.
    intent = name or ""
    try:
        tgt = json.loads(target) if target else {}
        kws = [s.get("value", "") for s in (tgt.get("signals") or []) if s.get("type") == "keyword"]
        if kws:
            intent = f"{name} {' '.join(kws)}".strip()
    except Exception:
        pass

    try:
        from services.portfolio_planner import plan_portfolio
        plan = plan_portfolio(name or intent, intent, use_llm=True)
        scope = plan.get("source_scope") or plan.get("selected_collections") or []
        if scope:
            policy["source_scope"] = scope
            if plan.get("keep_keywords") and not policy.get("keep_keywords"):
                policy["keep_keywords"] = plan["keep_keywords"]
            # Persist the planner's MULTILINGUAL entity aliases. The planner has
            # always produced them ("expand its entities, include aliases and
            # other-language names") but they were dropped here, so the resolver
            # only ever queried the user's own wording — which meant a topic was
            # searched in exactly one language. 愿景 语言三原则 ①②: the entity
            # profile is language-independent, and search queries are generated
            # per SOURCE language, not per user language. source_resolver turns
            # these into one Google News route per edition.
            if plan.get("entities") and not policy.get("entities"):
                policy["entities"] = plan["entities"]
            return json.dumps(policy)
    except Exception:
        pass
    return fetch_policy_json


@router.post("/", response_model=TrackerResponse)
def create_tracker(tracker_in: TrackerCreate, session: Session = Depends(get_api_session)):
    from services.intent_normalizer import generate_tracker_normalized_intent
    data = tracker_in.model_dump()
    # R4: a Watch Target is planned once at creation — attach curated sources.
    data["fetch_policy"] = _ensure_source_scope(
        data.get("name", ""), data.get("target", ""), data.get("fetch_policy"))
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
def delete_tracker(tracker_id: int, session: Session = Depends(get_api_session)):
    tracker = session.get(Tracker, tracker_id)
    if not tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")
    session.delete(tracker)
    session.commit()
    return {"message": f"Tracker {tracker_id} deleted successfully"}

@router.post("/{tracker_id}/toggle", response_model=TrackerResponse)
def toggle_tracker(tracker_id: int, session: Session = Depends(get_api_session)):
    tracker = session.get(Tracker, tracker_id)
    if not tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")
    tracker.is_active = not tracker.is_active
    session.add(tracker)
    session.commit()
    session.refresh(tracker)
    return tracker

@router.post("/{tracker_id}/high-attention", response_model=TrackerResponse)
def toggle_high_attention(tracker_id: int, session: Session = Depends(get_api_session)):
    """Flip a target's high-attention flag. High-attention targets alert earlier
    (a CONFIRMED/CORROBORATED increment is pushed, not just shown) — 愿景 #2."""
    tracker = session.get(Tracker, tracker_id)
    if not tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")
    tracker.is_high_attention = not tracker.is_high_attention
    session.add(tracker)
    session.commit()
    session.refresh(tracker)
    return tracker

@router.post("/{tracker_id}/run")
def trigger_tracker_scrape(tracker_id: int, session: Session = Depends(get_api_session)):
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
def update_tracker(tracker_id: int, tracker_in: TrackerCreate, session: Session = Depends(get_api_session)):
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
def test_ad_hoc_route(req: AdHocRouteTestRequest, session: Session = Depends(get_api_session)):
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
def test_existing_tracker_route(tracker_id: int, session: Session = Depends(get_api_session)):
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
def test_resolve_intent(req: AdHocRouteTestRequest, session: Session = Depends(get_api_session)):
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
def run_tracker_trace(tracker_id: int, session: Session = Depends(get_api_session)):
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
def get_tracker_traces(tracker_id: int, limit: int = 20, session: Session = Depends(get_api_session)):
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
def export_tracker_trace(run_id: int, session: Session = Depends(get_api_session)):
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
