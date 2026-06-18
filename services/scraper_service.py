import sys
import time
import json
import urllib.parse
from datetime import datetime, timezone
from typing import Optional, List

from repositories.repository import DBRepository
from db.models import RawArticle
from scrapers.tier1_rss import BasicRSSScraper
from scrapers.tier3_agentic import AgenticScraper, CookieExpiredException
from services.source_resolver import SourceResolver, SourceRoute
from services.source_normalizer import SourceNormalizer
from services.adapters import RssAdapter, RssHubAdapter, AgenticAdapter, SourceItem

db = DBRepository()

def print_safe(message: str):
    """
    Safely prints messages containing Unicode/emoji characters under Windows consoles.
    """
    try:
        print(message)
    except UnicodeEncodeError:
        try:
            encoding = sys.stdout.encoding or 'utf-8'
            print(message.encode(encoding, errors='replace').decode(encoding))
        except:
            try:
                print(message.encode('ascii', errors='replace').decode('ascii'))
            except:
                pass

from services.privacy import desensitize_url, scrub_sensitive_info

def run_route_test(
    target: str,
    source_intent: str,
    fetch_policy: Optional[str] = None,
    auth_profile_id: Optional[int] = None,
    session = None
) -> dict:
    """
    Executes route resolution and dry-run fetching for testing/observability.
    """
    resolver = SourceResolver(fetch_policy=fetch_policy, auth_profile_id=auth_profile_id)
    routes = resolver.resolve_routes(source_intent, target)
    
    resolved_routes = []
    selected_route = None
    fallback_triggered = False
    
    total_item_count = 0
    latest_time = None
    sample_titles = []
    quality_score = 0.0
    final_error_type = None
    final_error_message = None
    
    adapters = {
        "RssAdapter": RssAdapter(),
        "RssHubAdapter": RssHubAdapter(),
        "AgenticAdapter": AgenticAdapter()
    }
    
    for route in routes:
        adapter_name = route.adapter
        adapter = adapters.get(adapter_name)
        if not adapter:
            continue
            
        start_time = time.time()
        ok = False
        http_status = 200
        error_type = None
        error_msg = None
        items = []
        
        try:
            items = adapter.fetch(route, auth_profile_id=route.auth_profile_id if route.auth_profile_id is not None else auth_profile_id)
            max_items = resolver.policy.get("max_items_per_route", 20)
            if items:
                items = items[:max_items]
            ok = True
        except CookieExpiredException as ce:
            http_status = 401
            error_type = "AUTH_EXPIRED"
            error_msg = str(ce)
        except Exception as e:
            http_status = 500
            error_type = "NETWORK_ERROR"
            error_msg = str(e)
            
        duration = int((time.time() - start_time) * 1000)
        
        # Determine latest time and sample titles
        route_latest_time = None
        route_titles = []
        for it in items:
            route_titles.append(it.title)
            if it.published_at:
                if route_latest_time is None or it.published_at > route_latest_time:
                    route_latest_time = it.published_at
                    
        route_titles = route_titles[:5]
        
        # Simple quality score calculation: count of non-empty titles/contents
        route_quality = 0.0
        if items:
            valid_items = sum(1 for it in items if it.title and len(it.content) > 10)
            route_quality = round(valid_items / len(items), 2)
            
        route_info = {
            "route_id": route.route_id,
            "adapter": route.adapter,
            "url_or_command": route.url_or_command,
            "purpose": route.purpose,
            "requires_auth": route.requires_auth,
            "auth_profile_id": route.auth_profile_id,
            "auth_status": route.auth_status,
            "http_status": http_status,
            "ok": ok,
            "error_type": error_type,
            "error_message": error_msg,
            "item_count": len(items),
            "latest_item_time": route_latest_time,
            "sample_titles": route_titles,
            "quality_score": route_quality,
            "fallback_triggered": fallback_triggered
        }
        resolved_routes.append(route_info)
        
        if ok and selected_route is None:
            selected_route = route.route_id
            total_item_count = len(items)
            latest_time = route_latest_time
            sample_titles = route_titles
            quality_score = route_quality
            
        if not ok:
            fallback_triggered = True
            if selected_route is None:
                final_error_type = error_type
                final_error_message = error_msg
                
    return {
        "original_target": target,
        "resolved_routes": resolved_routes,
        "selected_route": selected_route,
        "fallback_triggered": fallback_triggered,
        "item_count": total_item_count,
        "latest_item_time": latest_time,
        "sample_titles": sample_titles,
        "quality_score": quality_score,
        "error_type": final_error_type,
        "error_message": final_error_message
    }

