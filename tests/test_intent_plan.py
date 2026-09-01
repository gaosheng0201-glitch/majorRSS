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


# --- P4.0c: suggested sources — guards, verification, consumption ----------------

def _plan_with_suggestions(sugg, verify=False):
    _seed_collection()
    payload = {"lane": "radar", "suggested_sources": sugg}
    with patch("services.llm_provider.get_provider", return_value=_StubPlanner(payload)):
        return plan_intent("盯着 claude 模型的动向", "claude", use_llm=True, verify=verify)


def test_suggestion_guards_shape_and_drop():
    out = _plan_with_suggestions([
        {"kind": "account", "value": "https://x.com/AnthropicAI", "reason": "breaks news"},
        {"kind": "account", "value": "@anthropicai", "reason": "dup, different case"},
        {"kind": "subreddit", "value": "r/ClaudeAI"},
        {"kind": "rss", "value": "not a url"},
        {"kind": "page_monitor", "value": "https://www.anthropic.com/news"},
        {"kind": "telepathy", "value": "https://example.com"},
        {"kind": "account", "value": "this handle is way too long to be real"},
    ])
    s = out["intent_plan"]["suggested_sources"]
    assert [(x["kind"], x["value"]) for x in s] == [
        ("account", "AnthropicAI"), ("subreddit", "ClaudeAI"),
        ("page_monitor", "https://www.anthropic.com/news")]
    assert s[0]["platform"] == "twitter" and s[1]["platform"] == "reddit"
    # Unverified (verify=False): nothing is auto-selected.
    assert all(not x["selected"] and not x["verified"] for x in s)


def test_verification_selects_only_what_exists():
    def fake_verify(s):
        return s["kind"] == "rss"
    with patch("services.source_verifier.verify_one", side_effect=fake_verify):
        out = _plan_with_suggestions([
            {"kind": "rss", "value": "https://example.com/feed.xml"},
            {"kind": "account", "value": "ghost_handle"},
        ], verify=True)
    s = out["intent_plan"]["suggested_sources"]
    assert (s[0]["verified"], s[0]["selected"]) == (True, True)
    assert (s[1]["verified"], s[1]["selected"]) == (False, False)


def test_resolver_consumes_selected_suggestions_only():
    from services.source_resolver import SourceResolver
    policy = json.dumps({"keyword_strategy": "default", "max_days": 7, "intent_plan": {
        "suggested_sources": [
            {"kind": "rss", "value": "https://example.com/feed.xml", "selected": True},
            {"kind": "subreddit", "value": "ClaudeAI", "platform": "reddit", "selected": True},
            {"kind": "account", "value": "AnthropicAI", "platform": "twitter", "selected": True},
            {"kind": "rss", "value": "https://unchecked.example/feed", "selected": False},
            {"kind": "page_monitor", "value": "https://www.anthropic.com/news", "selected": True},
        ]}})
    routes = SourceResolver(fetch_policy=policy).resolve_routes("KEYWORD_DISCOVERY", json.dumps(["claude"]))
    urls = [r.url_or_command for r in routes]
    assert "https://example.com/feed.xml" in urls
    assert "https://www.reddit.com/r/ClaudeAI/new.rss" in urls
    acct = [r for r in routes if r.route_id.startswith(("nitter_sugg", "rsshub_sugg", "agentic_sugg"))]
    assert len(acct) == 3 and all(r.is_account for r in acct)
    assert "https://unchecked.example/feed" not in urls
    assert not any("anthropic.com/news" in u for u in urls), "page_monitor is a Subscription, not a route"
    # Suggested sources outrank shared presets (5) but not the target's own routes.
    assert all(r.priority == 4 for r in routes if r.route_id.startswith("sugg_"))


def test_page_monitor_suggestion_materialises_a_subscription():
    from backend.api.trackers import materialize_page_monitors
    from db.database import get_session
    from db.models import Tracker, Subscription
    from sqlmodel import select
    policy = json.dumps({"intent_plan": {"suggested_sources": [
        {"kind": "page_monitor", "value": "https://www.anthropic.com/news", "selected": True},
        {"kind": "page_monitor", "value": "https://ignored.example/x", "selected": False},
    ]}})
    with get_session() as s:
        t = Tracker(name="claude-c", tracker_type="KEYWORD", target="[]", radar_section="AI",
                    source_intent="KEYWORD_DISCOVERY", fetch_policy=policy, fetch_interval_minutes=30)
        s.add(t); s.commit(); s.refresh(t)
        assert materialize_page_monitors(t, s) == 1
        assert materialize_page_monitors(t, s) == 0          # idempotent
        subs = s.exec(select(Subscription).where(
            Subscription.target_url == "https://www.anthropic.com/news")).all()
        assert len(subs) == 1 and subs[0].fetch_interval_minutes == 60


# --- P4.1 registry lexicon + P4.2 emergent sources ------------------------------

