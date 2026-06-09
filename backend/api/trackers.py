from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from typing import List
from db.database import get_session
from db.models import Tracker, TaskRequest
from backend.schemas import TrackerCreate, TrackerResponse

router = APIRouter(prefix="/trackers", tags=["trackers"])

@router.get("/", response_model=List[TrackerResponse])
def get_trackers(session: Session = Depends(get_session)):
    return session.exec(select(Tracker)).all()

@router.post("/", response_model=TrackerResponse)
def create_tracker(tracker_in: TrackerCreate, session: Session = Depends(get_session)):
    db_tracker = Tracker(**tracker_in.model_dump())
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
    
    # Create TaskRequest for Scrape
    scrape_task = TaskRequest(
        job_type="SCRAPE",
        target_type="TRACKER",
        target_id=str(tracker_id),
        status="PENDING"
    )
    # Create TaskRequest for Process
    process_task = TaskRequest(
        job_type="PROCESS",
        target_type="TRACKER",
        target_id=str(tracker_id),
        status="PENDING"
    )
    session.add(scrape_task)
    session.add(process_task)
    session.commit()
    
    return {"message": "Scrape and AI process tasks queued successfully"}

@router.put("/{tracker_id}", response_model=TrackerResponse)
def update_tracker(tracker_id: int, tracker_in: TrackerCreate, session: Session = Depends(get_session)):
    tracker = session.get(Tracker, tracker_id)
    if not tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")
    
    # Update fields
    for key, val in tracker_in.model_dump().items():
        setattr(tracker, key, val)
        
    session.add(tracker)
    session.commit()
    session.refresh(tracker)
    return tracker
