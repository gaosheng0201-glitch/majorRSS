import os
import json
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from datetime import datetime, timezone, timedelta
from db.database import get_session
from db.models import IntelReport, DailyBriefing, TokenUsage
from sqlmodel import select
from typing import Optional

def get_target_language() -> str:
    lang_map = {
        "zh": "Chinese (简体中文)",
        "en": "English",
        "ko": "Korean (한국어)",
        "ja": "Japanese (日本語)",
        "ru": "Russian (Русский)"
    }
    return lang_map.get(os.environ.get("SYSTEM_LANGUAGE", "zh").lower(), "Chinese (简体中文)")

class FactCheckResult(BaseModel):
    validity_category: str = Field(description="Must be one of: [VALID_NEWS], [SPAM], [MALICIOUS_LINK], [NOISE]")
    importance_score: int = Field(description="Score from 1 to 5, where 5 is highly important/breaking news.")
    title: str = Field(description="A concise, high-value title summarizing the core event or main update of this batch in the language specified in the system instructions. Do not exceed 12 words.")
    llm_summary: str = Field(description="A concise, factual summary of the core news/update in the language specified in the system instructions. Remove marketing fluff. Leave blank or short if it is a duplicate.")
    key_entities: list[str] = Field(default=[], description="List of core entities (people, products, companies) mentioned, max 5.")
    relevant_source_indices: list[int] = Field(default=[], description="List of Source indices (e.g. [1, 3]) that were actually relevant to the news and used for the summary. Exclude indices of noise or irrelevant sources.")
    event_timestamp: Optional[str] = Field(default=None, description="The ISO8601 string (e.g. 2026-05-11T12:00:00Z) of when the event happened or the article was published, based on the text. If absolutely unknown or hidden, return null.")
    duplicate_of_report_id: Optional[int] = Field(default=None, description="If the core event in this batch is already reported in the provided list of 'Recent Summaries', set this to the ID of that duplicate report. Otherwise, return null.")

