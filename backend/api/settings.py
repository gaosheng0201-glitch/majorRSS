from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlmodel import Session, select, func
from typing import List, Optional
import os
from pydantic import BaseModel
from db.database import get_session, get_api_session
from db.models import TokenUsage, PipelineStatus, InvestigationRecord
from backend.schemas import InvestigationCreate, InvestigationResponse
from llm.investigator import run_native_grounding, run_major_funnel

router = APIRouter(prefix="/settings", tags=["settings"])

def update_env_variable(key: str, value: str):
    from db.config import get_env_path
    env_path = get_env_path()
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
    from db.config import save_secure_config
    save_secure_config("GEMINI_API_KEY", req.api_key)
    # Inject into in-memory environment immediately for active session
    os.environ["GEMINI_API_KEY"] = req.api_key.strip()
    return {"status": "ok", "message": "API Key saved securely"}

@router.get("/api-key/status")
def get_api_key_status():
    from db.config import load_secure_config
    key = load_secure_config("GEMINI_API_KEY")
    if key:
        # Show first 6 and last 4 characters, mask the middle
        masked_key = key
        if len(key) > 10:
            masked_key = f"{key[:6]}...{key[-4:]}"
        return {"has_key": True, "masked_key": masked_key}
    return {"has_key": False, "masked_key": ""}

class LLMConfigUpdate(BaseModel):
    provider: str = "gemini"           # gemini | openai_compatible
    base_url: Optional[str] = ""       # OpenAI-compatible endpoint (Ollama/LM Studio/vLLM)
    model: Optional[str] = ""          # generation model (blank = provider default)
    embed_model: Optional[str] = ""    # embedding model (blank = provider default)
    api_key: Optional[str] = ""        # for openai_compatible; blank keeps existing / none

@router.get("/llm-config")
def get_llm_config():
    """Current model/backend selection so the user isn't stuck with a black-box
    default (docs/semantic_layer_audit.md §2/§3). Defaults reflect what
    get_provider() would use."""
    return {
        "provider": os.environ.get("LLM_PROVIDER", "gemini"),
        "base_url": os.environ.get("LLM_BASE_URL", ""),
        "model": os.environ.get("LLM_MODEL", ""),
        "embed_model": os.environ.get("LLM_EMBED_MODEL", ""),
        "defaults": {
            "gemini": {"model": "gemini-3.6-flash", "embed_model": "gemini-embedding-2"},
            "openai_compatible": {"model": "gpt-4o-mini", "embed_model": "text-embedding-3-small"},
        },
    }

@router.post("/llm-config")
def save_llm_config(req: LLMConfigUpdate):
    """Persist model/backend choice to .env (loaded on startup). get_provider()
    reads these per call, so it takes effect on the next AI operation."""
    update_env_variable("LLM_PROVIDER", req.provider or "gemini")
    update_env_variable("LLM_BASE_URL", (req.base_url or "").strip())
    update_env_variable("LLM_MODEL", (req.model or "").strip())
    update_env_variable("LLM_EMBED_MODEL", (req.embed_model or "").strip())
    if req.api_key:
        update_env_variable("LLM_API_KEY", req.api_key.strip())
    return {"status": "ok", "message": "Model configuration saved"}

class SystemLanguageUpdate(BaseModel):
    language: str

@router.post("/system-language")
def save_system_language(req: SystemLanguageUpdate):
    update_env_variable("SYSTEM_LANGUAGE", req.language)
    return {"status": "ok", "message": "System language saved successfully"}

@router.get("/health")
def health_check():
    from db.database import get_database_diagnostics
    from services import scheduler_state
    return {
        "status": "ok",
        "message": "FastAPI backend is running",
        "database": get_database_diagnostics(),
        # "Is the scraping engine actually running?" — running / starting /
        # stalled / error, plus per-job next fire times.
        "scheduler": scheduler_state.get_state(),
    }

@router.get("/app-logs")
def get_app_logs(lines: int = 200):
    from services.log_service import tail_log, get_log_path
    return {
        "path": get_log_path(),
        "lines": tail_log(lines),
    }

