import sqlite3
import os

def migrate_db():
    db_path = "major_rss.db"
    if not os.path.exists(db_path):
        print(f"Database {db_path} not found. Skipping migration.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Check if 'source' table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='source'")
        if not cursor.fetchone():
            print("Table 'source' does not exist. Already migrated?")
            return

        print("Migrating 'source' to 'tracker'...")
        
        # Read old sources
        cursor.execute("SELECT id, name, url, tier, radar_section, is_active, created_at, last_scraped_at FROM source")
        sources = cursor.fetchall()

        # Rename rawarticle source_id to tracker_id, but SQLite ALTER TABLE is limited
        # So we will drop the rawarticle and recreate it (or rename column if sqlite version supports it)
        # Actually SQLite >= 3.25 supports RENAME COLUMN
        try:
            cursor.execute("ALTER TABLE rawarticle RENAME COLUMN source_id TO tracker_id")
            print("Renamed rawarticle.source_id to tracker_id.")
        except Exception as e:
            print(f"Could not rename rawarticle column: {e}")

        try:
            cursor.execute("ALTER TABLE pipelinestatus RENAME COLUMN source_name TO tracker_name")
            print("Renamed pipelinestatus.source_name to tracker_name.")
        except Exception as e:
            print(f"Could not rename pipelinestatus column: {e}")

        # Create new Tracker table
        # We drop it first if it exists from a previous partial run
        cursor.execute("DROP TABLE IF EXISTS tracker")
        cursor.execute('''
            CREATE TABLE tracker (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR NOT NULL,
                tracker_type VARCHAR NOT NULL,
                target VARCHAR NOT NULL,
                tier INTEGER NOT NULL,
                radar_section VARCHAR NOT NULL,
                is_active BOOLEAN NOT NULL,
                fetch_interval_minutes INTEGER NOT NULL,
                prompt_override VARCHAR,
                cookie_string VARCHAR,
                created_at DATETIME NOT NULL,
                last_scraped_at DATETIME
            )
        ''')

        # Insert data into Tracker
        for s in sources:
            s_id, name, url, tier, radar_section, is_active, created_at, last_scraped_at = s
            # Map URL -> tracker_type='URL', target=url
            cursor.execute('''
                INSERT INTO tracker (id, name, tracker_type, target, tier, radar_section, is_active, fetch_interval_minutes, prompt_override, cookie_string, created_at, last_scraped_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (s_id, name, 'URL', url, tier, radar_section, is_active, 30, None, None, created_at, last_scraped_at))

        print(f"Migrated {len(sources)} sources to trackers.")

        # Drop the old source table
        cursor.execute("DROP TABLE source")
        
        # Update dailybriefing if needed
        # We need to add section_name to dailybriefing
        try:
            cursor.execute("ALTER TABLE dailybriefing ADD COLUMN section_name VARCHAR NOT NULL DEFAULT 'ALL'")
            print("Added section_name to dailybriefing.")
        except Exception as e:
            print(f"Could not add section_name to dailybriefing: {e}")

        conn.commit()
        print("Migration complete!")
    except Exception as e:
        print(f"Migration error: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_db()
