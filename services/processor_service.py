import os
import hashlib
import json
import urllib.parse
from datetime import datetime, timezone
from repositories.repository import DBRepository
from db.models import IntelReport
from llm.processor import process_article
from services.app_mode import is_pure_rss_mode
from services.log_service import get_logger

db = DBRepository()
logger = get_logger("processor")

# Token economy guards. Agentic snapshots put the entire page text into a
# single article; without truncation one snapshot can cost tens of thousands
# of prompt tokens on its own.
MAX_CHARS_PER_ARTICLE = int(os.environ.get("LLM_MAX_CHARS_PER_ARTICLE", "6000"))
MAX_CHARS_PER_BUNDLE = int(os.environ.get("LLM_MAX_CHARS_PER_BUNDLE", "36000"))
# Cap how many of a thread's members are sent to the LLM per (re)fusion so a
# large accreting thread doesn't re-send everything each cycle (bounded cost).
# Provenance/counts still reflect ALL members — only the LLM input is capped.
FUSION_MAX_MEMBERS = int(os.environ.get("FUSION_MAX_MEMBERS", "12"))
# P1.1 gate: an aggregator-only (firehose) thread must reach this many DISTINCT
# publishers before it earns an LLM summary. Curated/first-party/high-attention
# sources bypass the gate entirely (opt-in is itself a signal).
FUSION_MIN_SOURCES = int(os.environ.get("FUSION_MIN_SOURCES", "3"))


def _thread_worth_summary(thread, members, tracker):
    """P1.1 channel-tiered gate: does this event-thread earn an LLM summary, or
    stay a lead (title + sources, no generation model touched)? "The source you
    opted into is itself a signal": curated presets, tracked accounts and
    first-party sources always pass; the keyword firehose must earn it via
    resonance or multi-source corroboration. Returns (worth: bool, reason: str)."""
    from services.provenance import HIGH_WEIGHT
    tiers = {getattr(m, "source_tier", None) for m in members}
    if tiers & set(HIGH_WEIGHT):
        return True, "high-weight source (curated/first-party/account)"
    if thread.lifecycle == "CONFIRMED":            # a first-party source is present
        return True, "CONFIRMED lifecycle"
    if getattr(tracker, "is_high_attention", False):
        return True, "high-attention target"
    if thread.is_resonant:
        return True, "resonant"
    if (thread.distinct_source_count or 0) >= FUSION_MIN_SOURCES:
        return True, f"{thread.distinct_source_count} distinct publishers"
    return False, "aggregator-only, not resonant, < min distinct publishers"

def get_todays_token_usage() -> int:
    """Total tokens spent today (UTC), across all models and actions."""
    from datetime import datetime, timezone
    from sqlmodel import select, func
    from db.database import get_session
    from db.models import TokenUsage
    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
    with get_session() as session:
        total = session.exec(
            select(func.coalesce(func.sum(TokenUsage.total_tokens), 0)).where(TokenUsage.created_at >= day_start)
        ).one()
    return int(total or 0)

def is_llm_budget_exhausted() -> bool:
    """LLM_DAILY_TOKEN_BUDGET > 0 enables a hard daily spend ceiling (BYOK
    users pay per token; a runaway noisy source must not drain their quota)."""
    budget = int(os.environ.get("LLM_DAILY_TOKEN_BUDGET", "0"))
    if budget <= 0:
        return False
    used = get_todays_token_usage()
    if used >= budget:
        logger.warning(f"Daily LLM token budget exhausted: {used}/{budget}. Skipping LLM processing until tomorrow (UTC).")
        return True
    return False

def process_tracker_fusion(tracker_id: int):
    """P2.1: fuse per EVENT-THREAD, not blind 10-article batches. The semantic
    layer already merged same-event articles into one StoryThread; fusion now
    summarizes a thread's members into ONE summary on the thread. This fixes the
    fragmentation (one event → one card, not N) and removes the cross-report dedup
    machinery (the thread IS the dedup unit). Articles without a thread_id are NOT
    fused — they wait for the semantic layer to cluster them (cluster-first, then
    LLM). IntelReport is deprecated; the summary lives on StoryThread.summary."""
    if is_pure_rss_mode():
        return

    tracker = db.get_tracker(tracker_id)
    if not tracker:
        return

    import time
    from db.database import get_session
    from db.models import RawArticle, StoryThread
    from sqlmodel import select

    with get_session() as s:
        # Threads with NEW unprocessed (non-gated) members — fresh content.
        rows = s.exec(
            select(RawArticle.thread_id).where(
                RawArticle.tracker_id == tracker_id,
                RawArticle.processed == False,
                RawArticle.relevance_gated == False,
                RawArticle.thread_id.is_not(None),
            ).distinct()
        ).all()
        # Threads never summarized yet (backlog / post-deploy transition): their
        # members may already be processed, so normal fusion would skip them
        # forever. Fold them in HERE — this IS the backfill, so the feed
        # self-populates after deploy with no dead function or manual step. Once
        # summarized they drop out unless new members arrive. (When the P1.1 gate
        # lands it applies here too, so noise threads aren't backfilled.)
        backlog = s.exec(
            select(StoryThread.id).where(
                StoryThread.tracker_id == tracker_id,
                StoryThread.summary.is_(None),
                StoryThread.member_count > 0,
            )
        ).all()
    pending_thread_ids = list({tid for tid in rows if tid is not None} | set(backlog))

    for thread_id in pending_thread_ids:
        if is_llm_budget_exhausted():
            db.set_pipeline_status(tracker.name, "AI Fusion",
                                   "Daily LLM token budget exhausted; deferring processing to tomorrow.")
            break
        try:
            _fuse_thread(tracker, thread_id)
        except Exception as e:
            logger.error(f"Fusion failed for thread {thread_id}: {e}", exc_info=e)
        # Protect API RPM between per-thread summaries.
        time.sleep(1.5)


