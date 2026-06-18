import sys
import os
import hashlib
import difflib
from datetime import datetime, timezone, timedelta
import json
from bs4 import BeautifulSoup

# Ensure root is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlmodel import select
from db.database import get_session
from db.models import Subscription, PageSnapshot, SubscriptionUpdate, PipelineRun, PipelineEvent
from scrapers.tier3_agentic import AgenticScraper, CookieExpiredException
import time
import urllib.parse

from services.privacy import desensitize_url, scrub_sensitive_info

def clean_html_for_diff(html_content: str, extract_selector: str = None, ignore_selector: str = None) -> str:
    """
    Smart Diff Filter:
    1. Parse HTML
    2. Extract CSS selector if specified
    3. Ignore CSS selector if specified
    4. Remove volatile nodes: <time>, dynamic spans, pure number nodes.
    5. Extract structural skeleton: text blocks and <a> links.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Extract selector
    if extract_selector:
        selected_node = soup.select_one(extract_selector)
        if selected_node:
            soup = selected_node
        else:
            return ""
            
    # Ignore selector
    if ignore_selector:
        for node in soup.select(ignore_selector):
            node.decompose()

    # Remove common noise tags
    for tag in soup.find_all(['script', 'style', 'noscript', 'meta', 'link', 'svg', 'time']):
        tag.decompose()
        
    extracted_lines = []
    
    # We prioritize <a> tags and significant paragraph texts
    for element in soup.find_all(['a', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'div', 'span']):
        text = element.get_text(strip=True)
        # Skip empty text
        if not text:
            continue
            
        # Ignore purely numeric text or common counts like "1.4万"
        if text.isdigit() or (len(text) > 1 and text[:-1].isdigit() and text[-1] in ['万', 'k', 'm', 'w']):
            continue
            
        # If it's a link, we attach the href to anchor the meaning
        if element.name == 'a':
            href = element.get('href', '')
            if text:
                extracted_lines.append(f"LINK: {text} ({href})")
        else:
            # Keep headings and paragraph blocks (always significant), or longer texts from other blocks
            if element.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p'] or len(text) > 15:
                extracted_lines.append(f"TEXT: {text}")
                
    # Deduplicate while preserving order to avoid list spam
    seen = set()
    clean_lines = []
    for line in extracted_lines:
        if line not in seen:
            seen.add(line)
            clean_lines.append(line)
            
    return "\n".join(clean_lines)

def process_subscription(session, sub: Subscription, now: datetime):
    # Get or generate fresh normalized_intent canonically
    from services.intent_normalizer import generate_subscription_normalized_intent
    fresh_intent = generate_subscription_normalized_intent(
        target_url=sub.target_url,
        fetch_interval_minutes=sub.fetch_interval_minutes,
        diff_policy=sub.diff_policy
    )
    if sub.normalized_intent != fresh_intent:
        sub.normalized_intent = fresh_intent
        session.add(sub)
        session.commit()
    normalized_intent = sub.normalized_intent

    run = PipelineRun(
        subscription_id=sub.id,
        normalized_intent=normalized_intent,
        status="RUNNING",
        started_at=datetime.now(timezone.utc).replace(tzinfo=None)
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    step_counter = 1
    cost_browser = False
    cost_llm = False
    success = False
    accepted_items = 0
    error_summary = None

    try:
        print(f"Monitoring Subscription: {sub.name} ({sub.target_url})")
        
        # RESOLVE Event
        from scrapers.url_normalizer import is_rss_url
        is_rss = is_rss_url(sub.target_url)
        strategy_desc = "RSS feed parsing" if is_rss else "Webpage monitoring"
        
        resolve_event = PipelineEvent(
            run_id=run.id,
            step_index=step_counter,
            stage="RESOLVE",
            status="SUCCESS",
            output_summary=f"Resolved target strategy: {strategy_desc}",
            duration_ms=0
        )
        session.add(resolve_event)
        session.commit()
        step_counter += 1

        fetch_start = time.time()
        html_content = ""
        clean_text = ""

        if is_rss:
            import feedparser
            import requests
            headers = {'User-Agent': 'Mozilla/5.0 MajorRSS/1.0'}
            res = requests.get(sub.target_url, headers=headers, timeout=30)
            feed = feedparser.parse(res.content)
            items = []
            for entry in feed.entries[:10]:
                title = entry.get('title', '')
                link = entry.get('link', '')
                items.append(f"TEXT: {title}")
                if link:
                    items.append(f"LINK: {title} ({link})")
            clean_text = "\n".join(items)
            if not clean_text.strip():
                clean_text = "TEXT: No items found in feed."
                
            fetch_duration = int((time.time() - fetch_start) * 1000)
            fetch_event = PipelineEvent(
                run_id=run.id,
                step_index=step_counter,
                stage="FETCH",
                input_data=desensitize_url(sub.target_url),
                output_summary=f"Parsed RSS feed. Extracted {len(items)} items",
                status="SUCCESS",
                duration_ms=fetch_duration
            )
            session.add(fetch_event)
            session.commit()
            step_counter += 1
        else:
            policy = {}
            if sub.diff_policy:
                try:
                    policy = json.loads(sub.diff_policy)
                except:
                    pass
            js_rendering = policy.get("js_rendering", False)
            extract_sel = policy.get("extract_selector")
            ignore_sel = policy.get("ignore_selector")
            
            if js_rendering:
                cost_browser = True
                scraper = AgenticScraper(sub.target_url)
                html_content = scraper.fetch_text_snapshot(return_html=True)
            else:
                import requests
                headers = {'User-Agent': 'Mozilla/5.0 MajorRSS/1.0'}
                res = requests.get(sub.target_url, headers=headers, timeout=30)
                html_content = res.text
            
            if not html_content:
                raise Exception("Failed to fetch HTML content (returned empty)")
                
            fetch_duration = int((time.time() - fetch_start) * 1000)
            fetch_event = PipelineEvent(
                run_id=run.id,
                step_index=step_counter,
                stage="FETCH",
                adapter="AgenticAdapter" if js_rendering else "StaticAdapter",
                input_data=desensitize_url(sub.target_url),
                output_summary=f"Fetched HTML (length: {len(html_content)} bytes)",
                status="SUCCESS",
                duration_ms=fetch_duration
            )
            session.add(fetch_event)
            session.commit()
            step_counter += 1
            
            # CLEAN Event
            clean_start = time.time()
            clean_text = clean_html_for_diff(html_content, extract_selector=extract_sel, ignore_selector=ignore_sel)
            clean_duration = int((time.time() - clean_start) * 1000)
            
            if not clean_text.strip():
                raise Exception("Extracted text is empty after filtering")
                
            clean_event = PipelineEvent(
                run_id=run.id,
                step_index=step_counter,
                stage="CLEAN",
                output_summary=f"Cleaned HTML. Text length: {len(clean_text)} characters",
                status="SUCCESS",
                duration_ms=clean_duration
            )
            session.add(clean_event)
            session.commit()
            step_counter += 1
            
        # DIFF Event
        diff_start = time.time()
        # 2. Hash computation
        text_hash = hashlib.sha256(clean_text.encode('utf-8')).hexdigest()
        
        # 3. Get last snapshot
        last_snapshot = session.exec(select(PageSnapshot).where(PageSnapshot.subscription_id == sub.id).order_by(PageSnapshot.created_at.desc())).first()
        
        diff_text = ""
        change_detected = False
        if not last_snapshot or last_snapshot.content_hash != text_hash:
            change_detected = True
            if last_snapshot:
                old_lines = last_snapshot.content_text.splitlines()
                new_lines = clean_text.splitlines()
                # Use unified_diff to extract only the changes (+/-)
                diff_lines = list(difflib.unified_diff(old_lines, new_lines, lineterm='', fromfile='Old', tofile='New', n=1))
                diff_text = "\n".join(diff_lines)
            else:
                diff_text = "INITIAL SNAPSHOT CAPTURED."
                diff_lines = []
                
            # Save new snapshot
            new_snapshot = PageSnapshot(subscription_id=sub.id, content_hash=text_hash, content_text=clean_text)
            session.add(new_snapshot)
            
            # Create Update Notification if it's not the initial snapshot
            if last_snapshot and diff_text.strip():
                # Parse diff policy options
                keep_keywords = []
                ignore_keywords = []
                monitor_goal = "none"
                if sub.diff_policy:
                    try:
                        dp = json.loads(sub.diff_policy)
                        keep_keywords = [kw.strip().lower() for kw in dp.get("keep_keywords", []) if kw.strip()]
                        ignore_keywords = [kw.strip().lower() for kw in dp.get("ignore_keywords", []) if kw.strip()]
                        monitor_goal = dp.get("monitor_goal", "none")
                    except:
                        pass

                added_lines = [line[1:] for line in diff_lines if line.startswith('+') and not line.startswith('+++')]
                removed_lines = [line[1:] for line in diff_lines if line.startswith('-') and not line.startswith('---')]
                added_text = " ".join(added_lines).lower()
                
                is_pure_deletion = len(removed_lines) > 0 and len(added_lines) == 0
                is_filtered_out = False
                
                # 1. Pure deletion check
                if is_pure_deletion and monitor_goal != "whole_page_change":
                    is_filtered_out = True
                    
                # 2. Keep keywords check
                if not is_filtered_out and keep_keywords:
                    if not any(kw in added_text for kw in keep_keywords):
                        is_filtered_out = True
                        
                # 3. Ignore keywords check
                if not is_filtered_out and ignore_keywords:
                    if any(kw in added_text for kw in ignore_keywords):
                        is_filtered_out = True

                if not is_filtered_out:
                    new_update = SubscriptionUpdate(subscription_id=sub.id, diff_text=diff_text)
                    session.add(new_update)
                    sub.last_status = "Update Detected"
                    accepted_items = 1
                else:
                    sub.last_status = "Update Ignored (Filtered)"
                    accepted_items = 0
            else:
                sub.last_status = "Tracking Started"
                accepted_items = 0
        else:
            sub.last_status = "No Changes"
            accepted_items = 0
            
        diff_duration = int((time.time() - diff_start) * 1000)
        diff_event = PipelineEvent(
            run_id=run.id,
            step_index=step_counter,
            stage="DIFF",
            output_summary=f"Diff completed. Change detected: {change_detected}. Diff size: {len(diff_text)} chars",
            status="SUCCESS",
            duration_ms=diff_duration
        )
        session.add(diff_event)
        session.commit()
        step_counter += 1
        
        success = True
            
    except CookieExpiredException as e:
        duration = int((time.time() - fetch_start) * 1000)
        print(f"Cookie expired for {sub.name}: {e}")
        sub.last_status = "Error: Cookie Expired"
        error_summary = f"Cookie Expired: {e}"
        
        fail_event = PipelineEvent(
            run_id=run.id,
            step_index=step_counter,
            stage="FETCH",
            status="FAILED",
            error="AUTH_EXPIRED",
            duration_ms=duration
        )
        session.add(fail_event)
        session.commit()
        step_counter += 1
    except Exception as e:
        duration = int((time.time() - fetch_start) * 1000)
        print(f"Error processing subscription {sub.name}: {e}")
        sub.last_status = f"Error: {str(e)[:50]}"
        error_summary = str(e)
        
        fail_event = PipelineEvent(
            run_id=run.id,
            step_index=step_counter,
            stage="FETCH" if not html_content else "CLEAN",
            status="FAILED",
            error=scrub_sensitive_info(str(e))[:100],
            duration_ms=duration
        )
        session.add(fail_event)
        session.commit()
        step_counter += 1
    finally:
        sub.last_scraped_at = now.replace(tzinfo=None) if now.tzinfo else now
        session.add(sub)
        session.commit()
        
        # Finalize PipelineRun
        run.status = "SUCCESS" if success else "FAILED"
        run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
        run.total_routes = 1
        run.total_items = 1 if success else 0
        run.accepted_items = accepted_items
        run.cost_flag_browser = cost_browser
        run.cost_flag_llm = cost_llm
        if error_summary:
            run.error_summary = scrub_sensitive_info(error_summary)[:200]
        session.add(run)
        session.commit()

def run_subscription_job():
    print("Running scheduled subscription monitor job...")
    session = get_session()
    subs = session.exec(select(Subscription).where(Subscription.is_active == True)).all()
    
    now = datetime.now(timezone.utc)
    for sub in subs:
        if not sub.last_scraped_at:
            process_subscription(session, sub, now)
        else:
            last_scraped = sub.last_scraped_at
            if last_scraped.tzinfo is None:
                last_scraped = last_scraped.replace(tzinfo=timezone.utc)
                
            if now - last_scraped >= timedelta(minutes=sub.fetch_interval_minutes):
                process_subscription(session, sub, now)

if __name__ == "__main__":
    run_subscription_job()
