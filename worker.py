import sys
import os
import time
import hashlib
import concurrent.futures
from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import select
from dotenv import load_dotenv

# Ensure root is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

from db.database import get_session
from db.models import Tracker, RawArticle, IntelReport, PipelineStatus
from scrapers.tier1_rss import BasicRSSScraper
from scrapers.tier3_agentic import AgenticScraper, CookieExpiredException
from llm.processor import process_article, scan_trends
from datetime import datetime, timezone, timedelta
import json
import requests
import urllib.parse

def set_status(session, tracker_name: str, action: str, detail: str):
    new_status = PipelineStatus(
        tracker_name=tracker_name,
        action_type=action,
        detail=detail,
        updated_at=datetime.now(timezone.utc)
    )
    session.add(new_status)
    session.commit()
    
    # Keep only the latest 50 logs globally to prevent database bloat
    all_logs = session.exec(select(PipelineStatus).order_by(PipelineStatus.updated_at.desc())).all()
    if len(all_logs) > 50:
        for old_log in all_logs[50:]:
            session.delete(old_log)
        session.commit()

def clear_status(session, tracker_name: str):
    pass

def _fetch_url(session, tracker: Tracker, url: str, tier: int, max_days: int = 7) -> bool:
    """Helper to fetch and store from a specific URL. Returns True if successful."""
    try:
        if tier == 1 or tier == 2:
            scraper = BasicRSSScraper(url)
            items = scraper.fetch()
            
            # Unleash limit: iterate all items, apply time filter
            for item in items:
                if max_days > 0 and item.get("published_at"):
                    age = datetime.now(timezone.utc) - item["published_at"]
                    if age.days > max_days:
                        continue
                
                existing_url = session.exec(select(RawArticle).where(RawArticle.url == item["url"])).first()
                existing_title = session.exec(select(RawArticle).where(RawArticle.title == item["title"]).where(RawArticle.tracker_id == tracker.id)).first()
                
                if not existing_url and not existing_title:
                    raw = RawArticle(
                        tracker_id=tracker.id,
                        title=item["title"],
                        url=item["url"],
                        content=item["content"],
                        published_at=item["published_at"]
                    )
                    session.add(raw)
                    try:
                        session.commit()
                        print(f"Saved raw article: {raw.title}")
                    except Exception as commit_e:
                        session.rollback()
                        # Likely an IntegrityError from concurrent fetching, safe to ignore
                        print(f"Skipped duplicate insert due to concurrency: {raw.url}")
        elif tier == 3:
            scraper = AgenticScraper(url, tracker.cookie_string)
            text = scraper.fetch_text_snapshot()
            if text:
                content_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
                existing = session.exec(select(RawArticle).where(RawArticle.url.like(f"{url}#%")).order_by(RawArticle.created_at.desc())).first()
                
                is_duplicate = False
                if existing:
                    if existing.content == text:
                        is_duplicate = True
                    else:
                        import difflib
                        similarity = difflib.SequenceMatcher(None, existing.content, text).quick_ratio()
                        if similarity > 0.95:
                            print(f"Skipping {tracker.name}: 相似度 {similarity:.2f} > 0.95, 仅存在动态噪音。")
                            is_duplicate = True
                
                if not is_duplicate:
                    raw = RawArticle(
                        tracker_id=tracker.id,
                        title=f"Snapshot: {tracker.name}",
                        url=url + f"#{content_hash}",
                        content=text
                    )
                    session.add(raw)
                    try:
                        session.commit()
                        print(f"Saved new Agentic snapshot for {tracker.name}")
                    except Exception as commit_e:
                        session.rollback()
                        print(f"Skipped duplicate snapshot insert due to concurrency: {raw.url}")
        return True
    except CookieExpiredException as e:
        print(f"Auth Failed for {url}: {e}")
        set_status(session, tracker.name, "Auth Failed", str(e))
        return False
    except Exception as e:
        print(f"Fetch failed for {url}: {e}")
        # Extract domain for cleaner logging
        domain = urllib.parse.urlparse(url).netloc
        set_status(session, tracker.name, "Probe Failed", f"[{domain}] {e}")
        return False

