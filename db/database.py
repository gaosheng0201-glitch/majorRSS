import os
from dotenv import load_dotenv
from sqlmodel import SQLModel, create_engine, Session
from .models import Tracker, RawArticle, IntelReport, PipelineStatus, DailyBriefing, TrendAlert, TokenUsage

from dotenv import load_dotenv
from db.config import get_env_path, get_db_url, load_secure_config

# Load environment variables (from user data directory if packaged)
load_dotenv(get_env_path())

# Load secure API key from DPAPI config and inject into environment variables in memory
secure_key = load_secure_config("GEMINI_API_KEY")
if secure_key:
    os.environ["GEMINI_API_KEY"] = secure_key

database_url = get_db_url()

from sqlalchemy.pool import NullPool
from sqlalchemy import event

connect_args = {}
# Only apply SQLite-specific thread safety overrides
if database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    from sqlalchemy.pool import NullPool
    engine = create_engine(database_url, echo=False, connect_args=connect_args, poolclass=NullPool)
else:
    # For Postgres, use robust QueuePool with higher limits to prevent timeouts
    engine = create_engine(database_url, echo=False, connect_args=connect_args, pool_size=30, max_overflow=50, pool_pre_ping=True)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    return Session(engine, expire_on_commit=False)
