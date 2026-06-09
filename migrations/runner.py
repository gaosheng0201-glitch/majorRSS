import os
import sys
from sqlmodel import select, SQLModel

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import engine, get_session
from db.models import SchemaVersion

def run_migrations():
    print("Running migrations...")
    # SQLModel create_all will create tables that don't exist yet (like TaskRequest and SchemaVersion)
    SQLModel.metadata.create_all(engine)
    
    with get_session() as session:
        # We define our applied migrations here
        migrations = [
            "0001_initial_and_task_request"
        ]
        
        for m in migrations:
            existing = session.exec(select(SchemaVersion).where(SchemaVersion.version_id == m)).first()
            if not existing:
                print(f"Applying migration: {m}")
                sv = SchemaVersion(version_id=m)
                session.add(sv)
                session.commit()
                print(f"Successfully applied {m}")
            else:
                print(f"Migration {m} already applied.")

if __name__ == "__main__":
    run_migrations()
