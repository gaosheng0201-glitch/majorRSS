import hashlib
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from typing import List, Optional, Tuple
from db.models import RawArticle
from repositories.repository import DBRepository
from scrapers.url_normalizer import auto_route
from services.adapters import SourceItem
from services.provenance import Tier, tier_for_url, HIGH_WEIGHT, is_untrusted_code_host_path

class SourceNormalizer:
    def __init__(self):
        self.db = DBRepository()

    def clean_html(self, html_content: str) -> str:
        if not html_content:
            return ""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            # Extract script, style, iframe, link, meta, embed, object
            for element in soup(["script", "style", "iframe", "link", "meta", "embed", "object"]):
                element.extract()
            # Return cleaned HTML
            return str(soup)
        except Exception:
            return html_content

    def check_keywords_match(self, title: str, content: str, keywords: List[str]) -> bool:
        if not keywords:
            return True
        text = f"{title} {content}".lower()
        return any(kw.lower() in text for kw in keywords)

    def normalize_and_save(
        self, 
        items: List[SourceItem], 
        tracker_id: int, 
        max_days: int = 7,
        keep_keywords: Optional[List[str]] = None,
        ignore_keywords: Optional[List[str]] = None
    ) -> Tuple[int, int, int]:
        """
        Normalizes and persists raw articles.
        Returns:
            Tuple[int, int, int]: (saved_count, duplicate_count, filtered_count)
        """
        saved = 0
        duplicates = 0
        filtered = 0

        now = datetime.now(timezone.utc)

        # P0.5 near-duplicate pre-filter: recent titles for this tracker + titles
        # accepted earlier in this batch, so near-verbatim re-syndication is
        # dropped before it costs an embed + fusion. Identity-guarded (see dedup).
        from services import dedup, noise_filter
        recent_titles = self.db.get_recent_titles(tracker_id)
        batch_titles = []

        for item in items:
            # 1. Age check
            if max_days > 0 and item.published_at:
                age = now - item.published_at
                if age.days > max_days:
                    filtered += 1
                    continue
                    
            # 2. Keep keywords — AGGREGATOR ONLY (B5).
            # keep_keywords exists to narrow a keyword firehose, where the source
            # carries no trust of its own. Applying it to a source the user
            # deliberately picked inverts its purpose: measured on the live DB,
            # 21 of 39 curated presets had ZERO articles despite 510 successful
            # fetches each — arXiv (340 fresh papers/day), Hugging Face, Cloudflare
            # and Anthropic Status were all dropped here because an official post
            # rarely repeats the vendor's own brand name in its title, while
            # gnews/reddit items always match (the keyword was in the query). That
            # single asymmetry is a large part of why 94% of the corpus came from
            # aggregators. Curated/first-party sources are trusted wholesale; the
            # junk floor and the fusion gate remain their quality control.
            _item_tier = tier_for_url(item.url, item.tier or Tier.CURATED)
            if keep_keywords and _item_tier not in HIGH_WEIGHT and \
                    not self.check_keywords_match(item.title, item.content, keep_keywords):
                filtered += 1
                continue
                
            # 3. Ignore keywords check
            if ignore_keywords and self.check_keywords_match(item.title, item.content, ignore_keywords):
                filtered += 1
                continue

            # 3b. Editorial screens (A1–A5). All deterministic and zero-cost, run
            # before any embed/fusion spend. The relevance gate cannot catch these
            # — they are topically ON-target (the "Gemini Pro voucher" ad scored
            # 0.648 against a Gemini tracker).
            #
            # TIER-SCOPED: aggregator items only. A source the user hand-picked is
            # trusted wholesale — a vendor's own "we built X" post is a real
            # launch, and a curated feed's release tag may be exactly what they
            # asked to watch. Only the keyword firehose gets screened.
            # Code-host user content (a github repo that is not a release, a HF
            # model card) is screened even though it lands in CURATED: it arrived
            # via an aggregator and is published by anyone, so it did not earn the
            # "the user picked this source" exemption. Measured: 20 "Show HN: my
            # side project" posts were inheriting github.com's first-party trust
            # and skipping every screen.
            _screened = _item_tier not in HIGH_WEIGHT or is_untrusted_code_host_path(item.url)
            if _screened:
                if noise_filter.is_promotional(item.title, item.url):
                    filtered += 1
                    continue
                # A1: bare version tags / empty titles with no body to summarize.
                if noise_filter.is_contentless(item.title, item.content):
                    filtered += 1
                    continue
                # A3: r/u_* profile posts that are ALSO self-promo/contentless.
                # (A blanket profile-sub drop was measured to kill real Opus 5
                # scoops, so the screen is guarded — see noise_filter.)
                if noise_filter.is_low_value_profile_post(item.title, item.content, item.url):
                    filtered += 1
                    continue
                # A4: third-party self-launches ("I built X that uses Claude").
                if noise_filter.is_self_launch(item.title, item.url):
                    filtered += 1
                    continue
                # A5: ambiguous-term collisions (zodiac Gemini, the dCi Grok engine).
                if noise_filter.ambiguous_without_context(item.title, item.content):
                    filtered += 1
                    continue
                # A6: subreddit meta posts, recurring bot threads, job/referral spam.
                if noise_filter.is_community_housekeeping(item.title, item.url):
                    filtered += 1
                    continue
                
            # 3. Canonicalize URL
            canonical_url = auto_route(item.url)
            
            # 4. Clean content
            cleaned_content = self.clean_html(item.content)
            
            # 5. Fingerprint (deduplication)
            # Use provided fingerprint or generate from URL
            content_hash = item.fingerprint or hashlib.md5(canonical_url.encode('utf-8')).hexdigest()
            
            # Check db for duplicate URL or title
            if self.db.check_url_exists(canonical_url) or self.db.check_title_exists(tracker_id, item.title):
                duplicates += 1
                continue

            # P0.5: near-verbatim re-syndication (same headline across outlets),
            # identity-guarded so serial/versioned siblings are NOT collapsed.
            if any(dedup.is_near_duplicate(item.title, t) for t in recent_titles) or \
               any(dedup.is_near_duplicate(item.title, t) for t in batch_titles):
                duplicates += 1
                continue
            batch_titles.append(item.title)

            # Provenance tier (docs/source_tiering.md): the route stamped a base
            # tier on the item; refine it by the actual article URL so an opt-in
            # source whose article sits on a first-party domain becomes PRIMARY.
            # AGGREGATED (keyword firehose) never upgrades.
            source_tier = tier_for_url(canonical_url, item.tier or Tier.CURATED)

            # Create RawArticle
            article = RawArticle(
                tracker_id=tracker_id,
                title=item.title,
                url=canonical_url,
                content=cleaned_content,
                published_at=item.published_at.replace(tzinfo=None) if item.published_at else None,
                processed=False,
                source_tier=source_tier,
            )
            
            # Save
            if self.db.save_raw_article(article):
                saved += 1
            else:
                duplicates += 1
                
        return saved, duplicates, filtered
