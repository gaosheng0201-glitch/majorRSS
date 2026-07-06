"""
Pytest setup: point every test at a throwaway SQLite DB and disable any real
API key, BEFORE the app modules (which build the engine at import) are imported.
"""
import os
import tempfile

# Must run before any `import db.database` (engine is built from DATABASE_URL at
# import time). conftest is imported before test modules, so this is early enough.
_TMP_DB = os.path.join(tempfile.mkdtemp(prefix="majorss_test_"), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("LLM_API_KEY", None)
os.environ["LLM_PROVIDER"] = "gemini"  # -> FallbackEmbedder without a key

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(scope="session", autouse=True)
def _create_schema():
    from db.database import create_db_and_tables
    create_db_and_tables()
    yield
