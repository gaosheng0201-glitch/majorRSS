"""P4.2 涌现源发现 — the radar teaches you your own blind spots.

Cold-start discovery (P4.1 / slice c) asks a model who breaks a topic's news.
This engine asks the SIGNAL instead: which X handles and publishers keep
turning up inside threads that actually earned attention — resonant, or
corroborated/confirmed — for a target. A leak that is always "as @someone
posted" across three separate stories is a source the target should follow
directly, ahead of the aggregators that quote it.

Mechanics (all deterministic, zero tokens):
  scan   → for each attention-earning thread in the window, extract mentions
           (@handles, x.com/twitter.com profile links, non-aggregator publisher
           domains) from members; count DISTINCT THREADS per (target, source)
           over the thread's lens; candidates ≥ min_threads that the target
           does not already watch become EmergentSource rows (pending).
  accept → existence-checked like any suggestion (FxTwitter for a handle, a
           real feed discovered for a domain), then appended to the target's
           intent_plan.suggested_sources as selected — the same contract the
           resolver already consumes. Additive only: this never down-weights
           anything (the roadmap's "反馈最后" constraint stays intact).
  dismiss→ sticky; a rescan updates the count but never resurrects it.
"""
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

from services.log_service import get_logger
from services.provenance import domain as _domain, _AGGREGATOR_DOMAINS

logger = get_logger("emergent")

_HANDLE_RE = re.compile(r"(?<![\w.@/])@([A-Za-z0-9_]{3,15})\b")
_XLINK_RE = re.compile(r"https?://(?:www\.|mobile\.)?(?:x\.com|twitter\.com)/([A-Za-z0-9_]{1,15})"
                       r"(?:/status/\d+)?", re.I)
_X_RESERVED = {"i", "home", "search", "explore", "intent", "share", "hashtag", "settings",
               "messages", "notifications", "login", "signup", "compose"}
_NOISE_HANDLES = {"gmail", "yahoo", "outlook", "hotmail", "icloud", "protonmail", "media",
                  "everyone", "here", "channel", "username", "example", "user", "mention"}
_NOISE_DOMAINS = tuple(_AGGREGATOR_DOMAINS) + (
    "x.com", "twitter.com", "t.co", "youtube.com", "youtu.be", "github.com", "linkedin.com",
    "facebook.com", "instagram.com", "wikipedia.org", "google.com", "bing.com", "t.me",
    "discord.com", "discord.gg", "tiktok.com", "threads.net", "bsky.app", "mastodon.social",
    # X mirrors are proxies of x.com, not publishers; arXiv is a registry that
    # the ai_papers preset already covers wholesale.
    "nitter.", "xcancel.com", "arxiv.org",
)
# @mentions inside code-host content are GitHub users (release-note credits),
# not X handles — measured: "@maxisbey ×7" from a repo's release notes.
_CODE_HOSTS = ("github.com", "gitlab.com", "huggingface.co", "githubusercontent.com")
_DOMAIN_MIN_THREADS = 6   # an outlet must recur more than a person to be worth a direct feed
_FEED_PATHS = ("/feed", "/rss", "/feed/", "/rss.xml", "/feed.xml", "/atom.xml", "/index.xml",
               "/blog/feed", "/blog/rss", "/news/rss")


def extract_mentions(title: str, content: str, url: str) -> Set[Tuple[str, str]]:
    """Sources a member points at: ("account", handle) and ("domain", host)."""
    text = f"{title or ''}\n{content or ''}"[:20000]
    out: Set[Tuple[str, str]] = set()
    d = _domain(url or "")
    if d.startswith("www."):
        d = d[4:]
    for m in _XLINK_RE.finditer(text):
        h = m.group(1)
        if h.lower() not in _X_RESERVED and h.lower() not in _NOISE_HANDLES:
            out.add(("account", h))
    if not any(c in d for c in _CODE_HOSTS):
        for m in _HANDLE_RE.finditer(text):
            h = m.group(1)
            if h.lower() not in _NOISE_HANDLES:
                out.add(("account", h))
    if d and "." in d and not any(n in d for n in _NOISE_DOMAINS):
        out.add(("domain", d))
    return out


def _thread_lens(th) -> Set[int]:
    ids = set()
    if th.tracker_id is not None:
        ids.add(int(th.tracker_id))
    try:
        ids.update(int(i) for i in json.loads(th.tracker_ids or "[]") if i is not None)
    except Exception:
        pass
    return ids


