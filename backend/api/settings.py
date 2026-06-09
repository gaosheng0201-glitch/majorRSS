from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlmodel import Session, select, func
from typing import List
import os
from pydantic import BaseModel
from db.database import get_session
from db.models import TokenUsage, PipelineStatus, InvestigationRecord
from backend.schemas import InvestigationCreate, InvestigationResponse
from llm.investigator import run_native_grounding, run_major_funnel

router = APIRouter(prefix="/settings", tags=["settings"])

def update_env_variable(key: str, value: str):
    env_path = ".env"
    lines = []
    found = False
    new_line = f"{key}='{value.strip()}'\n"
    
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        for idx, line in enumerate(lines):
            if line.strip().startswith(f"{key}="):
                lines[idx] = new_line
                found = True
                break
                
    if not found:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] = lines[-1] + "\n"
        lines.append(new_line)
        
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
        
    os.environ[key] = value.strip()

class ApiKeyUpdate(BaseModel):
    api_key: str

@router.post("/api-key")
def save_api_key(req: ApiKeyUpdate):
    update_env_variable("GEMINI_API_KEY", req.api_key)
    return {"status": "ok", "message": "API Key saved successfully"}

class SystemLanguageUpdate(BaseModel):
    language: str

@router.post("/system-language")
def save_system_language(req: SystemLanguageUpdate):
    update_env_variable("SYSTEM_LANGUAGE", req.language)
    return {"status": "ok", "message": "System language saved successfully"}

@router.get("/health")
def health_check():
    return {"status": "ok", "message": "FastAPI backend is running"}

@router.get("/token-usage")
def get_token_usage(session: Session = Depends(get_session)):
    usages = session.exec(select(TokenUsage).order_by(TokenUsage.created_at.desc())).all()
    # Summarize stats
    totals = {}
    daily_trend = {}
    for u in usages:
        if u.model_name not in totals:
            totals[u.model_name] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0}
        totals[u.model_name]["prompt_tokens"] += u.prompt_tokens
        totals[u.model_name]["completion_tokens"] += u.completion_tokens
        totals[u.model_name]["total_tokens"] += u.total_tokens
        totals[u.model_name]["calls"] += 1
        
        # Calculate daily trend on all records
        if u.created_at:
            # Format as M/D matching frontend
            date_str = u.created_at.strftime("%#m/%#d") if os.name == 'nt' else u.created_at.strftime("%-m/%-d")
            daily_trend[date_str] = daily_trend.get(date_str, 0) + u.total_tokens
            
    # Format daily_trend to a list of dicts for the frontend
    # Sort dates chronologically (most recent last, up to 10 days)
    def date_key(x):
        try:
            parts = [int(p) for p in x.split("/")]
            return parts[0], parts[1]
        except:
            return 0, 0
            
    sorted_dates = sorted(daily_trend.keys(), key=date_key)
    trend_list = [{"date": d, "tokens": daily_trend[d]} for d in sorted_dates[-10:]]
    
    return {
        "raw_usage": usages[:100],  # Limit raw usage list
        "summary": totals,
        "daily_trend": trend_list
    }

@router.get("/pipeline-logs")
def get_pipeline_logs(session: Session = Depends(get_session)):
    return session.exec(select(PipelineStatus).order_by(PipelineStatus.updated_at.desc()).limit(50)).all()

@router.get("/investigations", response_model=List[InvestigationResponse])
def get_investigations(session: Session = Depends(get_session)):
    return session.exec(select(InvestigationRecord).order_by(InvestigationRecord.created_at.desc())).all()

def run_investigation_task(query: str):
    # This runs in the background and saves directly to the DB
    try:
        native_res = run_native_grounding(query)
    except Exception as e:
        native_res = f"Error: {e}"
        
    try:
        # We pass a simple callback that prints to stdout since it runs in the background
        funnel_res = run_major_funnel(query, status_callback=lambda msg: print(f"[Investigator] {msg}"))
    except Exception as e:
        funnel_res = f"Error: {e}"
        
    # Save results to database
    with get_session() as session:
        record = InvestigationRecord(
            query=query,
            native_result=native_res,
            funnel_result=funnel_res
        )
        session.add(record)
        session.commit()

@router.post("/investigate")
def trigger_investigation(req: InvestigationCreate, background_tasks: BackgroundTasks):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
        
    background_tasks.add_task(run_investigation_task, req.query)
    return {"message": "Investigation task started in background"}

class AuthLoginRequest(BaseModel):
    platform: str

@router.get("/auth/status")
def get_auth_status():
    from scrapers.auth_helper import AUTH_PLATFORMS, check_cookie_health
    import os
    
    results = []
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for key, val in AUTH_PLATFORMS.items():
        cookie_file = val["cookie_file"]
        cookie_path = os.path.join(root_dir, cookie_file)
        has_cookie = os.path.exists(cookie_path)
        is_healthy = check_cookie_health(key, cookie_path) if has_cookie else False
        
        mtime = None
        if has_cookie:
            try:
                mtime = os.path.getmtime(cookie_path)
            except:
                pass
                
        results.append({
            "key": key,
            "name": val["name"],
            "has_cookie": has_cookie,
            "is_healthy": is_healthy,
            "mtime": mtime
        })
    return results

@router.post("/auth/login")
def do_auth_login(req: AuthLoginRequest):
    from scrapers.auth_helper import interactive_login
    success, msg = interactive_login(req.platform)
    return {"success": success, "message": msg}