def scrape_single_tracker(tracker_id: int):
    from db.models import PipelineRun, PipelineEvent, Tracker
    from db.database import get_session
    from datetime import datetime, timezone
    import time
    
    session = get_session()
    tracker = session.get(Tracker, tracker_id)
    if not tracker:
        session.close()
        return
        
    db.set_pipeline_status(tracker.name, "Scraping", f"Tracker ({tracker.tracker_type}) is fetching data...")
    
    # 1. Resolve routes
    resolver = SourceResolver(fetch_policy=tracker.fetch_policy, auth_profile_id=tracker.auth_profile_id)
    routes = resolver.resolve_routes(tracker.source_intent, tracker.target)
    
    # Get or generate fresh normalized_intent canonically
    from services.intent_normalizer import generate_tracker_normalized_intent
    fresh_intent = generate_tracker_normalized_intent(
        name=tracker.name,
        source_intent=tracker.source_intent,
        target=tracker.target,
        fetch_policy=tracker.fetch_policy
    )
    if tracker.normalized_intent != fresh_intent:
        tracker.normalized_intent = fresh_intent
        session.add(tracker)
        session.commit()
    normalized_intent = tracker.normalized_intent

    run = PipelineRun(
        tracker_id=tracker.id,
        normalized_intent=normalized_intent,
        status="RUNNING",
        started_at=datetime.now(timezone.utc).replace(tzinfo=None)
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    adapters = {
        "RssAdapter": RssAdapter(),
        "RssHubAdapter": RssHubAdapter(),
        "AgenticAdapter": AgenticAdapter()
    }
    
    # Determine keep/ignore keywords for filtering from fetch_policy
    keep_keywords = []
    ignore_keywords = []
    if tracker.fetch_policy:
        try:
            fp = json.loads(tracker.fetch_policy)
            keep_keywords = fp.get("keep_keywords", [])
            ignore_keywords = fp.get("ignore_keywords", [])
        except:
            pass
            
    max_days = resolver.policy.get("max_days", 7)
    
    saved_total = 0
    dup_total = 0
    filt_total = 0
    success = False
    
    normalizer = SourceNormalizer()
    step_counter = 1
    total_items_fetched = 0
    cost_browser = False
    cost_llm = False

    # Write route resolution event
    resolve_event = PipelineEvent(
        run_id=run.id,
        step_index=step_counter,
        stage="RESOLVE",
        status="SUCCESS",
        output_summary=f"Resolved {len(routes)} routes from signals",
        duration_ms=0
    )
    session.add(resolve_event)
    session.commit()
    step_counter += 1
    
    for route in routes:
        route_start_time = time.time()
        adapter_name = route.adapter
        adapter = adapters.get(adapter_name)
        if not adapter:
            route_event = PipelineEvent(
                run_id=run.id,
                step_index=step_counter,
                stage="FETCH",
                route_id=route.route_id,
                adapter=adapter_name,
                status="FAILED",
                error=f"Adapter {adapter_name} not found"
            )
            session.add(route_event)
            session.commit()
            step_counter += 1
            continue
            
        if adapter_name == "AgenticAdapter":
            cost_browser = True
            
        try:
            print_safe(f"Executing route {route.route_id} using {adapter_name}...")
            items = adapter.fetch(route, auth_profile_id=route.auth_profile_id)
            max_items = resolver.policy.get("max_items_per_route", 20)
            if items:
                items = items[:max_items]
            total_items_fetched += len(items)
            
            # Normalize and persist
            saved, dup, filtered = normalizer.normalize_and_save(
                items=items,
                tracker_id=tracker.id,
                max_days=max_days,
                keep_keywords=keep_keywords,
                ignore_keywords=ignore_keywords
            )
            saved_total += saved
            dup_total += dup
            filt_total += filtered
            
            duration = int((time.time() - route_start_time) * 1000)
            route_event = PipelineEvent(
                run_id=run.id,
                step_index=step_counter,
                stage="FETCH",
                route_id=route.route_id,
                adapter=adapter_name,
                input_data=desensitize_url(route.url_or_command),
                output_summary=f"Fetched {len(items)} items. Saved {saved}, Dup {dup}, Filtered {filtered} (Auth: {route.auth_status})",
                status="SUCCESS" if len(items) > 0 or saved > 0 or dup > 0 else "FAILED",
                duration_ms=duration
            )
            session.add(route_event)
            session.commit()
            step_counter += 1
            
            if len(items) > 0 and (saved > 0 or dup > 0):
                success = True
                print_safe(f"Route {route.route_id} succeeded: saved {saved}, duplicates {dup}, filtered {filtered}")
                break
            else:
                print_safe(f"Route {route.route_id} returned {len(items)} items, but saved={saved}, dup={dup}. Trying fallback route...")
        except CookieExpiredException as ce:
            duration = int((time.time() - route_start_time) * 1000)
            error_msg = f"Auth Failed for {route.url_or_command}: {ce}"
            print_safe(error_msg)
            db.set_pipeline_status(tracker.name, "Auth Failed", error_msg)
            
            route_event = PipelineEvent(
                run_id=run.id,
                step_index=step_counter,
                stage="FETCH",
                route_id=route.route_id,
                adapter=adapter_name,
                input_data=desensitize_url(route.url_or_command),
                status="FAILED",
                error="AUTH_EXPIRED",
                duration_ms=duration
            )
            session.add(route_event)
            session.commit()
            step_counter += 1
        except Exception as e:
            duration = int((time.time() - route_start_time) * 1000)
            domain = urllib.parse.urlparse(route.url_or_command).netloc
            error_msg = f"Fetch failed for {route.url_or_command}: {e}"
            print_safe(error_msg)
            db.set_pipeline_status(tracker.name, "Probe Failed", f"[{domain}] {e}")
            
            route_event = PipelineEvent(
                run_id=run.id,
                step_index=step_counter,
                stage="FETCH",
                route_id=route.route_id,
                adapter=adapter_name,
                input_data=desensitize_url(route.url_or_command),
                status="FAILED",
                error=scrub_sensitive_info(str(e))[:100],
                duration_ms=duration
            )
            session.add(route_event)
            session.commit()
            step_counter += 1
            
    # Update last scraped time
    tracker.last_scraped_at = datetime.now(timezone.utc).replace(tzinfo=None)
    session.add(tracker)
    session.commit()
    
    # Save PipelineRun status
    run.status = "SUCCESS" if success else "FAILED"
    run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
    run.total_routes = len(routes)
    run.total_items = total_items_fetched
    run.accepted_items = saved_total
    run.cost_flag_browser = cost_browser
    run.cost_flag_llm = cost_llm
    if not success:
        run.error_summary = "All routes failed or returned no new items"
    session.add(run)
    session.commit()
    session.close()
        
    db.set_pipeline_status(tracker.name, "Completed", f"Scrape complete. Saved {saved_total} new items, skipped {dup_total} duplicates, filtered {filt_total} items.")
