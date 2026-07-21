"""
Publish exporter (R7 Phase 1) — the missing half of the site groundwork.

Turns local StoryThreads into a PublishedDigest v0.1 JSON (docs/publish_contract.md)
that the public site (site/) consumes. Every thread passes the compliance gate
(§6): summary not full text, PII cleaned, authorized-source content excluded,
source provenance (title+url+time), honest AI labeling. The site trusts the
result and never touches the DB.

Form A ("desktop push") per official_feed_automation.md: a scheduler task writes
site/data/digest.json (+ generated RSS). No Supabase needed at this phase —
publisher.signature stays null (multi-publisher signing is Phase 2).
"""
import json
import hashlib
import os
import urllib.parse
from datetime import datetime, timezone, timedelta
from xml.sax.saxutils import escape as xml_escape

from sqlmodel import select

from services.log_service import get_logger
from services.privacy import clean_pii, scrub_sensitive_info

logger = get_logger("publish")

CONTRACT_VERSION = "0.1"
PUBLIC_SUMMARY_MAX_CHARS = 500   # §6.1
QUOTE_MAX_CHARS = 120            # §6.2
INSTANCE_ID = os.environ.get("PUBLISH_INSTANCE_ID", "author-main")
PUBLISHER_NAME = os.environ.get("PUBLISH_PUBLISHER_NAME", "majorflow")


def _now():
    return datetime.now(timezone.utc)


def _iso(dt) -> str:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _public_id(thread_id: int) -> str:
    """Stable public id — never expose the raw autoincrement int (§5 mapping)."""
    h = hashlib.sha256(f"{INSTANCE_ID}:{thread_id}".encode()).hexdigest()[:8]
    return f"thr_{h}"


def _domain(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return ""


def _auth_platform_domains() -> set:
    from scrapers.auth_helper import AUTH_PLATFORMS
    out = set()
    for p in AUTH_PLATFORMS.values():
        for d in p.get("domains", []):
            out.add(d.lower())
    return out


def _source_kind(url: str) -> str:
    from services.semantic_ingest import _is_first_party
    if _is_first_party(url):
        return "first_party"
    d = _domain(url)
    social = ("x.com", "twitter.com", "reddit.com", "news.ycombinator.com", "weibo.com",
              "bilibili.com", "xiaohongshu.com", "instagram.com", "tiktok.com")
    if any(s in d for s in social):
        return "social"
    if "rsshub" in d or "nitter" in d or "news.google.com" in d:
        return "generated_feed"
    return "media"


def _fact_level(lifecycle: str, distinct_sources: int) -> str:
    """§5 derivation. We can't detect source conflict without conflict data, so
    'disputed' is not emitted here (a future enrichment); default is conservative."""
    if lifecycle == "CONFIRMED":
        return "verified"
    if lifecycle == "CORROBORATED":
        return "verified"
    if lifecycle == "LEAD" and distinct_sources <= 1:
        return "observed"
    return "low_confidence"


def build_published_digest(window_hours: int = 168) -> dict:
    """Build the PublishedDigest v0.1 dict from local data, gated for compliance."""
    from db.database import get_session
    from db.models import StoryThread, RawArticle, RadarAlert, Tracker

    now = _now()
    since = (now - timedelta(hours=window_hours)).replace(tzinfo=None)
    auth_domains = _auth_platform_domains()

    threads_out = []
    topics_seen = {}
    excluded_auth = 0

    with get_session() as session:
        threads = session.exec(
            select(StoryThread).where(StoryThread.last_update_at >= since)
            .order_by(StoryThread.is_resonant.desc(), StoryThread.last_update_at.desc())
        ).all()

        for th in threads:
            members = session.exec(
                select(RawArticle).where(RawArticle.thread_id == th.id)
                .order_by(RawArticle.created_at.desc())
            ).all()
            if not members:
                continue

            # §6.4 HARD GATE: exclude any thread carrying content from an
            # authorized (cookie/login) platform domain — auth content never
            # leaves the machine. Conservative domain match (over-excludes).
            if any(any(ad in _domain(m.url) for ad in auth_domains) for m in members):
                excluded_auth += 1
                continue

            alerts = session.exec(
                select(RadarAlert).where(RadarAlert.thread_id == th.id)
                .order_by(RadarAlert.created_at.desc())
            ).all()

            # Sources (§5): title + url + published_at, kind, first_party first.
            sources = []
            for m in members[:8]:
                sources.append({
                    "title": clean_pii(m.title or ""),
                    "url": m.url,
                    "site": _domain(m.url),
                    "kind": _source_kind(m.url),
                    "published_at": _iso(m.published_at or m.created_at),
                    "quote": None,
                })
            order = {"first_party": 0, "media": 1, "generated_feed": 2, "social": 3}
            sources.sort(key=lambda s: order.get(s["kind"], 4))

            # Summary (§6.1): a synthesized alert summary if present, else an
            # extractive fallback (thread title) — never full text; PII-cleaned;
            # capped. ai_generated / method are honest (盲区 #4).
            alert_summary = next((a.summary for a in alerts if a.summary), None)
            if alert_summary:
                # Strip the citation block the alert appends; keep the prose.
                text = alert_summary.split("\n\n**")[0].strip()
                summary = {"text": clean_pii(text)[:PUBLIC_SUMMARY_MAX_CHARS],
                           "language": "zh", "ai_generated": True, "method": "synthesized"}
            else:
                summary = {"text": clean_pii(th.title or "")[:PUBLIC_SUMMARY_MAX_CHARS],
                           "language": "zh", "ai_generated": False, "method": "extractive"}

            # Increments (§5): from the alert history (what changed, when).
            increments = [{
                "at": _iso(a.created_at),
                "note": clean_pii((a.title or a.reason or "")[:200]),
                "citation_indexes": [0],
            } for a in alerts[:6]]
            if not increments:
                increments = [{
                    "at": _iso(th.first_seen_at),
                    "note": "首次聚类" if summary["language"] == "zh" else "first clustered",
                    "citation_indexes": [0],
                }]

            topic_id = f"topic-{th.tracker_id}" if th.tracker_id else "topic-general"
            if topic_id not in topics_seen and th.tracker_id:
                tr = session.get(Tracker, th.tracker_id)
                topics_seen[topic_id] = {
                    "id": topic_id,
                    "title": (tr.name if tr else "综合"),
                    "description": (tr.radar_section if tr else ""),
                    "language": "zh",
                }

            threads_out.append({
                "id": _public_id(th.id),
                "topic_id": topic_id,
                "title": clean_pii(th.title or ""),
                "lifecycle": th.lifecycle,
                "fact_level": _fact_level(th.lifecycle, th.distinct_source_count),
                "importance": th.importance_score or (4 if th.lifecycle == "CONFIRMED" else 3 if th.lifecycle == "CORROBORATED" else 2),
                "is_resonant": th.is_resonant,
                "distinct_source_count": th.distinct_source_count,
                "first_seen_at": _iso(th.first_seen_at),
                "last_update_at": _iso(th.last_update_at),
                "summary": summary,
                "increments": increments,
                "sources": sources,
                # §6 gate outcomes — the site trusts these.
                "provenance": {"pii_cleaned": True, "auth_content_excluded": True, "rights": "public_summary"},
            })

    # Stats (§3, optional) — the quiet "noise filtered" line (盲区 #8). Emit the
    # full get_radar_stats subset the site reads (window_hours / noise_filtered /
    # duplicates_merged / events_tracked / ...).
    try:
        from services.radar_digest import get_radar_stats
        stats = get_radar_stats(window_hours)
    except Exception:
        stats = None

    logger.info(f"Published digest: {len(threads_out)} threads, {len(topics_seen)} topics, "
                f"{excluded_auth} excluded (auth content).")
    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": _iso(now),
        "publisher": {"name": PUBLISHER_NAME, "instance_id": INSTANCE_ID, "signature": None},
        "window": {"from": _iso(now - timedelta(hours=window_hours)), "to": _iso(now)},
        "topics": list(topics_seen.values()),
        "threads": threads_out,
        "stats": stats,
    }