@router.post("/publish")
def trigger_publish(window_hours: int = 168):
    """Manually build the public digest (R7 Form A) — compliance-gated
    PublishedDigest JSON + generated RSS written to site/data/. Bypasses the
    PUBLISH_ENABLED gate (explicit user action)."""
    from services.publish_service import write_site_digest
    try:
        res = write_site_digest(window_hours)
        return {"status": "ok", **res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/account-guards")
def get_account_guards(session: Session = Depends(get_api_session)):
    """Per-authorized-account protection state (愿景 #10): budget/utilization,
    circuit status, and the two-sided health signals — over-protection
    (under-used + queued) is surfaced as loudly as risk."""
    from db.models import AccountGuardState
    from services.account_guard import account_status
    rows = session.exec(select(AccountGuardState)).all()
    return [account_status(r.account_key) for r in rows]

@router.get("/token-usage")
def get_token_usage(session: Session = Depends(get_api_session)):
    from services.pricing import cost_usd
    usages = session.exec(select(TokenUsage).order_by(TokenUsage.created_at.desc())).all()

    totals = {}        # by model (kept for frontend compatibility)
    by_action = {}     # by exact action_type
    by_category = {}   # coarse: Embedding / Fusion / TrendScan / Briefing / … — the "where's the money" view (P1.2)
    by_target = {}     # per fusion target (action_type "FactCheck: <tracker>")
    daily_trend = {}
    total_cost = 0.0

    def _category(action: str) -> str:
        a = action or ""
        if a.startswith("Embedding"):     return "Embedding (向量)"
        if a.startswith("FactCheck"):     return "Fusion (融合)"
        if a.startswith("TrendScan"):     return "TrendScan (趋势)"
        if a.startswith("DailyBriefing"): return "DailyBriefing (简报)"
        if a.startswith("EventArbiter"):  return "EventArbiter (事件仲裁)"
        if a.startswith("AlertSynthesis"):return "AlertSynthesis (告警合成)"
        if a.startswith("PortfolioPlan"): return "PortfolioPlan (规划)"
        return a or "Other"

    def _acc(bucket: dict, key: str, u, cost: float):
        e = bucket.setdefault(key, {"prompt_tokens": 0, "completion_tokens": 0,
                                    "total_tokens": 0, "calls": 0, "estimated_cost_usd": 0.0})
        e["prompt_tokens"] += u.prompt_tokens
        e["completion_tokens"] += u.completion_tokens
        e["total_tokens"] += u.total_tokens
        e["calls"] += 1
        e["estimated_cost_usd"] += cost

    for u in usages:
        cost = cost_usd(u.model_name, u.prompt_tokens, u.completion_tokens)
        total_cost += cost
        _acc(totals, u.model_name, u, cost)
        _acc(by_action, u.action_type or "Other", u, cost)
        _acc(by_category, _category(u.action_type), u, cost)
        if (u.action_type or "").startswith("FactCheck:"):
            target = (u.action_type.split(":", 1)[1].strip() or "unknown")
            _acc(by_target, target, u, cost)
        if u.created_at:
            # Keyed by ISO date, not "8/7". The old label carried no year, so the
            # sort compared (month, day) and would reorder the whole series at a
            # year boundary; it also cannot be used to place a day on a calendar.
            iso = u.created_at.strftime("%Y-%m-%d")
            e = daily_trend.setdefault(iso, {"tokens": 0, "cost_usd": 0.0, "calls": 0})
            e["tokens"] += u.total_tokens
            e["cost_usd"] += cost
            e["calls"] += 1

    # Round every bucket's accumulated cost.
    for bucket in (totals, by_action, by_category, by_target):
        for e in bucket.values():
            e["estimated_cost_usd"] = round(e["estimated_cost_usd"], 6)

    # Every day we have, not the last 10: a calendar view needs the whole window,
    # and the days with NO usage are part of the answer — the old shape dropped
    # them entirely, so a six-day gap where the app was not running rendered as
    # continuous consumption. The client fills the range; this just has to be
    # complete and sortable. `date` stays for the existing label.
    trend_list = [
        {
            "iso": iso,
            "date": f"{int(iso[5:7])}/{int(iso[8:10])}",
            "tokens": v["tokens"],
            "cost_usd": round(v["cost_usd"], 6),
            "calls": v["calls"],
        }
        for iso, v in sorted(daily_trend.items())
    ]

    return {
        "raw_usage": usages[:100],  # Limit raw usage list
        "summary": totals,
        "by_action": by_action,
        "by_category": by_category,
        "by_target": by_target,
        "daily_trend": trend_list,
        "estimated_cost_usd": round(total_cost, 4),
    }

@router.get("/pipeline-logs")
def get_pipeline_logs(session: Session = Depends(get_api_session)):
    return session.exec(select(PipelineStatus).order_by(PipelineStatus.updated_at.desc()).limit(50)).all()

@router.get("/investigations", response_model=List[InvestigationResponse])
def get_investigations(session: Session = Depends(get_api_session)):
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
    from db.config import get_cookie_path
    
    results = []
    for key, val in AUTH_PLATFORMS.items():
        cookie_file = val["cookie_file"]
        cookie_path = get_cookie_path(cookie_file)
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

class DbSettingsUpdate(BaseModel):
    retention_days: int
    max_size_mb: int

class PgConnectionInfo(BaseModel):
    host: str
    port: int
    username: str
    password: str
    database: str

class DbSwitchRequest(BaseModel):
    engine_type: str  # "sqlite" | "postgres"
    postgres_info: PgConnectionInfo | None = None

@router.get("/db-status")
def get_settings_db_status():
    from services.db_cleanup_service import get_db_status
    try:
        return get_db_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/db-settings")
def update_settings_db_config(req: DbSettingsUpdate):
    try:
        update_env_variable("DB_CLEANUP_RETENTION_DAYS", str(req.retention_days))
        update_env_variable("DB_CLEANUP_MAX_SIZE_MB", str(req.max_size_mb))
        return {"status": "ok", "message": "Database settings saved successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/db-cleanup")
def trigger_settings_db_cleanup(background_tasks: BackgroundTasks):
    from services.db_cleanup_service import run_db_cleanup
    try:
        background_tasks.add_task(run_db_cleanup)
        return {"status": "ok", "message": "Database cleanup triggered in background"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def get_postgres_password(password: str) -> str:
    import urllib.parse
    if password == "********":
        existing_url = os.environ.get("DATABASE_URL", "")
        if existing_url.startswith("postgresql"):
            try:
                url_part = existing_url.split("://", 1)[1]
                auth_part, _ = url_part.split("@", 1)
                _, existing_pass = auth_part.split(":", 1)
                return urllib.parse.unquote_plus(existing_pass)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Failed to reuse existing password: {e}")
        else:
            raise HTTPException(status_code=400, detail="No existing Postgres password found to reuse")
    return password

@router.post("/db-test-connection")
def test_postgres_db_connection(req: PgConnectionInfo):
    from services.db_cleanup_service import test_pg_connection
    password = get_postgres_password(req.password)
    success, message = test_pg_connection(
        host=req.host,
        port=req.port,
        user=req.username,
        password=password,
        dbname=req.database
    )
    return {"success": success, "message": message}

@router.post("/db-switch")
def switch_database_engine(req: DbSwitchRequest):
    import urllib.parse
    try:
        if req.engine_type == "sqlite":
            from db.config import get_env_path
            env_path = get_env_path()
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                new_lines = [l for l in lines if not l.strip().startswith("DATABASE_URL=")]
                with open(env_path, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
            if "DATABASE_URL" in os.environ:
                del os.environ["DATABASE_URL"]
        elif req.engine_type == "postgres":
            if not req.postgres_info:
                raise HTTPException(status_code=400, detail="Postgres connection info is required")
            
            info = req.postgres_info
            password = get_postgres_password(info.password)
            safe_pass = urllib.parse.quote_plus(password)
            db_url = f"postgresql://{info.username}:{safe_pass}@{info.host}:{info.port}/{info.database}"
            update_env_variable("DATABASE_URL", db_url)
        else:
            raise HTTPException(status_code=400, detail="Invalid engine type")
            
        return {"status": "ok", "message": "Database engine settings saved. Please restart the app."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class AppModeUpdate(BaseModel):
    app_mode: str

@router.get("/app-mode")
def get_app_mode():
    return {"app_mode": os.environ.get("APP_MODE", "ai_fusion")}

@router.post("/app-mode")
def update_app_mode(req: AppModeUpdate):
    if req.app_mode not in ["ai_fusion", "pure_rss"]:
        raise HTTPException(status_code=400, detail="Invalid app mode")
    try:
        update_env_variable("APP_MODE", req.app_mode)
        return {"status": "ok", "message": "App mode updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
