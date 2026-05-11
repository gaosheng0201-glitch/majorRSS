import sqlite3
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

db_path = os.path.join("d:\\majorRSS", "major_rss.db")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE intelreport ADD COLUMN key_entities VARCHAR DEFAULT '[]'")
    print("Added key_entities to intelreport.")
except Exception as e:
    print("Column may already exist:", e)

conn.commit()
conn.close()

from db.database import create_db_and_tables
create_db_and_tables()
print("Created missing tables.")
