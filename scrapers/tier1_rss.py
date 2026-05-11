import feedparser
from datetime import datetime, timezone
import time
from typing import List, Dict, Any

class BasicRSSScraper:
    def __init__(self, url: str):
        self.url = url
        
    def fetch(self) -> List[Dict[str, Any]]:
        print(f"Fetching RSS from {self.url}...")
        parsed_feed = feedparser.parse(self.url)
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
