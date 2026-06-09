import argparse
import sys
import os
import json

# Ensure root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.database import get_session
from db.models import IntelReport, DailyBriefing, PipelineStatus
from sqlmodel import select
from datetime import datetime, timezone

def get_news(section: str, format: str):
    session = get_session()
    query = select(IntelReport).where(IntelReport.validity_category.in_(["[VALID_NEWS]", "VALID_NEWS"]))
    if section:
        query = query.where(IntelReport.radar_section == section)
    
    reports = session.exec(query.order_by(IntelReport.created_at.desc()).limit(20)).all()
    
    if format == 'json':
        data = []
        for r in reports:
            try:
                entities = json.loads(r.key_entities)
            except:
                entities = []
            data.append({
                "id": r.original_content_hash,
                "radar_section": r.radar_section,
                "source_url": r.source_url,
                "importance_score": r.importance_score,
                "validity_category": r.validity_category,
                "key_entities": entities,
                "summary": r.llm_summary,
                "scraped_at": r.created_at.isoformat()
            })
            
        output = {
            "mip_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data": data
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        for r in reports:
            print(f"[{r.importance_score}⭐] {r.radar_section}: {r.source_url}")
            print(f"Summary: {r.llm_summary}\n")

def get_status():
    session = get_session()
    statuses = session.exec(select(PipelineStatus)).all()
    if not statuses:
        print(json.dumps({"status": "idle", "message": "No active tasks in the pipeline."}))
        return
        
    data = [{"source": s.tracker_name, "action": s.action_type, "detail": s.detail} for s in statuses]
    print(json.dumps({"status": "active", "tasks": data}, indent=2, ensure_ascii=False))

def get_briefing():
    session = get_session()
    briefing = session.exec(select(DailyBriefing).order_by(DailyBriefing.created_at.desc())).first()
    if not briefing:
        print(json.dumps({"error": "No daily briefing available."}))
        return
    print(json.dumps({
        "date": briefing.date_str,
        "content": briefing.content
    }, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MajorRSS CLI API for AI Agents")
    subparsers = parser.add_subparsers(dest="command")
    
    # Get command
    get_parser = subparsers.add_parser("get", help="Get latest valid news")
    get_parser.add_argument("--section", type=str, help="Filter by radar section (e.g. 'Frontier Outpost')")
    get_parser.add_argument("--format", type=str, choices=["json", "text"], default="json", help="Output format")
    
    # Status command
    status_parser = subparsers.add_parser("status", help="Get current pipeline status")
    
    # Briefing command
    briefing_parser = subparsers.add_parser("briefing", help="Get latest daily briefing")
    
    args = parser.parse_args()
    
    if args.command == "get":
        get_news(args.section, args.format)
    elif args.command == "status":
        get_status()
    elif args.command == "briefing":
        get_briefing()
    else:
        parser.print_help()