def _fuse_thread(tracker, thread_id: int):
    """Summarize one event-thread's members into StoryThread.summary."""
    from db.database import get_session
    from db.models import RawArticle, StoryThread
    from sqlmodel import select

    with get_session() as session:
        thread = session.get(StoryThread, thread_id)
        if not thread:
            return
        members = session.exec(
            select(RawArticle).where(RawArticle.thread_id == thread_id)
            .order_by(RawArticle.created_at.desc())
        ).all()
        if not members:
            return

        # P1.1 channel-tiered gate: only worthy threads earn an LLM summary; the
        # rest stay leads (visible in the radar as title + sources, no generation
        # model spent). Members are NOT marked processed on a gate miss, so the
        # thread is re-evaluated next cycle — one that later gains resonance or a
        # curated source gets summarized then.
        worth, reason = _thread_worth_summary(thread, members, tracker)
        if not worth:
            logger.info(f"Thread {thread_id} gated — no summary ({reason}); stays a lead.")
            return

        # What to SEND to the LLM: newest members (latest developments), capped for
        # cost (#7), PLUS the original lead (oldest) so re-fusion never summarizes
        # off follow-up chatter alone (#6). Provenance/counts use ALL members (#2).
        to_send = list(members[:FUSION_MAX_MEMBERS])
        lead = members[-1]
        if lead not in to_send:
            to_send.append(lead)

        selected, entries, total_chars = [], [], 0
        for u in to_send:
            content = (u.content or "")
            if len(content) > MAX_CHARS_PER_ARTICLE:
                content = content[:MAX_CHARS_PER_ARTICLE] + "\n[... content truncated ...]"
            published_str = f"\nPublished: {u.published_at.isoformat()}" if u.published_at else ""
            entry = f"Source {len(selected)+1}: {u.url}\nTitle: {u.title}{published_str}\nContent:\n{content}\n\n"
            if selected and total_chars + len(entry) > MAX_CHARS_PER_BUNDLE:
                break
            selected.append(u)
            entries.append(entry)
            total_chars += len(entry)

        db.set_pipeline_status(tracker.name, "AI Fusion",
                               f"Summarizing event thread ({len(members)} sources)...")
        bundled_text = f"=== OSINT FUSION FOR TARGET: {tracker.target} ===\n\n" + "".join(entries)
        result = process_article(
            bundled_text, tracker.radar_section,
            prompt_override=tracker.prompt_override, tracker_name=tracker.name,
        )

        # Cited = sources the summary is based on; the rest are same-event
        # corroboration (honest labels, per P0.2), not noise.
        if getattr(result, "relevant_source_indices", None):
            valid_sources = [selected[i - 1] for i in result.relevant_source_indices if 1 <= i <= len(selected)]
        else:
            valid_sources = list(selected)
        if not valid_sources:
            valid_sources = list(selected)
        valid_ids = {u.id for u in valid_sources}
        # Corroboration = every OTHER member of the event, INCLUDING members past
        # the char/count cap — so nothing is silently dropped from provenance (#2).
        other_sources = [u for u in members if u.id not in valid_ids]

        cited_links = "\n".join([f"- [{u.title}]({u.url})" for u in valid_sources])
        other_links = "\n".join([f"- [{u.title}]({u.url})" for u in other_sources])
        dup_block = (
            f"\n\n**:material/content_copy: 重复/佐证来源（同一事件的其他报道）:**\n{other_links}"
            if other_sources else ""
        )
        final_summary = (
            f"[TITLE: {result.title}]\n\n{result.llm_summary}\n\n---\n"
            f"**:material/menu_book: 摘要引用来源:**\n{cited_links}"
            f"{dup_block}"
            f"\n\n<br>\n\n**:material/radar: 探测任务来源 (Tracker):** `{tracker.name}`"
        )
        composite_urls = ", ".join([urllib.parse.urlparse(u.url).netloc for u in members])
        if len(composite_urls) > 80:
            composite_urls = composite_urls[:77] + "..."

        # Keep-best guard (#6): a low-value follow-up must not erase a surfaced
        # event. Never demote an already-VALID thread to noise; keep max importance.
        _VALID = ("[VALID_NEWS]", "VALID_NEWS")
        new_validity = result.validity_category
        if (thread.validity_category in _VALID) and (new_validity not in _VALID):
            new_validity = thread.validity_category
        thread.summary = final_summary
        thread.validity_category = new_validity
        thread.radar_section = tracker.radar_section
        thread.importance_score = max(int(thread.importance_score or 0), int(result.importance_score or 0))
        thread.key_entities = json.dumps(result.key_entities)
        thread.event_timestamp = result.event_timestamp
        thread.source_url = f"Fused from {len(members)} sources ({composite_urls})"
        thread.summarized_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.add(thread)

        # Mark every member processed (even those past the char budget — they are
        # the same event, represented by this summary; must not be re-fused).
        for u in members:
            if not u.processed:
                u.processed = True
                session.add(u)
        session.commit()
        logger.info(f"Fused thread {thread_id}: {thread.validity_category} score {thread.importance_score} "
                    f"({len(selected)} sent / {len(members)} members)")
