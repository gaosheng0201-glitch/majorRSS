"""Intake noise filter — deterministic, zero-cost editorial screening.

Why this exists (2026-07-23, found in live testing): the relevance gate is
TOPICAL, not editorial. A Reddit ad selling "Gemini Ai Pro vouchers" scored
relevance **0.648** against a Gemini target — far above the 0.35 threshold —
because it genuinely *is* about Gemini. Embeddings cannot separate "news about X"
from "someone selling X"; both sit in the same semantic neighbourhood. Raising
the threshold would kill real news long before it killed the ad. So the screen
has to be ORTHOGONAL to similarity: a deterministic pattern check applied at
intake, before anything is embedded or fused.

Deliberately NARROW — only two near-zero-false-positive signals:
  1. community marketplace TAGS ([OFFER] / [WTS] / [H]…[W] …)
  2. promotional SUBREDDITS (r/DiscountOffer90, r/deals, …), matched on
     tokenised name parts so "r/IdealSociety" is not caught by "deal".

Loose word matches (coupon / "30% off" / cheap) are intentionally NOT used:
"Nvidia cuts prices 30% off" is real news. Precision over recall here — a missed
ad is a minor annoyance, a dropped scoop is a product failure.
"""
import re

# Marketplace post conventions: [OFFER], (WTS), [SELLING], [GIVEAWAY] … at the
# start of a title. Near-zero false positives — these are structural tags.
_MARKET_TAG = re.compile(
    r"^\s*[\[(]\s*(offer|wts|wtb|wtt|selling|sell|for\s*sale|giveaway|promo|discount|deal)\s*[\])]",
    re.I)

# Trade posts pairing [H]ave with [W]ant, in either order.
_HAVE_WANT = re.compile(r"\[\s*h\s*\][^\[]*\[\s*w\s*\]|\[\s*w\s*\][^\[]*\[\s*h\s*\]", re.I)

_SUB_RE = re.compile(r"/r/([A-Za-z0-9_]+)", re.I)

_PROMO_WORDS = {
    "discount", "discounts", "offer", "offers", "deal", "deals",
    "coupon", "coupons", "promo", "promos", "cheap", "giveaway", "giveaways",
    "freebie", "freebies", "sale", "sales", "marketplace", "selling",
    "forsale", "flipping", "resell", "reselling",
}

# All-lowercase compound subreddit names (r/subscriptionsharing) can't be split
# by the camelCase tokenizer, so also match a few HIGH-DISTINCTIVENESS substrings.
# Only terms unlikely to appear inside an unrelated word — deliberately NOT
# "deal"/"sale"/"share" (which would hit Ideal…, wholesale, sharing-economy).
_PROMO_SUBSTRINGS = (
    "discount", "coupon", "giveaway", "forsale", "cheap", "promo",
    "subscriptionsharing", "accountsharing", "sharingaccount",
    "subscriptionshare", "accountshare",
)


def subreddit_of(url: str):
    m = _SUB_RE.search(url or "")
    return m.group(1) if m else None


def _sub_tokens(sub: str):
    """Split a subreddit name into words on camelCase / digits / underscores, so
    'DiscountOffer90' -> {discount, offer} but 'IdealSociety' -> {ideal, society}
    (i.e. 'deal' inside 'Ideal' does NOT match)."""
    parts = re.split(r"[_\d]+|(?<=[a-z])(?=[A-Z])", sub or "")
    return [p.lower() for p in parts if p]


def is_promotional(title: str, url: str = "") -> bool:
    """True for marketplace / promo posts: topically relevant, zero intelligence
    value (voucher resales, giveaways, ads)."""
    t = title or ""
    if _MARKET_TAG.search(t) or _HAVE_WANT.search(t):
        return True
    sub = subreddit_of(url)
    if sub:
        if any(tok in _PROMO_WORDS for tok in _sub_tokens(sub)):
            return True
        low = sub.lower()
        if any(s in low for s in _PROMO_SUBSTRINGS):
            return True
    return False
