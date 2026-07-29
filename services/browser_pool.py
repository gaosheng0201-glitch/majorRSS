"""
Persistent browser pool (R1, 愿景 #10 + 性能).

The old path launched a fresh Chromium for every URL every cycle: expensive, and
a churning fingerprint that reads as a bot. This keeps a long-lived browser and
reuses one context per account, so an authenticated account looks like the same
device across visits and session cookies rotate naturally in a live context.

Threading: Playwright's sync API binds its objects to the creating thread and is
not thread-safe. The scraper runs across a 2-worker ThreadPool (plus scheduler
threads), so the pool is THREAD-LOCAL — each thread lazily owns its own
Playwright + browser + context cache. Threads persist in the pool, so reuse
spans both the URLs of one scrape and successive cycles.
"""
import os
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from services.log_service import get_logger

logger = get_logger("browser_pool")

_UNRESOLVED = object()
_browsers_verdict = _UNRESOLVED


def _default_browsers_dir() -> Path:
    """Playwright's own per-platform cache location, i.e. where `playwright
    install` puts browsers."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ms-playwright"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "ms-playwright"


def ensure_browsers_path() -> Optional[str]:
    """Point Playwright at browsers that actually exist, and say so when they don't.

    Playwright's own `_transport.py` does, verbatim:

        if getattr(sys, "frozen", False):
            env.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

    "0" means "browsers live inside the package", which is true for PyInstaller
    builds that bundle them — ours does not. The result was that every agentic
    fetch in the packaged app looked in `driver/package/.local-browsers/…`, found
    nothing, and failed: 0 successes out of 399 attempts, which silently took the
    whole browser/auth capability offline (and with it the only route to
    login-walled platforms). Because Playwright uses setdefault, presetting the
    variable is enough to override it.

    Returns None when browsers are available, or a human-readable reason when
    they are missing, so callers can surface something actionable instead of the
    misleading errors this used to produce. Resolved once per process: the
    verdict is cached so the value we set ourselves is never mistaken on a later
    call for an operator-supplied one.
    """
    global _browsers_verdict
    if _browsers_verdict is not _UNRESOLVED:
        return _browsers_verdict
    _browsers_verdict = _resolve_browsers_path()
    return _browsers_verdict


def _resolve_browsers_path() -> Optional[str]:
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH") not in (None, "", "0"):
        return None                       # operator set it explicitly; respect that
    bundled = Path(getattr(sys, "_MEIPASS", "")) / "playwright" / "driver" / "package" / ".local-browsers"
    if getattr(sys, "frozen", False) and bundled.is_dir() and any(bundled.iterdir()):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"   # genuinely bundled
        return None
    shared = _default_browsers_dir()
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(shared)
    if not shared.is_dir() or not any(shared.glob("chromium*")):
        return (f"Playwright browsers are not installed at {shared}. "
                f"Run `playwright install chromium` once to enable browser-based "
                f"(agentic / authorized) sources.")
    logger.info(f"Playwright browsers: {shared}")
    return None

_DEFAULT_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_ANON_KEY = "__anon__"

_local = threading.local()

# Global cache generation. Re-authorization rewrites a platform's cookie file;
# without invalidation the pooled context keeps the STALE storage_state and the
# refreshed login never takes effect (defeats cookie rotation). The auth flow
# calls bump_generation() after writing cookies; contexts built at an older
# generation are rebuilt on next acquire.
_gen_lock = threading.Lock()
_global_generation = 0


def bump_generation():
    """Invalidate all pooled contexts (call after re-auth rewrites cookies)."""
    global _global_generation
    with _gen_lock:
        _global_generation += 1


def _current_generation():
    with _gen_lock:
        return _global_generation


def _thread_state():
    st = getattr(_local, "state", None)
    if st is None:
        st = {"pw": None, "browser": None, "contexts": {}, "gen": {}}
        _local.state = st
    return st


def _ensure_browser(st):
    from playwright.sync_api import sync_playwright
    problem = ensure_browsers_path()
    if problem:
        raise RuntimeError(problem)
    if st["browser"] is not None and st["browser"].is_connected():
        return st["browser"]
    # (Re)start playwright + browser for this thread.
    if st["pw"] is None:
        st["pw"] = sync_playwright().start()
    st["browser"] = st["pw"].chromium.launch(headless=True)
    st["contexts"] = {}  # contexts belong to the old browser; drop them
    st["gen"] = {}
    logger.info(f"Launched browser for thread {threading.current_thread().name}")
    return st["browser"]


def _get_context(st, context_key: str, storage_state=None, user_agent: str = _DEFAULT_UA):
    gen = _current_generation()
    ctx = st["contexts"].get(context_key)
    if ctx is not None:
        if st["gen"].get(context_key) == gen:
            return ctx
        # Stale (re-auth bumped the generation): rebuild from fresh storage_state.
        try:
            ctx.close()
        except Exception:
            pass
        st["contexts"].pop(context_key, None)
    browser = _ensure_browser(st)
    kwargs = {"user_agent": user_agent, "viewport": {"width": 1280, "height": 800}}
    if storage_state:
        kwargs["storage_state"] = storage_state
    ctx = browser.new_context(**kwargs)
    st["contexts"][context_key] = ctx
    st["gen"][context_key] = gen
    return ctx


@contextmanager
def acquire_page(context_key: Optional[str] = None, storage_state=None, user_agent: str = _DEFAULT_UA):
    """Yield a Playwright page from a reused context for context_key (None →
    shared anonymous context). Only the page is closed on exit; the browser and
    context stay alive for reuse. On any pool error the caller should fall back
    to a one-off browser."""
    st = _thread_state()
    key = context_key or _ANON_KEY
    try:
        ctx = _get_context(st, key, storage_state=storage_state, user_agent=user_agent)
    except Exception:
        # Poisoned browser/context — reset this thread's state and retry once.
        logger.warning("Context acquisition failed; resetting thread browser state and retrying.")
        shutdown_thread()
        st = _thread_state()
        ctx = _get_context(st, key, storage_state=storage_state, user_agent=user_agent)

    page = ctx.new_page()
    try:
        yield page
    finally:
        try:
            page.close()
        except Exception:
            pass


@contextmanager
def one_off_browser():
    """A throwaway browser for the fallback path, reusing THIS thread's
    Playwright driver when it already has one.

    Playwright's sync API permits exactly one running instance per thread. The
    fallback used to call `sync_playwright().start()` unconditionally, so once
    the pool had started one in the same thread the fallback died with "Sync API
    inside the asyncio loop" — an error about the *second* start, which masked
    whatever actually broke the pooled attempt (in practice: missing browsers).
    Only the browser is one-off; the driver is shared and left running.
    """
    problem = ensure_browsers_path()
    if problem:
        raise RuntimeError(problem)
    st = _thread_state()
    owns_driver = st["pw"] is None
    if owns_driver:
        from playwright.sync_api import sync_playwright
        st["pw"] = sync_playwright().start()
    browser = st["pw"].chromium.launch(headless=True)
    try:
        yield browser
    finally:
        try:
            browser.close()
        except Exception:
            pass


def invalidate_context(context_key: str):
    """Drop a cached context (e.g. after re-authorization changes its cookies)
    so the next acquire rebuilds it from fresh storage_state."""
    st = _thread_state()
    ctx = st["contexts"].pop(context_key, None)
    if ctx is not None:
        try:
            ctx.close()
        except Exception:
            pass


def shutdown_thread():
    """Tear down the current thread's browser + contexts (best effort)."""
    st = getattr(_local, "state", None)
    if not st:
        return
    for ctx in list(st["contexts"].values()):
        try:
            ctx.close()
        except Exception:
            pass
    st["contexts"] = {}
    try:
        if st["browser"] is not None:
            st["browser"].close()
    except Exception:
        pass
    try:
        if st["pw"] is not None:
            st["pw"].stop()
    except Exception:
        pass
    _local.state = {"pw": None, "browser": None, "contexts": {}}
