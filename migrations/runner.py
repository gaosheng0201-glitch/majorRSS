import os
import sys
from sqlmodel import select, SQLModel

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import engine, get_session
from db.models import SchemaVersion

def run_migrations():
    print("Running migrations...")
    # SQLModel create_all will create tables that don't exist yet (like AuthProfile, TaskRequest, and SchemaVersion)
    SQLModel.metadata.create_all(engine)
    
    with get_session() as session:
        migrations = [
            "0001_initial_and_task_request",
            "0002_intent_and_auth_profile",
            "0003_task_retry_columns",
            "0004_subscription_diff_policy",
            "0005_pipeline_trace_tables",
            "0006_semantic_and_radar_columns"
        ]
        
        for m in migrations:
            existing = session.exec(select(SchemaVersion).where(SchemaVersion.version_id == m)).first()
            if not existing:
                print(f"Applying migration: {m}")
                
                if m == "0002_intent_and_auth_profile":
                    from sqlalchemy import inspect, text
                    import json
                    
                    # 1. Idempotent column addition
                    inspector = inspect(engine)
                    columns = [col["name"] for col in inspector.get_columns("tracker")]
                    
                    conn = session.connection()
                    if "source_intent" not in columns:
                        conn.execute(text("ALTER TABLE tracker ADD COLUMN source_intent VARCHAR(255)"))
                    if "fetch_policy" not in columns:
                        conn.execute(text("ALTER TABLE tracker ADD COLUMN fetch_policy TEXT"))
                    if "auth_profile_id" not in columns:
                        conn.execute(text("ALTER TABLE tracker ADD COLUMN auth_profile_id INTEGER"))
                    session.commit()
                    
                    # 2. Legacy backfill
                    from db.models import Tracker
                    trackers = session.exec(select(Tracker)).all()
                    for t in trackers:
                        modified = False
                        
                        # Backfill source_intent
                        if not t.source_intent or t.source_intent == "RSS_FEED":
                            if t.tracker_type == "URL":
                                t.source_intent = "RSS_FEED"
                                modified = True
                            elif t.tracker_type == "KEYWORD":
                                t.source_intent = "KEYWORD_DISCOVERY"
                                modified = True
                            elif t.tracker_type == "ACCOUNT":
                                t.source_intent = "ACCOUNT_TRACKING"
                                modified = True
                            elif t.tracker_type == "HYBRID":
                                t.source_intent = "HYBRID"
                                modified = True
                        
                        # Backfill fetch_policy
                        if not t.fetch_policy:
                            policy = {
                                "url_strategy": "auto",
                                "keyword_strategy": "default",
                                "account_strategy": "auto",
                                "fallback_enabled": True,
                                "max_days": 7,
                                "max_items_per_route": 20,
                                "min_relevance": 0.35
                            }
                            
                            if t.source_intent == "RSS_FEED":
                                is_probably_rss = False
                                for suffix in [".xml", ".rss", ".atom", "feed", "rsshub", "rss=1"]:
                                    if t.target and suffix in t.target.lower():
                                        is_probably_rss = True
                                        break
                                
                                if is_probably_rss:
                                    policy["url_strategy"] = "rss_first"
                                else:
                                    policy["url_strategy"] = "auto"
                                    
                                if t.tier == 3:
                                    policy["url_strategy"] = "agentic"
                                    
                            t.fetch_policy = json.dumps(policy)
                            modified = True
                            
                        if modified:
                            session.add(t)
                    session.commit()
                
                elif m == "0003_task_retry_columns":
                    from sqlalchemy import inspect, text
                    inspector = inspect(engine)
                    table_name = "taskrequest"
                    if "taskrequest" not in inspector.get_table_names():
                        if "task_request" in inspector.get_table_names():
                            table_name = "task_request"
                    
                    columns = [col["name"] for col in inspector.get_columns(table_name)]
                    conn = session.connection()
                    if "retry_count" not in columns:
                        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN retry_count INTEGER DEFAULT 0"))
                    if "max_retries" not in columns:
                        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN max_retries INTEGER DEFAULT 3"))
                    session.commit()

                elif m == "0004_subscription_diff_policy":
                    from sqlalchemy import inspect, text
                    inspector = inspect(engine)
                    table_name = "subscription"
                    if "subscription" not in inspector.get_table_names():
                        if "subscriptions" in inspector.get_table_names():
                            table_name = "subscriptions"
                    
                    columns = [col["name"] for col in inspector.get_columns(table_name)]
                    conn = session.connection()
                    if "diff_policy" not in columns:
                        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN diff_policy TEXT"))
                    session.commit()

                elif m == "0005_pipeline_trace_tables":
                    from sqlalchemy import inspect, text
                    inspector = inspect(engine)
                    
                    # 1. Add normalized_intent to tracker table if missing
                    tracker_table = "tracker"
                    if "tracker" not in inspector.get_table_names():
                        if "trackers" in inspector.get_table_names():
                            tracker_table = "trackers"
                    columns_tracker = [col["name"] for col in inspector.get_columns(tracker_table)]
                    conn = session.connection()
                    if "normalized_intent" not in columns_tracker:
                        conn.execute(text(f"ALTER TABLE {tracker_table} ADD COLUMN normalized_intent TEXT"))
                        
                    # 2. Add normalized_intent to subscription table if missing
                    sub_table = "subscription"
                    if "subscription" not in inspector.get_table_names():
                        if "subscriptions" in inspector.get_table_names():
                            sub_table = "subscriptions"
                    columns_sub = [col["name"] for col in inspector.get_columns(sub_table)]
                    if "normalized_intent" not in columns_sub:
                        conn.execute(text(f"ALTER TABLE {sub_table} ADD COLUMN normalized_intent TEXT"))
                    session.commit()

                elif m == "0006_semantic_and_radar_columns":
                    # R3/R5 added columns to EXISTING tables. create_all only
                    # creates new tables (StoryThread/ArticleEmbedding/RadarAlert),
                    # never ALTERs existing ones — so on an upgraded DB these
                    # columns are missing and the whole pipeline crashes. Add them
                    # idempotently (guarded by inspector) like migrations 0002-0005.
                    from sqlalchemy import inspect, text
                    inspector = inspect(engine)
                    conn = session.connection()

                    ra_table = "rawarticle"
                    if ra_table not in inspector.get_table_names() and "raw_article" in inspector.get_table_names():
                        ra_table = "raw_article"
                    if ra_table in inspector.get_table_names():
                        ra_cols = [c["name"] for c in inspector.get_columns(ra_table)]
                        if "thread_id" not in ra_cols:
                            conn.execute(text(f"ALTER TABLE {ra_table} ADD COLUMN thread_id INTEGER"))
                        if "relevance_gated" not in ra_cols:
                            conn.execute(text(f"ALTER TABLE {ra_table} ADD COLUMN relevance_gated BOOLEAN DEFAULT 0"))

                    tr_table = "tracker"
                    if tr_table not in inspector.get_table_names() and "trackers" in inspector.get_table_names():
                        tr_table = "trackers"
                    if tr_table in inspector.get_table_names():
                        tr_cols = [c["name"] for c in inspector.get_columns(tr_table)]
                        if "is_high_attention" not in tr_cols:
                            conn.execute(text(f"ALTER TABLE {tr_table} ADD COLUMN is_high_attention BOOLEAN DEFAULT 0"))
                    session.commit()

                sv = SchemaVersion(version_id=m)
                session.add(sv)
                session.commit()
                print(f"Successfully applied {m}")
            else:
                print(f"Migration {m} already applied.")

    try:
        from services.source_preset_service import upsert_source_presets_from_seed
        result = upsert_source_presets_from_seed()
        print(
            "Source preset seed synced: "
            f"{result['sources']} sources, "
            f"{result['collections']} collections, "
            f"{result['collection_items']} collection items."
        )
    except FileNotFoundError as e:
        print(f"Source preset seed skipped: {e}")

if __name__ == "__main__":
    run_migrations()
