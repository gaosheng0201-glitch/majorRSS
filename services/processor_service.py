import os
import hashlib
import json
import urllib.parse
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
    if is_pure_rss_mode():
        return

    tracker = db.get_tracker(tracker_id)
    if not tracker: return

    import time

    # Process unprocessed articles in batches of 10 in a sequential loop
    batch_size = 10

    while True:
        if is_llm_budget_exhausted():
            db.set_pipeline_status(tracker.name, "AI Fusion", "Daily LLM token budget exhausted; deferring processing to tomorrow.")
            break

        unprocessed = db.get_unprocessed_articles(tracker_id, limit=batch_size)
        if not unprocessed:
            break

        # 1. Fetch recent reports for deduplication context
        recent_reports = db.get_recent_reports(tracker.radar_section, limit=8)
        recent_context = ""
        if recent_reports:
            context_items = []
            for r in recent_reports:
                summary_text = r.llm_summary.split("\n\n---")[0] if "\n\n---" in r.llm_summary else r.llm_summary
                context_items.append(f"Report ID: {r.id}\nCategory: {r.validity_category}\nSummary: {summary_text}")
            recent_context = "\n\n".join(context_items)

        # Bundle with per-article truncation and a total-size ceiling. Articles
        # that do not fit stay processed=False and are picked up next loop.
        selected = []
        entries = []
        total_chars = 0
        for u in unprocessed:
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
        unprocessed = selected

        db.set_pipeline_status(tracker.name, "AI Fusion", f"Gemini is cross-validating a batch of {len(unprocessed)} sources...")

        bundled_text = f"=== OSINT FUSION FOR TARGET: {tracker.target} ===\n\n" + "".join(entries)
            
        result = process_article(
            bundled_text, 
            tracker.radar_section, 
            prompt_override=tracker.prompt_override, 
            tracker_name=tracker.name,
            recent_context=recent_context
        )
        
        # Extract valid sources based on LLM relevant indices
        if hasattr(result, 'relevant_source_indices') and result.relevant_source_indices:
            valid_sources = [unprocessed[i-1] for i in result.relevant_source_indices if 1 <= i <= len(unprocessed)]
        else:
            valid_sources = unprocessed

        # 2. Check if this batch is a duplicate of a recent report
        merged = False
        if hasattr(result, 'duplicate_of_report_id') and result.duplicate_of_report_id is not None:
            # Try to merge sources into existing report
            merged = db.append_sources_to_report(result.duplicate_of_report_id, valid_sources, unprocessed)
            if merged:
                logger.info(f"Deduplication: Merged {len(unprocessed)} articles into existing IntelReport {result.duplicate_of_report_id}")
                db.set_pipeline_status(tracker.name, "AI Fusion", f"Deduplication: Merged batch into existing report ID: {result.duplicate_of_report_id}")
        
        # 3. If not merged (either duplicate_of_report_id was null, or report was not found in DB)
        if not merged:
            lead_article = unprocessed[0]
            if hasattr(result, 'relevant_source_indices') and result.relevant_source_indices:
                # Pydantic 1-based index to 0-based Python list index
                first_valid_idx = result.relevant_source_indices[0] - 1
                if 0 <= first_valid_idx < len(unprocessed):
                    lead_article = unprocessed[first_valid_idx]
                    
            composite_urls = ", ".join([urllib.parse.urlparse(u.url).netloc for u in unprocessed])
            if len(composite_urls) > 80:
                composite_urls = composite_urls[:77] + "..."
                
            source_links = "\n".join([f"- [{u.title}]({u.url})" for u in valid_sources])
            raw_urls_md = "\n".join([f"- {u.url}" for u in unprocessed])
            
            final_summary = f"[TITLE: {result.title}]\n\n{result.llm_summary}\n\n---\n**:material/menu_book: Source Evidence:**\n{source_links}\n\n<br>\n\n**:material/radar: 探测任务来源 (Tracker):** `{tracker.name}`\n\n**:material/link: 本次融合的所有原始 URL (含被过滤的噪音):**\n{raw_urls_md}"
            
            report = IntelReport(
                raw_article_id=lead_article.id,
                source_url=f"Fused from {len(unprocessed)} sources ({composite_urls})",
                validity_category=result.validity_category,
                radar_section=tracker.radar_section,
                llm_summary=final_summary,
                importance_score=result.importance_score,
                original_content_hash=hashlib.sha256(bundled_text.encode('utf-8')).hexdigest(),
                key_entities=json.dumps(result.key_entities),
                event_timestamp=result.event_timestamp
            )
            
            db.save_intel_report(report, unprocessed)
            logger.info(f"Fused {len(unprocessed)} articles into IntelReport: {report.validity_category} - Score {report.importance_score}")
        
        # Add 1.5s delay between batches to protect API RPM rate limits
        time.sleep(1.5)
