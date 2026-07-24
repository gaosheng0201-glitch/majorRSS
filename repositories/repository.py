from db.database import get_session
from db.models import Tracker, RawArticle, PipelineStatus, TaskRequest
from sqlmodel import select
from datetime import datetime, timezone
import json

class DBRepository:
    def get_active_trackers(self):
        with get_session() as session:
            return session.exec(select(Tracker).where(Tracker.is_active == True)).all()
            
    def get_tracker(self, tracker_id: int):
        with get_session() as session:
            return session.get(Tracker, tracker_id)
            
    def save_raw_article(self, article: RawArticle) -> bool:
        with get_session() as session:
            try:
                session.add(article)
                session.commit()
                return True
            except Exception as e:
                session.rollback()
                return False
                
    def check_url_exists(self, url: str) -> bool:
        with get_session() as session:
            return session.exec(select(RawArticle).where(RawArticle.url == url)).first() is not None
            
    def check_title_exists(self, tracker_id: int, title: str) -> bool:
        with get_session() as session:
            return session.exec(select(RawArticle).where(RawArticle.title == title).where(RawArticle.tracker_id == tracker_id)).first() is not None

    def get_recent_titles(self, tracker_id: int = None, days: int = 3, limit: int = 500):
        """Recent article titles — the comparison set for the P0.5 near-duplicate
        pre-filter (bounded window + cap so it stays cheap). GLOBAL across
        trackers, consistent with the global URL-uniqueness semantics: the same
        story caught by two overlapping trackers (gemini/grok/openAI/claude all
        catch each other's news) belongs to whichever fetched it first, instead
        of entering twice and becoming two per-tracker threads → two summaries.
        `tracker_id` is kept for API compatibility but no longer filters."""
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)
        with get_session() as session:
            return list(session.exec(
                select(RawArticle.title)
                .where(RawArticle.created_at >= cutoff)
                .order_by(RawArticle.created_at.desc())
                .limit(limit)
            ).all())
            
    def set_pipeline_status(self, tracker_name: str, action: str, detail: str):
        with get_session() as session:
            new_status = PipelineStatus(
                tracker_name=tracker_name,
                action_type=action,
                detail=detail,
                updated_at=datetime.now(timezone.utc).replace(tzinfo=None)
            )
            session.add(new_status)
            session.commit()
            
            all_logs = session.exec(select(PipelineStatus).order_by(PipelineStatus.updated_at.desc())).all()
            if len(all_logs) > 50:
                for old_log in all_logs[50:]:
                    session.delete(old_log)
                session.commit()
                
    def get_unprocessed_articles(self, tracker_id: int, limit: int = 50):
        # relevance_gated items stay in the Raw Feed but are excluded from LLM
        # fusion (token economy) — see the semantic_ingest relevance gate.
        with get_session() as session:
            return session.exec(select(RawArticle).where(
                RawArticle.tracker_id == tracker_id,
                RawArticle.processed == False,
                RawArticle.relevance_gated == False,
            ).order_by(RawArticle.created_at.desc()).limit(limit)).all()

    def get_trackers_with_unprocessed_articles(self):
        with get_session() as session:
            return session.exec(select(RawArticle.tracker_id).where(
                RawArticle.processed == False,
                RawArticle.relevance_gated == False,
            ).distinct()).all()
            
    # NOTE (P2.1): the IntelReport write path (save_intel_report /
    # get_recent_reports / append_sources_to_report) was removed — fusion writes
    # StoryThread.summary now and nothing called these (verified by grep). The
    # IntelReport TABLE stays dormant for rollback; see docs/radar_quality_roadmap §G.

    def get_pending_tasks(self, job_type: str = None):
        with get_session() as session:
            query = select(TaskRequest).where(TaskRequest.status == "PENDING")
            if job_type:
                query = query.where(TaskRequest.job_type == job_type)
            return session.exec(query.order_by(TaskRequest.created_at.asc())).all()
            
    def update_task_status(self, task_id: int, status: str, error: str = None):
        with get_session() as session:
            task = session.get(TaskRequest, task_id)
            if task:
                task.status = status
                if status == "RUNNING":
                    task.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
                elif status in ["COMPLETED", "FAILED"]:
                    task.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
                if error:
                    task.error = error
                session.add(task)
                session.commit()

            return True
