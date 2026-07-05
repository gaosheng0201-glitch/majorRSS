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
from services.error_classifier import classify_error, format_error
from services.log_service import get_logger

db = DBRepository()
logger = get_logger("scraper")

def print_safe(message: str):
    """Legacy shim: pipeline messages now go through the logging service
    (rotating file + encoding-safe console)."""
    logger.info(message)

from services.privacy import desensitize_url, scrub_sensitive_info

def _mark_auth_expired(session, auth_profile_id: Optional[int], url: str):
    """When a scrape hits a login wall, reflect it on the AuthProfile so the
    Settings page shows 'Expired / re-authorize' instead of a stale 'Active'.
    Falls back to platform detection from the URL for legacy per-platform
    cookie flows that are not linked to a profile id."""
    from db.models import AuthProfile
    from sqlmodel import select
    try:
        profiles = []
        if auth_profile_id:
            p = session.get(AuthProfile, auth_profile_id)
            if p:
                profiles.append(p)
        else:
            from scrapers.auth_helper import AUTH_PLATFORMS
            for key, platform in AUTH_PLATFORMS.items():
                if any(d in url for d in platform["domains"]):
                    profiles.extend(session.exec(select(AuthProfile).where(AuthProfile.platform == key)).all())
                    break
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for p in profiles:
            p.status = "Expired"
            p.last_checked_at = now
            session.add(p)
        if profiles:
            session.commit()
            logger.warning(f"Marked {len(profiles)} auth profile(s) as Expired after login wall at {desensitize_url(url)}")
    except Exception as e:
        logger.warning(f"Failed to update auth profile status: {e}")

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
            error_type = classify_error(e)
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
    from db.models import Tracker
    from db.database import get_session
    from datetime import datetime, timezone
    import time

    session = get_session()
    tracer = None
    tracker_name = f"tracker#{tracker_id}"
    try:
        tracker = session.get(Tracker, tracker_id)
        if not tracker:
            return
        tracker_name = tracker.name

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

        from services.pipeline_trace import PipelineTracer
        tracer = PipelineTracer.start(session, tracker_id=tracker.id, normalized_intent=normalized_intent)

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
            except Exception:
                pass

        max_days = resolver.policy.get("max_days", 7)

        saved_total = 0
        dup_total = 0
        filt_total = 0
        # A route that fetched without raising means the source is reachable —
        # even if every item was a duplicate or got filtered. That is a healthy
        # quiet feed, not a failure, and must not trigger the browser fallback.
        fetched_ok = False
        content_delivered = False
        last_error = None

        normalizer = SourceNormalizer()
        total_items_fetched = 0
        cost_browser = False
        cost_llm = False

        # Write route resolution event
        tracer.event("RESOLVE", output_summary=f"Resolved {len(routes)} routes from signals")

        for route in routes:
            route_start_time = time.time()
            adapter_name = route.adapter
            adapter = adapters.get(adapter_name)
            if not adapter:
                tracer.event("FETCH", status="FAILED", route_id=route.route_id,
                             adapter=adapter_name, error=f"Adapter {adapter_name} not found")
                continue

            if adapter_name == "AgenticAdapter":
                cost_browser = True

            # Source-health gate: skip a source that is inside its backoff window
            # or quarantined, so a failing source is not re-hit at full cadence.
            from services import source_health
            # Per-endpoint (not per-domain) key so one failing keyword search
            # doesn't back off every tracker sharing news.google.com etc.
            health_key = source_health.route_key(route.url_or_command)
            skip, skip_reason = source_health.should_skip(health_key)
            if skip:
                logger.info(f"Skipping route {route.route_id} ({health_key}): {skip_reason}")
                tracer.event("FETCH", status="SKIPPED", route_id=route.route_id, adapter=adapter_name,
                             input_data=desensitize_url(route.url_or_command),
                             error=f"source_health:{skip_reason}")
                continue

            # Account guard: an authorized route spends the account's fragile,
            # rationed credit. Skip when the circuit is open or the hourly budget
            # is spent; queued work waits rather than hammering the account.
            account_key = None
            if route.auth_profile_id and route.auth_status == "matched":
                account_key = f"{route.platform}:profile_{route.auth_profile_id}"
                from services import account_guard, humanized

                # Quiet-window defer FIRST — don't spend budget on a request we
                # then defer for the nightly quiet window.
                pace = humanized.pace_authorized_request(account_key)
                if pace["skipped_quiet"]:
                    logger.info(f"Deferring route {route.route_id} ({account_key}): quiet window")
                    tracer.event("FETCH", status="SKIPPED", route_id=route.route_id, adapter=adapter_name,
                                 input_data=desensitize_url(route.url_or_command),
                                 error="humanized:quiet_window")
                    continue

                # Atomic gate-and-consume (no TOCTOU across the two scrape threads).
                allowed, guard_reason = account_guard.try_consume(account_key)
                if not allowed:
                    logger.info(f"Account guard deferred route {route.route_id} ({account_key}): {guard_reason}")
                    tracer.event("FETCH", status="SKIPPED", route_id=route.route_id, adapter=adapter_name,
                                 input_data=desensitize_url(route.url_or_command),
                                 error=f"account_guard:{guard_reason}")
                    continue

            try:
                logger.info(f"Executing route {route.route_id} using {adapter_name}...")
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

                fetched_ok = True
                duration = int((time.time() - route_start_time) * 1000)
                source_health.record_success(health_key, latency_ms=duration)
                if account_key:
                    account_guard.record_yield(account_key, items=len(items))
                tracer.event("FETCH", route_id=route.route_id, adapter=adapter_name,
                             input_data=desensitize_url(route.url_or_command),
                             output_summary=f"Fetched {len(items)} items. Saved {saved}, Dup {dup}, Filtered {filtered} (Auth: {route.auth_status})",
                             duration_ms=duration)

                if len(items) > 0:
                    # Route delivered content; whether anything was new is a
                    # freshness question, not a routing one. Stop here.
                    content_delivered = True
                    logger.info(f"Route {route.route_id} delivered {len(items)} items: saved {saved}, duplicates {dup}, filtered {filtered}")
                    break
                else:
                    logger.info(f"Route {route.route_id} reachable but returned 0 items. Trying fallback route...")
            except CookieExpiredException as ce:
                duration = int((time.time() - route_start_time) * 1000)
                last_error = ce
                error_msg = f"Auth Failed for {route.url_or_command}: {ce}"
                logger.warning(error_msg)
                db.set_pipeline_status(tracker.name, "Auth Failed", error_msg)
                _mark_auth_expired(session, route.auth_profile_id, route.url_or_command)
                # A login wall is a risk signal — trip the account circuit so we
                # stop hitting the platform with a rejected session.
                if account_key:
                    account_guard.record_risk_signal(account_key, signal="login_wall")

                tracer.event("FETCH", status="FAILED", route_id=route.route_id, adapter=adapter_name,
                             input_data=desensitize_url(route.url_or_command),
                             error="AUTH_EXPIRED", duration_ms=duration)
            except Exception as e:
                duration = int((time.time() - route_start_time) * 1000)
                last_error = e
                domain = urllib.parse.urlparse(route.url_or_command).netloc
                error_type = classify_error(e)
                logger.warning(f"Fetch failed for {route.url_or_command} [{error_type}]: {e}")
                db.set_pipeline_status(tracker.name, "Probe Failed", f"[{domain}] {error_type}: {e}")
                source_health.record_failure(health_key, error_type=error_type)
                # Rate-limit / captcha on an authorized route = account risk signal.
                if account_key and error_type in ("RATE_LIMITED", "CAPTCHA_REQUIRED"):
                    account_guard.record_risk_signal(account_key, signal=error_type)

                tracer.event("FETCH", status="FAILED", route_id=route.route_id, adapter=adapter_name,
                             input_data=desensitize_url(route.url_or_command),
                             error=scrub_sensitive_info(format_error(e))[:200], duration_ms=duration)

        # Update last scraped time
        tracker.last_scraped_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.add(tracker)
        session.commit()

        # Finalize run status.
        # SUCCESS       — new articles saved.
        # NO_NEW_ITEMS  — sources reachable, nothing new (quiet feed / all dup / filtered).
        # FAILED        — every route errored or was unreachable.
        if saved_total > 0:
            final_status, final_error = "SUCCESS", None
        elif fetched_ok:
            final_status = "NO_NEW_ITEMS"
            final_error = None if content_delivered else "Routes reachable but returned 0 items"
        else:
            final_status = "FAILED"
            final_error = (scrub_sensitive_info(format_error(last_error))
                           if last_error is not None else "No executable routes resolved")
        tracer.finish(final_status, total_routes=len(routes), total_items=total_items_fetched,
                      accepted_items=saved_total, error_summary=final_error,
                      cost_browser=cost_browser, cost_llm=cost_llm)

        db.set_pipeline_status(tracker.name, "Completed", f"Scrape complete ({final_status}). Saved {saved_total} new items, skipped {dup_total} duplicates, filtered {filt_total} items.")
    except Exception as e:
        # Nothing above may crash invisibly: record the failure on the run (if
        # one was created) and in the activity log, then re-raise so callers
        # (task poller retry logic, scheduler thread pool) see it too.
        logger.error(f"Scrape crashed for {tracker_name}: {e}", exc_info=e)
        try:
            if tracer is not None:
                tracer.finish("FAILED", error_summary=format_error(e))
            db.set_pipeline_status(tracker_name, "Crashed", scrub_sensitive_info(format_error(e)))
        except Exception:
            logger.exception(f"Failed to record crash for {tracker_name}")
        raise
    finally:
        session.close()
