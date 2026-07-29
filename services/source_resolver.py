import json
import urllib.parse
from dataclasses import dataclass
from typing import List, Optional

from services.provenance import Tier

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
    # Provenance tier (docs/source_tiering.md). Default CURATED (user opted-in:
    # direct URLs, tracked accounts, portfolio presets); keyword firehoses stamp
    # AGGREGATED. The normalizer refines CURATED→PRIMARY by the item's URL.
    tier: str = Tier.CURATED
    # This route exists because the user NAMED an account (the people radar).
    # Only the resolver knows this; by consumption time the URL is all that is
    # left, and a URL cannot tell "an account we follow" from "a link to one".
    is_account: bool = False

# Google News serves a per-EDITION index. Without hl/gl/ceid it answers from the
# en-US edition, so a non-English query returns English articles or — combined
# with the `when:Nd` operator — nothing at all. Measured 2026-07-29:
#   "渐冻症 when:7d"  no locale → 0 items    with locale → 41 Chinese items
#   "渐冻症"          no locale → 7 ENGLISH  with locale → 100 Chinese items
#   "大谷翔平"         no locale → 100 ENGLISH results
# That made keyword discovery structurally English-only: a Chinese/Japanese/
# Korean topic silently produced nothing or off-language coverage. The edition is
# derived from the query's script, so it needs no configuration.
_CJK_EDITIONS = (
    # (test, hl, gl, ceid)
    (lambda ch: "぀" <= ch <= "ヿ", "ja", "JP", "JP:ja"),          # kana → Japanese
    (lambda ch: "가" <= ch <= "힯", "ko", "KR", "KR:ko"),          # hangul → Korean
    (lambda ch: "一" <= ch <= "鿿", "zh-CN", "CN", "CN:zh-Hans"),  # han → Chinese
)


def gnews_locale_params(query: str) -> str:
    """Google News edition parameters for a query, derived from its script.
    Returns '' for Latin text (the default en-US edition is already right)."""
    text = query or ""
    # Kana/Hangul are decisive; Han alone means Chinese (Japanese text almost
    # always carries kana too, so it is checked first).
    for test, hl, gl, ceid in _CJK_EDITIONS:
        if any(test(ch) for ch in text):
            return f"&hl={hl}&gl={gl}&ceid={ceid}"
    return ""


