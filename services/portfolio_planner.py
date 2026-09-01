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


# High-signal token → preset collection ids. Bridges the gap where a target names
# a specific entity (grok, xai, bitcoin, cve...) that isn't literally present in a
# collection's title/keywords, so the no-model fallback still routes to the right
# curated first-party sources instead of collapsing to a keyword Google search
# (愿景: 纯 RSS 模式无 key 也要有价值). Ids not present at runtime are ignored.
_ENTITY_LEXICON = {
    # frontier AI / models
    "ai": ["frontier_model_labs", "ai_infra_radar"],
    "llm": ["frontier_model_labs", "ai_papers"],
    "agi": ["frontier_model_labs"], "model": ["frontier_model_labs"],
    "openai": ["frontier_model_labs", "ai_infra_radar"], "gpt": ["frontier_model_labs"],
    "anthropic": ["frontier_model_labs"], "claude": ["frontier_model_labs"],
    "gemini": ["frontier_model_labs"], "deepmind": ["frontier_model_labs"],
    "grok": ["frontier_model_labs"], "xai": ["frontier_model_labs"],
    "grokai": ["frontier_model_labs"], "spacexai": ["frontier_model_labs"],
    "llama": ["frontier_model_labs"], "mistral": ["frontier_model_labs"],
    "huggingface": ["ai_infra_radar"], "inference": ["ai_infra_radar"],
    "gpu": ["ai_infra_radar"], "nvidia": ["ai_infra_radar"],
    "paper": ["ai_papers"], "arxiv": ["ai_papers"], "research": ["academic_research"],
    "api": ["developer_tools_changelog"], "changelog": ["developer_tools_changelog"],
    "sdk": ["developer_tools_changelog"], "developer": ["developer_tools_changelog"],
    # crypto
    "crypto": ["crypto_web3_watch", "crypto_people_radar"], "bitcoin": ["crypto_web3_watch"],
    "btc": ["crypto_web3_watch"], "eth": ["crypto_web3_watch"], "ethereum": ["crypto_web3_watch"],
    "web3": ["crypto_web3_watch"], "defi": ["crypto_web3_watch"], "solana": ["crypto_web3_watch"],
    # security
    "security": ["cybersecurity_watch"], "cve": ["cybersecurity_watch"],
    "vulnerability": ["cybersecurity_watch"], "exploit": ["cybersecurity_watch"],
    "breach": ["cybersecurity_watch"], "malware": ["cybersecurity_watch"],
    # finance / policy / health
    "market": ["market_and_economy_baseline"], "economy": ["market_and_economy_baseline"],
    "stock": ["market_and_economy_baseline"], "fed": ["market_and_economy_baseline"],
    "policy": ["policy_international_orgs", "regulatory_radar"],
    "regulation": ["regulatory_radar"], "regulatory": ["regulatory_radar"],
    "health": ["healthcare_medicine"], "medical": ["healthcare_medicine"],
    "disease": ["healthcare_medicine"], "drug": ["healthcare_medicine"],
}


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
    valid_ids = {c["id"] for c in collections}

    # 1) Entity lexicon: map named entities/topics to their curated collections.
    lexicon_hits: dict = {}
    for tok in target_tokens:
        for cid in _ENTITY_LEXICON.get(tok, []):
            if cid in valid_ids:
                lexicon_hits[cid] = lexicon_hits.get(cid, 0) + 3  # weight over raw overlap

    # 2) Token overlap against each collection's title/description/keywords.
    scored = []
    for c in collections:
        blob = " ".join([c["title"], c["description"], " ".join(map(str, c["categories"])), " ".join(map(str, c["keywords"]))])
        overlap = len(target_tokens & _tokens(blob)) + lexicon_hits.get(c["id"], 0)
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


# ---------------------------------------------------------------------------
# P4.0 意图探索 — IntentPlan, PortfolioPlan's successor (docs/p4_intent_design.md)
#
# One natural-language sentence → one LLM call at creation time → a complete,
# structured task definition the runtime executes deterministically afterwards.
# PortfolioPlan stays: it is the down-converted subset older code reads, and the
# deterministic fallback still produces it. IntentPlan adds what Drift 3 said
# was missing: per-alias language/region intent, per-target official domains,
# and the radar-vs-monitor lane call.
# ---------------------------------------------------------------------------

_DOMAIN_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.[a-z0-9-]{1,63})+$")


class AliasSpec(BaseModel):
    text: str = Field(description="The alias itself, e.g. '渐冻症' / 'ALS' / '筋萎縮性側索硬化症'")
    lang: str = Field(default="en", description="BCP-47 language of this alias, e.g. 'zh', 'en', 'ja'")
    regions: List[str] = Field(default=[], description="Region editions worth searching for this alias, e.g. ['CN'] or ['US','GB']")
    role: str = Field(default="name", description="name | person | org | product | ticker")


