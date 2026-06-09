import sys
import os
import hashlib
import difflib
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

# Ensure root is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlmodel import select
from db.database import get_session
from db.models import Subscription, PageSnapshot, SubscriptionUpdate
from scrapers.tier3_agentic import AgenticScraper, CookieExpiredException

def clean_html_for_diff(html_content: str) -> str:
    """
    Smart Diff Filter:
    1. Parse HTML
    2. Remove volatile nodes: <time>, dynamic spans, pure number nodes.
    3. Extract structural skeleton: text blocks and <a> links.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
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
            # Only keep significant text blocks to avoid layout noise
            if len(text) > 15:
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
    try:
        print(f"Monitoring Subscription: {sub.name} ({sub.target_url})")
        
        from scrapers.url_normalizer import is_rss_url
        if is_rss_url(sub.target_url):
            import feedparser
            import requests
            try:
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
            except Exception as e:
                sub.last_status = f"Error: Failed to fetch RSS - {str(e)}"
                return
        else:
            scraper = AgenticScraper(sub.target_url)
            # Fetch raw HTML using Tier 3 (handles React/Vue and bypasses basic anti-bot)
            html_content = scraper.fetch_text_snapshot(return_html=True)
            
            if not html_content:
                sub.last_status = "Error: Failed to fetch HTML"
                return
                
            # 1. Smart Filtering
            clean_text = clean_html_for_diff(html_content)
            if not clean_text.strip():
                sub.last_status = "Error: Extracted text is empty"
                return
            
        # 2. Hash computation
        text_hash = hashlib.sha256(clean_text.encode('utf-8')).hexdigest()
        
        # 3. Get last snapshot
        last_snapshot = session.exec(select(PageSnapshot).where(PageSnapshot.subscription_id == sub.id).order_by(PageSnapshot.created_at.desc())).first()
        
        if not last_snapshot or last_snapshot.content_hash != text_hash:
            print(f"Change detected for {sub.name}!")
            
            diff_text = ""
            if last_snapshot:
                old_lines = last_snapshot.content_text.splitlines()
                new_lines = clean_text.splitlines()
                # Use unified_diff to extract only the changes (+/-)
                diff = difflib.unified_diff(old_lines, new_lines, lineterm='', fromfile='Old', tofile='New', n=1)
                diff_text = "\n".join(diff)
            else:
                diff_text = "INITIAL SNAPSHOT CAPTURED."
                
            # Save new snapshot
            new_snapshot = PageSnapshot(subscription_id=sub.id, content_hash=text_hash, content_text=clean_text)
            session.add(new_snapshot)
            
            # Create Update Notification if it's not the initial snapshot
            if last_snapshot and diff_text.strip():
                new_update = SubscriptionUpdate(subscription_id=sub.id, diff_text=diff_text)
                session.add(new_update)
                sub.last_status = "Update Detected"
            else:
                sub.last_status = "Tracking Started"
        else:
            sub.last_status = "No Changes"
            
    except CookieExpiredException as e:
        print(f"Cookie expired for {sub.name}: {e}")
        sub.last_status = "Error: Cookie Expired"
    except Exception as e:
        print(f"Error processing subscription {sub.name}: {e}")
        sub.last_status = f"Error: {str(e)[:50]}"
    finally:
        sub.last_scraped_at = now.replace(tzinfo=None) if now.tzinfo else now
        session.add(sub)
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
