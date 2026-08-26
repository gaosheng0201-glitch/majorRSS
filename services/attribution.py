"""Cross-target relevance attribution (author ruling 2026-08-26).

Ownership used to be a race artifact: the shared conditional-GET cache means
whichever tracker fetches a shared feed first is the only one that ever SEES
its items, and URL uniqueness makes that permanent. The author hit it twice —
Claude's official SDLC playbook owned by the grok tracker, invisible under the
claude filter chip.

The ruling: a piece that concerns several targets shows under ALL of them —
the SAME piece, not copies. So ownership stays with the fetcher (harmless once
display no longer depends on it), and intake computes a VISIBILITY SET: which
targets' profiles this item matches. Deterministic string matching against
planned data (entities, per-target official domains) — no runtime LLM, per
决策在规划期; and stamped at intake, never re-derived at consumption, per
source_tiering §2.

Precision rules (an article mentioning Claude once in passing should NOT flood
the claude filter):
  - official-domain hit  → relevant, always (the target's own channel);
  - an entity in the TITLE (word-bounded for Latin, substring for CJK) → relevant;
  - ≥2 distinct entities in the body → relevant;
  - keep_keywords deliberately NOT used — they are search nets ("leak", "API"),
    far too generic to assert aboutness.
"""
import json
import re
from typing import List, Optional

from services.provenance import domain as _domain

# Entities shorter than this are too ambiguous to match on at all ("AI", "X").
_MIN_TERM = 3


class TrackerProfile:
    def __init__(self, tracker_id: int, entities: List[str], official_domains: List[str]):
        self.tracker_id = tracker_id
        self.official_domains = tuple(d.lower() for d in official_domains if d)
        self.latin_terms = []
        self.cjk_terms = []
        for e in entities or []:
            e = (e or "").strip()
            if len(e) < _MIN_TERM and not any("一" <= ch <= "鿿" for ch in e):
                continue
            if re.search(r"[一-鿿぀-ヿ가-힯]", e):
                self.cjk_terms.append(e.lower())
            else:
                self.latin_terms.append(re.compile(
                    r"(?<![0-9A-Za-z])" + re.escape(e) + r"(?![0-9A-Za-z])", re.I))


def load_profiles(session=None) -> List[TrackerProfile]:
    """Profiles of all ACTIVE trackers, from their planned data."""
    from db.database import get_session
    from db.models import Tracker
    from sqlmodel import select

    def _build(trackers):
        out = []
        for t in trackers:
            try:
                policy = json.loads(t.fetch_policy) if t.fetch_policy else {}
            except Exception:
                policy = {}
            ip = policy.get("intent_plan") or {}
            entities = policy.get("entities") or []
            if t.name and t.name not in entities:
                entities = [t.name] + list(entities)
            out.append(TrackerProfile(
                t.id, entities, ip.get("official_domains") or []))
        return out

    if session is not None:
        return _build(session.exec(select(Tracker).where(Tracker.is_active == True)).all())  # noqa: E712
    with get_session() as s:
        return _build(s.exec(select(Tracker).where(Tracker.is_active == True)).all())


def _matches(profile: TrackerProfile, title: str, content: str, url_domain: str) -> bool:
    if profile.official_domains and any(
            url_domain == d or url_domain.endswith("." + d) for d in profile.official_domains):
        return True
    title = title or ""
    for rx in profile.latin_terms:
        if rx.search(title):
            return True
    tl = title.lower()
    if any(term in tl for term in profile.cjk_terms):
        return True
    body = (content or "")[:20000]
    hits = 0
    for rx in profile.latin_terms:
        if rx.search(body):
            hits += 1
            if hits >= 2:
                return True
    bl = body.lower()
    for term in profile.cjk_terms:
        if term in bl:
            hits += 1
            if hits >= 2:
                return True
    return False


def relevant_tracker_ids(title: str, content: str, url: str,
                         profiles: List[TrackerProfile],
                         owner_id: Optional[int] = None) -> List[int]:
    """All tracker ids whose profile this item matches. The owner is included
    implicitly by callers; it is excluded here to keep the stored set small."""
    d = _domain(url or "")
    out = []
    for p in profiles:
        if owner_id is not None and p.tracker_id == owner_id:
            continue
        if _matches(p, title, content, d):
            out.append(p.tracker_id)
    return out


def restamp_recent(days: int = 30) -> dict:
    """Recompute cross-target visibility for recent articles against CURRENT
    profiles. Idempotent and deterministic; run after profile backfills so
    newly-learned official_domains reach rows stamped before the knowledge
    existed."""
    from datetime import datetime, timedelta
    from db.database import get_session
    from db.models import RawArticle
    from sqlmodel import select

    changed = 0
    with get_session() as session:
        profiles = load_profiles(session)
        cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = session.exec(select(RawArticle).where(RawArticle.created_at >= cutoff)).all()
        for r in rows:
            ids = relevant_tracker_ids(r.title or "", (r.content or "")[:20000],
                                       r.url or "", profiles, owner_id=r.tracker_id)
            new = json.dumps(ids) if ids else None
            if new != r.also_tracker_ids:
                r.also_tracker_ids = new
                session.add(r)
                changed += 1
        session.commit()
    return {"restamped": changed, "scanned": len(rows)}
