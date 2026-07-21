import os
import sys
import time
import traceback
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
from services import scheduler_state
from services.log_service import get_logger
from llm.processor import scan_trends
from worker_subscription import run_subscription_job

db = DBRepository()
logger = get_logger("scheduler")

# Persistent scrape thread pool. Reused across cycles (not recreated per run) so
# each worker thread keeps its pooled browser alive between cycles — cross-cycle
# browser reuse + no per-cycle Chromium leak. Threads are daemon-owned; their
# browsers are reaped with the sidecar process on exit.
_scrape_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="scrape")

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
                    logger.warning(f"Task {task.id} ({task.job_type}) is stale (running for {elapsed:.1f}m).")
                    task.retry_count = (task.retry_count or 0) + 1
                    max_ret = task.max_retries if task.max_retries is not None else 3
                    if task.retry_count < max_ret:
                        logger.info(f"Task {task.id} retry_count={task.retry_count} < {max_ret}. Rescheduling to PENDING.")
                        task.status = "PENDING"
                        task.started_at = None
                        task.error = f"Stale timeout attempt {task.retry_count} exceeded {limit} mins."
                    else:
                        logger.warning(f"Task {task.id} reached max retries. Recovering as FAILED.")
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
                    logger.info(f"Skipping PROCESS task {task.id} because APP_MODE=pure_rss.")
                else:
                    process_tracker_fusion(int(task.target_id))
            elif task.job_type == "TREND_SCAN":
                if is_pure_rss_mode():
                    logger.info(f"Skipping TREND_SCAN task {task.id} because APP_MODE=pure_rss.")
                else:
                    scan_trends()
            # other types can be added here
            
            db.update_task_status(task.id, "COMPLETED")
        except Exception as e:
            logger.error(f"Task {task.id} failed: {e}", exc_info=e)
            from db.database import get_session
            from db.models import TaskRequest
            from datetime import datetime, timezone
            with get_session() as session:
                refreshed_task = session.get(TaskRequest, task.id)
                if refreshed_task:
                    refreshed_task.retry_count = (refreshed_task.retry_count or 0) + 1
                    max_ret = refreshed_task.max_retries if refreshed_task.max_retries is not None else 3
                    if refreshed_task.retry_count < max_ret:
                        logger.info(f"Task {refreshed_task.id} failed. retry_count={refreshed_task.retry_count} < {max_ret}. Rescheduling to PENDING.")
                        refreshed_task.status = "PENDING"
                        refreshed_task.started_at = None
                        refreshed_task.error = f"Attempt {refreshed_task.retry_count} failed: {str(e)}"
                    else:
                        logger.warning(f"Task {refreshed_task.id} failed and reached max retries ({max_ret}). Marking as FAILED.")
                        refreshed_task.status = "FAILED"
                        refreshed_task.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
                        refreshed_task.error = f"Reached max retries ({max_ret}). Last error: {str(e)}"
                    session.add(refreshed_task)
                    session.commit()

def run_scraping_job():
    logger.info("Running scheduled scraping job...")
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
                logger.info(f"Skipping {t.name}, next scrape in {next_in:.1f} minutes.")

    if not trackers_to_run:
        logger.info("No trackers ready for scraping.")
        return

    future_map = {_scrape_executor.submit(scrape_single_tracker, t.id): t for t in trackers_to_run}
    for future in concurrent.futures.as_completed(future_map):
        t = future_map[future]
        exc = future.exception()
        if exc:
            logger.error(f"Scrape crashed for tracker {t.id} ({t.name}): {exc}", exc_info=exc)

def run_semantic_job():
    # Embed + thread-cluster new articles, then evaluate alerts on the updated
    # threads. Runs in BOTH modes: the fallback embedder needs no key, so
    # clustering/dedup/alerting work even in pure-RSS mode (synthesis degrades
    # to citation-only when no generation model).
    try:
        from services.semantic_ingest import run_semantic_ingest, refresh_resonance
        run_semantic_ingest()
        refresh_resonance()  # decay stale resonance flags
    except Exception as e:
        logger.error(f"Semantic ingest failed: {e}", exc_info=e)
    try:
        from services.alert_engine import evaluate_alerts
        evaluate_alerts()
    except Exception as e:
        logger.error(f"Alert evaluation failed: {e}", exc_info=e)

def run_publish_job():
    # R7 Form A ("desktop push"): build the compliance-gated public digest and
    # write site/data/digest.json + generated RSS. Opt-in via PUBLISH_ENABLED so
    # a private radar never publishes by accident.
    if os.environ.get("PUBLISH_ENABLED", "0") not in ("1", "true", "True"):
        return
    try:
        from services.publish_service import write_site_digest
        res = write_site_digest()
        logger.info(f"Published digest: {res}")
    except Exception as e:
        logger.error(f"Publish job failed: {e}", exc_info=e)

