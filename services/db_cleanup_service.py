import os
from sqlmodel import select, func, text, Session
from sqlalchemy import delete as sa_delete, update as sa_update
from db.database import engine, get_db_url
from db.models import RawArticle, IntelReport, DailyBriefing, TrendAlert, TokenUsage, StoryThread, RadarAlert
from datetime import datetime, timezone, timedelta
from services.log_service import get_logger

logger = get_logger("db_cleanup")

def get_db_status():
    """
    Computes database file size, row counts, retention limits,
    and returns if database size exceeds limits or has expired entries.
    """
    db_url = get_db_url()
    db_size_mb = 0.0
    engine_type = "sqlite" if db_url.startswith("sqlite") else "postgres"
    pg_info = None
    
    if db_url.startswith("sqlite"):
        db_path = db_url.replace("sqlite:///", "")
        if os.path.exists(db_path):
            db_size_mb = os.path.getsize(db_path) / (1024 * 1024)
    else:
        try:
            with Session(engine) as session:
                # current_database() avoids fragile URL parsing (a trailing
                # ?sslmode=... query would corrupt a split('/')[-1] dbname).
                res = session.execute(text("SELECT pg_database_size(current_database())"))
                size_bytes = res.scalar() or 0
                db_size_mb = size_bytes / (1024 * 1024)
        except Exception as e:
            logger.error(f"Failed to query Postgres DB size: {e}")
            
        try:
            import urllib.parse
            # parse postgresql://username:password@host:port/database
            url_part = db_url.split("://", 1)[1]
            auth_part, rest = url_part.split("@", 1)
            username, password = auth_part.split(":", 1)
            password = urllib.parse.unquote_plus(password)
            host_port, database = rest.split("/", 1)
            if ":" in host_port:
                host, port = host_port.split(":", 1)
                port = int(port)
            else:
                host = host_port
                port = 5432
            pg_info = {
                "host": host,
                "port": port,
                "username": username,
                "password": "********",
                "database": database
            }
        except Exception as e:
            logger.warning(f"Failed to parse DATABASE_URL for Postgres info: {e}")
            
    with Session(engine) as session:
        raw_articles = session.exec(select(func.count(RawArticle.id))).one()
        intel_reports = session.exec(select(func.count(IntelReport.id))).one()
        story_threads = session.exec(select(func.count(StoryThread.id))).one()
        daily_briefings = session.exec(select(func.count(DailyBriefing.id))).one()
        trend_alerts = session.exec(select(func.count(TrendAlert.id))).one()
        token_usages = session.exec(select(func.count(TokenUsage.id))).one()
        
    retention_days = int(os.environ.get("DB_CLEANUP_RETENTION_DAYS", "0"))
    max_size_mb = int(os.environ.get("DB_CLEANUP_MAX_SIZE_MB", "0"))
    
    is_over_size_limit = max_size_mb > 0 and db_size_mb > max_size_mb
    
    expired_articles_count = 0
    if retention_days > 0:
        cutoff_naive = (datetime.now(timezone.utc) - timedelta(days=retention_days)).replace(tzinfo=None)
        try:
            with Session(engine) as session:
                expired_articles_count += session.exec(select(func.count(RawArticle.id)).where(RawArticle.created_at < cutoff_naive)).one()
                expired_articles_count += session.exec(select(func.count(IntelReport.id)).where(IntelReport.created_at < cutoff_naive)).one()
        except Exception as e:
            logger.warning(f"Failed to query expired counts: {e}")
            
    return {
        "engine_type": engine_type,
        "postgres_info": pg_info,
        "db_size_mb": round(db_size_mb, 2),
        "row_counts": {
            "raw_articles": raw_articles,
            "intel_reports": intel_reports,
            "story_threads": story_threads,
            "daily_briefings": daily_briefings,
            "trend_alerts": trend_alerts,
            "token_usages": token_usages
        },
        "retention_days": retention_days,
        "max_size_mb": max_size_mb,
        "is_over_size_limit": is_over_size_limit,
        "expired_articles_count": expired_articles_count
    }

