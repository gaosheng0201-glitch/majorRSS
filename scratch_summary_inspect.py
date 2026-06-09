from sqlmodel import Session, select
from db.database import engine
from db.models import IntelReport

with Session(engine) as session:
    report = session.exec(select(IntelReport).order_by(IntelReport.id.desc()).limit(1)).first()
    if report:
        print("Report ID:", report.id)
        print("llm_summary (repr):", repr(report.llm_summary))
    else:
        print("No report found.")
