import os
import re
import hashlib
import json
import urllib.parse
from datetime import datetime, timezone
from repositories.repository import DBRepository
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


# Feed boilerplate that precedes the real text. Measured on live data: arXiv
# items begin "arXiv:2607.20452v1 Announce Type: new", which is metadata, not the
# abstract.
_BOILERPLATE = re.compile(
    r"^\s*(?:arxiv:\S+\s*)?(?:announce\s+type:\s*\w+\s*)?"
    r"(?:abstract:\s*)?", re.I)


def _lead_snippet(content: str, title: str = "", limit: int = 300) -> str:
    """The source's own opening, cleaned for display.

    RawArticle.content keeps its HTML (clean_html only strips script/style), so
    tags must come off here or they land in the feed verbatim — measured:
    "<p>Changes since langchain-openai==1.4.0</p>". Feed boilerplate is dropped,
    and a first line that merely repeats the headline is skipped so the card does
    not say the same thing twice.
    """
    from bs4 import BeautifulSoup
    try:
        text = BeautifulSoup(content or "", "html.parser").get_text(" ", strip=True)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", content or "")
    text = _BOILERPLATE.sub("", re.sub(r"\s+", " ", text)).strip()
    if not text:
        return ""
    norm_title = re.sub(r"\W+", "", (title or "")).lower()
    parts = [p.strip() for p in re.split(r"(?<=[。．.!?！？])\s+", text) if p.strip()]
    out = []
    for p in parts:
        if re.sub(r"\W+", "", p).lower() == norm_title:
            continue                      # a line that is just the headline again
        out.append(p)
        if sum(len(x) for x in out) >= 80:  # one short sentence is rarely enough
            break
    if not out:
        # Everything the body had was the headline again (common for feeds whose
        # <description> just echoes the title). Say nothing rather than twice.
        return "" if re.sub(r"\W+", "", text).lower() == norm_title else text[:limit].strip()
    return " ".join(out)[:limit].strip()


def _extractive_summary(thread, members, tracker) -> str:
    """The 抽取式 path (愿景 line 184: 合成优先抽取式；置信不足只给原文关键句+链接).

    Used when there is nothing to SYNTHESIZE — a single source telling a story
    once. Synthesis means reconciling several accounts of one event or reporting
    what changed; with one account the source's own words are both cheaper and
    more faithful than a paraphrase (愿景 line 35: 真相与溯源). Zero LLM.
    """
    lead = members[0]
    snippet = _lead_snippet(lead.content or "", lead.title or "")
    links = "\n".join(f"- [{m.title}]({m.url})" for m in members[:8])
    return (f"[TITLE: {lead.title}]\n\n{snippet}\n\n---\n"
            f"**:material/menu_book: 摘要引用来源:**\n{links}"
            f"\n\n<br>\n\n**:material/radar: 探测任务来源 (Tracker):** `{tracker.name}`")


_SCRIPT_TESTS = (
    ("ja", re.compile(r"[぀-ヿ]")),        # kana is decisive for Japanese
    ("ko", re.compile(r"[가-힣]")),        # hangul
    ("ru", re.compile(r"[А-я]")),          # cyrillic
    ("zh", re.compile(r"[一-鿿]")),        # han without kana → Chinese
)


def _detect_language(text: str) -> str:
    """Coarse language of a source item, by script. Kana/hangul/cyrillic are
    decisive; bare han means Chinese; anything else is treated as English."""
    t = text or ""
    for code, pattern in _SCRIPT_TESTS:
        if pattern.search(t):
            return code
    return "en"


def _needs_translation(members) -> bool:
    """True when a source is not in the user's narration language.

    愿景 语言三原则①: the input language decides the NARRATION language, never
    the search scope — a Chinese user tracking a topic should receive Japanese
    and English coverage rendered in Chinese, because some things surface earlier
    in another language and different countries report different angles. The
    extractive path quotes a source verbatim, so using it across a language
    boundary would drop raw foreign text into the AI feed and collapse that
    surface into what the lead view already is. Translation is the whole reason
    that surface exists, so it is worth the tokens.

    Note this compares SPECIFIC languages, not a CJK/non-CJK split: a Japanese
    post is just as foreign to a Chinese reader as an English one.
    """
    target = (os.environ.get("SYSTEM_LANGUAGE", "zh") or "zh").strip().lower()[:2]
    for m in members:
        src = _detect_language((m.title or "") + " " + (m.content or "")[:300])
        if src != target:
            return True
    return False


