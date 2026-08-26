"""P4.0a — IntentPlan: one sentence of intent → a structured, guarded plan.

Contract: docs/p4_intent_design.md. These pin the guards (models invent things;
the plan must not), the lane boundary examples ruled in the roadmap, the
pure-RSS fallback floor, and the strangler-fig down-conversion the current
runtime keeps reading.
"""
import json

from unittest.mock import patch

from services.portfolio_planner import IntentPlan, AliasSpec, plan_intent


class _StubPlanner:
    """Generation provider returning a canned IntentPlan JSON."""
    name = "stub-planner"
    supports_generation = True

    def __init__(self, payload: dict):
        self._payload = payload

    def generate(self, prompt, system=None, schema=None, temperature=0.0):
        return json.dumps(self._payload), {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}


def _seed_collection(cid="frontier_model_labs"):
    from db.database import get_session
    from db.models import SourcePresetCollection
    from sqlmodel import select
    with get_session() as s:
        if not s.exec(select(SourcePresetCollection)
                      .where(SourcePresetCollection.collection_id == cid)).first():
            s.add(SourcePresetCollection(collection_id=cid, title="Frontier Model Labs",
                                         description="lab newsrooms", source_count=5))
            s.commit()


def _plan_with(payload: dict, intent="盯着 gemini 模型的动向", name="gemini"):
    _seed_collection()
    with patch("services.llm_provider.get_provider", return_value=_StubPlanner(payload)):
        return plan_intent(intent, name, use_llm=True)


# --- schema roundtrip + down-conversion ---------------------------------------

def test_plan_roundtrips_and_down_converts_for_legacy_runtime():
    out = _plan_with({
        "lane": "radar", "lane_reason": "topic",
        "entities": [
            {"text": "Gemini", "lang": "en", "regions": ["US"], "role": "product"},
            {"text": "ジェミニ", "lang": "ja", "regions": ["JP"], "role": "product"},
        ],
        "official_domains": ["deepmind.google", "blog.google"],
        "selected_collections": ["frontier_model_labs", "not_a_real_collection"],
        "keep_keywords": ["Gemini"], "ignore_keywords": ["horoscope"],
        "warmup_days": 7, "narration_lang": "zh", "rationale": "r",
    })
    plan = IntentPlan(**out["intent_plan"])          # roundtrip
    assert [a.lang for a in plan.entities] == ["en", "ja"]
    fp = out["fetch_policy"]
    # Legacy keys today's resolver reads — the strangler-fig contract.
    assert fp["entities"] == ["Gemini", "ジェミニ"]
    assert fp["keep_keywords"] == ["Gemini"]
    assert fp["max_days"] == 7
    assert fp["intent_plan"]["official_domains"] == ["deepmind.google", "blog.google"]
    # Hallucinated collection id filtered out.
    assert fp["source_scope"] == ["frontier_model_labs"]


# --- guards --------------------------------------------------------------------

def test_invented_official_domains_are_rejected():
    out = _plan_with({"lane": "radar", "official_domains":
                      ["deepmind.google", "not a domain", "javascript:alert(1)", "UPPER.Com"]})
    assert out["intent_plan"]["official_domains"] == ["deepmind.google", "upper.com"]


def test_monitor_without_url_downgrades_to_radar():
    out = _plan_with({"lane": "monitor", "monitor_url": "", "lane_reason": "watch it"})
    assert out["intent_plan"]["lane"] == "radar"
    assert "downgraded" in out["intent_plan"]["lane_reason"]


def test_monitor_with_url_stays_monitor():
    # The roadmap's boundary example: a specific artifact whose change IS the event.
    out = _plan_with({"lane": "monitor",
                      "monitor_url": "https://clinicaltrials.gov/study/NCT123",
                      "lane_reason": "specific artifact"},
                     intent="ClinicalTrials 上这个试验状态变了没")
    assert out["intent_plan"]["lane"] == "monitor"
    assert out["intent_plan"]["monitor_url"].startswith("https://")


def test_warmup_and_interval_are_clamped():
    out = _plan_with({"lane": "radar", "warmup_days": 3650, "fetch_interval_minutes": 1})
    assert out["intent_plan"]["warmup_days"] == 90
    assert out["intent_plan"]["fetch_interval_minutes"] == 5


def test_bogus_lane_defaults_to_radar():
    out = _plan_with({"lane": "everything"})
    assert out["intent_plan"]["lane"] == "radar"


# --- pure-RSS floor -------------------------------------------------------------

def test_no_model_falls_back_deterministically():
    # conftest guarantees no key → FallbackEmbedder (supports_generation=False).
    out = plan_intent("盯着渐冻症的新疗法", "渐冻症", use_llm=True)
    assert out["planner_used"] == "fallback"
    plan = IntentPlan(**out["intent_plan"])
    assert plan.lane == "radar"
    assert plan.narration_lang == "zh"          # narration follows input language…
    assert out["fetch_policy"]["intent_plan"]   # …and the plan still stores whole.


def test_fallback_detects_narration_lang_only():
    # Language三原则①: input language decides narration, never search scope —
    # the fallback must not pretend to know source geography it can't derive.
    out = plan_intent("Watch ALS therapy news", use_llm=False)
    assert out["intent_plan"]["narration_lang"] == "en"


# --- P4.0b: the runtime consumes the plan --------------------------------------

