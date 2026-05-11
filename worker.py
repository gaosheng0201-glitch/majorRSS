import sys
import os
import time
import hashlib
from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import select
from dotenv import load_dotenv

# Ensure root is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

from db.database import get_session
from db.models import Source, RawArticle, IntelReport, PipelineStatus
from scrapers.tier1_rss import BasicRSSScraper
from scrapers.tier3_agentic import AgenticScraper
from llm.processor import process_article, scan_trends
from datetime import datetime, timezone
import json
import requests

def set_status(session, source_name: str, action: str, detail: str):
    new_status = PipelineStatus(
        source_name=source_name,
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

def clear_status(session, source_name: str):
    # No longer delete, just append an idle/completed state if needed
    pass

def run_scraping_job():
    print("Running scheduled scraping job...")
    session = next(get_session())
    sources = session.exec(select(Source).where(Source.is_active == True)).all()
    
    for source in sources:
        try:
            set_status(session, source.name, "Scraping", f"Tier {source.tier} scraper is fetching data...")
            if source.tier == 1 or source.tier == 2:
                scraper = BasicRSSScraper(source.url)
                items = scraper.fetch()
                
                # Take top 3 to avoid spamming the LLM
                for item in items[:3]:
                    existing = session.exec(select(RawArticle).where(RawArticle.url == item["url"])).first()
                    if not existing:
                        raw = RawArticle(
                            source_id=source.id,
                            title=item["title"],
                            url=item["url"],
                            content=item["content"],
                            published_at=item["published_at"]
                        )
                        session.add(raw)
                        session.commit()
                        print(f"Saved raw article: {raw.title}")
            elif source.tier == 3:
                scraper = AgenticScraper(source.url)
                text = scraper.fetch_text_snapshot()
                if text:
                    content_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
                    existing = session.exec(select(RawArticle).where(RawArticle.url == source.url).order_by(RawArticle.created_at.desc())).first()
                    
                    if not existing or existing.content != text:
                        raw = RawArticle(
                            source_id=source.id,
                            title=f"Snapshot: {source.name}",
                            url=source.url + f"#{content_hash}", # unique pseudo-url
                            content=text
                        )
                        session.add(raw)
                        session.commit()
                        print(f"Saved new Agentic snapshot for {source.name}")
            
            clear_status(session, source.name)
        except Exception as e:
            print(f"Error scraping source {source.name}: {e}")
            set_status(session, source.name, "Error", f"Scraping failed: {e}")

def run_processing_job():
    print("Running scheduled processing job...")
    session = next(get_session())
    unprocessed = session.exec(select(RawArticle).where(RawArticle.processed == False)).all()
    
    for raw in unprocessed:
        try:
            source = session.get(Source, raw.source_id)
            set_status(session, source.name, "AI Processing", f"Gemini 3.1 Pro is fact-checking '{raw.title[:30]}...'")
            result = process_article(raw.content, source.radar_section)
            
            report = IntelReport(
                raw_article_id=raw.id,
                source_url=raw.url,
                validity_category=result.validity_category,
                radar_section=source.radar_section,
                llm_summary=result.llm_summary,
                importance_score=result.importance_score,
                original_content_hash=hashlib.sha256(raw.content.encode('utf-8')).hexdigest(),
                key_entities=json.dumps(result.key_entities)
            )
            session.add(report)
            raw.processed = True
            session.add(raw)
            session.commit()
            print(f"Processed article into IntelReport: {report.validity_category} - Score {report.importance_score}")
            
            webhook_url = os.environ.get("CENTRAL_SITE_WEBHOOK_URL")
            if webhook_url and "VALID_NEWS" in result.validity_category:
                payload = {
                    "mip_version": "1.0",
                    "data": [{
                        "id": report.original_content_hash,
                        "radar_section": report.radar_section,
                        "source_url": report.source_url,
                        "importance_score": report.importance_score,
                        "validity_category": report.validity_category,
                        "key_entities": result.key_entities,
                        "summary": report.llm_summary,
                        "scraped_at": report.created_at.isoformat()
                    }]
                }
                headers = {"Authorization": f"Bearer {os.environ.get('NODE_SYNC_TOKEN', '')}"}
                try:
                    requests.post(webhook_url, json=payload, headers=headers, timeout=5)
                    print("Pushed to central webhook.")
                except Exception as ex:
                    print(f"Webhook push failed: {ex}")
                    
            clear_status(session, source.name)
            time.sleep(2)
        except Exception as e:
            print(f"Error processing article {raw.id}: {e}")
            if 'source' in locals() and source:
                set_status(session, source.name, "Error", f"AI Processing failed: {e}")

def run_trend_scan_job():
    print("Running scheduled trend scan job...")
    try:
        scan_trends()
    except Exception as e:
        print(f"Error scanning trends: {e}")

def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_scraping_job, 'interval', minutes=30)
    scheduler.add_job(run_processing_job, 'interval', minutes=5)
    scheduler.add_job(run_trend_scan_job, 'interval', hours=2)
    scheduler.start()
    print("Scheduler started. Press Ctrl+C to exit.")
    
    # Run once immediately
    run_scraping_job()
    run_processing_job()
    run_trend_scan_job()
    
    try:
        while True:
            time.sleep(2)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()

if __name__ == "__main__":
    start_scheduler()
