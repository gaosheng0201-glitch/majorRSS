import feedparser
from datetime import datetime, timezone
import time
from typing import List, Dict, Any

from services.http_client import conditional_get
from services.log_service import get_logger

logger = get_logger("scraper.rss")

class BasicRSSScraper:
    def __init__(self, url: str):
        self.url = url

    def fetch(self) -> List[Dict[str, Any]]:
        logger.info(f"Fetching RSS from {self.url}...")
        import requests
        try:
            # Conditional GET: an unchanged feed returns 304 (empty body) and we
            # skip parsing entirely — a healthy quiet feed costs one header trip.
            result = conditional_get(self.url)
        except requests.exceptions.RequestException as e:
            raise Exception(f"HTTP Error: {str(e)}")

        if not result.changed:
            return []

        parsed_feed = feedparser.parse(result.content)

        if getattr(parsed_feed, 'bozo', 0) and len(parsed_feed.entries) == 0:
            raise Exception(f"RSS Parse Error: {getattr(parsed_feed, 'bozo_exception', 'Unknown')}")
            
        results = []
        for entry in parsed_feed.entries:
            published_time = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                published_time = datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=timezone.utc)
            
            results.append({
                "title": entry.title if hasattr(entry, 'title') else "No Title",
                "url": entry.link if hasattr(entry, 'link') else entry.id,
                "content": entry.summary if hasattr(entry, 'summary') else (entry.description if hasattr(entry, 'description') else ""),
                "published_at": published_time
            })
        return results
