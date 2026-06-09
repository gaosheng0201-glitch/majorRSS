import os
import sys
import threading
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# Add root folder to sys.path so we can import services/db modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import create_db_and_tables
from scheduler import start_scheduler
from backend.api import trackers, intelligence, briefing, monitors, settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup actions
    print("[FastAPI] Starting local backend services...")
    create_db_and_tables()
    
    # Start scheduler in a background daemon thread
    # The start_scheduler function runs migrations and keeps polling in a loop
    scheduler_thread = threading.Thread(target=start_scheduler, daemon=True)
    scheduler_thread.start()
    print("[FastAPI] Background scheduler thread launched.")
    
    yield
    # Shutdown actions
    print("[FastAPI] Shutting down backend services...")

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
    "tauri://localhost",
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
app.include_router(intelligence.router, prefix="/api")
app.include_router(briefing.router, prefix="/api")
app.include_router(monitors.router, prefix="/api")
app.include_router(settings.router, prefix="/api")

@app.get("/")
def index():
    return {"message": "Welcome to MajorRSS API. Explore the docs at /docs"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8765, reload=True)
