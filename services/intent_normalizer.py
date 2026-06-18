import json
from typing import Optional

def generate_tracker_normalized_intent(name: str, source_intent: str, target: str, fetch_policy: Optional[str]) -> str:
    policy_profile = "balanced"
    if fetch_policy:
        try:
            fp = json.loads(fetch_policy)
            if fp.get("keyword_strategy") == "trusted_news_only":
                policy_profile = "strict"
            elif fp.get("use_default_osint") is True and fp.get("max_items_per_route", 0) > 25:
                policy_profile = "broad"
        except:
            pass

    intent_map = {
        "intent_type": "topic_discovery" if source_intent == "HYBRID" else "single_feed_subscription" if source_intent == "RSS_FEED" else "single_account_subscription",
        "topic": name,
        "signals": [],
        "policy_profile": policy_profile
    }
    try:
        target_data = json.loads(target)
        if isinstance(target_data, dict) and "signals" in target_data:
            intent_map["signals"] = target_data.get("signals", [])
            intent_map["topic"] = target_data.get("topic", name)
        elif isinstance(target_data, list):
            intent_map["signals"] = [{"type": "keyword", "value": kw} for kw in target_data]
        else:
            intent_map["signals"] = [{"type": "website", "value": target}]
    except:
        intent_map["signals"] = [{"type": "website", "value": target}]
        
    return json.dumps(intent_map)

def generate_subscription_normalized_intent(target_url: str, fetch_interval_minutes: int, diff_policy: Optional[str]) -> str:
    from scrapers.url_normalizer import is_rss_url
    intent_type = "single_feed_subscription" if is_rss_url(target_url) else "page_change_monitor"
    
    monitor_goal = "none"
    filters = {"keep": [], "ignore": []}
    if diff_policy:
        try:
            dp = json.loads(diff_policy)
            monitor_goal = dp.get("monitor_goal", "none")
            if monitor_goal == "none" and dp.get("extract_selector"):
                monitor_goal = "article_change"
            filters["keep"] = dp.get("keep_keywords", [])
            filters["ignore"] = dp.get("ignore_keywords", [])
        except:
            pass
            
    intent_map = {
        "intent_type": intent_type,
        "target": target_url,
        "monitor_goal": monitor_goal,
        "filters": filters,
        "frequency_minutes": fetch_interval_minutes
    }
    return json.dumps(intent_map)
