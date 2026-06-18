import json
import urllib.parse
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class SourceRoute:
    route_id: str
    adapter: str          # "RssAdapter" | "RssHubAdapter" | "AgenticAdapter"
    url_or_command: str
    purpose: str          # "discovery" | "enrichment" | "snapshot"
    requires_auth: bool
    platform: str
    priority: int = 1
    auth_profile_id: Optional[int] = None
    auth_status: str = "none" # "none" | "matched" | "missing"

class SourceResolver:
    def __init__(self, fetch_policy: Optional[str] = None, auth_profile_id: Optional[int] = None):
        self.auth_profile_id = auth_profile_id
        self.policy = self._parse_policy(fetch_policy)

    def _parse_policy(self, fetch_policy_str: Optional[str]) -> dict:
        default_policy = {
            "url_strategy": "auto",
            "keyword_strategy": "default",
            "account_strategy": "auto",
            "fallback_enabled": True,
            "max_days": 7,
            "max_items_per_route": 20,
            "min_relevance": 0.35,
            "use_default_osint": True
        }
        if not fetch_policy_str:
            return default_policy
        try:
            user_policy = json.loads(fetch_policy_str)
            default_policy.update(user_policy)
        except:
            pass
        return default_policy

    def resolve_routes(self, source_intent: str, target: str) -> List[SourceRoute]:
        # Auto-detect new Topic + Signals format to handle unified topic discoveries
        try:
            target_data = json.loads(target)
            if isinstance(target_data, dict) and "topic" in target_data and "signals" in target_data:
                routes = self._resolve_hybrid_routes(target)
                self._enrich_routes_with_auth(routes)
                return routes
        except:
            pass

        intent = source_intent.upper()
        if intent == "RSS_FEED":
            routes = self._resolve_rss_routes(target)
        elif intent == "KEYWORD_DISCOVERY":
            routes = self._resolve_keyword_routes(target)
        elif intent == "ACCOUNT_TRACKING":
            routes = self._resolve_account_routes(target)
        elif intent == "HYBRID":
            routes = self._resolve_hybrid_routes(target)
        else:
            # Fallback/Backward compatibility mapping
            routes = self._resolve_rss_routes(target)
            
        self._enrich_routes_with_auth(routes)
        return routes

    def _enrich_routes_with_auth(self, routes: List[SourceRoute]):
        try:
            from db.database import get_session
            from db.models import AuthProfile
            from sqlmodel import select
            
            with get_session() as session:
                # Query all active AuthProfiles
                profiles = session.exec(select(AuthProfile).where(AuthProfile.status == "Active")).all()
                profile_map = {p.platform.lower(): p.id for p in profiles}
                
                for r in routes:
                    if r.requires_auth or r.adapter == "AgenticAdapter":
                        platform = r.platform.lower()
                        if platform in profile_map:
                            r.auth_profile_id = profile_map[platform]
                            r.auth_status = "matched"
                            r.requires_auth = True
                        elif self.auth_profile_id is not None:
                            r.auth_profile_id = self.auth_profile_id
                            r.auth_status = "matched"
                            r.requires_auth = True
                        else:
                            r.auth_profile_id = None
                            if r.requires_auth or r.platform in ["twitter", "bilibili", "weibo"]:
                                r.auth_status = "missing"
                                r.requires_auth = True
                            else:
                                r.auth_status = "none"
                    else:
                        r.auth_profile_id = None
                        r.auth_status = "none"
        except Exception as e:
            # Fallback for offline/test environments
            print(f"Error enriching routes with auth: {e}")
            for r in routes:
                if r.requires_auth or r.adapter == "AgenticAdapter":
                    if self.auth_profile_id is not None:
                        r.auth_profile_id = self.auth_profile_id
                        r.auth_status = "matched"
                        r.requires_auth = True
                    else:
                        r.auth_profile_id = None
                        r.auth_status = "missing" if (r.requires_auth or r.platform in ["twitter", "bilibili", "weibo"]) else "none"
                        if r.auth_status == "missing":
                            r.requires_auth = True
                else:
                    r.auth_profile_id = None
                    r.auth_status = "none"

    def _resolve_rss_routes(self, target: str) -> List[SourceRoute]:
        # Handle list of targets if newline/json separated
        urls = self._parse_targets(target)
        routes = []
        
        strategy = self.policy.get("url_strategy", "auto")
        fallback = self.policy.get("fallback_enabled", True)
        
        for idx, u in enumerate(urls):
            is_probably_rss = False
            for suffix in [".xml", ".rss", ".atom", "feed", "rsshub", "rss=1"]:
                if suffix in u.lower():
                    is_probably_rss = True
                    break
                    
            if strategy == "rss_first":
                routes.append(SourceRoute(
                    route_id=f"rss_feed_{idx}",
                    adapter="RssAdapter",
                    url_or_command=u,
                    purpose="discovery",
                    requires_auth=False,
                    platform="rss",
                    priority=1
                ))
                if fallback:
                    routes.append(SourceRoute(
                        route_id=f"agentic_snapshot_{idx}",
                        adapter="AgenticAdapter",
                        url_or_command=u,
                        purpose="snapshot",
                        requires_auth=False,
                        platform="web",
                        priority=2
                    ))
            elif strategy == "agentic":
                routes.append(SourceRoute(
                    route_id=f"agentic_snapshot_{idx}",
                    adapter="AgenticAdapter",
                    url_or_command=u,
                    purpose="snapshot",
                    requires_auth=self.auth_profile_id is not None,
                    platform="web",
                    priority=1
                ))
            elif strategy == "no_fallback":
                routes.append(SourceRoute(
                    route_id=f"rss_feed_{idx}",
                    adapter="RssAdapter",
                    url_or_command=u,
                    purpose="discovery",
                    requires_auth=False,
                    platform="rss",
                    priority=1
                ))
            else: # "auto" strategy
                if is_probably_rss:
                    routes.append(SourceRoute(
                        route_id=f"rss_feed_{idx}",
                        adapter="RssAdapter",
                        url_or_command=u,
                        purpose="discovery",
                        requires_auth=False,
                        platform="rss",
                        priority=1
                    ))
                    if fallback:
                        routes.append(SourceRoute(
                            route_id=f"agentic_snapshot_{idx}",
                            adapter="AgenticAdapter",
                            url_or_command=u,
                            purpose="snapshot",
                            requires_auth=False,
                            platform="web",
                            priority=2
                        ))
                else:
                    # Webpage snapshot first, optional RSS check alternate is done inside RssAdapter internally
                    routes.append(SourceRoute(
                        route_id=f"agentic_snapshot_{idx}",
                        adapter="AgenticAdapter",
                        url_or_command=u,
                        purpose="snapshot",
                        requires_auth=False,
                        platform="web",
                        priority=1
                    ))
                    if fallback:
                        routes.append(SourceRoute(
                            route_id=f"rss_alternate_{idx}",
                            adapter="RssAdapter",
                            url_or_command=u,
                            purpose="discovery",
                            requires_auth=False,
                            platform="rss",
                            priority=2
                        ))
        return routes

    def _resolve_keyword_routes(self, target: str) -> List[SourceRoute]:
        keywords = self._parse_targets(target)
        routes = []
        strategy = self.policy.get("keyword_strategy", "default")
        
        for idx, kw in enumerate(keywords):
            encoded_kw = urllib.parse.quote(kw)
            
            # Default includes Google News, HN, and Reddit
            # trusted_news_only only includes Google News (and curated feeds when defined)
            if strategy in ["default", "news_only", "tech_sources", "trusted_news_only"]:
                routes.append(SourceRoute(
                    route_id=f"gnews_{idx}",
                    adapter="RssAdapter",
                    url_or_command=f"https://news.google.com/rss/search?q={encoded_kw}",
                    purpose="discovery",
                    requires_auth=False,
                    platform="gnews",
                    priority=1
                ))
            if strategy in ["default", "tech_sources"]:
                routes.append(SourceRoute(
                    route_id=f"hn_{idx}",
                    adapter="RssAdapter",
                    url_or_command=f"https://hnrss.org/newest?q={encoded_kw}",
                    purpose="discovery",
                    requires_auth=False,
                    platform="hackernews",
                    priority=1
                ))
            if strategy in ["default", "social_forum"]:
                routes.append(SourceRoute(
                    route_id=f"reddit_{idx}",
                    adapter="RssAdapter",
                    url_or_command=f"https://www.reddit.com/search.rss?q={encoded_kw}&sort=new",
                    purpose="discovery",
                    requires_auth=False,
                    platform="reddit",
                    priority=1
                ))
        return routes

    def _resolve_account_routes(self, target: str) -> List[SourceRoute]:
        accounts = self._parse_targets(target)
        routes = []
        
        for idx, acc in enumerate(accounts):
            platform = self._detect_platform(acc)
            # Strip prefixes and format correctly
            account_name = acc.strip()
            for prefix in ["bilibili:", "twitter:", "x:", "x.com:", "weibo:", "instagram:", "tiktok:", "reddit:"]:
                if account_name.lower().startswith(prefix):
                    account_name = account_name[len(prefix):].strip()
                    break
            if account_name.startswith("@"):
                account_name = account_name[1:].strip()
            
            # URL parsing fallback for extracting account name/ID
            if "bilibili.com" in account_name.lower():
                import re
                match = re.search(r'space\.bilibili\.com/(\d+)', account_name.lower())
                if match:
                    account_name = match.group(1)
            elif "/" in account_name:
                parsed = urllib.parse.urlparse(account_name)
                path = parsed.path.strip("/")
                parts = [p for p in path.split("/") if p]
                if parts:
                    account_name = parts[0]
            
            if platform == "twitter":
                # Route 1: Nitter (RssAdapter)
                routes.append(SourceRoute(
                    route_id=f"nitter_twitter_{idx}",
                    adapter="RssAdapter",
                    url_or_command=f"https://nitter.net/{account_name}/rss",
                    purpose="discovery",
                    requires_auth=False,
                    platform="twitter",
                    priority=1
                ))
                # Route 2: RSSHub (RssHubAdapter)
                routes.append(SourceRoute(
                    route_id=f"rsshub_twitter_{idx}",
                    adapter="RssHubAdapter",
                    url_or_command=f"rsshub:/twitter/user/{account_name}",
                    purpose="discovery",
                    requires_auth=False,
                    platform="twitter",
                    priority=2
                ))
                # Route 3: Playwright Agentic (AgenticAdapter)
                routes.append(SourceRoute(
                    route_id=f"agentic_twitter_{idx}",
                    adapter="AgenticAdapter",
                    url_or_command=f"https://x.com/{account_name}",
                    purpose="snapshot",
                    requires_auth=self.auth_profile_id is not None,
                    platform="twitter",
                    priority=3
                ))
            elif platform == "bilibili":
                # Route 1: RSSHub (RssHubAdapter)
                routes.append(SourceRoute(
                    route_id=f"rsshub_bilibili_{idx}",
                    adapter="RssHubAdapter",
                    url_or_command=f"rsshub:/bilibili/user/video/{account_name}",
                    purpose="discovery",
                    requires_auth=False,
                    platform="bilibili",
                    priority=1
                ))
                # Route 2: Playwright Agentic (AgenticAdapter)
                routes.append(SourceRoute(
                    route_id=f"agentic_bilibili_{idx}",
                    adapter="AgenticAdapter",
                    url_or_command=f"https://space.bilibili.com/{account_name}",
                    purpose="snapshot",
                    requires_auth=self.auth_profile_id is not None,
                    platform="bilibili",
                    priority=2
                ))
            elif platform == "weibo":
                routes.append(SourceRoute(
                    route_id=f"rsshub_weibo_{idx}",
                    adapter="RssHubAdapter",
                    url_or_command=f"rsshub:/weibo/user/{account_name}",
                    purpose="discovery",
                    requires_auth=False,
                    platform="weibo",
                    priority=1
                ))
            else:
                # Default generic platform mapping using RSSHub
                routes.append(SourceRoute(
                    route_id=f"rsshub_generic_{idx}",
                    adapter="RssHubAdapter",
                    url_or_command=f"rsshub:/{platform}/user/{account_name}" if platform != "unknown" else f"rsshub:/twitter/user/{account_name}",
                    purpose="discovery",
                    requires_auth=False,
                    platform=platform,
                    priority=1
                ))
        return routes

    def _resolve_hybrid_routes(self, target: str) -> List[SourceRoute]:
        routes = []
        try:
            target_data = json.loads(target)
            if not isinstance(target_data, dict):
                return []
        except:
            return []
            
        if "topic" in target_data and "signals" in target_data:
            signals = target_data.get("signals", [])
            urls = []
            keywords = []
            accounts = []
            for sig in signals:
                stype = sig.get("type")
                sval = sig.get("value")
                if not sval:
                    continue
                if stype == "keyword":
                    keywords.append(sval)
                elif stype == "account":
                    accounts.append(sval)
                elif stype in ["website", "rss"]:
                    urls.append(sval)
        else:
            urls = target_data.get("urls", [])
            keywords = target_data.get("keywords", [])
            accounts = target_data.get("accounts", [])
            
        # Resolve URLs
        if urls:
            routes.extend(self._resolve_rss_routes(json.dumps(urls)))
            
        # Resolve Keywords only if use_default_osint is True (safeguarded for strict-mode news fallback)
        keyword_strategy = self.policy.get("keyword_strategy", "default")
        use_default_osint = self.policy.get("use_default_osint", True)
        if keywords and not urls and not accounts and keyword_strategy == "trusted_news_only":
            use_default_osint = True
            
        if keywords and use_default_osint:
            routes.extend(self._resolve_keyword_routes(json.dumps(keywords)))
            
        # Resolve Accounts
        if accounts:
            routes.extend(self._resolve_account_routes(json.dumps(accounts)))
            
        return routes

    def _detect_platform(self, target: str) -> str:
        target_lower = target.lower().strip()
        # Support prefixes: e.g. "bilibili:12345"
        if target_lower.startswith("bilibili:"):
            return "bilibili"
        if target_lower.startswith("twitter:") or target_lower.startswith("x:") or target_lower.startswith("x.com:"):
            return "twitter"
        if target_lower.startswith("weibo:"):
            return "weibo"
        if target_lower.startswith("instagram:"):
            return "instagram"
        if target_lower.startswith("tiktok:"):
            return "tiktok"
        if target_lower.startswith("reddit:"):
            return "reddit"

        # Support @username starting with @ -> default to twitter
        if target_lower.startswith("@"):
            return "twitter"

        # Support purely numeric inputs -> default to bilibili
        if target_lower.isdigit():
            return "bilibili"

        if "bilibili.com" in target_lower or "space.bilibili" in target_lower:
            return "bilibili"
        if "twitter.com" in target_lower or "x.com" in target_lower:
            return "twitter"
        if "instagram.com" in target_lower:
            return "instagram"
        if "reddit.com" in target_lower:
            return "reddit"
        if "weibo.com" in target_lower or "weibo.cn" in target_lower:
            return "weibo"
        if "tiktok.com" in target_lower:
            return "tiktok"
        return "unknown"

    def _parse_targets(self, target_str: str) -> list:
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
