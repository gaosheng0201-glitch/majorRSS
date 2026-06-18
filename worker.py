"""
Backward compatibility wrapper. 
worker.py is maintained so that existing bats, legacy scripts, and manual test commands still function.
Actual logic has been moved to scheduler.py, services/scraper_service.py, and services/processor_service.py
"""

from scheduler import start_scheduler, run_scraping_job, run_processing_job, run_trend_scan_job
from services.scraper_service import scrape_single_tracker as _scrape_single_tracker
from services.processor_service import process_tracker_fusion as _process_tracker_fusion
from db.database import get_session

_fetch_url = None  # Deprecated in refactored pipeline

def set_status(*args, **kwargs):
    from repositories.repository import DBRepository
    db = DBRepository()
    db.set_pipeline_status(args[1], args[2], args[3])

def clear_status(*args, **kwargs):
    pass

if __name__ == "__main__":
    start_scheduler()
