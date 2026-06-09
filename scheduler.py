import os
import sys
import time
import concurrent.futures
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from db.database import create_db_and_tables
from migrations.runner import run_migrations
from repositories.repository import DBRepository
from services.scraper_service import scrape_single_tracker
from services.processor_service import process_tracker_fusion
from llm.processor import scan_trends
from worker_subscription import run_subscription_job

db = DBRepository()

def process_task_requests():
    """Polls the TaskRequest table for UI-triggered jobs."""
    tasks = db.get_pending_tasks()
    for task in tasks:
        db.update_task_status(task.id, "RUNNING")
        try:
            if task.job_type == "SCRAPE" and task.target_type == "TRACKER":
                scrape_single_tracker(int(task.target_id))
            elif task.job_type == "PROCESS" and task.target_type == "TRACKER":
                process_tracker_fusion(int(task.target_id))
            elif task.job_type == "TREND_SCAN":
                scan_trends()
            # other types can be added here
            
            db.update_task_status(task.id, "COMPLETED")
        except Exception as e:
            print(f"Task {task.id} failed: {e}")
            db.update_task_status(task.id, "FAILED", error=str(e))

def run_scraping_job():
    print("Running scheduled scraping job...")
    trackers = db.get_active_trackers()
    
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
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(scrape_single_tracker, t.id) for t in trackers_to_run]
        concurrent.futures.wait(futures)

def run_processing_job():
    print("Running Intelligence Fusion job...")
    trackers_with_work = db.get_trackers_with_unprocessed_articles()
    
    # Process trackers sequentially to prevent concurrent Gemini API rate limit spikes
    for tid in trackers_with_work:
        try:
            process_tracker_fusion(tid)
        except Exception as e:
            print(f"Error processing fusion for tracker {tid}: {e}")

def run_trend_scan_job():
    print("Running scheduled trend scan job...")
    try:
        scan_trends()
    except Exception as e:
        print(f"Error scanning trends: {e}")

def start_scheduler():
    # Setup DB schema & run light migrations
    run_migrations()
    
    scheduler = BackgroundScheduler()
    scheduler.add_job(process_task_requests, 'interval', seconds=30)
    scheduler.add_job(run_scraping_job, 'interval', minutes=30)
    scheduler.add_job(run_processing_job, 'interval', minutes=5)
    scheduler.add_job(run_trend_scan_job, 'interval', hours=2)
    scheduler.add_job(run_subscription_job, 'interval', minutes=5)
    scheduler.start()
    print("Scheduler started. Press Ctrl+C to exit.")
    
    process_task_requests()
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
