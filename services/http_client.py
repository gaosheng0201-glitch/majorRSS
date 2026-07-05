"""
Conditional-GET HTTP layer (R1, 愿景 #4).

A changelog / docs page polled every 5 minutes should cost almost nothing when
it hasn't changed. This client persists ETag / Last-Modified validators per URL
and sends If-None-Match / If-Modified-Since; an unchanged page returns 304 with
an empty body — one header round-trip, zero parsing, zero LLM tokens. For
servers that send no validators we fall back to a stored body hash so "changed
vs unchanged" is still answerable without re-processing.
"""
import hashlib
from datetime import datetime, timezone
from typing import Optional, Tuple

import requests

from services.log_service import get_logger

logger = get_logger("http")

DEFAULT_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 MajorRSS/2.0")


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ConditionalResult:
    """Outcome of a conditional fetch.
    changed=False means the resource is byte-identical to last time (304 or
    matching hash) — callers can skip all downstream work."""
    def __init__(self, changed: bool, status: int, content: Optional[bytes], from_cache: bool):
        self.changed = changed
        self.status = status
        self.content = content
        self.from_cache = from_cache


def _load_entry(session, url: str):
    from db.models import HttpCacheEntry
    from sqlmodel import select
    return session.exec(select(HttpCacheEntry).where(HttpCacheEntry.url == url)).first()


def conditional_get(url: str, timeout: int = 20, ua: str = DEFAULT_UA) -> ConditionalResult:
    """GET url using stored validators. Returns ConditionalResult.
    On 304 or an unchanged body hash, changed=False and content is None."""
    from db.database import get_session
    from db.models import HttpCacheEntry

    headers = {"User-Agent": ua}
    with get_session() as session:
        entry = _load_entry(session, url)
        if entry:
            if entry.etag:
                headers["If-None-Match"] = entry.etag
            if entry.last_modified:
                headers["If-Modified-Since"] = entry.last_modified

    resp = requests.get(url, headers=headers, timeout=timeout)
    now = _now()

    if resp.status_code == 304:
        with get_session() as session:
            entry = _load_entry(session, url)
            if entry:
                entry.last_status = 304
                entry.last_checked_at = now
                session.add(entry)
                session.commit()
        logger.info(f"304 Not Modified: {url}")
        return ConditionalResult(changed=False, status=304, content=None, from_cache=True)

    resp.raise_for_status()
    body = resp.content
    body_hash = hashlib.sha256(body).hexdigest()

    etag = resp.headers.get("ETag")
    last_modified = resp.headers.get("Last-Modified")

    with get_session() as session:
        entry = _load_entry(session, url)
        unchanged_by_hash = bool(entry and entry.content_hash == body_hash)
        if not entry:
            entry = HttpCacheEntry(url=url)
        entry.etag = etag
        entry.last_modified = last_modified
        entry.content_hash = body_hash
        entry.last_status = resp.status_code
        entry.last_checked_at = now
        entry.updated_at = now
        session.add(entry)
        session.commit()

    if unchanged_by_hash:
        # 200 but identical bytes — server just doesn't support validators.
        logger.info(f"200 but unchanged body hash: {url}")
        return ConditionalResult(changed=False, status=resp.status_code, content=body, from_cache=True)

    return ConditionalResult(changed=True, status=resp.status_code, content=body, from_cache=False)
