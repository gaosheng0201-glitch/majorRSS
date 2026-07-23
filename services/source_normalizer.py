import hashlib
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from typing import List, Optional, Tuple
from db.models import RawArticle
from repositories.repository import DBRepository
from scrapers.url_normalizer import auto_route
from services.adapters import SourceItem
from services.provenance import Tier, tier_for_url

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
                    
            # 2. Keep keywords check
            if keep_keywords and not self.check_keywords_match(item.title, item.content, keep_keywords):
                filtered += 1
                continue
                
            # 3. Ignore keywords check
            if ignore_keywords and self.check_keywords_match(item.title, item.content, ignore_keywords):
                filtered += 1
                continue

            # 3b. Promotional / marketplace posts (ads, voucher resales). The
            # relevance gate can't catch these — they're topically ON-target (a
            # "Gemini Pro voucher" ad scored 0.648 vs a Gemini tracker). Screened
            # deterministically here, before any embed/fusion cost.
            if noise_filter.is_promotional(item.title, item.url):
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