def _twitter_account_routes(handle: str, id_prefix: str, auth_profile_id=None,
                            base_priority: int = 1) -> List[SourceRoute]:
    """Fallback chain for one X/Twitter account, shared by keyword-derived and
    preset account sources (B3/B4).

    Tier order is set by what actually works (verified 2026-07-28):
      1. nitter.net RSS — free, no credentials, all 7 tracked accounts returned
         content. NOTE: it answers 200 with an EMPTY body for script user-agents
         and under rate limiting, which the freshness assertion (B1) now records
         as a failure instead of "no news today", so the next tier gets a turn.
      2. RSSHub — the PUBLIC instance disabled its twitter route permanently
         (302 → google.com/404), so this tier only pays off with a self-hosted
         RSSHUB_URL; kept because that is a supported deployment.
      3. Agentic snapshot — needs an authorized session; platform is "twitter"
         (not "rsshub") so _enrich_routes_with_auth can actually attach one.
    """
    return [
        SourceRoute(route_id=f"nitter_{id_prefix}", adapter="RssAdapter",
                    url_or_command=f"https://nitter.net/{handle}/rss",
                    purpose="discovery", requires_auth=False, platform="twitter",
                    priority=base_priority, tier=Tier.CURATED, is_account=True),
        SourceRoute(route_id=f"rsshub_{id_prefix}", adapter="RssHubAdapter",
                    url_or_command=f"rsshub:/twitter/user/{handle}",
                    purpose="discovery", requires_auth=False, platform="twitter",
                    priority=base_priority + 1, tier=Tier.CURATED, is_account=True),
        SourceRoute(route_id=f"agentic_{id_prefix}", adapter="AgenticAdapter",
                    url_or_command=f"https://x.com/{handle}",
                    purpose="snapshot", requires_auth=auth_profile_id is not None,
                    platform="twitter", priority=base_priority + 2, tier=Tier.CURATED,
                    is_account=True),
    ]


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
                routes = self._append_portfolio_routes(routes)
                routes = self._apply_budget(routes)
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

        # Watch Target portfolio: expand selected preset collections into routes
        # (the planner's source_scope), then cap by the per-target budget.
        routes = self._append_portfolio_routes(routes)
        routes = self._apply_budget(routes)
        self._enrich_routes_with_auth(routes)
        return routes

    def _append_portfolio_routes(self, routes: List[SourceRoute]) -> List[SourceRoute]:
        """Turn the fetch_policy's source_scope (preset collection ids) into
        routes from the curated preset library. This is how a planned portfolio
        actually executes. No-op when no source_scope is set."""
        scope = self.policy.get("source_scope") or []
        if not scope:
            return routes
        try:
            from db.database import get_session
            from db.models import SourcePresetCollectionItem, SourcePreset
            from sqlmodel import select
            existing_urls = {r.url_or_command for r in routes}
            added = []
            with get_session() as session:
                preset_ids = []
                for cid in scope:
                    items = session.exec(
                        select(SourcePresetCollectionItem)
                        .where(SourcePresetCollectionItem.collection_id == cid)
                        .order_by(SourcePresetCollectionItem.sort_order)
                    ).all()
                    preset_ids.extend(it.preset_id for it in items)
                # Preserve order, dedup.
                seen = set()
                for pid in preset_ids:
                    if pid in seen:
                        continue
                    seen.add(pid)
                    preset = session.exec(select(SourcePreset).where(SourcePreset.preset_id == pid)).first()
                    if not preset or not preset.url or preset.url in existing_urls:
                        continue
                    stype = (preset.source_type or "rss").lower()
                    url = preset.url
                    if stype == "account":
                        # A social account (e.g. https://x.com/sama) can't be parsed
                        # as RSS — the raw profile page is HTML.
                        handle = url.rstrip("/").split("/")[-1]
                        low = url.lower()
                        if "x.com" in low or "twitter.com" in low:
                            # X accounts get the SAME 3-tier fallback chain as
                            # keyword-derived account routes (B3/B4). Previously a
                            # preset account was locked to the single rsshub route
                            # with platform="rsshub" — which meant (a) no fallback
                            # when that instance died, and (b) _enrich_routes_with_auth
                            # never matched a twitter AuthProfile, so an authorized
                            # session could never be used. Measured effect: all 7
                            # tracked people-radar accounts, 0 successes ever, while
                            # rsshub.app's twitter route is permanently disabled
                            # (302 → google.com/404).
                            for r in _twitter_account_routes(handle, f"preset_{pid}",
                                                             self.auth_profile_id, base_priority=5):
                                if r.url_or_command not in existing_urls:
                                    added.append(r)
                                    existing_urls.add(r.url_or_command)
                            existing_urls.add(preset.url)
                            continue
                        adapter, platform = "AgenticAdapter", "web"
                    elif stype == "rsshub" or url.startswith("rsshub:"):
                        adapter, platform = "RssHubAdapter", "rsshub"
                    elif stype in ("web", "webpage", "html"):
                        adapter, platform = "AgenticAdapter", "web"
                    else:
                        adapter, platform = "RssAdapter", "rss"
                    added.append(SourceRoute(
                        route_id=f"preset_{pid}",
                        adapter=adapter,
                        url_or_command=url,
                        purpose="discovery",
                        requires_auth=False,
                        platform=platform,
                        # Lower priority band than a target's own routes (1-3) so
                        # the budget cap keeps the user's explicit sources +
                        # their fallbacks before tangential portfolio presets.
                        priority=5,
                    ))
                    existing_urls.add(preset.url)
            return routes + added
        except Exception as e:
            # Portfolio expansion must never break base resolution.
            print(f"[SourceResolver] Portfolio expansion failed: {e}")
            return routes

    def _apply_budget(self, routes: List[SourceRoute]) -> List[SourceRoute]:
        """Cap the number of sources fetched per run (per-target budget). 0/None
        = unlimited. Keeps lower-priority routes as fallback ordering intact."""
        cap = self.policy.get("max_sources_per_run", 0) or 0
        if cap and len(routes) > cap:
            # Stable sort by priority so the cap keeps the best routes.
            ordered = sorted(routes, key=lambda r: r.priority)
            return ordered[:cap]
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
        
        # Source-level date window for the ONLY search route that pulls a wide
        # historical window: Google News. Google News search supports `when:Nd`,
        # so limit the query to the target's lookback window (max_days) instead of
        # fetching everything and age-gating after download (愿景 line 87: 源头拦截
        # 优于抓后过滤). This is the target's configured backfill window, not the
        # poll interval. HN/Reddit are `newest`/`sort=new` (already latest-N,
        # naturally bounded) and standard RSS feeds have no query date param, so
        # the post-fetch age gate stays the right mechanism for those.
        try:
            max_days = int(self.policy.get("max_days", 7) or 0)
        except Exception:
            max_days = 7

        for idx, kw in enumerate(keywords):
            encoded_kw = urllib.parse.quote(kw)
            gnews_q = f"{kw} when:{max_days}d" if max_days > 0 else kw
            gnews_encoded = urllib.parse.quote(gnews_q)

            # Default includes Google News, HN, and Reddit
            # trusted_news_only only includes Google News (and curated feeds when defined)
            if strategy in ["default", "news_only", "tech_sources", "trusted_news_only"]:
                routes.append(SourceRoute(
                    route_id=f"gnews_{idx}",
                    adapter="RssAdapter",
                    url_or_command=(f"https://news.google.com/rss/search?q={gnews_encoded}"
                                    f"{gnews_locale_params(kw)}"),
                    purpose="discovery",
                    requires_auth=False,
                    platform="gnews",
                    priority=1,
                    tier=Tier.AGGREGATED,
                ))
            if strategy in ["default", "tech_sources"]:
                routes.append(SourceRoute(
                    route_id=f"hn_{idx}",
                    adapter="RssAdapter",
                    url_or_command=f"https://hnrss.org/newest?q={encoded_kw}",
                    purpose="discovery",
                    requires_auth=False,
                    platform="hackernews",
                    priority=1,
                    tier=Tier.AGGREGATED,
                ))
            if strategy in ["default", "social_forum"]:  # noqa: E501 (loop continues below)
                routes.append(SourceRoute(
                    route_id=f"reddit_{idx}",
                    adapter="RssAdapter",
                    url_or_command=f"https://www.reddit.com/search.rss?q={encoded_kw}&sort=new",
                    purpose="discovery",
                    requires_auth=False,
                    platform="reddit",
                    priority=1,
                    tier=Tier.AGGREGATED,
                ))

        # Cross-language coverage (愿景 语言三原则, 2026-07-05 — wired 2026-07-29).
        # The portfolio planner has always expanded a target into MULTILINGUAL
        # entity aliases, but they were dropped before reaching the resolver, so a
        # topic was only ever searched in the user's own wording. Principle ①: the
        # entity profile is language-independent and the input language decides
        # only the narration, never the search scope — a topic's source geography
        # is a property of the TOPIC (Apple Siri = EN first-party + ja supply chain
        # + zh leaks). Principle ②: queries are generated per SOURCE language via
        # Google News hl/gl editions. Principle ③: this is purely ADDITIVE — the
        # user's own keywords always keep their routes.
        # One route per edition (aliases of the same edition are OR-ed), so this
        # adds at most a couple of routes however many aliases there are.
        aliases = [a for a in (self.policy.get("entities") or []) if a and a.strip()]
        if aliases and strategy in ["default", "news_only", "tech_sources", "trusted_news_only"]:
            covered = {gnews_locale_params(k) for k in keywords}
            by_edition = {}
            for a in aliases:
                loc = gnews_locale_params(a)
                if loc in covered:
                    continue          # that edition is already queried
                by_edition.setdefault(loc, []).append(a.strip())
            for i, (loc, terms) in enumerate(by_edition.items()):
                q = " OR ".join(f'"{t}"' for t in terms[:6])
                if max_days > 0:
                    q = f"{q} when:{max_days}d"
                routes.append(SourceRoute(
                    route_id=f"gnews_xlang_{i}",
                    adapter="RssAdapter",
                    url_or_command=(f"https://news.google.com/rss/search?"
                                    f"q={urllib.parse.quote(q)}{loc}"),
                    purpose="discovery",
                    requires_auth=False,
                    platform="gnews",
                    priority=2,       # after the user's own keywords
                    tier=Tier.AGGREGATED,
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
                # Shared 3-tier chain (nitter → rsshub → authorized agentic).
                routes.extend(_twitter_account_routes(
                    account_name, f"twitter_{idx}", self.auth_profile_id, base_priority=1))
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
        # Every route from here is an account the user named, whatever platform
        # it landed on. Stamped once at the exit rather than at each construction
        # site, so a new platform branch cannot silently forget it.
        for r in routes:
            r.is_account = True
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