def _scrape_single_tracker(tracker_id: int):
    """Worker thread function for scraping a single tracker with isolated DB session."""
    session = get_session()
    try:
        tracker = session.get(Tracker, tracker_id)
        if not tracker:
            return
            
        set_status(session, tracker.name, "Scraping", f"Tracker ({tracker.tracker_type}) is fetching data...")
        
        if tracker.tracker_type == "HYBRID":
            try:
                target_data = json.loads(tracker.target)
            except json.JSONDecodeError:
                print(f"Failed to decode HYBRID target for {tracker.name}: {tracker.target}")
                return
                
            # 1. Process specific URLs
            max_days = target_data.get("max_days", 7)
            
            for u in target_data.get("urls", []):
                _fetch_url(session, tracker, u, tier=1, max_days=max_days)
                
            # 2. Process Keywords across OSINT engines
            if target_data.get("use_default_osint", False):
                for kw in target_data.get("keywords", []):
                    encoded_kw = urllib.parse.quote(kw)
                    gnews_url = f"https://news.google.com/rss/search?q={encoded_kw}"
                    _fetch_url(session, tracker, gnews_url, tier=1, max_days=max_days)
                    
                    hn_url = f"https://hnrss.org/newest?q={encoded_kw}"
                    _fetch_url(session, tracker, hn_url, tier=1, max_days=max_days)
                    
                    reddit_url = f"https://www.reddit.com/search.rss?q={encoded_kw}&sort=new"
                    _fetch_url(session, tracker, reddit_url, tier=1, max_days=max_days)
                    
            # 3. Process Social Accounts with Nitter -> RSSHub fallback
            for acc in target_data.get("accounts", []):
                account_name = acc.replace('@', '')
                if tracker.cookie_string:
                    # High risk Tier 3 scraping using cookies directly on Twitter
                    twitter_url = f"https://twitter.com/{account_name}"
                    _fetch_url(session, tracker, twitter_url, tier=3, max_days=max_days)
                else:
                    # Low risk Tier 1 scraping using Nitter
                    nitter_url = f"https://nitter.net/{account_name}/rss"
                    success = _fetch_url(session, tracker, nitter_url, tier=1, max_days=max_days)
                    if not success:
                        print(f"Nitter failed for {account_name}, falling back to RSSHub...")
                        set_status(session, tracker.name, "Fallback", f"Nitter failed, automatically switching to RSSHub for {account_name}")
                        rsshub_url = f"https://rsshub.app/twitter/user/{account_name}"
                        _fetch_url(session, tracker, rsshub_url, tier=1, max_days=max_days)

        tracker.last_scraped_at = datetime.now(timezone.utc)
        session.add(tracker)
        session.commit()
        clear_status(session, tracker.name)
    except Exception as e:
        print(f"Error scraping tracker {tracker_id}: {e}")
        tracker = session.get(Tracker, tracker_id)
        if tracker:
            set_status(session, tracker.name, "Error", f"Scraping failed: {e}")

def run_scraping_job():
    print("Running scheduled scraping job...")
    session = get_session()
    trackers = session.exec(select(Tracker).where(Tracker.is_active == True)).all()
    
    trackers_to_run = []
    now = datetime.now(timezone.utc)
    for t in trackers:
        if not t.last_scraped_at:
            trackers_to_run.append(t)
        else:
            last_scraped = t.last_scraped_at
            if last_scraped.tzinfo is None:
                last_scraped = last_scraped.replace(tzinfo=timezone.utc)
                
            if now - last_scraped >= timedelta(minutes=t.fetch_interval_minutes):
                trackers_to_run.append(t)
            else:
                next_in = t.fetch_interval_minutes - (now - last_scraped).total_seconds() / 60
                print(f"Skipping {t.name}, next scrape in {next_in:.1f} minutes.")
                
    if not trackers_to_run:
        print("No trackers ready for scraping.")
        return
    
    # Run scraping concurrently, max 5 threads
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_scrape_single_tracker, t.id) for t in trackers_to_run]
        concurrent.futures.wait(futures)