def _already_watched(session, cutoff) -> Tuple[Set[str], Dict[int, Set[str]]]:
    """Sources already watched, as lower-cased keys 'account:handle' /
    'domain:host'. Global = the preset library PLUS what deliberate routes
    actually delivered in the window: any domain that arrived stamped
    curated/primary is by definition reached first-hand already (a feed's own
    host — raw.githubusercontent.com for the Olshansk feeds — says nothing
    about the publisher it delivers, so the data is the honest map), and any
    handle read through a from_account route is already followed."""
    from db.models import RawArticle, SourcePreset, Tracker
    from sqlmodel import select
    glob: Set[str] = set()
    for p in session.exec(select(SourcePreset)).all():
        u = (p.url or "").lower()
        if not u:
            continue
        if "x.com/" in u or "twitter.com/" in u:
            glob.add("account:" + u.rstrip("/").split("/")[-1])
        else:
            d = _domain(u)
            glob.add("domain:" + (d[4:] if d.startswith("www.") else d))
    for url, tier, from_account in session.exec(select(
            RawArticle.url, RawArticle.source_tier, RawArticle.from_account)
            .where(RawArticle.created_at >= cutoff)).all():
        d = _domain(url or "")
        d = d[4:] if d.startswith("www.") else d
        if tier in ("primary", "curated") and d:
            glob.add("domain:" + d)
        if from_account:
            m = _XLINK_RE.match(url or "")
            if m:
                glob.add("account:" + m.group(1).lower())
            elif "nitter." in d or "xcancel" in d:
                parts = [p for p in (url or "").split("/") if p]
                if len(parts) >= 3:
                    glob.add("account:" + parts[2].lower())
    per: Dict[int, Set[str]] = defaultdict(set)
    for t in session.exec(select(Tracker)).all():
        try:
            policy = json.loads(t.fetch_policy) if t.fetch_policy else {}
        except Exception:
            continue
        ip = policy.get("intent_plan") or {}
        for d in ip.get("official_domains") or []:
            per[t.id].add("domain:" + d.lower())
        for s in ip.get("suggested_sources") or []:
            if not isinstance(s, dict):
                continue
            k, v = (s.get("kind") or "").lower(), (s.get("value") or "").lower()
            if k == "account":
                per[t.id].add("account:" + v)
            elif k == "rss":
                per[t.id].add("domain:" + _domain(v).replace("www.", "", 1))
    return glob, per


def scan_emergent_sources(window_days: int = 14, min_threads: int = 3) -> dict:
    from db.database import get_session
    from db.models import EmergentSource, RawArticle, StoryThread
    from sqlmodel import or_, select

    cutoff = datetime.utcnow() - timedelta(days=window_days)
    with get_session() as session:
        threads = session.exec(select(StoryThread).where(
            StoryThread.last_update_at >= cutoff,
            or_(StoryThread.is_resonant == True,  # noqa: E712
                StoryThread.lifecycle.in_(["CORROBORATED", "CONFIRMED"])),
        )).all()
        if not threads:
            return {"scanned_threads": 0, "candidates": 0, "new": 0}
        lens_by_thread = {th.id: _thread_lens(th) for th in threads}
        title_by_thread = {th.id: (th.title or "")[:80] for th in threads}

        counts: Dict[Tuple[int, str, str], dict] = {}
        for tid, title, content, url in session.exec(select(
                RawArticle.thread_id, RawArticle.title, RawArticle.content, RawArticle.url)
                .where(RawArticle.thread_id.in_(list(lens_by_thread.keys())))).all():
            mentions = extract_mentions(title, content, url)
            if not mentions:
                continue
            for tracker_id in lens_by_thread[tid]:
                for kind, value in mentions:
                    key = (tracker_id, kind, value.lower())
                    slot = counts.setdefault(key, {"value": value, "threads": set()})
                    slot["threads"].add(tid)

        glob, per = _already_watched(session, cutoff)
        watched_domains = [k[7:] for k in glob if k.startswith("domain:")]
        existing = {(e.tracker_id, e.kind, e.value_key): e
                    for e in session.exec(select(EmergentSource)).all()}
        candidates = new = 0
        now = datetime.utcnow()
        for (tracker_id, kind, vkey), slot in counts.items():
            n = len(slot["threads"])
            if n < (max(min_threads, _DOMAIN_MIN_THREADS) if kind == "domain" else min_threads):
                continue
            wk = f"{kind}:{vkey}"
            if wk in glob or wk in per.get(tracker_id, set()):
                continue
            if kind == "domain" and any(vkey == w or vkey.endswith("." + w) or w.endswith("." + vkey)
                                        for w in watched_domains):
                continue   # rss.arxiv.org already watched ⇒ arxiv.org is not new
            candidates += 1
            samples = [title_by_thread[t] for t in sorted(slot["threads"])[:5]]
            row = existing.get((tracker_id, kind, vkey))
            if row is None:
                row = EmergentSource(tracker_id=tracker_id, kind=kind, value=slot["value"],
                                     value_key=vkey, thread_count=n,
                                     sample_titles=json.dumps(samples, ensure_ascii=False),
                                     status="pending", first_seen_at=now, updated_at=now)
                new += 1
            else:
                row.thread_count = n
                row.sample_titles = json.dumps(samples, ensure_ascii=False)
                row.updated_at = now
            session.add(row)
        session.commit()
    logger.info(f"Emergent sources: scanned {len(threads)} threads, {candidates} candidates, {new} new")
    return {"scanned_threads": len(threads), "candidates": candidates, "new": new}


