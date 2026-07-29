"""Source provenance — the shared "where did this come from / how much do we
trust it" layer (docs/source_tiering.md). Public infrastructure: radar fusion,
feed, publish, scoring and feedback all read it. Two orthogonal facets:

  - Tier (trust): PRIMARY / CURATED / AGGREGATED — stamped at intake by the
    resolver (route-derived, lossless). Consumed by the fusion gate, scoring,
    feedback. "Capture now, weight-application later" (source_tiering.md §2).

  - real_publisher(): the actual outlet behind an aggregator link. Google News
    redirects all collapse to news.google.com, so counting distinct URL domains
    made distinct_source_count ≡ 1 for every gnews-heavy thread — corroboration
    / resonance / lifecycle all died (P0.4). The real publisher is the
    " - Publisher" suffix Google News appends to the title.

This module is the single home for first-party detection too, so semantic_ingest
and publish_service stop each re-deriving it from a private copy.
"""
import re
import urllib.parse


class Tier:
    PRIMARY = "primary"        # first-party: the subject's own official channel
    CURATED = "curated"        # user opted-in: portfolio presets, tracked accounts, direct URLs
    AGGREGATED = "aggregated"  # keyword firehose: Google News / Reddit / HN search


# PRIMARY|CURATED never get channel-gated (opt-in is itself a signal); AGGREGATED
# must earn a summary via resonance / corroboration. See radar_quality_roadmap P1.1.
HIGH_WEIGHT = (Tier.PRIMARY, Tier.CURATED)


# First-party / authoritative source patterns → PRIMARY tier + lifecycle CONFIRMED.
# Heuristic baseline: official primary sources (gov, standards, code, papers,
# vendor newsrooms). R4's portfolio planner can later supply each target's own
# official domains for precise detection; this is the floor.
_FIRST_PARTY_SUFFIXES = (".gov", ".gov.cn", ".mil", ".edu")
_FIRST_PARTY_DOMAINS = (
    "arxiv.org", "github.com", "github.io", "openai.com", "anthropic.com",
    "blog.google", "ai.googleblog.com", "developer.apple.com", "apple.com",
    "microsoft.com", "nvidia.com", "sec.gov", "fda.gov", "who.int",
    "clinicaltrials.gov", "europa.eu",
)

# Aggregator / meta-search domains: many real outlets hide behind one domain, so
# the domain is NOT a publisher identity for corroboration counting.
_AGGREGATOR_DOMAINS = ("news.google.com", "reddit.com", "ycombinator", "hnrss")

# Google News appends " - Publisher" to the item title; capture the last such
# segment (no dashes inside, sane length) as the real outlet.
_GNEWS_TITLE_PUB = re.compile(r"\s[\-–—]\s([^\-–—]{2,60})$")


def domain(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return (url or "").lower()


# Paths on an otherwise first-party domain that are MARKETING, not announcements.
# PRIMARY tier bypasses the fusion gate unconditionally, so without this the
# vendor's own comms team spends the trust the domain earned: the content audit
# found customer stories and op-eds on openai.com getting the same paid treatment
# as a model launch. These paths stay CURATED — still trusted, still exempt from
# keyword filtering, but they must earn a summary like any other curated source.
_MARKETING_PATH_MARKERS = (
    "/customer-stories", "/customers/", "/case-stud", "/testimonial",
    "/global-affairs", "/policy/", "/opinion", "/editorial",
    "/careers", "/jobs", "/events/", "/webinar", "/pricing",
)


def is_marketing_path(url: str) -> bool:
    """True for vendor-domain URLs that are marketing/PR rather than product or
    research announcements (see _MARKETING_PATH_MARKERS)."""
    try:
        path = urllib.parse.urlparse(url or "").path.lower()
    except Exception:
        path = (url or "").lower()
    return any(m in path for m in _MARKETING_PATH_MARKERS)


# github.com hosts BOTH official vendor releases and anything any user pushes.
# Trusting the whole domain let 20 "Show HN: my side project" posts inherit
# PRIMARY and skip the editorial screens entirely (measured). Only release and
# changelog paths are first-party; everything else is ordinary user content and
# must earn its place like any other aggregator item.
_CODE_HOST_DOMAINS = ("github.com", "github.io", "gitlab.com", "huggingface.co")
_CODE_HOST_OFFICIAL_PATHS = ("/releases", "/tags", "/changelog", "/blog", "/security/advisories")


def is_untrusted_code_host_path(url: str) -> bool:
    """True for a code-hosting URL that is NOT a release/changelog — i.e. ordinary
    user-published content that should not inherit the domain's first-party trust."""
    d = domain(url)
    if not any(d == h or d.endswith("." + h) for h in _CODE_HOST_DOMAINS):
        return False
    try:
        path = urllib.parse.urlparse(url or "").path.lower()
    except Exception:
        path = (url or "").lower()
    return not any(p in path for p in _CODE_HOST_OFFICIAL_PATHS)


def is_first_party(url: str) -> bool:
    d = domain(url)
    if any(d.endswith(sfx) for sfx in _FIRST_PARTY_SUFFIXES):
        return True
    return any(d == fp or d.endswith("." + fp) for fp in _FIRST_PARTY_DOMAINS)


def tier_for_url(url: str, base: str) -> str:
    """Final tier for an item: refine a route's base tier by the item's own URL.
    An opt-in source (CURATED base) whose article sits on a first-party domain is
    PRIMARY. AGGREGATED never upgrades — a keyword-search hit that happens to
    point at a vendor domain is still a firehose catch, not a curated source.
    Marketing paths on a first-party domain stay CURATED (B6): domain-level trust
    should not be spendable by the vendor's marketing team."""
    if base == Tier.AGGREGATED:
        return Tier.AGGREGATED
    if is_first_party(url) and not is_marketing_path(url) \
            and not is_untrusted_code_host_path(url):
        return Tier.PRIMARY
    return Tier.CURATED


def real_publisher(url: str, title: str = "") -> str:
    """Outlet identity key for corroboration counting. Google News links share
    news.google.com — the real publisher is the title's ' - Publisher' suffix.
    Reddit / HN are single platforms (one source, not N). Everything else keys on
    its own domain. Lower-cased so the same outlet collapses to one key."""
    d = domain(url)
    if "news.google.com" in d:
        m = _GNEWS_TITLE_PUB.search(title or "")
        return (m.group(1).strip().lower() if m else "news.google.com")
    if "reddit.com" in d:
        return "reddit.com"
    if "ycombinator" in d or "hnrss" in d:
        return "news.ycombinator.com"
    return d or "unknown"
