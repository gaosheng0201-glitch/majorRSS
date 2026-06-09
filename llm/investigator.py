import os
import json
from typing import List, Callable, Optional
from pydantic import BaseModel, Field
from duckduckgo_search import DDGS
from google import genai
from google.genai import types

from scrapers.tier3_agentic import AgenticScraper

class ChosenURLs(BaseModel):
    urls: List[str] = Field(description="Top 1 or 2 most authoritative source URLs to deep dive into.")

def _get_client(api_key: Optional[str] = None) -> genai.Client:
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set.")
    return genai.Client(api_key=api_key)

def log_token_usage(model_name: str, action_type: str, response):
    if hasattr(response, 'usage_metadata') and response.usage_metadata:
        try:
            from db.database import get_session
            from db.models import TokenUsage
            with get_session() as session:
                usage = TokenUsage(
                    model_name=model_name,
                    action_type=action_type,
                    prompt_tokens=response.usage_metadata.prompt_token_count or 0,
                    completion_tokens=response.usage_metadata.candidates_token_count or 0,
                    total_tokens=response.usage_metadata.total_token_count or 0
                )
                session.add(usage)
                session.commit()
        except Exception as e:
            print("Failed to log investigator token usage:", e)

def run_native_grounding(query: str, api_key: Optional[str] = None) -> str:
    """
    Pipeline A: Uses Gemini's native Google Search Grounding.
    """
    try:
        client = _get_client(api_key)
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=f"Conduct a thorough investigation and fact-check for the following query. Provide a comprehensive summary and verdict.\n\nQuery: {query}",
            config=types.GenerateContentConfig(
                tools=[{"googleSearch": {}}],
            )
        )
        log_token_usage('gemini-2.5-flash', 'Grounding Fact-Check', response)
        return response.text
    except Exception as e:
        return f"🚨 Native Grounding Failed: {e}\n\n*Note: Your API Key or GCP Project might not have access to Google Search Grounding for this model.*"

def run_major_funnel(query: str, api_key: Optional[str] = None, status_callback: Optional[Callable[[str], None]] = None) -> str:
    """
    Pipeline B: MajorRSS Custom Funnel (DDG -> LLM Triage -> Agentic Scrape -> Final Verdict)
    """
    try:
        client = _get_client(api_key)
    except Exception as e:
        return f"🚨 Initialization Failed: {e}"
        
    # Phase 1: Search
    if status_callback: status_callback("Phase 1/4: Searching DuckDuckGo...")
    try:
        results = DDGS().text(query, max_results=10)
        results_list = list(results) # Convert generator to list
        if not results_list:
            return "❌ No search results found on DuckDuckGo."
    except Exception as e:
        return f"🚨 DuckDuckGo Search Failed: {e}\n\n*Note: DuckDuckGo may be rate-limiting your IP.*"
        
    snippets = "\n".join([f"[{i}] {r.get('title', '')} - {r.get('href', '')}\n{r.get('body', '')}" for i, r in enumerate(results_list)])
    
    # Phase 2: LLM Triage
    if status_callback: status_callback("Phase 2/4: LLM Triaging sources...")
    try:
        triage_prompt = f"Analyze these search snippets. Select 1 or 2 most authoritative and direct URLs that can help fact-check this claim: '{query}'. Return ONLY the URLs.\n\nSnippets:\n{snippets}"
        
        triage_res = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=triage_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ChosenURLs,
            )
        )
        log_token_usage('gemini-2.5-flash', 'Investigator Triage', triage_res)
        
        chosen_data = json.loads(triage_res.text)
        urls_to_scrape = chosen_data.get('urls', [])[:2] # Limit to max 2
    except Exception as e:
        return f"🚨 LLM Triage Failed: {e}"
        
    if not urls_to_scrape:
        return "❌ LLM could not identify any authoritative sources from the snippets."
        
    # Phase 3: Agent Scrape
    if status_callback: status_callback(f"Phase 3/4: Deep scraping {len(urls_to_scrape)} URLs using AgenticScraper...")
    scraped_texts = []
    
    for url in urls_to_scrape:
        try:
            if status_callback: status_callback(f"Phase 3/4: Scraping {url}...")
            scraper = AgenticScraper(url)
            text = scraper.fetch_text_snapshot()
            # Truncate to 15k chars per URL to avoid blowing up context window unnecessarily
            scraped_texts.append(f"--- SOURCE: {url} ---\n{text[:15000]}") 
        except Exception as e:
            scraped_texts.append(f"--- SOURCE: {url} ---\nFailed to scrape: {e}")
            
    # Phase 4: Final Verdict
    if status_callback: status_callback("Phase 4/4: LLM Synthesizing Final Verdict...")
    try:
        full_context = "\n\n".join(scraped_texts)
        verdict_prompt = f"You are a Senior OSINT Analyst. Fact-check the following claim based ONLY on the provided full-text sources. Do not make up information.\n\nClaim: '{query}'\n\nSources:\n{full_context}\n\nProvide a detailed verdict (True/False/Unverified), explanation, and explicitly cite your sources."
        
        final_res = client.models.generate_content(
            model='gemini-2.5-flash', # Flash is fast and capable enough for this
            contents=verdict_prompt
        )
        log_token_usage('gemini-2.5-flash', 'Investigator Verdict', final_res)
        return final_res.text
    except Exception as e:
        return f"🚨 Final Verdict Synthesis Failed: {e}"
