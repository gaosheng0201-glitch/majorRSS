import os
import json
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from datetime import datetime, timezone, timedelta
from db.database import get_session
from db.models import IntelReport, DailyBriefing, TokenUsage
from sqlmodel import select

class FactCheckResult(BaseModel):
    validity_category: str = Field(description="Must be one of: [VALID_NEWS], [SPAM], [MALICIOUS_LINK], [NOISE]")
    importance_score: int = Field(description="Score from 1 to 5, where 5 is highly important/breaking news.")
    llm_summary: str = Field(description="A concise, factual summary of the core news/update. Remove marketing fluff.")
    key_entities: list[str] = Field(default=[], description="List of core entities (people, products, companies) mentioned, max 5.")

def process_article(content: str, radar_section: str, api_key: str = None) -> FactCheckResult:
    """
    Passes the scraped content through Gemini to fact-check, categorize, and summarize.
    """
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set.")
    
    client = genai.Client(api_key=api_key)
    
    # Select prompt based on section
    if radar_section == "Frontier Outpost":
        system_instruction = (
            "You are an AI Fact-Checker for the 'Frontier Outpost' radar. "
            "Your job is to read the latest updates from AI model vendors (OpenAI, Anthropic, etc). "
            "Extract the real impact on developer workflows, ignore marketing fluff. "
            "Determine if the content is valid news, spam, a malicious link, or just noise."
        )
    else:
        system_instruction = (
            "You are an AI Fact-Checker for the 'Geek Radar'. "
            "Your job is to read open source news, GitHub trending descriptions, and community discussions. "
            "Summarize the community consensus or the tool's core utility. "
            "Determine if the content is valid news, spam, a malicious link, or just noise."
        )

    response = client.models.generate_content(
        model='gemini-3-flash-preview',
        contents=f"Analyze the following content:\n\n{content}",
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=FactCheckResult,
            temperature=0.2,
        ),
    )
    
    if hasattr(response, 'usage_metadata') and response.usage_metadata:
        try:
            session = next(get_session())
            usage = TokenUsage(
                model_name='gemini-3-flash-preview',
                action_type='FactCheck',
                prompt_tokens=response.usage_metadata.prompt_token_count or 0,
                completion_tokens=response.usage_metadata.candidates_token_count or 0,
                total_tokens=response.usage_metadata.total_token_count or 0
            )
            session.add(usage)
            session.commit()
        except:
            pass
    
    result_dict = json.loads(response.text)
    return FactCheckResult(**result_dict)

def generate_daily_briefing(api_key: str = None) -> str:
    """
    Fetches all VALID_NEWS from the past 24 hours and uses Gemini
    to generate a cohesive daily briefing / podcast script.
    """
    session = next(get_session())
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    
    reports = session.exec(
        select(IntelReport)
        .where(IntelReport.validity_category.in_(["[VALID_NEWS]", "VALID_NEWS"]))
        .where(IntelReport.created_at >= yesterday)
    ).all()
    
    if not reports:
        return "Not enough news in the past 24 hours to generate a briefing."
        
    content_list = []
    for r in reports:
        content_list.append(f"Source: {r.source_url}\nSection: {r.radar_section}\nSummary: {r.llm_summary}\nImportance: {r.importance_score}/5\n")
        
    master_text = "\n---\n".join(content_list)
    
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set.")
    
    client = genai.Client(api_key=api_key)
    
    system_instruction = (
        "You are an expert technology analyst and podcast host. "
        "Your task is to review the following high-value intelligence reports collected over the past 24 hours. "
        "Synthesize them into a cohesive, engaging 'Daily Briefing'. "
        "Group related topics together, highlight the most important updates (5-star importance), and explain the broader industry context or implications. "
        "Use markdown formatting. Do not just list them out; tell a narrative of what happened in tech/AI today."
    )

    response = client.models.generate_content(
        model='gemini-3.1-pro-preview', # Use latest 3.1 Pro
        contents=f"Generate the daily briefing based on the following raw reports:\n\n{master_text}",
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.4,
        ),
    )
    
    if hasattr(response, 'usage_metadata') and response.usage_metadata:
        try:
            usage = TokenUsage(
                model_name='gemini-3.1-pro-preview',
                action_type='DailyBriefing',
                prompt_tokens=response.usage_metadata.prompt_token_count or 0,
                completion_tokens=response.usage_metadata.candidates_token_count or 0,
                total_tokens=response.usage_metadata.total_token_count or 0
            )
            session.add(usage)
        except:
            pass
    
    briefing_text = response.text
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    existing = session.exec(select(DailyBriefing).where(DailyBriefing.date_str == date_str)).first()
    if existing:
        existing.content = briefing_text
        session.add(existing)
    else:
        db_briefing = DailyBriefing(date_str=date_str, content=briefing_text)
        session.add(db_briefing)
    session.commit()
    
    
    return briefing_text