def test_edition_params_from_planned_pairs():
    from services.source_resolver import gnews_edition_params as ep
    assert ep("en", "US") == "" and ep("en") == ""
    assert ep("ja", "JP") == "&hl=ja&gl=JP&ceid=JP:ja"
    assert ep("zh", "CN") == "&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    assert ep("zh", "TW") == "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    assert ep("fr", "") == "&hl=fr&gl=FR&ceid=FR:fr"
    assert ep("en", "GB") == "&hl=en&gl=GB&ceid=GB:en"


def test_resolver_derives_routes_from_planned_aliases_not_script_guessing():
    # The demotion the 7-29 correction ruled: with a plan, editions come from the
    # planner's (lang, regions), and "Shohei Ohtani" can reach the JP edition —
    # something script-guessing could never do for a Latin-script alias.
    from services.source_resolver import SourceResolver
    policy = json.dumps({
        "keyword_strategy": "default", "max_days": 7,
        "intent_plan": {"entities": [
            {"text": "大谷翔平", "lang": "ja", "regions": ["JP"]},
            {"text": "Shohei Ohtani", "lang": "en", "regions": ["JP"]},
            {"text": "大谷翔平", "lang": "zh", "regions": ["CN", "TW"]},
        ]},
    })
    r = SourceResolver(fetch_policy=policy)
    routes = r._resolve_keyword_routes(json.dumps(["Ohtani"]))
    xlang = [rt.url_or_command for rt in routes if rt.route_id.startswith("gnews_xlang")]
    assert any("ceid=JP:ja" in u and "%E5%A4%A7%E8%B0%B7" in u for u in xlang), xlang
    assert any("ceid=CN:zh-Hans" in u for u in xlang)
    assert any("ceid=TW:zh-Hant" in u for u in xlang)
    # Latin alias explicitly aimed at the JP edition rides the ja route bucket
    # or its own — either way JP:en/JP:ja coverage exists beyond guessing.
    assert all(rt.tier == "aggregated" for rt in routes if rt.route_id.startswith("gnews")), \
        "planned editions are still firehose routes — AGGREGATED never upgrades"


def test_resolver_without_plan_keeps_script_guess_fallback():
    from services.source_resolver import SourceResolver
    policy = json.dumps({"keyword_strategy": "default", "max_days": 7,
                         "entities": ["大谷翔平", "Shohei Ohtani"]})
    r = SourceResolver(fetch_policy=policy)
    routes = r._resolve_keyword_routes(json.dumps(["Ohtani"]))
    xlang = [rt.url_or_command for rt in routes if rt.route_id.startswith("gnews_xlang")]
    assert any("ceid=CN:zh-Hans" in u for u in xlang), "han-script guess still works plan-less"


def test_per_target_official_domain_upgrades_only_with_the_grant():
    from services.provenance import Tier, tier_for_url
    url = "https://blog.cloudflare.com/some-release/"
    # Globally: still CURATED (the Cloudflare lesson).
    assert tier_for_url(url, Tier.CURATED) == Tier.CURATED
    # For the tracker whose plan names it: PRIMARY.
    assert tier_for_url(url, Tier.CURATED, ("blog.cloudflare.com",)) == Tier.PRIMARY
    # Marketing-path guard still applies even to granted domains.
    assert tier_for_url("https://blog.cloudflare.com/careers/x", Tier.CURATED,
                        ("blog.cloudflare.com",)) == Tier.CURATED
    # And AGGREGATED never upgrades, grant or no grant.
    assert tier_for_url(url, Tier.AGGREGATED, ("blog.cloudflare.com",)) == Tier.AGGREGATED


# --- Cross-target visibility (author ruling 2026-08-26) -------------------------

def _profiles():
    from services.attribution import TrackerProfile
    return [
        TrackerProfile(1, ["Gemini", "DeepMind"], ["deepmind.google"]),
        TrackerProfile(4, ["Claude", "Anthropic"], ["claude.com", "anthropic.com"]),
    ]


def test_official_domain_grants_visibility_regardless_of_title():
    # The SDLC case: title never says "Claude"; the domain says everything.
    from services.attribution import relevant_tracker_ids
    ids = relevant_tracker_ids("The AI-Native SDLC playbook", "some body",
                               "https://claude.com/blog/the-ai-native-sdlc-playbook",
                               _profiles(), owner_id=2)
    assert ids == [4]


def test_title_entity_match_is_enough():
    from services.attribution import relevant_tracker_ids
    ids = relevant_tracker_ids("Claude vs Gemini: which codes better?", "",
                               "https://example.com/x", _profiles(), owner_id=1)
    assert ids == [4]          # owner (gemini) excluded; claude matched via title


def test_single_passing_mention_in_body_is_not_aboutness():
    # Precision guard: one body mention must not flood the other filter.
    from services.attribution import relevant_tracker_ids
    body = "This tool is great. Unlike Claude, it runs offline."
    assert relevant_tracker_ids("A new local LLM tool", body,
                                "https://example.com/y", _profiles(), owner_id=1) == []


def test_two_distinct_entities_in_body_are():
    from services.attribution import relevant_tracker_ids
    body = "Claude improved a lot this quarter. Anthropic also shipped memory."
    assert relevant_tracker_ids("Model roundup", body,
                                "https://example.com/z", _profiles(), owner_id=1) == [4]


def test_word_boundary_blocks_substring_hits():
    from services.attribution import TrackerProfile, relevant_tracker_ids
    profs = [TrackerProfile(7, ["Grok"], [])]
    assert relevant_tracker_ids("Grokking deep learning textbooks", "", 
                                "https://example.com/a", profs) == []
    assert relevant_tracker_ids("Grok 4.6 released", "",
                                "https://example.com/b", profs) == [7]