class SourceSuggestion(BaseModel):
    kind: str = Field(description="rss | account | subreddit | registry | page_monitor")
    value: str = Field(description="URL / @handle / subreddit name / registry query")
    platform: str = Field(default="", description="twitter / reddit / ... when kind is account or subreddit")
    reason: str = Field(default="", description="Why this source fits (explainability > automation)")
    verified: bool = Field(default=False, description="Existence-checked. Models invent sources; unverified stays a suggestion.")
    # Whether the runtime consumes it. Verification sets it (verified → on,
    # unverified → off by default); the user flips it in the proposal card.
    selected: bool = Field(default=False)


class IntentPlan(BaseModel):
    lane: str = Field(default="radar", description="'radar' (follow a TOPIC: multi-source, must earn attention) or 'monitor' (watch a SPECIFIC artifact: any change IS the event)")
    lane_reason: str = Field(default="", description="One sentence on why this lane")
    monitor_url: str = Field(default="", description="When lane=monitor: the exact page URL to diff-watch")
    entities: List[AliasSpec] = Field(default=[], description="Language-independent entity profile: the target plus aliases in every language it is reported in")
    official_domains: List[str] = Field(default=[], description="THIS target's own official domains (per-target first-party), e.g. ['deepmind.google'] for a Gemini target")
    selected_collections: List[str] = Field(default=[], description="Preset collection ids from the catalog")
    suggested_sources: List[SourceSuggestion] = Field(default=[], description="Sources beyond the presets (slice c; keep empty unless certain)")
    keep_keywords: List[str] = Field(default=[])
    ignore_keywords: List[str] = Field(default=[], description="Disambiguation excludes, e.g. 'horoscope' for a Gemini-the-model target")
    warmup_days: int = Field(default=7, description="Backfill window at creation: fast topics 7, slow topics up to 90")
    fetch_interval_minutes: int = Field(default=30)
    narration_lang: str = Field(default="zh", description="Language the USER wrote in — decides narration only, never search scope")
    rationale: str = Field(default="")


_INTENT_SYSTEM = (
    "You are the intent planner for a personal intelligence radar. The user writes ONE "
    "natural-language sentence about what they want to know; you produce the complete, "
    "structured watch definition. Rules:\n"
    "1. LANE: 'radar' when the intent is following a TOPIC (noisy, multi-source); 'monitor' "
    "when it is watching one SPECIFIC artifact (a page, an API doc, a signup form) where any "
    "change is the event — then put the exact URL in monitor_url.\n"
    "2. ENTITIES: expand into a language-independent profile. The topic's source geography is "
    "a property of the TOPIC, never of the request: decide it YOURSELF for every target, "
    "whether or not the user mentions languages. Ask: where is this subject natively reported? "
    "Which language communities break or leak its news first? Include an alias for EACH such "
    "language with its region editions — a Japanese athlete gets ja aliases, a Chinese company "
    "gets zh, a French lab gets fr, always, unprompted. The user's input language only sets "
    "narration_lang and must never widen or narrow search coverage.\n"
    "3. official_domains: the target's OWN channels only (vendor newsroom, project blog). "
    "Never press, never multi-topic portfolio blogs.\n"
    "4. ignore_keywords: disambiguate collisions (a 'gemini' AI target must exclude horoscope "
    "senses; 'grok' must exclude the Renault engine).\n"
    "5. selected_collections: only ids present in the catalog; prefer few and high-signal.\n"
    "6. suggested_sources (max 8, each with a one-line reason): sources BEYOND the preset "
    "collections that a serious follower of this target would watch. Kinds: 'rss' (the "
    "target's own feed URL), 'account' (the 1-3 X handles that break its news — value is "
    "the bare handle, platform 'twitter'), 'subreddit' (its community, bare name), "
    "'page_monitor' (a page whose CHANGE is the signal: the official newsroom LISTING page "
    "or a 'what's new'/release-notes page — an announcement published off the usual feed "
    "path is caught only this way), 'registry' (a registry/database query URL). Every "
    "suggestion is existence-checked afterwards, so only name sources you are confident "
    "exist; never invent URLs.\n"
    "7. warmup_days: fast-moving topics 7; slow domains (research, disease) up to 90."
)


def _detect_narration_lang(text: str) -> str:
    for ch in text or "":
        if "぀" <= ch <= "ヿ":
            return "ja"
        if "가" <= ch <= "힯":
            return "ko"
        if "一" <= ch <= "鿿":
            return "zh"
    return "en"


_SUGGESTION_KINDS = ("rss", "account", "subreddit", "registry", "page_monitor")
_HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_SUBREDDIT_RE = re.compile(r"^[A-Za-z0-9_]{2,21}$")