def test_registry_lexicon_reaches_the_no_model_floor():
    out = plan_intent("盯着渐冻症的新疗法", "渐冻症", use_llm=False, verify=False)
    kinds = [(s["kind"], s["value"]) for s in out["intent_plan"]["suggested_sources"]]
    assert any(k == "registry" and "clinicaltrials.gov" in v for k, v in kinds), kinds


def test_extract_mentions_finds_handles_links_and_publishers():
    from services.emergent_sources import extract_mentions
    m = extract_mentions("Leak: per @jimmy_apples the model lands Tuesday",
                         "see https://x.com/apples_jimmy/status/123 and mail me at foo@gmail.com",
                         "https://www.theverge.com/2026/9/1/story")
    assert ("account", "jimmy_apples") in m
    assert ("account", "apples_jimmy") in m
    assert ("domain", "theverge.com") in m
    assert not any(v == "gmail" for _, v in m)
    # Aggregator hosts are never a publisher identity.
    assert ("domain", "news.google.com") not in extract_mentions("t", "", "https://news.google.com/rss/x")


def _seed_emergent(handle="leakerguy", n_threads=3):
    import json
    from datetime import datetime
    from db.database import get_session
    from db.models import Tracker, RawArticle, StoryThread
    with get_session() as s:
        t = Tracker(name="emergent-t", tracker_type="KEYWORD", target="[]", radar_section="AI",
                    source_intent="KEYWORD_DISCOVERY", fetch_policy=json.dumps({"entities": ["Foo"]}))
        s.add(t); s.commit(); s.refresh(t)
        for i in range(n_threads):
            th = StoryThread(tracker_id=t.id, tracker_ids=json.dumps([t.id]), title=f"story {i}",
                             lifecycle="CORROBORATED", member_count=1, distinct_source_count=2,
                             first_seen_at=datetime.utcnow(), last_update_at=datetime.utcnow())
            s.add(th); s.commit(); s.refresh(th)
            s.add(RawArticle(tracker_id=t.id, thread_id=th.id, title=f"as @{handle} reported {i}",
                             url=f"https://outlet{i}.example/{handle}/{i}", content="body"))
        s.commit()
        return t.id


def _cleanup_emergent():
    # Leave no unembedded articles behind: test_pipeline_flows counts pending
    # articles in the shared test DB.
    from db.database import get_session
    from db.models import Tracker, RawArticle, StoryThread, EmergentSource
    from sqlmodel import select, delete
    with get_session() as s:
        ids = [t.id for t in s.exec(select(Tracker).where(Tracker.name == "emergent-t")).all()]
        if ids:
            s.exec(delete(EmergentSource).where(EmergentSource.tracker_id.in_(ids)))
            s.exec(delete(RawArticle).where(RawArticle.tracker_id.in_(ids)))
            s.exec(delete(StoryThread).where(StoryThread.tracker_id.in_(ids)))
            s.exec(delete(Tracker).where(Tracker.id.in_(ids)))
            s.commit()


def test_emergent_scan_promotes_recurring_handle_and_respects_dismiss():
    from db.database import get_session
    from db.models import EmergentSource
    from services.emergent_sources import scan_emergent_sources, dismiss_emergent_source
    from sqlmodel import select
    tid = _seed_emergent("leakerguy", 3)
    _seed_emergent("onlyonce", 1)
    scan_emergent_sources(window_days=14, min_threads=3)
    with get_session() as s:
        rows = s.exec(select(EmergentSource).where(EmergentSource.tracker_id == tid)).all()
        by_key = {r.value_key: r for r in rows}
        assert "leakerguy" in by_key and by_key["leakerguy"].thread_count == 3
        assert "onlyonce" not in by_key
        # outlet0/1/2 are distinct domains → each seen once → never candidates.
        assert not any(r.kind == "domain" for r in rows)
        eid = by_key["leakerguy"].id
    dismiss_emergent_source(eid)
    scan_emergent_sources(window_days=14, min_threads=3)
    with get_session() as s:
        assert s.get(EmergentSource, eid).status == "dismissed"
    _cleanup_emergent()


def test_emergent_accept_appends_verified_suggestion():
    import json
    from db.database import get_session
    from db.models import EmergentSource, Tracker
    from services.emergent_sources import scan_emergent_sources, accept_emergent_source
    from sqlmodel import select
    tid = _seed_emergent("realhandle", 3)
    scan_emergent_sources(window_days=14, min_threads=3)
    with get_session() as s:
        eid = s.exec(select(EmergentSource).where(EmergentSource.tracker_id == tid,
                                                  EmergentSource.value_key == "realhandle")).first().id
    with patch("services.source_verifier._twitter_handle_alive", return_value=True):
        out = accept_emergent_source(eid)
    assert out["ok"] and out["added"]["kind"] == "account"
    with get_session() as s:
        policy = json.loads(s.get(Tracker, tid).fetch_policy)
        sugg = policy["intent_plan"]["suggested_sources"]
        assert any(x["value"] == "realhandle" and x["selected"] and x["verified"] for x in sugg)
        assert s.get(EmergentSource, eid).status == "accepted"
    _cleanup_emergent()
