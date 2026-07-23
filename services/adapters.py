import os
import json
import time
import hashlib
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from db.config import get_cookie_path
from services.source_resolver import SourceRoute
from scrapers.tier1_rss import BasicRSSScraper
from scrapers.tier3_agentic import AgenticScraper, CookieExpiredException

@dataclass
class SourceItem:
    source_id: str
    platform: str
    route: str
    title: str
    url: str
    content: str
    author: Optional[str] = None
    summary: Optional[str] = None
    published_at: Optional[datetime] = None
    metrics: Optional[Dict[str, Any]] = None
    raw_payload: Optional[Dict[str, Any]] = None
    fingerprint: Optional[str] = None
    # Provenance tier carried from the route (docs/source_tiering.md). The
    # normalizer refines it by the item URL and writes RawArticle.source_tier.
    tier: Optional[str] = None

class BaseAdapter:
    def fetch(self, route: SourceRoute, auth_profile_id: Optional[int] = None) -> List[SourceItem]:
        raise NotImplementedError

class RssAdapter(BaseAdapter):
    def fetch(self, route: SourceRoute, auth_profile_id: Optional[int] = None) -> List[SourceItem]:
        scraper = BasicRSSScraper(route.url_or_command)
        raw_items = scraper.fetch()
        
        items = []
        for idx, entry in enumerate(raw_items):
            published_at = entry.get("published_at")
            # Convert naive datetime to UTC if needed
            if published_at and published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)
                
            items.append(SourceItem(
                source_id=f"{route.route_id}_{idx}",
                platform=route.platform,
                tier=getattr(route, "tier", None),
                route=route.url_or_command,
                title=entry.get("title", "No Title"),
                url=entry.get("url", ""),
                content=entry.get("content", ""),
                published_at=published_at,
                raw_payload=entry
            ))
        return items

class RssHubAdapter(BaseAdapter):
    def fetch(self, route: SourceRoute, auth_profile_id: Optional[int] = None) -> List[SourceItem]:
        # Parse route like rsshub:/twitter/user/sama
        rsshub_path = route.url_or_command.replace("rsshub:", "")
        
        rsshub_base = os.environ.get("RSSHUB_URL", "https://rsshub.app").rstrip("/")
        full_url = f"{rsshub_base}{rsshub_path}"
        
        try:
            scraper = BasicRSSScraper(full_url)
            raw_items = scraper.fetch()
        except Exception as e:
            # Fallback to public RSSHub if self-hosted instance fails
            if rsshub_base != "https://rsshub.app":
                print(f"[RssHubAdapter] Self-hosted instance failed. Falling back to public rsshub.app: {e}")
                public_url = f"https://rsshub.app{rsshub_path}"
                scraper = BasicRSSScraper(public_url)
                raw_items = scraper.fetch()
            else:
                raise e
                
        items = []
        for idx, entry in enumerate(raw_items):
            published_at = entry.get("published_at")
            if published_at and published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)
                
            items.append(SourceItem(
                source_id=f"{route.route_id}_{idx}",
                platform=route.platform,
                tier=getattr(route, "tier", None),
                route=route.url_or_command,
                title=entry.get("title", "No Title"),
                url=entry.get("url", ""),
                content=entry.get("content", ""),
                published_at=published_at,
                raw_payload=entry
            ))
        return items

class AgenticAdapter(BaseAdapter):
    def fetch(self, route: SourceRoute, auth_profile_id: Optional[int] = None) -> List[SourceItem]:
        # Decrypt cookie_string if auth_profile_id is supplied
        cookie_string = None
        
        if auth_profile_id:
            from db.database import get_session
            from db.models import AuthProfile
            with get_session() as session:
                profile = session.get(AuthProfile, auth_profile_id)
                if profile:
                    cookie_path = get_cookie_path(profile.storage_ref)
                    if os.path.exists(cookie_path):
                        try:
                            with open(cookie_path, 'rb') as f:
                                content = f.read()
                            try:
                                from services.crypto_service import decrypt_data
                                decrypted_str = decrypt_data(content)
                                # Extract raw cookies from playwright storage state JSON
                                state = json.loads(decrypted_str)
                                cookies = []
                                for c in state.get("cookies", []):
                                    cookies.append(f"{c['name']}={c['value']}")
                                if cookies:
                                    cookie_string = "; ".join(cookies)
                            except Exception as e:
                                print(f"[AgenticAdapter] Failed to decrypt secure auth profile cookie: {e}")
                        except Exception as e:
                            print(f"[AgenticAdapter] Failed to read auth profile cookie file: {e}")
                            
        scraper = AgenticScraper(route.url_or_command, cookie_string=cookie_string)
        text = scraper.fetch_text_snapshot()
        
        if not text:
            return []
            
        content_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
        
        # Agentic snapshot returns a single Snapshot item representing the page
        item = SourceItem(
            source_id=f"{route.route_id}_snapshot",
            platform=route.platform,
            tier=getattr(route, "tier", None),
            route=route.url_or_command,
            title=f"Snapshot: {route.url_or_command}",
            url=route.url_or_command + f"#{content_hash}",
            content=text,
            published_at=datetime.now(timezone.utc),
            fingerprint=content_hash
        )
        return [item]