def _site_data_dir() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(root, "site", "data")
    os.makedirs(d, exist_ok=True)
    return d


def write_site_digest(window_hours: int = 168) -> dict:
    """Form A push: build the digest and write site/data/digest.json + RSS."""
    digest = build_published_digest(window_hours)
    data_dir = _site_data_dir()
    with open(os.path.join(data_dir, "digest.json"), "w", encoding="utf-8") as f:
        json.dump(digest, f, ensure_ascii=False, indent=2)
    _write_rss(digest, data_dir)
    return {"threads": len(digest["threads"]), "topics": len(digest["topics"])}


def _write_rss(digest: dict, data_dir: str):
    """Generated RSS (§7): item = a thread's latest increment; guid = id+time."""
    items = []
    for t in digest["threads"]:
        link = t["sources"][0]["url"] if t["sources"] else ""
        desc = scrub_sensitive_info(t["summary"]["text"])
        items.append(
            f"<item><title>{xml_escape(t['title'])}</title>"
            f"<link>{xml_escape(link)}</link>"
            f"<guid isPermaLink=\"false\">{t['id']}:{t['last_update_at']}</guid>"
            f"<pubDate>{xml_escape(t['last_update_at'] or '')}</pubDate>"
            f"<description>{xml_escape(desc)}</description></item>"
        )
    rss = (f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<rss version=\"2.0\"><channel>"
           f"<title>MajorRSS · {PUBLISHER_NAME}</title>"
           f"<description>去噪情报分发</description>"
           f"<lastBuildDate>{digest['generated_at']}</lastBuildDate>"
           + "".join(items) + "</channel></rss>")
    with open(os.path.join(data_dir, "feed.xml"), "w", encoding="utf-8") as f:
        f.write(rss)
