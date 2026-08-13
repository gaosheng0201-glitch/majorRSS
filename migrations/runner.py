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
            "0006_semantic_and_radar_columns",
            "0007_source_tier",
            "0008_thread_summary",
            "0009_indexes_and_gate_marker",
            "0010_fusion_increment_snapshot",
            "0011_from_account",
            "0012_release_rate_limit_quarantine",
            "0013_release_capability_failures",
            "0014_first_party_floor_restamp",
            "0015_replay_material_timestamps"
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

                elif m == "0007_source_tier":
                    # Provenance capture (docs/source_tiering.md / P0.4): stamp each
                    # article's source tier at intake. Nullable — legacy rows stay
                    # NULL (unknown → treated as aggregated by the fusion gate).
                    from sqlalchemy import inspect, text
                    inspector = inspect(engine)
                    conn = session.connection()
                    ra_table = "rawarticle"
                    if ra_table not in inspector.get_table_names() and "raw_article" in inspector.get_table_names():
                        ra_table = "raw_article"
                    if ra_table in inspector.get_table_names():
                        ra_cols = [c["name"] for c in inspector.get_columns(ra_table)]
                        if "source_tier" not in ra_cols:
                            conn.execute(text(f"ALTER TABLE {ra_table} ADD COLUMN source_tier VARCHAR"))
                    session.commit()

                elif m == "0008_thread_summary":
                    # P2.1: the fused event summary moves onto StoryThread (single
                    # source of truth; IntelReport deprecated). Add the summary +
                    # display/classification columns idempotently.
                    from sqlalchemy import inspect, text
                    inspector = inspect(engine)
                    conn = session.connection()
                    st_table = "storythread"
                    if st_table in inspector.get_table_names():
                        st_cols = [c["name"] for c in inspector.get_columns(st_table)]
                        for col, ddl in [
                            ("summary", "TEXT"),
                            ("validity_category", "VARCHAR"),
                            ("radar_section", "VARCHAR"),
                            ("key_entities", "TEXT DEFAULT '[]'"),
                            ("event_timestamp", "VARCHAR"),
                            ("source_url", "VARCHAR"),
                            ("summarized_at", "DATETIME"),
                        ]:
                            if col not in st_cols:
                                conn.execute(text(f"ALTER TABLE {st_table} ADD COLUMN {col} {ddl}"))
                        # summarized_at is the hot feed ordering/filter key;
                        # create_all only builds the index on fresh DBs, so add it
                        # here for upgraded DBs (else every feed query full-scans).
                        conn.execute(text(
                            f"CREATE INDEX IF NOT EXISTS ix_storythread_summarized_at "
                            f"ON {st_table} (summarized_at)"))
                    # Legacy TrendAlert.related_article_ids held IntelReport ids;
                    # make_alert_response now resolves them as StoryThread ids
                    # (independent id spaces → wrong/empty sources). Purge pre-P2.1
                    # alerts — they are transient and regenerate from live threads.
                    ta_table = "trendalert"
                    if ta_table in inspector.get_table_names():
                        conn.execute(text(f"DELETE FROM {ta_table}"))
                    session.commit()

                elif m == "0009_indexes_and_gate_marker":
                    # (a) Columns added by ALTER TABLE in 0006/0007 declared
                    # index=True in the model, but create_all only builds indexes
                    # on FRESH databases — upgraded DBs were full-scanning the hot
                    # paths (fusion pending query, tier gate, member lookups).
                    # (b) gate_checked_at: P1.1 gate re-evaluation marker so gated
                    # threads are only re-checked when they actually change,
                    # instead of every 5-minute cycle forever.
                    from sqlalchemy import inspect, text
                    inspector = inspect(engine)
                    conn = session.connection()
                    ra_table = "rawarticle"
                    if ra_table not in inspector.get_table_names() and "raw_article" in inspector.get_table_names():
                        ra_table = "raw_article"
                    if ra_table in inspector.get_table_names():
                        for col in ("thread_id", "relevance_gated", "source_tier"):
                            conn.execute(text(
                                f"CREATE INDEX IF NOT EXISTS ix_{ra_table}_{col} ON {ra_table} ({col})"))
                    st_table = "storythread"
                    if st_table in inspector.get_table_names():
                        st_cols = [c["name"] for c in inspector.get_columns(st_table)]
                        if "gate_checked_at" not in st_cols:
                            conn.execute(text(f"ALTER TABLE {st_table} ADD COLUMN gate_checked_at DATETIME"))
                    session.commit()

                elif m == "0010_fusion_increment_snapshot":
                    # Re-fusion needs to know what the signals looked like at the
                    # LAST fusion, to distinguish a real development from more
                    # copies of the same story (see _fuse_thread's material-
                    # increment gate). Backfill existing summarized threads from
                    # their current values so they don't all re-fuse once.
                    from sqlalchemy import inspect, text
                    inspector = inspect(engine)
                    conn = session.connection()
                    st_table = "storythread"
                    if st_table in inspector.get_table_names():
                        st_cols = [c["name"] for c in inspector.get_columns(st_table)]
                        if "fused_source_count" not in st_cols:
                            conn.execute(text(f"ALTER TABLE {st_table} ADD COLUMN fused_source_count INTEGER"))
                        if "fused_lifecycle" not in st_cols:
                            conn.execute(text(f"ALTER TABLE {st_table} ADD COLUMN fused_lifecycle VARCHAR"))
                        conn.execute(text(
                            f"UPDATE {st_table} SET fused_source_count = distinct_source_count, "
                            f"fused_lifecycle = lifecycle "
                            f"WHERE summary IS NOT NULL AND fused_source_count IS NULL"))
                    # Junk-floored articles are settled, not pending: clear the
                    # backlog the old behaviour accumulated (526 of 572 "pending").
                    ra_table = "rawarticle"
                    if ra_table not in inspector.get_table_names() and "raw_article" in inspector.get_table_names():
                        ra_table = "raw_article"
                    if ra_table in inspector.get_table_names():
                        conn.execute(text(
                            f"UPDATE {ra_table} SET processed = 1 "
                            f"WHERE relevance_gated = 1 AND processed = 0"))
                    session.commit()

                elif m == "0011_from_account":
                    # Stamp "this came from an account the user NAMED" at intake
                    # instead of re-deriving it from the URL host at fusion time
                    # (docs/source_tiering.md §2). Legacy rows default to 0: they
                    # simply take the normal gate path rather than the people-radar
                    # bypass, which is the safe direction — under-, not over-trusting.
                    from sqlalchemy import inspect, text
                    inspector = inspect(engine)
                    conn = session.connection()
                    ra_table = "rawarticle"
                    if ra_table not in inspector.get_table_names() and "raw_article" in inspector.get_table_names():
                        ra_table = "raw_article"
                    if ra_table in inspector.get_table_names():
                        ra_cols = [c["name"] for c in inspector.get_columns(ra_table)]
                        if "from_account" not in ra_cols:
                            conn.execute(text(
                                f"ALTER TABLE {ra_table} ADD COLUMN from_account BOOLEAN DEFAULT 0"))
                    session.commit()

                elif m == "0012_release_rate_limit_quarantine":
                    # Rate limiting is now handled at host scope (host_politeness),
                    # so endpoints no longer accrue penalties for it. The records
                    # already on disk were written under the old rule and would
                    # mask the fix for hours — or forever, since a quarantined
                    # route never runs, never succeeds, and so never clears.
                    # Measured here before the reset: 5 quarantined, 10 degraded,
                    # backoffs up to 2.4h, all attributed to a host-wide refusal
                    # that none of these endpoints caused. Release them; the host
                    # cooldown is what should have been holding them back.
                    from sqlalchemy import inspect, text
                    inspector = inspect(engine)
                    conn = session.connection()
                    if "sourcehealth" in inspector.get_table_names():
                        conn.execute(text(
                            "UPDATE sourcehealth SET consecutive_failures = 0, "
                            "state = 'healthy', next_eligible_at = NULL "
                            "WHERE last_error_type = 'RATE_LIMITED'"))
                    session.commit()

                elif m == "0013_release_capability_failures":
                    # Companion to 0012, for the other not-the-endpoint's-fault
                    # class. While the packaged app could not find a browser, the
                    # 7 x.com routes recorded 7 failures and 0 successes each —
                    # one short of permanent quarantine — for a bug on our side.
                    # With the browser fixed they were still serving ~5.5h
                    # backoffs, so the repair stayed invisible.
                    #
                    # Scope: never succeeded AND last error unclassified. That is
                    # exactly the browser-outage signature (verified: 7 rows, all
                    # x.com). Deliberately safe to over-apply — a route released
                    # in error simply fails once more and re-earns its backoff
                    # within one cycle, whereas leaving it costs a capability
                    # that looks broken for hours after it was fixed.
                    from sqlalchemy import inspect, text
                    inspector = inspect(engine)
                    conn = session.connection()
                    if "sourcehealth" in inspector.get_table_names():
                        conn.execute(text(
                            "UPDATE sourcehealth SET consecutive_failures = 0, "
                            "state = 'healthy', next_eligible_at = NULL "
                            "WHERE total_success = 0 AND last_error_type = 'UNKNOWN_ERROR'"))
                    session.commit()

                elif m == "0014_first_party_floor_restamp":
                    # The first-party floor gained the frontier labs' own
                    # channels (deepmind.google et al. — see provenance.py for
                    # what was added and what deliberately was not). Tier is
                    # stamped at intake, so rows ingested under the old floor
                    # carry CURATED for what is now recognisably first-party;
                    # left alone, "Introducing Gemini 3.7 Flash" stays a muted
                    # singleton lead forever. Re-stamp those rows through the
                    # real tier_for_url (so the marketing-path and code-host
                    # guards still apply), then mirror what ingest would have
                    # done had it known: threads that now contain a PRIMARY
                    # member are promoted to CONFIRMED, and their gate marker is
                    # cleared so the next processing cycle re-evaluates them
                    # (gate_checked_at IS NULL is the re-check trigger).
                    from db.models import RawArticle, StoryThread
                    from services.provenance import Tier, tier_for_url
                    from sqlmodel import select as _select
                    restamped, thread_ids = 0, set()
                    rows = session.exec(_select(RawArticle).where(
                        RawArticle.source_tier == Tier.CURATED)).all()
                    for ra in rows:
                        new_tier = tier_for_url(ra.url or "", Tier.CURATED)
                        if new_tier == Tier.PRIMARY:
                            ra.source_tier = Tier.PRIMARY
                            session.add(ra)
                            restamped += 1
                            if ra.thread_id:
                                thread_ids.add(ra.thread_id)
                    promoted = 0
                    for tid in thread_ids:
                        th = session.get(StoryThread, tid)
                        if th is None:
                            continue
                        if th.lifecycle != "CONFIRMED":
                            th.lifecycle = "CONFIRMED"
                            promoted += 1
                        th.gate_checked_at = None
                        session.add(th)
                    session.commit()
                    print(f"first_party_floor_restamp: {restamped} articles → primary, "
                          f"{promoted} threads promoted CONFIRMED, "
                          f"{len(thread_ids)} threads queued for gate re-check")

                elif m == "0015_replay_material_timestamps":
                    # summarized_at now MEANS "when the story last materially
                    # changed" (radar sorts by it), and re-summaries now require
                    # ≥25% publisher growth or a promotion. But stamps written
                    # under the old any-new-publisher rule stand: the measured
                    # case is a 3-week-old, 39-publisher thread whose stamp says
                    # "today" because two straggler outlets re-burned it hours
                    # before this rule landed — so it outranks today's real news
                    # PERMANENTLY (the stamp only moves on the next material
                    # change, which for a settled story never comes). Same shape
                    # as 0012/0013: correct the records the old rule wrote, or
                    # the fix stays invisible.
                    #
                    # Replay each summarised thread's publisher-arrival sequence
                    # under the new rule (baseline advances only when an arrival
                    # is material, mirroring fusion's snapshot) and move the
                    # stamp BACK to the last material arrival. Never forward,
                    # and lifecycle promotions are unreplayable (no history) so
                    # threads may keep a slightly-late stamp — the safe side.
                    # Summary text is untouched; this corrects display honesty.
                    from db.models import RawArticle, StoryThread
                    from services.processor_service import is_material_increment
                    from services.provenance import real_publisher
                    from sqlmodel import select as _select
                    moved = 0
                    sthreads = session.exec(_select(StoryThread).where(
                        StoryThread.summary.is_not(None))).all()
                    for th in sthreads:
                        members = session.exec(
                            _select(RawArticle).where(RawArticle.thread_id == th.id)
                            .order_by(RawArticle.created_at)).all()
                        if not members or not th.summarized_at:
                            continue
                        pubs, prev = set(), 0
                        last_material = members[0].created_at
                        for mrow in members:
                            pubs.add(real_publisher(mrow.url or "", mrow.title or ""))
                            if is_material_increment(prev, "", len(pubs), ""):
                                last_material = mrow.created_at
                                prev = len(pubs)
                        if last_material and last_material < th.summarized_at:
                            th.summarized_at = last_material
                            session.add(th)
                            moved += 1
                    session.commit()
                    print(f"replay_material_timestamps: {moved}/{len(sthreads)} "
                          f"summarised threads moved back to their last material change")

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