def run_processing_job():
    if is_pure_rss_mode():
        logger.info("Skipping Intelligence Fusion job because APP_MODE=pure_rss.")
        return

    logger.info("Running Intelligence Fusion job...")
    trackers_with_work = db.get_trackers_with_unprocessed_articles()
    
    # Process trackers sequentially to prevent concurrent Gemini API rate limit spikes
    for tid in trackers_with_work:
        try:
            process_tracker_fusion(tid)
        except Exception as e:
            logger.error(f"Error processing fusion for tracker {tid}: {e}", exc_info=e)

def run_trend_scan_job():
    if is_pure_rss_mode():
        logger.info("Skipping trend scan because APP_MODE=pure_rss.")
        return

    from services.processor_service import is_llm_budget_exhausted
    if is_llm_budget_exhausted():
        logger.info("Skipping trend scan: daily LLM token budget exhausted.")
        return

    logger.info("Running scheduled trend scan job...")
    try:
        scan_trends()
    except Exception as e:
        logger.error(f"Error scanning trends: {e}", exc_info=e)

def _record_heartbeat(scheduler: BackgroundScheduler):
    jobs = []
    for job in scheduler.get_jobs():
        next_run = getattr(job, "next_run_time", None)
        jobs.append({
            "name": job.name,
            "next_run_time": next_run.isoformat() if next_run else None,
        })
    scheduler_state.heartbeat(jobs)

def start_scheduler(block: bool = True):
    """
    Starts the background job scheduler.

    block=True  — standalone worker mode: keeps the process alive until Ctrl+C.
    block=False — embedded mode (FastAPI lifespan thread): returns after start;
                  BackgroundScheduler owns its worker threads.
    Any startup failure is recorded in scheduler_state so /health can report it
    instead of the thread dying silently.
    """
    try:
        # Setup DB schema & run light migrations
        run_migrations()

        now = datetime.now(timezone.utc)
        scheduler = BackgroundScheduler()
        # next_run_time=now → jobs fire once at startup instead of waiting a
        # full interval; desktop sessions are often shorter than 30 minutes.
        scheduler.add_job(process_task_requests, 'interval', seconds=30, next_run_time=now,
                          name="task_poller")
        scheduler.add_job(run_scraping_job, 'interval', minutes=5, next_run_time=now,
                          name="tracker_scraping")
        # Semantic clustering runs before fusion so the LLM sees thread-organized,
        # de-duplicated content (works in pure-RSS mode too).
        scheduler.add_job(run_semantic_job, 'interval', minutes=5, next_run_time=now,
                          name="semantic_clustering")
        scheduler.add_job(run_processing_job, 'interval', minutes=5, next_run_time=now,
                          name="intelligence_fusion")
        # Trend scan costs LLM tokens; do not fire on every app launch.
        scheduler.add_job(run_trend_scan_job, 'interval', hours=2,
                          name="trend_scan")
        scheduler.add_job(run_subscription_job, 'interval', minutes=5, next_run_time=now,
                          name="subscription_check")
        # R7 public digest (opt-in via PUBLISH_ENABLED). Low-frequency: official
        # feeds are daily/weekly-grade. Delayed first run so it publishes after
        # the startup scrape+cluster has something to publish.
        scheduler.add_job(run_publish_job, 'interval', hours=6,
                          next_run_time=now + timedelta(minutes=10),
                          name="publish_digest")
        # Daily retention for user data (per settings) and telemetry tables
        # (PipelineRun/Event, PageSnapshot) which otherwise grow unbounded.
        # First run is delayed so it never competes with the startup scrape.
        from services.db_cleanup_service import run_maintenance
        scheduler.add_job(run_maintenance, 'interval', hours=24,
                          next_run_time=now + timedelta(minutes=15),
                          name="db_maintenance")
        # First heartbeat at now+5s (not now): the startup snapshot below races
        # with the next_run_time=now job stampede and can transiently miss a
        # job that is mid-execution, so refresh once the stampede settles.
        scheduler.add_job(lambda: _record_heartbeat(scheduler), 'interval', seconds=30,
                          next_run_time=now + timedelta(seconds=5), name="heartbeat")
        scheduler.start()
        scheduler_state.mark_started()
        _record_heartbeat(scheduler)
        logger.info("Scheduler started; all jobs kicked off immediately except trend_scan.")
    except Exception as e:
        scheduler_state.mark_error(f"{type(e).__name__}: {e}")
        logger.error(f"Scheduler failed to start: {e}\n{traceback.format_exc()}")
        if block:
            raise
        return

    if not block:
        return scheduler

    try:
        while True:
            time.sleep(2)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()

if __name__ == "__main__":
    start_scheduler()