def run_db_cleanup():
    """
    Cleans up old records according to retention settings, size threshold,
    and runs database compaction/vacuuming.
    """
    db_url = get_db_url()
    retention_days = int(os.environ.get("DB_CLEANUP_RETENTION_DAYS", "0"))
    max_size_mb = int(os.environ.get("DB_CLEANUP_MAX_SIZE_MB", "0"))
    
    deleted_count = 0
    
    # 1. Age-based Pruning
    if retention_days > 0:
        cutoff_naive = (datetime.now(timezone.utc) - timedelta(days=retention_days)).replace(tzinfo=None)
        with Session(engine) as session:
            # Delete RawArticles
            articles_to_delete = session.exec(select(RawArticle).where(RawArticle.created_at < cutoff_naive)).all()
            for a in articles_to_delete:
                session.delete(a)
            deleted_count += len(articles_to_delete)
            
            # Delete IntelReports
            reports_to_delete = session.exec(select(IntelReport).where(IntelReport.created_at < cutoff_naive)).all()
            for r in reports_to_delete:
                session.delete(r)
            deleted_count += len(reports_to_delete)
            
            # Delete TrendAlerts
            alerts_to_delete = session.exec(select(TrendAlert).where(TrendAlert.created_at < cutoff_naive)).all()
            for al in alerts_to_delete:
                session.delete(al)
            deleted_count += len(alerts_to_delete)

            # Delete TokenUsages
            tokens_to_delete = session.exec(select(TokenUsage).where(TokenUsage.created_at < cutoff_naive)).all()
            for tu in tokens_to_delete:
                session.delete(tu)
            deleted_count += len(tokens_to_delete)

            # P2.1: StoryThread now holds the feed's summaries — prune stale threads
            # too (else retention no longer bounds the feed). FK-safe order: drop
            # their alerts, detach any surviving articles, then the threads.
            old_threads = select(StoryThread.id).where(StoryThread.last_update_at < cutoff_naive)
            session.execute(sa_delete(RadarAlert).where(RadarAlert.thread_id.in_(old_threads)))
            session.execute(sa_update(RawArticle).where(RawArticle.thread_id.in_(old_threads)).values(thread_id=None))
            res = session.execute(sa_delete(StoryThread).where(StoryThread.last_update_at < cutoff_naive))
            deleted_count += res.rowcount or 0

            session.commit()
            
    # 2. Size-based Pruning
    if max_size_mb > 0:
        status = get_db_status()
        current_size = status["db_size_mb"]
        
        if current_size > max_size_mb:
            with Session(engine) as session:
                # Delete oldest 25% of RawArticles
                total_articles = session.exec(select(func.count(RawArticle.id))).one()
                if total_articles > 100:
                    limit_count = int(total_articles * 0.25)
                    oldest_articles = session.exec(select(RawArticle).order_by(RawArticle.created_at.asc()).limit(limit_count)).all()
                    for a in oldest_articles:
                        session.delete(a)
                    deleted_count += len(oldest_articles)
                
                # Delete oldest 25% of IntelReports
                total_reports = session.exec(select(func.count(IntelReport.id))).one()
                if total_reports > 50:
                    limit_count = int(total_reports * 0.25)
                    oldest_reports = session.exec(select(IntelReport).order_by(IntelReport.created_at.asc()).limit(limit_count)).all()
                    for r in oldest_reports:
                        session.delete(r)
                    deleted_count += len(oldest_reports)

                # P2.1: delete oldest 25% of StoryThreads (feed data lives here now).
                # Subquery in .in_() (not a materialized id list) to stay under
                # SQLite's bound-variable limit. FK-safe: alerts, then detach, then.
                total_threads = session.exec(select(func.count(StoryThread.id))).one()
                if total_threads > 50:
                    limit_count = int(total_threads * 0.25)
                    old_ids = select(StoryThread.id).order_by(StoryThread.last_update_at.asc()).limit(limit_count)
                    session.execute(sa_delete(RadarAlert).where(RadarAlert.thread_id.in_(old_ids)))
                    session.execute(sa_update(RawArticle).where(RawArticle.thread_id.in_(old_ids)).values(thread_id=None))
                    res = session.execute(sa_delete(StoryThread).where(StoryThread.id.in_(old_ids)))
                    deleted_count += res.rowcount or 0

                session.commit()

    # 3. Vacuuming / Defragmentation
    try:
        if db_url.startswith("sqlite"):
            with engine.connect() as connection:
                connection.execution_options(isolation_level="AUTOCOMMIT").execute(text("VACUUM"))
        else:
            with engine.connect() as connection:
                connection.execution_options(isolation_level="AUTOCOMMIT").execute(text("VACUUM ANALYZE"))
    except Exception as e:
        logger.warning(f"Database vacuum/compaction failed: {e}")

    return deleted_count