def _has_something_to_synthesize(thread, members) -> bool:
    """Does this thread need a GENERATION model, or is extraction enough?

    愿景 line 73 says synthesis happens 线索出现真实增量时 — the unit of synthesis
    is a thread's increment, not "a summary for every item". line 150 wants most
    content to never touch a generation model at all. So generation is reserved
    for the two cases where it actually adds something:
      • several independent accounts of one event to reconcile and cite
      • a re-fusion, i.e. a real increment on a thread that already has a summary
    A lone item — a 87-character tweet, one vendor blog post — has nothing to
    reconcile; summarizing it produces a paraphrase no shorter than the original.
    Measured 2026-07-29: 132 of 155 summaries (85%) were single-source.
    """
    if (thread.distinct_source_count or 0) >= 2:
        return True
    if len({(m.url or "").split("/")[2] if "//" in (m.url or "") else m.url for m in members}) >= 2:
        return True
    # Cross-language: quoting a foreign source verbatim would defeat the AI
    # feed's purpose (see _needs_translation).
    if _needs_translation(members):
        return True
    return False


def _thread_worth_summary(thread, members, tracker):
    """P1.1 channel-tiered gate: does this event-thread earn an LLM summary, or
    stay a lead (title + sources, no generation model touched)? "The source you
    opted into is itself a signal": curated presets, tracked accounts and
    first-party sources always pass; the keyword firehose must earn it via
    resonance or multi-source corroboration. Returns (worth: bool, reason: str)."""
    from services.provenance import HIGH_WEIGHT, Tier, is_tracked_account
    tiers = {getattr(m, "source_tier", None) for m in members}
    # PRIMARY only. CURATED used to auto-pass too, on the reasoning that "you
    # picked this source" — but you pick a SOURCE, not every topic it covers. A
    # portfolio blog like Cloudflare publishes on CDN, BGP and World Cup traffic
    # as well as AI, and each post was inheriting the bypass: measured, 5 of 5
    # Cloudflare summaries were off-topic (relevance 0.089-0.14, i.e. ABOVE the
    # junk floor — topical proximity cannot separate them, same lesson as P5).
    # A tracked entity's OWN domain (PRIMARY) still auto-passes: that is the
    # announcement the user is watching for. CURATED must now be relevant or
    # corroborated like anything else.
    if Tier.PRIMARY in tiers:
        return True, "first-party source"
    # Tracked accounts (the people radar) keep their bypass. Tightening CURATED
    # was aimed at portfolio blogs publishing off-topic posts; a person the user
    # NAMED is a different thing — it is the fast-tip channel the design values
    # (愿景: 社交源天然领先媒体数天) and is often foreign-language, so it is
    # precisely the content that needs synthesising into the narration language.
    if any(is_tracked_account(getattr(m, "url", "") or "") for m in members):
        return True, "tracked account (people radar)"
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
        from sqlmodel import or_
        backlog = s.exec(
            select(StoryThread.id).where(
                StoryThread.tracker_id == tracker_id,
                StoryThread.summary.is_(None),
                StoryThread.member_count > 0,
                # Re-evaluate a gated thread only when it has CHANGED since the
                # gate last saw it — not every 5-minute cycle forever (the gated
                # backlog grows unboundedly; churn must not grow with it).
                or_(StoryThread.gate_checked_at.is_(None),
                    StoryThread.last_update_at > StoryThread.gate_checked_at),
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
        # Cross-tracker duplicate guard: threads are per-tracker (semantic layer
        # clusters within a tracker), so the same event caught by two overlapping
        # trackers becomes two threads. Don't pay to summarize an event that
        # already HAS a summary on another tracker's thread — cheap title
        # near-dup check (P0.5 machinery) against recently summarized threads.
        from services.dedup import is_near_duplicate
        from datetime import timedelta
        recent_cut = (datetime.now(timezone.utc) - timedelta(days=7)).replace(tzinfo=None)
        others = session.exec(
            select(StoryThread.id, StoryThread.title).where(
                StoryThread.id != thread_id,
                StoryThread.summary.is_not(None),
                StoryThread.summarized_at >= recent_cut,
            )
        ).all()
        dup_of = next((oid for (oid, otitle) in others
                       if is_near_duplicate(thread.title or "", otitle or "")), None)
        if dup_of is not None:
            thread.gate_checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
            session.add(thread)
            for u in members:
                if not u.processed:
                    u.processed = True
                    session.add(u)
            session.commit()
            logger.info(f"Thread {thread_id} is a cross-tracker duplicate of summarized "
                        f"thread {dup_of}; skipping fusion (no double spend).")
            return

        # Material-increment gate for RE-fusion (P2.1 leftover #7): once a thread
        # has a summary, more members of the SAME story are not news. Re-fuse only
        # when the event actually developed — new independent publishers, or a
        # lifecycle promotion. Otherwise just record the new sources and leave the
        # summary (and its feed position) alone. Without this, an old thread was
        # re-summarized on every trickle of near-duplicate follow-ups and jumped
        # back to the top of the feed with no new information: measured 560 fusion
        # calls for 145 summaries (3.9x re-burn), with threads first seen 4-5 days
        # earlier sitting at the top of the feed.
        if thread.summary:
            prev_dsc = thread.fused_source_count or 0
            prev_life = thread.fused_lifecycle or ""
            _RANK = {"LEAD": 0, "CORROBORATED": 1, "CONFIRMED": 2}
            promoted = _RANK.get(thread.lifecycle or "", 0) > _RANK.get(prev_life, 0)
            if (thread.distinct_source_count or 0) <= prev_dsc and not promoted:
                thread.gate_checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
                session.add(thread)
                for u in members:
                    if not u.processed:
                        u.processed = True
                        session.add(u)
                session.commit()
                logger.info(f"Thread {thread_id}: no material increment "
                            f"(publishers {prev_dsc}→{thread.distinct_source_count}, "
                            f"{prev_life}→{thread.lifecycle}); keeping existing summary.")
                return

        worth, reason = _thread_worth_summary(thread, members, tracker)
        if not worth:
            # Mark the batch as SEEN: members flip processed=True (they were
            # deliberately held, not "pending" — the Dashboard KPI must not count
            # them forever) and the thread gets a gate marker so the backlog
            # query re-evaluates it only when it actually changes (a new member
            # bumps last_update_at and arrives processed=False, re-triggering
            # both paths). Caveat: flipping tracker.is_high_attention alone won't
            # re-gate old quiet threads until their next member (rare; the manual
            # summarize button is the escape hatch).
            thread.gate_checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
            session.add(thread)
            for u in members:
                if not u.processed:
                    u.processed = True
                    session.add(u)
            session.commit()
            logger.info(f"Thread {thread_id} gated — no summary ({reason}); stays a lead.")
            return

        # Extractive path (愿景 line 184). The thread earned a place in the feed,
        # but with a single account there is nothing to synthesize — quote the
        # source instead of paraphrasing it. Zero LLM, and more faithful.
        if thread.summary is None and not _has_something_to_synthesize(thread, members):
            thread.summary = _extractive_summary(thread, members, tracker)
            thread.validity_category = "[VALID_NEWS]"
            thread.radar_section = tracker.radar_section
            thread.key_entities = thread.key_entities or "[]"
            thread.source_url = f"Extractive from {len(members)} source(s)"
            thread.summarized_at = datetime.now(timezone.utc).replace(tzinfo=None)
            thread.fused_source_count = thread.distinct_source_count
            thread.fused_lifecycle = thread.lifecycle
            session.add(thread)
            for u in members:
                if not u.processed:
                    u.processed = True
                    session.add(u)
            session.commit()
            logger.info(f"Thread {thread_id} extractive (single source, nothing to synthesize) — no LLM.")
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
        # Snapshot the signals this fusion was based on, so the next cycle can
        # tell a real development from more copies of the same story.
        thread.fused_source_count = thread.distinct_source_count
        thread.fused_lifecycle = thread.lifecycle
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
