import os
import json
from typing import List, Callable, Optional
from pydantic import BaseModel, Field
from duckduckgo_search import DDGS

from scrapers.tier3_agentic import AgenticScraper
from services.llm_provider import get_provider


class ChosenURLs(BaseModel):
    urls: List[str] = Field(description="Top 1 or 2 most authoritative source URLs to deep dive into.")


def _record(provider_name: str, action: str, usage: dict) -> None:
    """Route token usage through the shared accounting so the daily budget brake
    sees investigator calls too (it previously used a separate ad-hoc logger)."""
    try:
        from llm.processor import _record_usage
        _record_usage(provider_name, action, usage or {})
    except Exception as e:
        print("Failed to record investigator token usage:", e)


def run_native_grounding(query: str, api_key: Optional[str] = None) -> str:
    """Pipeline A: Gemini-native Google Search grounding.

    This is a Gemini-only capability (googleSearch grounding has no equivalent in
    the OpenAI/local dialect), so it is *guarded*: if Gemini isn't the configured
    provider, return a helpful message pointing at the funnel instead of failing
    with a raw "GEMINI_API_KEY not set" — a local/OpenAI-compatible user should
    still be able to use Pipeline B.
    """
    key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("LLM_API_KEY")
    if not key or (not api_key and os.environ.get("LLM_PROVIDER", "gemini").lower() != "gemini"):
        return ("ℹ️ 原生联网核查依赖 Gemini 的 Google Search Grounding，当前未配置 Gemini。"
                "可改用下方「自建漏斗」（支持任意模型：Gemini / OpenAI 兼容 / 本地），"
                "或在系统设置中配置 Gemini API Key。")
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=key)  # bound to a local — no GC-mid-request risk
        model = os.environ.get("LLM_GROUNDING_MODEL", "gemini-2.5-flash")
        response = client.models.generate_content(
            model=model,
            contents=(f"Conduct a thorough investigation and fact-check for the following query. "
                      f"Provide a comprehensive summary and verdict.\n\nQuery: {query}"),
            config=types.GenerateContentConfig(tools=[{"googleSearch": {}}]),
        )
        um = getattr(response, "usage_metadata", None)
        if um:
            _record(f"gemini:{model}", "Grounding Fact-Check", {
                "prompt_tokens": um.prompt_token_count or 0,
                "completion_tokens": um.candidates_token_count or 0,
                "total_tokens": um.total_token_count or 0,
            })
        return response.text
    except Exception as e:
        return (f"🚨 Native Grounding Failed: {e}\n\n"
                "*Note: Your API Key or GCP Project might not have access to Google Search Grounding for this model.*")


def run_major_funnel(query: str, api_key: Optional[str] = None,
                     status_callback: Optional[Callable[[str], None]] = None) -> str:
    """Pipeline B: provider-agnostic OSINT funnel — DDG search → LLM triage →
    agentic scrape → LLM verdict. The LLM steps go through the provider
    abstraction, so this works with Gemini, OpenAI-compatible endpoints, and
    local models (Ollama/LM Studio/vLLM) — not just Gemini.
    """
    provider = get_provider()
    if not provider.supports_generation:
        return ("🚨 未配置可用于生成的模型。请在「系统设置」中配置 API Key，"
                "或指向本地模型（LLM_PROVIDER=openai_compatible + LLM_BASE_URL）。")

    # Phase 1: Search
    if status_callback:
        status_callback("Phase 1/4: Searching DuckDuckGo...")
    try:
        results_list = list(DDGS().text(query, max_results=10))
        if not results_list:
            return "❌ No search results found on DuckDuckGo."
    except Exception as e:
        return f"🚨 DuckDuckGo Search Failed: {e}\n\n*Note: DuckDuckGo may be rate-limiting your IP.*"

    snippets = "\n".join([f"[{i}] {r.get('title', '')} - {r.get('href', '')}\n{r.get('body', '')}"
                          for i, r in enumerate(results_list)])

    # Phase 2: LLM Triage (provider-agnostic)
    if status_callback:
        status_callback("Phase 2/4: LLM Triaging sources...")
    try:
        triage_prompt = (
            f"Analyze these search snippets. Select the 1 or 2 most authoritative and direct URLs "
            f"that can help fact-check this claim: '{query}'. "
            f'Return ONLY JSON of the form {{"urls": ["https://...", "https://..."]}}.\n\nSnippets:\n{snippets}'
        )
        text, usage = provider.generate(triage_prompt, schema=ChosenURLs, temperature=0.2)
        _record(provider.name, "Investigator Triage", usage)
        chosen_data = json.loads(text)
        urls_to_scrape = (chosen_data.get('urls') or [])[:2]
    except Exception as e:
        return f"🚨 LLM Triage Failed: {e}"

    if not urls_to_scrape:
        return "❌ LLM could not identify any authoritative sources from the snippets."

    # Phase 3: Agent Scrape (unchanged)
    if status_callback:
        status_callback(f"Phase 3/4: Deep scraping {len(urls_to_scrape)} URLs using AgenticScraper...")
    scraped_texts = []
    for url in urls_to_scrape:
        try:
            if status_callback:
                status_callback(f"Phase 3/4: Scraping {url}...")
            text = AgenticScraper(url).fetch_text_snapshot()
            scraped_texts.append(f"--- SOURCE: {url} ---\n{(text or '')[:15000]}")
        except Exception as e:
            scraped_texts.append(f"--- SOURCE: {url} ---\nFailed to scrape: {e}")

    # Phase 4: Final Verdict (provider-agnostic)
    if status_callback:
        status_callback("Phase 4/4: LLM Synthesizing Final Verdict...")
    try:
        full_context = "\n\n".join(scraped_texts)
        verdict_prompt = (
            f"You are a Senior OSINT Analyst. Fact-check the following claim based ONLY on the provided "
            f"full-text sources. Do not make up information.\n\nClaim: '{query}'\n\nSources:\n{full_context}\n\n"
            f"Provide a detailed verdict (True/False/Unverified), explanation, and explicitly cite your sources."
        )
        text, usage = provider.generate(verdict_prompt, temperature=0.2)
        _record(provider.name, "Investigator Verdict", usage)
        return text
    except Exception as e:
        return f"🚨 Final Verdict Synthesis Failed: {e}"
