from db.database import get_session
from db.models import Tracker, RawArticle, IntelReport, PipelineStatus, TaskRequest
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
        with get_session() as session:
            return session.exec(select(RawArticle).where(RawArticle.tracker_id == tracker_id, RawArticle.processed == False).order_by(RawArticle.created_at.desc()).limit(limit)).all()

    def get_trackers_with_unprocessed_articles(self):
        with get_session() as session:
            return session.exec(select(RawArticle.tracker_id).where(RawArticle.processed == False).distinct()).all()
            
    def save_intel_report(self, report: IntelReport, source_articles):
        with get_session() as session:
            session.add(report)
            for u in source_articles:
                u.processed = True
                session.add(u)
            session.commit()
            
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

    def get_recent_reports(self, section_name: str, limit: int = 10):
        with get_session() as session:
            return session.exec(
                select(IntelReport)
                .where(IntelReport.radar_section == section_name)
                .where(IntelReport.validity_category.in_(["[VALID_NEWS]", "VALID_NEWS"]))
                .order_by(IntelReport.created_at.desc())
                .limit(limit)
            ).all()

    def append_sources_to_report(self, report_id: int, new_valid_sources, raw_articles):
        with get_session() as session:
            report = session.get(IntelReport, report_id)
            if not report:
                return False
                
            summary = report.llm_summary
            
            # Filter duplicates to avoid adding identical URLs
            unique_new_valid = [u for u in new_valid_sources if u.url not in summary]
            unique_raw = [u for u in raw_articles if u.url not in summary]
            
            # 1. Append new valid sources in "Source Evidence" section
            if unique_new_valid:
                new_links_md = "\n".join([f"- [{u.title}]({u.url})" for u in unique_new_valid])
                if "**:material/menu_book: Source Evidence:**" in summary:
                    parts = summary.split("**:material/menu_book: Source Evidence:**\n")
                    if len(parts) == 2:
                        summary = parts[0] + "**:material/menu_book: Source Evidence:**\n" + new_links_md + "\n" + parts[1]
                else:
                    summary += f"\n\n**:material/menu_book: Source Evidence:**\n{new_links_md}"
                
            # 2. Append new raw URLs in "本次融合的所有原始 URL" section
            if unique_raw:
                new_raw_md = "\n".join([f"- {u.url}" for u in unique_raw])
                if "本次融合的所有原始 URL (含被过滤的噪音):**" in summary:
                    parts = summary.split("本次融合的所有原始 URL (含被过滤的噪音):**\n")
                    if len(parts) == 2:
                        summary = parts[0] + "本次融合的所有原始 URL (含被过滤的噪音):**\n" + new_raw_md + "\n" + parts[1]
                else:
                    summary += f"\n\n**:material/link: 本次融合的所有原始 URL (含被过滤的噪音):**\n{new_raw_md}"
                
            report.llm_summary = summary
            
            # 3. Mark the new raw articles as processed
            for u in raw_articles:
                u.processed = True
                session.add(u)
                
            session.add(report)
            session.commit()
            return True