def cleanup_observability_data() -> int:
    """
    Retention for internal telemetry tables (PipelineRun/PipelineEvent traces
    and PageSnapshot page copies). These grow on every scheduled run, so —
    unlike user-facing data — this cleanup is always on, independent of the
    user's DB_CLEANUP_RETENTION_DAYS setting.
    """
    from db.models import PipelineRun, PipelineEvent, PageSnapshot, Subscription

    trace_days = int(os.environ.get("PIPELINE_TRACE_RETENTION_DAYS", "14"))
    snapshots_keep = int(os.environ.get("PAGE_SNAPSHOTS_KEEP_PER_SUBSCRIPTION", "3"))
    deleted = 0

    with Session(engine) as session:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=trace_days)).replace(tzinfo=None)
        # Delete by SUBQUERY predicate, not a materialized id list — a long
        # backlog would blow past SQLite's ~999 bound-variable limit and the
        # whole cleanup would fail, leaving telemetry to grow unbounded.
        old_runs = select(PipelineRun.id).where(PipelineRun.started_at < cutoff)
        res = session.execute(sa_delete(PipelineEvent).where(PipelineEvent.run_id.in_(old_runs)))
        deleted += res.rowcount or 0
        res = session.execute(sa_delete(PipelineRun).where(PipelineRun.started_at < cutoff))
        deleted += res.rowcount or 0

        # Page diffing only needs the latest snapshot per subscription; keep a
        # small history for debugging and drop the rest.
        sub_ids = session.exec(select(Subscription.id)).all()
        for sid in sub_ids:
            keep_ids = session.exec(
                select(PageSnapshot.id)
                .where(PageSnapshot.subscription_id == sid)
                .order_by(PageSnapshot.created_at.desc())
                .limit(snapshots_keep)
            ).all()
            res = session.execute(
                sa_delete(PageSnapshot).where(
                    PageSnapshot.subscription_id == sid,
                    PageSnapshot.id.not_in(keep_ids),
                )
            )
            deleted += res.rowcount or 0
        session.commit()

    return deleted

def run_maintenance():
    """Daily scheduled maintenance: user-data retention + telemetry retention."""
    try:
        user_deleted = run_db_cleanup()
    except Exception as e:
        user_deleted = 0
        logger.error(f"User-data cleanup failed: {e}", exc_info=e)
    try:
        telemetry_deleted = cleanup_observability_data()
    except Exception as e:
        telemetry_deleted = 0
        logger.error(f"Telemetry cleanup failed: {e}", exc_info=e)
    logger.info(f"DB maintenance done: {user_deleted} user rows, {telemetry_deleted} telemetry rows removed.")

def test_pg_connection(host, port, user, password, dbname):
    """
    Tries to connect to a PostgreSQL database with a short timeout.
    """
    from sqlmodel import create_engine
    import urllib.parse
    safe_pass = urllib.parse.quote_plus(password)
    pg_url = f"postgresql://{user}:{safe_pass}@{host}:{port}/{dbname}"
    
    try:
        temp_engine = create_engine(pg_url, connect_args={"connect_timeout": 5})
        with temp_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        temp_engine.dispose()
        return True, "Connection successful"
    except Exception as e:
        return False, str(e)
