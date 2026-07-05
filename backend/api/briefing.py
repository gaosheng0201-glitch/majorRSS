from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlmodel import Session, select
from typing import List
from db.database import get_session, get_api_session
from db.models import DailyBriefing
from backend.schemas import DailyBriefingResponse, DailyBriefingGenerateRequest
from llm.processor import generate_daily_briefing

router = APIRouter(prefix="/briefing", tags=["briefing"])

@router.get("/", response_model=List[DailyBriefingResponse])
def get_briefings(limit: int = 10, session: Session = Depends(get_api_session)):
    return session.exec(select(DailyBriefing).order_by(DailyBriefing.created_at.desc()).limit(limit)).all()

def generate_briefing_task(target_sections: List[str] = None):
    try:
        generate_daily_briefing(target_sections=target_sections)
    except Exception as e:
        print(f"Failed to generate briefing: {e}")

@router.post("/generate")
def trigger_briefing_generation(req: DailyBriefingGenerateRequest, background_tasks: BackgroundTasks):
    target_sections = None
    if req.section_name and req.section_name != "ALL":
        target_sections = [x.strip() for x in req.section_name.split(",") if x.strip()]
        
    background_tasks.add_task(generate_briefing_task, target_sections)
    return {"message": "Briefing generation queued in background"}
