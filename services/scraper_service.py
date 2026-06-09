import hashlib
import json
import urllib.parse
from datetime import datetime, timezone

from repositories.repository import DBRepository
from db.models import RawArticle
from scrapers.tier1_rss import BasicRSSScraper
from scrapers.tier3_agentic import AgenticScraper, CookieExpiredException

db = DBRepository()

def _fetch_url(tracker, url: str, tier: int, max_days: int = 7) -> bool:
    try:
        if tier == 1 or tier == 2:
            scraper = BasicRSSScraper(url)
            items = scraper.fetch()
            
            for item in items:
                if max_days > 0 and item.get("published_at"):
                    age = datetime.now(timezone.utc) - item["published_at"]
                    if age.days > max_days:
                        continue
                
                if not db.check_url_exists(item["url"]) and not db.check_title_exists(tracker.id, item["title"]):
                    raw = RawArticle(
                        tracker_id=tracker.id,
                        title=item["title"],
                        url=item["url"],
                        content=item["content"],
                        published_at=item["published_at"]
                    )
                    if db.save_raw_article(raw):
                        print(f"Saved raw article: {raw.title}")
                    else:
                        print(f"Skipped duplicate insert due to concurrency: {raw.url}")
        elif tier == 3:
            scraper = AgenticScraper(url, tracker.cookie_string)
            text = scraper.fetch_text_snapshot()
            if text:
                content_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
                is_duplicate = False # Deep similarity check would go here (fetch recent articles for url pattern)
                
                if not is_duplicate:
                    raw = RawArticle(
                        tracker_id=tracker.id,
                        title=f"Snapshot: {tracker.name}",
                        url=url + f"#{content_hash}",
                        content=text
                    )
                    if db.save_raw_article(raw):
                        print(f"Saved new Agentic snapshot for {tracker.name}")
        return True
    except CookieExpiredException as e:
        print(f"Auth Failed for {url}: {e}")
        db.set_pipeline_status(tracker.name, "Auth Failed", str(e))
        return False
    except Exception as e:
        print(f"Fetch failed for {url}: {e}")
        domain = urllib.parse.urlparse(url).netloc
        db.set_pipeline_status(tracker.name, "Probe Failed", f"[{domain}] {e}")
        return False

def scrape_single_tracker(tracker_id: int):
    tracker = db.get_tracker(tracker_id)
    if not tracker:
        return
        
    db.set_pipeline_status(tracker.name, "Scraping", f"Tracker ({tracker.tracker_type}) is fetching data...")
    
    def parse_targets(target_str: str) -> list:
        if not target_str:
            return []
        try:
            data = json.loads(target_str)
            if isinstance(data, list):
                return [str(item).strip() for item in data if item]
            if isinstance(data, str):
                return [data.strip()]
            return [str(data).strip()]
        except (json.JSONDecodeError, TypeError):
            return [t.strip() for t in target_str.split('\n') if t.strip()]
            
    if tracker.tracker_type == "HYBRID":
        try:
            target_data = json.loads(tracker.target)
        except json.JSONDecodeError:
            print(f"Failed to decode HYBRID target for {tracker.name}: {tracker.target}")
            return
            
        max_days = target_data.get("max_days", 7)
        
        for u in target_data.get("urls", []):
            _fetch_url(tracker, u, tier=1, max_days=max_days)
            
        if target_data.get("use_default_osint", False):
            for kw in target_data.get("keywords", []):
                encoded_kw = urllib.parse.quote(kw)
                gnews_url = f"https://news.google.com/rss/search?q={encoded_kw}"
                _fetch_url(tracker, gnews_url, tier=1, max_days=max_days)
                
                hn_url = f"https://hnrss.org/newest?q={encoded_kw}"
                _fetch_url(tracker, hn_url, tier=1, max_days=max_days)
                
                reddit_url = f"https://www.reddit.com/search.rss?q={encoded_kw}&sort=new"
                _fetch_url(tracker, reddit_url, tier=1, max_days=max_days)
                
        for acc in target_data.get("accounts", []):
            account_name = acc.replace('@', '')
            if tracker.cookie_string:
                twitter_url = f"https://twitter.com/{account_name}"
                _fetch_url(tracker, twitter_url, tier=3, max_days=max_days)
            else:
                nitter_url = f"https://nitter.net/{account_name}/rss"
                success = _fetch_url(tracker, nitter_url, tier=1, max_days=max_days)
                if not success:
                    print(f"Nitter failed for {account_name}, falling back to RSSHub...")
                    db.set_pipeline_status(tracker.name, "Fallback", f"Nitter failed, automatically switching to RSSHub for {account_name}")
                    rsshub_url = f"https://rsshub.app/twitter/user/{account_name}"
                    _fetch_url(tracker, rsshub_url, tier=1, max_days=max_days)

    elif tracker.tracker_type == "URL":
        urls = parse_targets(tracker.target)
        for u in urls:
            _fetch_url(tracker, u, tier=tracker.tier or 1, max_days=7)

    elif tracker.tracker_type == "KEYWORD":
        keywords = parse_targets(tracker.target)
        for kw in keywords:
            encoded_kw = urllib.parse.quote(kw)
            gnews_url = f"https://news.google.com/rss/search?q={encoded_kw}"
            _fetch_url(tracker, gnews_url, tier=1, max_days=7)
            
            hn_url = f"https://hnrss.org/newest?q={encoded_kw}"
            _fetch_url(tracker, hn_url, tier=1, max_days=7)
            
            reddit_url = f"https://www.reddit.com/search.rss?q={encoded_kw}&sort=new"
            _fetch_url(tracker, reddit_url, tier=1, max_days=7)

    elif tracker.tracker_type == "ACCOUNT":
        accounts = parse_targets(tracker.target)
        for acc in accounts:
            account_name = acc.replace('@', '')
            if tracker.cookie_string:
                twitter_url = f"https://twitter.com/{account_name}"
                _fetch_url(tracker, twitter_url, tier=3, max_days=7)
            else:
                nitter_url = f"https://nitter.net/{account_name}/rss"
                success = _fetch_url(tracker, nitter_url, tier=1, max_days=7)
                if not success:
                    print(f"Nitter failed for {account_name}, falling back to RSSHub...")
                    db.set_pipeline_status(tracker.name, "Fallback", f"Nitter failed, automatically switching to RSSHub for {account_name}")
                    rsshub_url = f"https://rsshub.app/twitter/user/{account_name}"
                    _fetch_url(tracker, rsshub_url, tier=1, max_days=7)

    from db.database import get_session
    with get_session() as session:
        t = session.get(type(tracker), tracker.id)
        t.last_scraped_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.add(t)
        session.commit()
