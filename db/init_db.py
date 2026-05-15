import sys
import os
from sqlmodel import select

# Add the parent directory to sys.path so we can import db module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import create_db_and_tables, get_session
from db.models import Source

def initialize():
    print("Creating database and tables...")
    create_db_and_tables()
    print("Database initialized successfully.")
    
    # Add a default basic RSS source for testing
    session = get_session()
    statement = select(Source).where(Source.name == "HuggingFace Daily Papers")
    existing = session.exec(statement).first()
    
    if not existing:
        hf_source = Source(
            name="HuggingFace Daily Papers",
            url="https://rsshub.app/huggingface/daily-papers",
            tier=1,
            radar_section="Geek Radar"
        )
        session.add(hf_source)
        session.commit()
        print("Added default source: HuggingFace Daily Papers")
    else:
        print("Default source already exists.")

if __name__ == "__main__":
    initialize()
