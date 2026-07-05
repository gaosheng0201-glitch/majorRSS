import os
import sys
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

startup_db_error = None

def _is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite")

def _is_postgres_url(url: str) -> bool:
    return url.startswith("postgresql") or url.startswith("postgres://")

def _build_engine(url: str):
    connect_args = {}
    if _is_sqlite_url(url):
        connect_args = {"check_same_thread": False}
        return create_engine(url, echo=False, connect_args=connect_args, poolclass=NullPool)

    if _is_postgres_url(url):
        # Avoid a stale packaged .env DATABASE_URL blocking the desktop app startup forever.
        connect_args = {"connect_timeout": int(os.environ.get("DB_CONNECT_TIMEOUT_SECONDS", "5"))}

    return create_engine(
        url,
        echo=False,
        connect_args=connect_args,
        pool_size=30,
        max_overflow=50,
        pool_pre_ping=True,
    )

def _attach_sqlite_pragmas(db_engine, url: str):
    if not _is_sqlite_url(url):
        return

    @event.listens_for(db_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        # Scheduler thread pool + task poller + API request threads all write
        # concurrently; without a busy timeout a held write lock surfaces as
        # an immediate "database is locked" error instead of a short wait.
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

engine = _build_engine(database_url)
_attach_sqlite_pragmas(engine, database_url)

def _fallback_to_local_sqlite(reason: Exception):
    global database_url, engine, startup_db_error

    startup_db_error = str(reason)
    print(f"[DB WARNING] Failed to initialize configured database: {reason}")
    print("[DB WARNING] Falling back to local SQLite for this packaged app session.")
    os.environ.pop("DATABASE_URL", None)
    database_url = get_db_url()
    engine = _build_engine(database_url)
    _attach_sqlite_pragmas(engine, database_url)

def create_db_and_tables():
    try:
        SQLModel.metadata.create_all(engine)
    except Exception as e:
        if getattr(sys, 'frozen', False) and _is_postgres_url(database_url):
            _fallback_to_local_sqlite(e)
            SQLModel.metadata.create_all(engine)
        else:
            raise

def get_session():
    return Session(engine, expire_on_commit=False)

def get_api_session():
    """FastAPI dependency. Unlike get_session (used as a context manager in
    services), this yields and always closes the session after the request —
    plain `Depends(get_session)` leaked one connection per API call."""
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()

def get_database_diagnostics():
    return {
        "database_url_kind": "sqlite" if _is_sqlite_url(database_url) else "postgres" if _is_postgres_url(database_url) else "other",
        "env_path": get_env_path(),
        "startup_db_error": startup_db_error,
    }
