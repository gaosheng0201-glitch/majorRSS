"""
Source portfolio planner (R4) — the SourceSelector from the vision.

Turns a user's watch target ("apple siri", "某罕见病的新进展") into a concrete
plan: entity aliases, which preset collections to draw from (and why), keep/
ignore keywords, and a per-run budget. Planned ONCE at target creation (and on
periodic re-plan), so every fetch afterward is deterministic execution — zero
planning tokens per cycle.

Two paths:
  - LLM path (provider configured): expands entities and selects collections
    with reasons — the smart selector.
  - Deterministic fallback (pure-RSS / no model): token-overlap matching of the
    target against collection titles/descriptions/keywords. Always available, so
    a target still gets a sane portfolio with no AI.
"""
import json
import re
from typing import List, Optional

from pydantic import BaseModel, Field

from services.log_service import get_logger

logger = get_logger("planner")

_TOKEN_RE = re.compile(r"[0-9a-zA-Z一-鿿]+")

DEFAULT_BUDGET = {
    "max_sources_per_run": 8,
    # Key must match what the executor reads (scraper_service uses
    # max_items_per_route); a mismatched key silently disables the per-source cap.
    "max_items_per_route": 10,
    "prefer_cached_articles": True,
    "fallback_to_google_news": True,
    "min_relevance": 0.35,
}


class PortfolioPlan(BaseModel):
    detected_domain: str = Field(description="Broad domain, e.g. 'ai_technology', 'healthcare', 'crypto', 'general'")
    entities: List[str] = Field(default=[], description="Target + aliases/related names (multilingual)")
    selected_collections: List[str] = Field(default=[], description="Chosen preset collection ids")
    keep_keywords: List[str] = Field(default=[])
    ignore_keywords: List[str] = Field(default=[])
    rationale: str = Field(default="", description="Why these sources fit the target")


def _tokens(text: str) -> set:
    return {t.lower() for t in _TOKEN_RE.findall(text or "")}


def _load_collections() -> List[dict]:
    """All preset collections as dicts (id, title, description, keywords)."""
    from db.database import get_session
    from db.models import SourcePresetCollection
    from sqlmodel import select
    out = []
    with get_session() as s:
        for c in s.exec(select(SourcePresetCollection)).all():
            try:
                cats = json.loads(c.categories_json or "[]")
            except Exception:
                cats = []
            try:
                kws = json.loads(c.default_keywords_json or "[]")
            except Exception:
                kws = []
            out.append({
                "id": c.collection_id, "title": c.title,
                "description": c.description or "", "categories": cats,
                "keywords": kws, "source_count": c.source_count,
            })
    return out


def _fallback_plan(name: str, intent_text: str, collections: List[dict], max_collections: int = 4) -> PortfolioPlan:
    """Deterministic: score each collection by token overlap with the target."""
    target_tokens = _tokens(f"{name} {intent_text}")
    scored = []
    for c in collections:
        blob = " ".join([c["title"], c["description"], " ".join(map(str, c["categories"])), " ".join(map(str, c["keywords"]))])
        overlap = len(target_tokens & _tokens(blob))
        if overlap > 0:
            scored.append((overlap, c["id"]))
    scored.sort(reverse=True)
    selected = [cid for _, cid in scored[:max_collections]]
    # Always include a general baseline as background if present and nothing else matched well.
    general = next((c["id"] for c in collections if "general" in c["id"].lower() or "baseline" in c["title"].lower()), None)
    if general and general not in selected:
        selected.append(general)
    return PortfolioPlan(
        detected_domain="general",
        entities=[name] if name else [],
        selected_collections=selected[:max_collections + 1],
        keep_keywords=[t for t in _tokens(name) if len(t) > 2][:6],
        ignore_keywords=[],
        rationale="Keyword-overlap match (no generation model configured).",
    )


def plan_portfolio(name: str, intent_text: str = "", use_llm: bool = True) -> dict:
    """Produce a source portfolio for a target. Returns a JSON-able dict with
    the plan + the resolved budget + which planner was used."""
    collections = _load_collections()
    plan: Optional[PortfolioPlan] = None
    planner_used = "fallback"

    if use_llm:
        try:
            from services.llm_provider import get_provider
            provider = get_provider()
            if provider.supports_generation:
                catalog = "\n".join(
                    f"- {c['id']}: {c['title']} — {c['description'][:100]}" for c in collections)
                system = (
                    "You are a source-selection planner for a personal intelligence radar. "
                    "Given a watch target, expand its entities (include aliases and other-language names), "
                    "detect its domain, and pick the MOST RELEVANT preset collections from the catalog "
                    "(prefer few, high-signal collections over many). Provide keep/ignore keywords and a short rationale. "
                    "Return only collection ids that appear in the catalog."
                )
                prompt = (
                    f"WATCH TARGET: {name}\n"
                    f"USER INTENT: {intent_text or '(none given)'}\n\n"
                    f"AVAILABLE COLLECTIONS:\n{catalog}"
                )
                text, usage = provider.generate(prompt, system=system, schema=PortfolioPlan, temperature=0.3)
                data = json.loads(text)
                plan = PortfolioPlan(**data)
                # Guard: keep only collection ids that actually exist.
                valid_ids = {c["id"] for c in collections}
                plan.selected_collections = [c for c in plan.selected_collections if c in valid_ids]
                planner_used = provider.name
                try:
                    from llm.processor import _record_usage
                    _record_usage(provider.name, "PortfolioPlan", usage)
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"LLM portfolio planning failed ({e}); using fallback.")

    if plan is None:
        plan = _fallback_plan(name, intent_text, collections)

    # Compose the fetch_policy the resolver/executor will run deterministically.
    fetch_policy = dict(DEFAULT_BUDGET)
    fetch_policy.update({
        "source_scope": plan.selected_collections,
        "keep_keywords": plan.keep_keywords,
        "ignore_keywords": plan.ignore_keywords,
        "entities": plan.entities,
    })

    return {
        "planner_used": planner_used,
        "detected_domain": plan.detected_domain,
        "entities": plan.entities,
        "selected_collections": plan.selected_collections,
        "keep_keywords": plan.keep_keywords,
        "ignore_keywords": plan.ignore_keywords,
        "rationale": plan.rationale,
        "budget": DEFAULT_BUDGET,
        "fetch_policy": fetch_policy,
    }