def _guard_suggestions(items: List[SourceSuggestion]) -> List[SourceSuggestion]:
    """Shape and de-duplicate planner suggestions before any network check:
    handles lose '@' and profile-URL wrapping, subreddits lose 'r/', URL kinds
    must be absolute http(s). Anything that cannot be shaped is dropped — the
    verifier only ever sees well-formed candidates."""
    out, seen = [], set()
    for s in items or []:
        kind = (s.kind or "").strip().lower()
        value = (s.value or "").strip()
        if kind not in _SUGGESTION_KINDS or not value:
            continue
        if kind == "account":
            v = value
            for pre in ("https://x.com/", "https://twitter.com/", "http://x.com/",
                        "http://twitter.com/", "x.com/", "twitter.com/"):
                if v.lower().startswith(pre):
                    v = v[len(pre):]
            v = v.strip("/").lstrip("@").split("/")[0]
            if not _HANDLE_RE.match(v):
                continue
            value = v
            s.platform = (s.platform or "twitter").lower() or "twitter"
        elif kind == "subreddit":
            v = value
            for pre in ("https://www.reddit.com/r/", "https://reddit.com/r/", "reddit.com/r/", "r/"):
                if v.lower().startswith(pre):
                    v = v[len(pre):]
            v = v.strip("/").split("/")[0]
            if not _SUBREDDIT_RE.match(v):
                continue
            value = v
            s.platform = "reddit"
        else:
            if not value.lower().startswith(("http://", "https://")) or " " in value:
                continue
        key = (kind, value.lower())
        if key in seen:
            continue
        seen.add(key)
        s.kind, s.value = kind, value
        out.append(s)
        if len(out) >= 8:
            break
    return out


def plan_intent(intent_text: str, name: str = "", use_llm: bool = True, verify: bool = True) -> dict:
    """One sentence of intent → IntentPlan (+ compatibility down-conversion).

    Returns {"planner_used", "intent_plan": <IntentPlan dict>, "fetch_policy":
    <ready-to-store policy carrying intent_plan AND the legacy keys the current
    runtime reads>} — strangler-fig: nothing existing changes behaviour until
    slice b teaches the resolver to read intent_plan itself.
    """
    collections = _load_collections()
    plan: Optional[IntentPlan] = None
    planner_used = "fallback"

    if use_llm:
        try:
            from services.llm_provider import get_provider
            provider = get_provider()
            if provider.supports_generation:
                catalog = "\n".join(
                    f"- {c['id']}: {c['title']} — {c['description'][:100]}" for c in collections)
                prompt = (
                    f"USER INTENT (one sentence): {intent_text}\n"
                    f"TARGET NAME (optional): {name or '(derive from intent)'}\n\n"
                    f"AVAILABLE COLLECTIONS:\n{catalog}"
                )
                text, usage = provider.generate(prompt, system=_INTENT_SYSTEM,
                                                schema=IntentPlan, temperature=0.3)
                plan = IntentPlan(**json.loads(text))
                planner_used = provider.name
                try:
                    from llm.processor import _record_usage
                    _record_usage(provider.name, "IntentPlan", usage)
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"LLM intent planning failed ({e}); using fallback.")

    if plan is None:
        # Pure-RSS floor: the deterministic portfolio planner, lifted into the
        # new shape. lane defaults to radar; the UI says a model unlocks
        # lane-detection and alias expansion.
        base = _fallback_plan(name or intent_text, intent_text, collections)
        nl = _detect_narration_lang(intent_text)
        plan = IntentPlan(
            lane="radar",
            lane_reason="No generation model configured; radar is the safe default.",
            entities=[AliasSpec(text=e, lang=nl) for e in base.entities],
            selected_collections=base.selected_collections,
            keep_keywords=base.keep_keywords,
            ignore_keywords=base.ignore_keywords,
            narration_lang=nl,
            rationale=base.rationale,
        )

    # --- Guards (the model invents things; the plan must not) ---
    valid_ids = {c["id"] for c in collections}
    plan.selected_collections = [c for c in plan.selected_collections if c in valid_ids]
    plan.lane = plan.lane if plan.lane in ("radar", "monitor") else "radar"
    plan.official_domains = [d.strip().lower() for d in plan.official_domains
                             if _DOMAIN_RE.match(d.strip().lower())][:8]
    plan.warmup_days = max(1, min(int(plan.warmup_days or 7), 90))
    plan.fetch_interval_minutes = max(5, min(int(plan.fetch_interval_minutes or 30), 24 * 60))
    if plan.lane == "monitor" and not plan.monitor_url.startswith(("http://", "https://")):
        # A monitor without a concrete URL is not a monitor.
        plan.lane, plan.monitor_url = "radar", ""
        plan.lane_reason += " (downgraded: no concrete URL to watch)"
    plan.suggested_sources = _guard_suggestions(plan.suggested_sources)
    if verify and plan.suggested_sources:
        from services.source_verifier import verify_suggestions
        plan.suggested_sources = [SourceSuggestion(**d) for d in
                                  verify_suggestions([s.model_dump() for s in plan.suggested_sources])]

    # --- Down-conversion: the keys today's runtime actually reads ---
    fetch_policy = dict(DEFAULT_BUDGET)
    fetch_policy.update({
        "source_scope": plan.selected_collections,
        "keep_keywords": plan.keep_keywords,
        "ignore_keywords": plan.ignore_keywords,
        "entities": [a.text for a in plan.entities],
        "max_days": plan.warmup_days,
        "intent_plan": plan.model_dump(),
    })
    return {
        "planner_used": planner_used,
        "intent_plan": plan.model_dump(),
        "fetch_policy": fetch_policy,
    }