def process_article(content: str, radar_section: str, prompt_override: str = None, api_key: str = None, tracker_name: str = None, recent_context: str = None) -> FactCheckResult:
    """
    Passes the scraped content through Gemini to fact-check, categorize, and summarize.
    """
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set.")
    
    client = genai.Client(api_key=api_key)

    if prompt_override:
        system_instruction = (
            f"You are an OSINT AI Analyst for the '{radar_section}' radar. "
            f"USER DIRECTIVE: {prompt_override}\n"
            "Analyze the content exactly as requested by the user directive. "
            "Determine if the content is valid news, spam, a malicious link, or just noise."
        )
    elif radar_section == "Frontier Outpost":
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

    target_lang = get_target_language()
    system_instruction += f"\n\nCRITICAL: You MUST write both the 'title' and 'llm_summary' in {target_lang} regardless of the input language."

    if recent_context:
        system_instruction += (
            "\n\nIMPORTANT DEDUPLICATION INSTRUCTION: You are provided with a list of 'RECENTLY REPORTED INTELLIGENCE REPORTS' (Recent Summaries) with their IDs. "
            "Your absolute priority is to avoid creating redundant reports. "
            "If the new content ONLY reports the same event/update that is already summarized in the recent list, "
            "you MUST classify the validity_category as '[NOISE]' or '[SPAM]', set `duplicate_of_report_id` to the ID of the matching report, "
            "and list the indices of the redundant sources under `relevant_source_indices`. "
            "If the new content contains BOTH duplicate news and new, valuable news, summarize ONLY the new news in `llm_summary`, "
            "and exclude the duplicate indices from `relevant_source_indices` while returning `duplicate_of_report_id` as null."
        )
        
    prompt_contents = f"Analyze the following content:\n\n{content}"
    if recent_context:
        prompt_contents = (
            f"--- RECENTLY REPORTED INTELLIGENCE REPORTS ---\n"
            f"{recent_context}\n\n"
            f"--- NEW CONTENT TO ANALYZE ---\n"
            f"{content}"
        )

    import time
    max_retries = 4
    base_sleep = 2
    
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model='gemini-3-flash-preview',
                contents=prompt_contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_schema=FactCheckResult,
                    temperature=0.2,
                ),
            )
            break
        except Exception as e:
            if "429" in str(e) or "Too Many Requests" in str(e) or "Resource exhausted" in str(e):
                if attempt == max_retries - 1:
                    raise e
                sleep_time = base_sleep * (2 ** attempt)
                print(f"Rate limited by Gemini API. Retrying in {sleep_time} seconds (attempt {attempt + 1}/{max_retries})...")
                time.sleep(sleep_time)
            else:
                raise e
    
    if hasattr(response, 'usage_metadata') and response.usage_metadata:
        try:
            with get_session() as session:
                usage = TokenUsage(
                    model_name='gemini-3-flash-preview',
                    action_type=f"FactCheck: {tracker_name}" if tracker_name else "FactCheck",
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

def generate_daily_briefing(target_sections: list[str] = None, api_key: str = None) -> str:
    """
    Fetches all VALID_NEWS since the last daily briefing (capped at 3 days)
    and uses Gemini to generate a cohesive daily briefing / podcast script.
    """
    session = get_session()
    
    # Retrieve the latest generated daily briefing to check the last briefing time
    last_briefing = session.exec(
        select(DailyBriefing).order_by(DailyBriefing.created_at.desc())
    ).first()
    
    now_utc = datetime.now(timezone.utc)
    if last_briefing:
        start_time = last_briefing.created_at
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        # Cap the start time to at most 3 days ago to prevent token overflow
        three_days_ago = now_utc - timedelta(days=3)
        if start_time < three_days_ago:
            start_time = three_days_ago
    else:
        # Default fallback to 24 hours ago
        start_time = now_utc - timedelta(days=1)
        
    query = select(IntelReport).where(IntelReport.validity_category.in_(["[VALID_NEWS]", "VALID_NEWS"])).where(IntelReport.created_at >= start_time)
    if target_sections:
        query = query.where(IntelReport.radar_section.in_(target_sections))
        
    reports = session.exec(query).all()
    
    # Also fetch subscription updates
    from db.models import SubscriptionUpdate, Subscription
    subs_updates = session.exec(select(SubscriptionUpdate, Subscription).join(Subscription).where(SubscriptionUpdate.created_at >= start_time)).all()
    
    if not reports and not subs_updates:
        session.close()
        return "Not enough news or updates since the last briefing to generate a new briefing."
        
    content_list = []
    if subs_updates:
        content_list.append("### [WEBPAGE MONITOR SUBSCRIPTIONS]")
        for update, sub in subs_updates:
            summary_txt = update.llm_summary if update.llm_summary else update.diff_text[:500]
            content_list.append(f"Source: {sub.target_url}\nSection: Monitor - {sub.name}\nSummary: {summary_txt}\nImportance: 4/5\n")
            
    if reports:
        content_list.append("### [RSS INTEL REPORTS]")
    for r in reports:
        content_list.append(f"Source: {r.source_url}\nSection: {r.radar_section}\nSummary: {r.llm_summary}\nImportance: {r.importance_score}/5\n")
        
    master_text = "\n---\n".join(content_list)
    
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set.")
    
    client = genai.Client(api_key=api_key)
    
    target_lang = get_target_language()
    system_instruction = (
        "You are an expert technology analyst and podcast host. "
        "Your task is to review the following high-value intelligence reports collected over the past 24 hours. "
        f"Synthesize them into a cohesive, engaging 'Daily Briefing' written entirely in {target_lang}. "
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
            session.commit()
        except:
            pass
    
    briefing_text = response.text
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    section_name_val = "ALL"
    if target_sections:
        section_name_val = ",".join(target_sections)
        
    existing = session.exec(select(DailyBriefing).where(DailyBriefing.date_str == date_str).where(DailyBriefing.section_name == section_name_val)).first()
    if existing:
        existing.content = briefing_text
        session.add(existing)
    else:
        db_briefing = DailyBriefing(date_str=date_str, section_name=section_name_val, content=briefing_text)
        session.add(db_briefing)
    session.commit()
    session.close()
    return briefing_text

def scan_trends(api_key: str = None):
    """
    Scans recent IntelReports for entity spikes and generates alerts.
    """
    from db.models import TrendAlert
    session = get_session()
    recent_time = datetime.now(timezone.utc) - timedelta(hours=12)
    
    reports = session.exec(
        select(IntelReport)
        .where(IntelReport.validity_category.in_(["[VALID_NEWS]", "VALID_NEWS"]))
        .where(IntelReport.created_at >= recent_time)
    ).all()
    
    if not reports:
        session.close()
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
                        session.close()
                        return
                client = genai.Client(api_key=api_key)
                
                content_list = [f"Source: {r.source_url}\nSummary: {r.llm_summary}" for r in data["reports"]]
                master_text = "\n---\n".join(content_list)
                
                target_lang = get_target_language()
                system_instruction = (
                    f"You are a Trend Analyst. Multiple sources have recently reported on '{data['name']}'. "
                    f"Analyze these reports and provide a short, urgent 1-paragraph alert summarizing "
                    f"what is happening with this entity. The alert summary MUST be written in {target_lang}."
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
    session.close()

def summarize_diff(diff_text: str, api_key: str = None) -> str:
    """Provides a concise summary of what changed in a text diff."""
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set.")
    
    client = genai.Client(api_key=api_key)
    target_lang = get_target_language()
    prompt = f"You are an assistant tracking webpage changes. The following is a diff showing what changed on a tracked page. Provide a very concise, 1-2 sentence summary of what was added, removed, or changed in {target_lang}. Ignore minor whitespace or formatting changes.\n\nDIFF:\n{diff_text}"
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        # Log token usage
        try:
            with get_session() as session:
                tu = TokenUsage(
                    model_name="gemini-2.5-flash",
                    action_type="Diff Summary",
                    prompt_tokens=response.usage_metadata.prompt_token_count,
                    completion_tokens=response.usage_metadata.candidates_token_count,
                    total_tokens=response.usage_metadata.total_token_count
                )
                session.add(tu)
                session.commit()
        except:
            pass
            
        return response.text
    except Exception as e:
        return f"Failed to summarize: {e}"
    
