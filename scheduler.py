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
from services.app_mode import is_pure_rss_mode
from llm.processor import scan_trends
from worker_subscription import run_subscription_job

db = DBRepository()

def recover_stale_tasks():
    """Finds tasks stuck in RUNNING state and marks them as FAILED or reschedules based on retry limit."""
    from db.database import get_session
    from db.models import TaskRequest
    from sqlmodel import select
    from datetime import datetime, timezone
    
    stale_limit_minutes = int(os.environ.get("TASK_STALE_MINUTES", "30"))
    now = datetime.now(timezone.utc)
    
    with get_session() as session:
        running_tasks = session.exec(select(TaskRequest).where(TaskRequest.status == "RUNNING")).all()
        for task in running_tasks:
            started_at = task.started_at
            if started_at:
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
                    
                limit = stale_limit_minutes
                if task.job_type == "TREND_SCAN":
                    limit = 120
                    
                elapsed = (now - started_at).total_seconds() / 60
                if elapsed >= limit:
                    print(f"[Scheduler] Task {task.id} ({task.job_type}) is stale (running for {elapsed:.1f}m).")
                    task.retry_count = (task.retry_count or 0) + 1
                    max_ret = task.max_retries if task.max_retries is not None else 3
                    if task.retry_count < max_ret:
                        print(f"[Scheduler] Task {task.id} retry_count={task.retry_count} < {max_ret}. Rescheduling to PENDING.")
                        task.status = "PENDING"
                        task.started_at = None
                        task.error = f"Stale timeout attempt {task.retry_count} exceeded {limit} mins."
                    else:
                        print(f"[Scheduler] Task {task.id} reached max retries. Recovering as FAILED.")
                        task.status = "FAILED"
                        task.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
                        task.error = f"Task exceeded stale limit of {limit} minutes and reached max retries ({max_ret})."
                    session.add(task)
        session.commit()

def process_task_requests():
    """Polls the TaskRequest table for UI-triggered jobs."""
    # Recover stale tasks first
    recover_stale_tasks()
    
    tasks = db.get_pending_tasks()
    for task in tasks:
        db.update_task_status(task.id, "RUNNING")
        try:
            if task.job_type == "SCRAPE" and task.target_type == "TRACKER":
                scrape_single_tracker(int(task.target_id))
            elif task.job_type == "PROCESS" and task.target_type == "TRACKER":
                if is_pure_rss_mode():
                    print(f"[Scheduler] Skipping PROCESS task {task.id} because APP_MODE=pure_rss.")
                else:
                    process_tracker_fusion(int(task.target_id))
            elif task.job_type == "TREND_SCAN":
                if is_pure_rss_mode():
                    print(f"[Scheduler] Skipping TREND_SCAN task {task.id} because APP_MODE=pure_rss.")
                else:
                    scan_trends()
            # other types can be added here
            
            db.update_task_status(task.id, "COMPLETED")
        except Exception as e:
            print(f"Task {task.id} failed: {e}")
            from db.database import get_session
            from db.models import TaskRequest
            from datetime import datetime, timezone
            with get_session() as session:
                refreshed_task = session.get(TaskRequest, task.id)
                if refreshed_task:
                    refreshed_task.retry_count = (refreshed_task.retry_count or 0) + 1
                    max_ret = refreshed_task.max_retries if refreshed_task.max_retries is not None else 3
                    if refreshed_task.retry_count < max_ret:
                        print(f"[Scheduler] Task {refreshed_task.id} failed. retry_count={refreshed_task.retry_count} < {max_ret}. Rescheduling to PENDING.")
                        refreshed_task.status = "PENDING"
                        refreshed_task.started_at = None
                        refreshed_task.error = f"Attempt {refreshed_task.retry_count} failed: {str(e)}"
                    else:
                        print(f"[Scheduler] Task {refreshed_task.id} failed and reached max retries ({max_ret}). Marking as FAILED.")
                        refreshed_task.status = "FAILED"
                        refreshed_task.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
                        refreshed_task.error = f"Reached max retries ({max_ret}). Last error: {str(e)}"
                    session.add(refreshed_task)
                    session.commit()

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
    if is_pure_rss_mode():
        print("Skipping Intelligence Fusion job because APP_MODE=pure_rss.")
        return

    print("Running Intelligence Fusion job...")
    trackers_with_work = db.get_trackers_with_unprocessed_articles()
    
    # Process trackers sequentially to prevent concurrent Gemini API rate limit spikes
    for tid in trackers_with_work:
        try:
            process_tracker_fusion(tid)
        except Exception as e:
            print(f"Error processing fusion for tracker {tid}: {e}")

def run_trend_scan_job():
    if is_pure_rss_mode():
        print("Skipping trend scan because APP_MODE=pure_rss.")
        return

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
    print("Scheduled jobs will run on their configured intervals after startup.")
    
    try:
        while True:
            time.sleep(2)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()

if __name__ == "__main__":
    start_scheduler()
