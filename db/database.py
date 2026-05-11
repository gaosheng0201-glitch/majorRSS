from sqlmodel import SQLModel, create_engine, Session
from .models import Source, RawArticle, IntelReport, PipelineStatus, DailyBriefing, TrendAlert, TokenUsage

sqlite_file_name = "major_rss.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

# echo=False prevents printing all SQL statements to the console
engine = create_engine(sqlite_url, echo=False)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session
