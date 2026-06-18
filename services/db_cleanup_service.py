import os
from sqlmodel import select, func, text, Session
from db.database import engine, get_db_url
from db.models import RawArticle, IntelReport, DailyBriefing, TrendAlert, TokenUsage
from datetime import datetime, timezone, timedelta

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
                # Extract dbname from postgresql://user:pass@host:port/dbname
                dbname = db_url.split("/")[-1]
                res = session.execute(text(f"SELECT pg_database_size('{dbname}')"))
                size_bytes = res.scalar() or 0
                db_size_mb = size_bytes / (1024 * 1024)
        except Exception as e:
            print(f"[ERROR] Failed to query Postgres DB size: {e}")
            
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
            print(f"[WARNING] Failed to parse DATABASE_URL for Postgres info: {e}")
            
    with Session(engine) as session:
        raw_articles = session.exec(select(func.count(RawArticle.id))).one()
        intel_reports = session.exec(select(func.count(IntelReport.id))).one()
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
            print(f"[WARNING] Failed to query expired counts: {e}")
            
    return {
        "engine_type": engine_type,
        "postgres_info": pg_info,
        "db_size_mb": round(db_size_mb, 2),
        "row_counts": {
            "raw_articles": raw_articles,
            "intel_reports": intel_reports,
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
        print(f"[WARNING] Database vacuum/compaction failed: {e}")
        
    return deleted_count

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