def _discover_feed(host: str) -> Optional[str]:
    from services.source_verifier import _rss_alive
    for path in _FEED_PATHS:
        url = f"https://{host}{path}"
        try:
            if _rss_alive(url):
                return url
        except Exception:
            continue
    return None


def accept_emergent_source(emergent_id: int) -> dict:
    """Promote a candidate to a first-class suggested source of its target —
    only after it passes the same existence checks every suggestion does."""
    from db.database import get_session
    from db.models import EmergentSource, Tracker
    from services.source_verifier import _twitter_handle_alive

    with get_session() as session:
        row = session.get(EmergentSource, emergent_id)
        if not row:
            return {"ok": False, "reason": "not found"}
        tracker = session.get(Tracker, row.tracker_id)
        if not tracker:
            return {"ok": False, "reason": "target gone"}
        if row.kind == "account":
            try:
                ok = _twitter_handle_alive(row.value)
            except Exception:
                ok = False
            if not ok:
                row.status = "no_route"
                session.add(row); session.commit()
                return {"ok": False, "reason": "handle not verifiable"}
            sugg = {"kind": "account", "value": row.value, "platform": "twitter"}
        else:
            feed = _discover_feed(row.value)
            if not feed:
                row.status = "no_route"
                session.add(row); session.commit()
                return {"ok": False, "reason": "no feed found on that domain"}
            sugg = {"kind": "rss", "value": feed, "platform": ""}
        sugg.update({"reason": f"涌现:{row.thread_count} 条获注意力线索反复指向", "verified": True,
                     "selected": True})
        try:
            policy = json.loads(tracker.fetch_policy) if tracker.fetch_policy else {}
        except Exception:
            policy = {}
        ip = policy.get("intent_plan") or {}
        lst = [s for s in (ip.get("suggested_sources") or []) if isinstance(s, dict)]
        if not any((s.get("kind"), (s.get("value") or "").lower()) == (sugg["kind"], sugg["value"].lower())
                   for s in lst):
            lst.append(sugg)
        ip["suggested_sources"] = lst
        policy["intent_plan"] = ip
        tracker.fetch_policy = json.dumps(policy)
        row.status = "accepted"
        row.updated_at = datetime.utcnow()
        session.add(tracker); session.add(row); session.commit()
        return {"ok": True, "added": sugg}


def dismiss_emergent_source(emergent_id: int) -> dict:
    from db.database import get_session
    from db.models import EmergentSource
    with get_session() as session:
        row = session.get(EmergentSource, emergent_id)
        if not row:
            return {"ok": False, "reason": "not found"}
        row.status = "dismissed"
        row.updated_at = datetime.utcnow()
        session.add(row); session.commit()
        return {"ok": True}


def list_emergent_sources(tracker_id: Optional[int] = None, status: str = "pending",
                          limit: int = 20) -> List[dict]:
    from db.database import get_session
    from db.models import EmergentSource, Tracker
    from sqlmodel import select
    with get_session() as session:
        q = select(EmergentSource).where(EmergentSource.status == status)
        if tracker_id is not None:
            q = q.where(EmergentSource.tracker_id == tracker_id)
        rows = session.exec(q.order_by(EmergentSource.thread_count.desc()).limit(limit)).all()
        names = {t.id: t.name for t in session.exec(select(Tracker)).all()}
        return [{
            "id": r.id, "tracker_id": r.tracker_id, "tracker_name": names.get(r.tracker_id, ""),
            "kind": r.kind, "value": r.value, "thread_count": r.thread_count,
            "sample_titles": json.loads(r.sample_titles or "[]"), "status": r.status,
            "first_seen_at": r.first_seen_at.isoformat() if r.first_seen_at else None,
        } for r in rows]