def backfill_tracker_entities(limit: int = 20) -> dict:
    """Give existing trackers the MULTILINGUAL aliases they never got (self-heal).

    The planner has always produced multilingual entities, and source_resolver now
    turns them into one Google News route per edition — but only trackers created
    through the planning path carry them. Everything created before that (or added
    directly) searches in exactly one language, which silently breaks the design's
    core promise: 愿景 语言三原则① — one topic normalises to a language-independent
    entity profile, and a user tracking something should receive coverage in every
    language it is reported in, not only their own. Measured on the live corpus:
    same-event Chinese/Japanese/English articles sit at 0.54-0.58 centred
    similarity, far above the 0.18 merge threshold, so once one tracker collects
    several languages the vector layer merges them by itself.

    Idempotent: only touches trackers with no `entities`. One cheap planner call
    each, capped by `limit`.
    """
    import json
    from db.database import get_session
    from db.models import Tracker
    from sqlmodel import select

    planned, skipped = 0, 0
    with get_session() as session:
        trackers = session.exec(select(Tracker)).all()
        for t in trackers:
            if planned >= limit:
                break
            try:
                policy = json.loads(t.fetch_policy) if t.fetch_policy else {}
            except Exception:
                skipped += 1
                continue
            if policy.get("entities"):
                continue
            intent = t.name or ""
            try:
                tgt = json.loads(t.target) if t.target else {}
                kws = [s.get("value", "") for s in (tgt.get("signals") or [])
                       if s.get("type") == "keyword"]
                if kws:
                    intent = f"{t.name} {' '.join(kws)}".strip()
            except Exception:
                pass
            try:
                plan = plan_portfolio(t.name or intent, intent, use_llm=True)
            except Exception as e:
                logger.warning(f"Entity backfill failed for {t.name}: {e}")
                skipped += 1
                continue
            ents = [e for e in (plan.get("entities") or []) if e and e.strip()]
            if not ents:
                skipped += 1
                continue
            policy["entities"] = ents
            t.fetch_policy = json.dumps(policy)
            session.add(t)
            planned += 1
            logger.info(f"Entity backfill: {t.name} → {ents[:6]}")
        session.commit()
    return {"planned": planned, "skipped": skipped}


def backfill_official_domains(limit: int = 10) -> dict:
    """Give existing trackers the per-target official_domains they never got.

    Cross-target visibility (attribution.py) leans on official_domains for the
    cases nothing else can catch — the flagship being an official blog item
    whose feed carries no body and whose title never names the vendor
    ("The AI-Native SDLC playbook" on claude.com). Trackers created before the
    intent flow have no intent_plan at all, so the rule was silently toothless
    for exactly the author's targets. One planning call per tracker, capped and
    idempotent; only official_domains is merged in — an existing plan or the
    legacy keys are never overwritten.
    """
    from db.database import get_session
    from db.models import Tracker
    from sqlmodel import select

    planned, skipped = 0, 0
    with get_session() as session:
        for t in session.exec(select(Tracker).where(Tracker.is_active == True)).all():  # noqa: E712
            if planned >= limit:
                break
            try:
                policy = json.loads(t.fetch_policy) if t.fetch_policy else {}
            except Exception:
                skipped += 1
                continue
            ip = policy.get("intent_plan") or {}
            if ip.get("official_domains"):
                continue
            try:
                out = plan_intent(t.name or "", t.name or "", use_llm=True)
            except Exception as e:
                logger.warning(f"official_domains backfill failed for {t.name}: {e}")
                skipped += 1
                continue
            domains = (out.get("intent_plan") or {}).get("official_domains") or []
            if not domains or out.get("planner_used") == "fallback":
                skipped += 1
                continue
            ip["official_domains"] = domains
            policy["intent_plan"] = ip
            t.fetch_policy = json.dumps(policy)
            session.add(t)
            planned += 1
            logger.info(f"official_domains backfill: {t.name} → {domains}")
        session.commit()
    return {"planned": planned, "skipped": skipped}
