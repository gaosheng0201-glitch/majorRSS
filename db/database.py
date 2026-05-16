import os
from dotenv import load_dotenv
from sqlmodel import SQLModel, create_engine, Session
from .models import Tracker, RawArticle, IntelReport, PipelineStatus, DailyBriefing, TrendAlert, TokenUsage

# Load environment variables (to capture DATABASE_URL if present)
load_dotenv()

database_url = os.environ.get("DATABASE_URL")

if not database_url:
    # Fallback to local SQLite if no external DB is configured
    sqlite_file_name = "major_rss.db"
    database_url = f"sqlite:///{sqlite_file_name}"

from sqlalchemy.pool import NullPool

connect_args = {}
# Only apply SQLite-specific thread safety overrides
if database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    from sqlalchemy.pool import NullPool
    engine = create_engine(database_url, echo=False, connect_args=connect_args, poolclass=NullPool)
else:
    # For Postgres, use robust QueuePool with higher limits to prevent timeouts
    engine = create_engine(database_url, echo=False, connect_args=connect_args, pool_size=30, max_overflow=50, pool_pre_ping=True)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    return Session(engine)
