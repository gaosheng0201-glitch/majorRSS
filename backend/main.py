import os
import sys
import threading
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# Add root folder to sys.path so we can import services/db modules
if getattr(sys, 'frozen', False):
    # PyInstaller frozen mode: use _MEIPASS as module root
    sys.path.insert(0, sys._MEIPASS)
else:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.log_service import setup_logging, get_logger

setup_logging()
logger = get_logger("backend")

from db.database import create_db_and_tables
from scheduler import start_scheduler
from backend.api import trackers, intelligence, briefing, monitors, settings, auth, source_presets, emergent

def _preload_persisted_config():
    """Load persisted config into os.environ at startup.

    The API key is saved (encrypted) to config.dat and providers resolve it from
    os.environ. save_api_key only injects it into the *saving* process, so after
    any restart the key was silently dropped and generation fell back to "no
    model" — breaking the planner/summaries every time the app was reopened.
    Re-inject it here so a saved key survives restarts.
    """
    try:
        from dotenv import load_dotenv
        from db.config import get_env_path, load_secure_config
        load_dotenv(get_env_path())
        for _k in ("GEMINI_API_KEY", "LLM_API_KEY", "LLM_PROVIDER",
                   "LLM_BASE_URL", "LLM_MODEL", "LLM_EMBED_MODEL"):
            _v = load_secure_config(_k)
            if _v and not os.environ.get(_k):
                os.environ[_k] = _v
        logger.info("Persisted config loaded (generation key present: %s).",
                    bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("LLM_API_KEY")))
    except Exception as e:
        logger.warning(f"Config preload skipped: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup actions
    logger.info("Starting local backend services...")
    _preload_persisted_config()
    create_db_and_tables()

    # Start scheduler in a background daemon thread. block=False: the thread
    # only runs migrations + scheduler.start() and then exits; job threads are
    # owned by APScheduler. Startup failures land in scheduler_state → /health.
    scheduler_thread = threading.Thread(target=lambda: start_scheduler(block=False), daemon=True)
    scheduler_thread.start()
    logger.info("Background scheduler thread launched.")

    yield
    # Shutdown actions
    logger.info("Shutting down backend services...")

app = FastAPI(
    title="MajorRSS API",
    description="Local backend API serving the MajorRSS Tauri/React desktop application",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Policy configuration to support local development and Tauri native origins
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://localhost",
    "http://127.0.0.1",
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(trackers.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(intelligence.router, prefix="/api")
app.include_router(briefing.router, prefix="/api")
app.include_router(monitors.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(source_presets.router, prefix="/api")
app.include_router(emergent.router, prefix="/api")

@app.get("/")
def index():
    return {"message": "Welcome to MajorRSS API. Explore the docs at /docs"}

if __name__ == "__main__":
    import uvicorn
    
    # Start parent process death watchdog
    def start_parent_watchdog():
        import threading
        parent_pid = os.getppid()
        if parent_pid <= 1:
            return
            
        def watchdog():
            if os.name == 'nt':
                import ctypes
                kernel32 = ctypes.windll.kernel32
                SYNCHRONIZE = 0x00100000
                handle = kernel32.OpenProcess(SYNCHRONIZE, False, parent_pid)
                if handle:
                    kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
                    kernel32.CloseHandle(handle)
                    os._exit(0)
            else:
                import time
                while True:
                    time.sleep(2)
                    if os.getppid() != parent_pid:
                        os._exit(0)
                        
        t = threading.Thread(target=watchdog, daemon=True)
        t.start()
        
    start_parent_watchdog()

    # Check if running as packaged app
    is_frozen = getattr(sys, 'frozen', False)
    if is_frozen:
        # Pass the app object directly in frozen mode to avoid import issues
        uvicorn.run(app, host="127.0.0.1", port=8765)
    else:
        uvicorn.run("main:app", host="127.0.0.1", port=8765, reload=True)