def _process_tracker_fusion(tracker_id: int):
    """Worker thread function for Intelligence Fusion: process all unprocessed articles for a tracker."""
    session = get_session()
    try:
        tracker = session.get(Tracker, tracker_id)
        if not tracker: return
        
        # Batch processing: take up to 50 newest to avoid payload too large
        unprocessed = session.exec(select(RawArticle).where(RawArticle.tracker_id == tracker_id, RawArticle.processed == False).order_by(RawArticle.created_at.desc()).limit(50)).all()
        if not unprocessed: return
        
        set_status(session, tracker.name, "AI Fusion", f"Gemini is cross-validating {len(unprocessed)} sources...")
        
        bundled_text = f"=== OSINT FUSION FOR TARGET: {tracker.target} ===\n\n"
        for idx, u in enumerate(unprocessed):
            # Unleash limit: send full content to LLM
            bundled_text += f"Source {idx+1}: {u.url}\nTitle: {u.title}\nContent:\n{u.content}\n\n"
            
        result = process_article(bundled_text, tracker.radar_section, prompt_override=tracker.prompt_override, tracker_name=tracker.name)
        
        # Link report to the first raw article for FK constraint
        lead_article = unprocessed[0]
        
        # Build composite URL showing breadth
        composite_urls = ", ".join([urllib.parse.urlparse(u.url).netloc for u in unprocessed])
        if len(composite_urls) > 80:
            composite_urls = composite_urls[:77] + "..."
            
        # Filter sources based on LLM's relevance array
        if hasattr(result, 'relevant_source_indices') and result.relevant_source_indices:
            valid_sources = [unprocessed[i-1] for i in result.relevant_source_indices if 1 <= i <= len(unprocessed)]
        else:
            valid_sources = unprocessed
            
        # Append clickable source links to the summary
        source_links = "\n".join([f"- [{u.title}]({u.url})" for u in valid_sources])
        final_summary = f"{result.llm_summary}\n\n---\n**📚 Source Evidence:**\n{source_links}"
        
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
        session.add(report)
        
        for u in unprocessed:
            u.processed = True
            session.add(u)
            
        session.commit()
        print(f"Fused {len(unprocessed)} articles into IntelReport: {report.validity_category} - Score {report.importance_score}")
        clear_status(session, tracker.name)
    except Exception as e:
        print(f"Error fusing tracker {tracker_id}: {e}")
        tracker = session.get(Tracker, tracker_id)
        if tracker:
            set_status(session, tracker.name, "Error", f"AI Fusion failed: {e}")

def run_processing_job():
    print("Running Intelligence Fusion job...")
    session = get_session()
    
    # Find trackers that have unprocessed articles
    trackers_with_work = session.exec(select(RawArticle.tracker_id).where(RawArticle.processed == False).distinct()).all()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_process_tracker_fusion, tid) for tid in trackers_with_work]
        concurrent.futures.wait(futures)

def run_trend_scan_job():
    print("Running scheduled trend scan job...")
    try:
        scan_trends()
    except Exception as e:
        print(f"Error scanning trends: {e}")

from db.database import create_db_and_tables
from worker_subscription import run_subscription_job

def start_scheduler():
    # Ensure database and tables exist before starting jobs
    create_db_and_tables()
    
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_scraping_job, 'interval', minutes=30)
    scheduler.add_job(run_processing_job, 'interval', minutes=5)
    scheduler.add_job(run_trend_scan_job, 'interval', hours=2)
    scheduler.add_job(run_subscription_job, 'interval', minutes=5)
    scheduler.start()
    print("Scheduler started. Press Ctrl+C to exit.")
    
    # Run once immediately
    run_scraping_job()
    run_processing_job()
    run_trend_scan_job()
    run_subscription_job()
    
    try:
        while True:
            time.sleep(2)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()

if __name__ == "__main__":
    start_scheduler()
