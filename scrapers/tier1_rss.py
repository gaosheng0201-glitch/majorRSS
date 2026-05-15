import feedparser
from datetime import datetime, timezone
import time
from typing import List, Dict, Any

class BasicRSSScraper:
    def __init__(self, url: str):
        self.url = url
        
    def fetch(self) -> List[Dict[str, Any]]:
        print(f"Fetching RSS from {self.url}...")
        # Set a custom user-agent to avoid getting blocked by Reddit/HackerNews
        agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 MajorRSS/1.1"
        parsed_feed = feedparser.parse(self.url, agent=agent)
        
        # Explicit status check to avoid silent failures
        if hasattr(parsed_feed, 'status') and parsed_feed.status >= 400:
            raise Exception(f"HTTP Error {parsed_feed.status}")
        
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
