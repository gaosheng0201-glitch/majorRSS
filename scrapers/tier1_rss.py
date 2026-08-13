import calendar
import feedparser
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from services.http_client import conditional_get
from services.log_service import get_logger

logger = get_logger("scraper.rss")


def entry_published_at(entry) -> Optional[datetime]:
    """Item timestamp as naive-free UTC, from feedparser's parsed struct.

    feedparser normalises `published_parsed` to a UTC struct_time. The old code
    ran it through `time.mktime()`, which interprets a struct as LOCAL STANDARD
    time — so on this machine (America/New_York, EST=UTC-5) every RSS item's
    published_at landed 5 hours in the future, DST notwithstanding (mktime
    honours the struct's tm_isdst=0). Field-verified on three DeepMind posts:
    feed said 17:04/14:01/15:06 UTC, we stored 22:04/19:01/20:06. For a product
    whose pitch is provenance, "who reported first" was systematically shuffled
    by source class. calendar.timegm is mktime's UTC twin.
    """
    parsed = getattr(entry, "published_parsed", None)
    if not parsed:
        return None
    return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)

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
            published_time = entry_published_at(entry)

            results.append({
                "title": entry.title if hasattr(entry, 'title') else "No Title",
                "url": entry.link if hasattr(entry, 'link') else entry.id,
                "content": entry.summary if hasattr(entry, 'summary') else (entry.description if hasattr(entry, 'description') else ""),
                "published_at": published_time
            })
        return results