def scan_trends(api_key: str = None):
    """
    Scans recent IntelReports for entity spikes and generates alerts.
    """
    from db.models import TrendAlert
    session = next(get_session())
    recent_time = datetime.now(timezone.utc) - timedelta(hours=12)
    
    reports = session.exec(
        select(IntelReport)
        .where(IntelReport.validity_category.in_(["[VALID_NEWS]", "VALID_NEWS"]))
        .where(IntelReport.created_at >= recent_time)
    ).all()
    
    if not reports:
        return
        
    entity_to_reports = {}
    for r in reports:
        try:
            entities = json.loads(r.key_entities)
            for e in entities:
                e_norm = e.strip().upper()
                if e_norm not in entity_to_reports:
                    entity_to_reports[e_norm] = {"name": e.strip(), "reports": []}
                entity_to_reports[e_norm]["reports"].append(r)
        except:
            pass
            
    # Check for threshold (e.g. appeared in >= 2 distinct sources for testing)
    for e_norm, data in entity_to_reports.items():
        unique_sources = set([r.source_url for r in data["reports"]])
        if len(unique_sources) >= 2:
            existing = session.exec(
                select(TrendAlert)
                .where(TrendAlert.entity_name == data["name"])
                .where(TrendAlert.created_at >= recent_time)
            ).first()
            if not existing:
                if not api_key:
                    api_key = os.environ.get("GEMINI_API_KEY")
                    if not api_key:
                        return
                client = genai.Client(api_key=api_key)
                
                content_list = [f"Source: {r.source_url}\nSummary: {r.llm_summary}" for r in data["reports"]]
                master_text = "\n---\n".join(content_list)
                
                system_instruction = (
                    f"You are a Trend Analyst. Multiple sources have recently reported on '{data['name']}'. "
                    "Analyze these reports and provide a short, urgent 1-paragraph alert summarizing "
                    "what is happening with this entity."
                )
                
                response = client.models.generate_content(
                    model='gemini-3-flash-preview',
                    contents=master_text,
                    config=types.GenerateContentConfig(system_instruction=system_instruction)
                )
                
                if hasattr(response, 'usage_metadata') and response.usage_metadata:
                    try:
                        usage = TokenUsage(
                            model_name='gemini-3-flash-preview',
                            action_type='TrendScan',
                            prompt_tokens=response.usage_metadata.prompt_token_count or 0,
                            completion_tokens=response.usage_metadata.candidates_token_count or 0,
                            total_tokens=response.usage_metadata.total_token_count or 0
                        )
                        session.add(usage)
                    except:
                        pass
                
                alert = TrendAlert(
                    entity_name=data["name"],
                    alert_summary=response.text,
                    related_article_ids=",".join([str(r.id) for r in data["reports"]])
                )
                session.add(alert)
                session.commit()
                print(f"Generated Trend Alert for: {data['name']}")
