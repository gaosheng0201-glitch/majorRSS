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


# alias, an optional ONE-word product line between alias and version ("Claude
# Opus 5.5", "Claude Fable 5.2"), the version, an optional tier suffix.
_VERSION_TERM_RE = r"(?<![0-9A-Za-z])({alias})(?:\s([A-Z][a-z]+))?\s?-?\s?(\d+(?:\.\d+)?)(?:\s?(Pro|Flash|Ultra|Lite|Max|Mini|Nano|Turbo|Plus|Sol|Astra|Cyber))?(?![0-9A-Za-z])"


def extract_version_terms(title: str, latin_aliases) -> Set[str]:
    """涌现关键词: alias-anchored version phrases in a TITLE — "Gemini 4 Pro",
    "GPT-6", "Fable 5.1" — the names leaks and pre-release tests are reported
    under. Anchored on the target's own aliases for precision; titles only.
    Why deterministic and not the planner: a model's world knowledge lags the
    product line (asked for Gemini's successor in 2026-09 it offered "Gemini
    2.5" and "Gemini 3"); the target's own leads already say "Gemini 4 Pro"."""
    out: Set[str] = set()
    t = title or ""
    anchors = []
    for alias in latin_aliases:
        a = alias.strip()
        if len(a) < 3 or re.search(r"\d", a):
            continue          # anchor on the bare product name, not on a versioned alias
        anchors.append(a)
    # A product line named on its own — "Opus 5.5", "Fable 5.2" — counts when
    # the title names the target somewhere else ("Anthropic tests … Opus 5.5").
    names_target = any(re.search(r"(?<![0-9A-Za-z])" + re.escape(a) + r"(?![0-9A-Za-z])", t, re.I) for a in anchors)
    if names_target:
        for a in list(anchors):
            parts = a.split()
            if len(parts) == 2 and parts[1][:1].isupper() and parts[1] not in anchors:
                anchors.append(parts[1])
    for a in anchors:
        for m in re.finditer(_VERSION_TERM_RE.format(alias=re.escape(a)), t, re.I):
            anchor = m.group(1) + (f" {m.group(2)}" if m.group(2) else "")
            base = f"{anchor} {m.group(3)}"
            out.add(base)
            if m.group(4):
                out.add(f"{base} {m.group(4)}")
    return out


_VER_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)")


def _version_of(term: str):
    m = _VER_NUM_RE.search(term or "")
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def _highest_alias_version(aliases, anchor: str):
    """The newest version the target already names for this product anchor —
    "what is coming" is at or above it; older versions are history, not a
    watch term (first live scan offered Gemini 3.5/3.6/3.7 to a target that
    already watches Gemini 4)."""
    best = None
    for a in aliases:
        if _VER_NUM_RE.split(a, 1)[0].strip().lower() == anchor.lower():
            v = _version_of(a)
            if v is not None and (best is None or v > best):
                best = v
    return best


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
        for e in policy.get("entities") or []:
            per[t.id].add("term:" + str(e).strip().lower())
        for a in ip.get("entities") or []:
            if isinstance(a, dict) and a.get("text"):
                per[t.id].add("term:" + str(a["text"]).strip().lower())
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
        # Version terms are learned from EVERY recent thread, not only the
        # attention-earning ones: a coming version's leaks are exactly the
        # single-source leads that have earned nothing yet ("Anthropic tests
        # Opus 5.5" from one outlet, a Polymarket post, a newsletter line).
        # Their recurrence across threads IS the signal. Accounts and
        # publishers still need attention-earning threads to count.
        all_recent = session.exec(select(StoryThread).where(StoryThread.last_update_at >= cutoff)).all()
        if not all_recent:
            return {"scanned_threads": 0, "candidates": 0, "new": 0}
        attention_ids = {th.id for th in threads}
        from services import thread_targets as tt
        lens_by_thread = {tid: {r.tracker_id for r in rows if r.llm_verdict is not False}
                          for tid, rows in tt.rows_for(session, [th.id for th in all_recent]).items()}
        from db.models import Tracker
        from services.target_profile import TargetProfile
        aliases_by_tracker: Dict[int, List[str]] = {}
        for t in session.exec(select(Tracker)).all():
            prof = TargetProfile.from_tracker(t)
            aliases_by_tracker[t.id] = [e for e in ([prof.name] + prof.entities)
                                        if e and not re.search(r"[一-鿿぀-ヿ가-힯]", e)]
        title_by_thread = {th.id: (th.title or "")[:80] for th in all_recent}

        counts: Dict[Tuple[int, str, str], dict] = {}
        for tid, title, content, url in session.exec(select(
                RawArticle.thread_id, RawArticle.title, RawArticle.content, RawArticle.url)
                .where(RawArticle.thread_id.in_(list(lens_by_thread.keys())))).all():
            mentions = extract_mentions(title, content, url) if tid in attention_ids else set()
            for tracker_id in lens_by_thread[tid]:
                for term in extract_version_terms(title, aliases_by_tracker.get(tracker_id, [])):
                    anchor = _VER_NUM_RE.split(term, 1)[0].strip()      # text before the version
                    floor = _highest_alias_version(aliases_by_tracker.get(tracker_id, []), anchor)
                    v = _version_of(term)
                    if floor is not None and v is not None and v < floor:
                        continue          # an older version than one already watched
                    key = (tracker_id, "term", term.lower())
                    counts.setdefault(key, {"value": term, "threads": set()})["threads"].add(tid)
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
        # 自然新版本 (author ruling 2026-09-18): a version phrase anchored on the
        # target's own name, at or above every version it already watches, and
        # recurring across several threads needs nobody's confirmation. It is
        # applied on the spot; the user is told, not asked. Accounts and
        # publishers still ask — following a person is a judgement call.
        auto = 0
        for row in session.exec(select(EmergentSource).where(
                EmergentSource.kind == "term", EmergentSource.status == "pending")).all():
            tr = session.get(Tracker, row.tracker_id)
            if tr is None or _version_of(row.value) is None:
                continue          # only version phrases self-apply; people/orgs wait for a click
            if _apply_term_alias(session, tr, row):
                auto += 1
                logger.info(f"Emergent term auto-added as alias: '{row.value}' → target '{tr.name}' "
                            f"({row.thread_count} threads)")
        session.commit()
    logger.info(f"Emergent sources: scanned {len(threads)} threads, {candidates} candidates, {new} new, "
                f"{auto} version terms auto-added")
    return {"scanned_threads": len(threads), "candidates": candidates, "new": new, "terms_auto_added": auto}


def _apply_term_alias(session, tracker, row) -> bool:
    """A recurring version phrase becomes an alias of its target: the matcher
    and the per-alias routes derive from aliases, so the next leak under that
    name is both fetched and related. Returns True if the alias was new."""
    try:
        policy = json.loads(tracker.fetch_policy) if tracker.fetch_policy else {}
    except Exception:
        policy = {}
    ip = policy.get("intent_plan") or {}
    added = False
    if row.value.lower() not in {str(e).lower() for e in policy.get("entities") or []}:
        policy.setdefault("entities", []).append(row.value)
        ip.setdefault("entities", []).append({"text": row.value, "lang": "en", "regions": ["US"], "role": "product"})
        added = True
    policy["intent_plan"] = ip
    tracker.fetch_policy = json.dumps(policy)
    row.status = "accepted"; row.updated_at = datetime.utcnow()
    session.add(tracker); session.add(row)
    return added


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
        if row.kind == "term":
            _apply_term_alias(session, tracker, row); session.commit()
            return {"ok": True, "added": {"kind": "term", "value": row.value}}
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
