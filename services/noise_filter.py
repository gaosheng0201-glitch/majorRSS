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


# --- A1: contentless titles ---------------------------------------------------
# The audit's most embarrassing finding: the LLM wrote summaries for three titles
# that were bare version strings with no body — "v0.14.23", "Release v5.14.0",
# "v5.13.1". A release tag alone carries no event; the actual changelog lives
# behind the link. Requires an EMPTY/near-empty body, so a real post titled
# "v5.14.0" with release notes still passes.
_VERSION_ONLY = re.compile(r"^\s*(?:release\s+)?v?\d+(?:\.\d+){1,3}(?:[-.][\w.]+)?\s*$", re.I)
_MIN_BODY_CHARS = 80


def is_contentless(title: str, content: str = "") -> bool:
    """True when the title carries no event and there is no body to make up for
    it (bare version tags, empty titles)."""
    t = (title or "").strip()
    body = (content or "").strip()
    if len(body) >= _MIN_BODY_CHARS:
        return False          # there is real content to summarize
    if not t:
        return True
    return bool(_VERSION_ONLY.match(t))


# --- A3: reddit profile subs --------------------------------------------------
# r/u_<user> are personal profile pages: no moderation, no community. Every one
# in the audit's 150-item sample was noise — but a full-corpus backtest showed
# that is NOT safe as a blanket rule: real scoops post there too ("Anthropic just
# dropped Opus 5…", "Opus 5 of Claude is Released"). Blanket-dropping them would
# have killed exactly the leak class this radar exists for.
# So a profile-sub post is dropped only when it ALSO looks like self-promotion or
# has no substance; a profile post carrying real news survives and is judged by
# the normal gates like anything else.
_PROFILE_SUB = re.compile(r"^u_", re.I)


def is_profile_sub(url: str = "") -> bool:
    """Bare structural check: is this a reddit personal-profile sub?"""
    sub = subreddit_of(url)
    return bool(sub and _PROFILE_SUB.match(sub))


def is_low_value_profile_post(title: str, content: str = "", url: str = "") -> bool:
    """A3 (guarded): profile-sub post that is ALSO self-promo or contentless.
    Never drops a profile post that carries a real story."""
    if not is_profile_sub(url):
        return False
    return is_self_launch(title, url) or is_contentless(title, content)


# --- A4: third-party self-launches --------------------------------------------
# 55% of the FEED's noise was self-promo: "I built X", "Show HN: my tool",
# "open-sourced my …" — where the tracked entity appears only as the instrument
# ("supports Claude Code", "powered by Gemini"). These pass every gate because
# they have a launch verb, a named entity and a fresh timestamp.
# GUARD (essential): only fires when the item did NOT come from the entity's own
# domain, so a genuine vendor launch post is never touched. First-party items are
# excluded by the caller via the tier check.
_SELF_LAUNCH = re.compile(
    # "I/we built|shipped|open-sourced …"
    r"\b(?:i|we)\s+(?:just\s+|finally\s+)?(?:built|made|created|launched|shipped|"
    r"released|open[- ]?sourced|wrote|developed)\b"
    # Subject-dropped headline style: "Open-sourced my tool", "Built a thing that…"
    r"|^\s*(?:just\s+)?(?:built|made|created|launched|shipped|released|"
    r"open[- ]?sourced)\s+(?:my|our|a|an|this)\b"
    r"|\bshow\s+hn\b"
    # "my app/tool/project…" anywhere — the possessive is the tell.
    r"|\b(?:my|our)\s+(?:new\s+|first\s+|latest\s+)?(?:app|tool|project|extension|"
    r"plugin|saas|startup|side[- ]project|library|package|bot|script|website)\b",
    re.I)


# A launch post that also reports a VENDOR event is not just self-promo — e.g.
# "Show HN: AI Toolbox supports Claude Opus 5" is the earliest mention of Opus 5
# some days. Full-corpus backtest found these, so the screen yields to a concrete
# vendor-news signal rather than dropping the item.
_VENDOR_EVENT = re.compile(
    r"\b(?:released?|releases|launch(?:e[sd])?|announce[sd]?|introduc(?:e[sd]|ing)|"
    r"ships?|shipped|drops?|dropped|deprecat\w*|discontinu\w*|price[sd]?|pricing|"
    r"outage|incident|down|lawsuit|sues?|sued|acquir\w*|funding|benchmark\w*|"
    r"vulnerab\w*|security|leak\w*|nerf\w*|rate.?limit\w*|supports?|"
    r"available|adds?\s+support|now\s+on)\b", re.I)
# …but only when a tracked-vendor/product token is present too, so a generic
# "I released my app" is still caught.
_VENDOR_TOKEN = re.compile(
    r"\b(?:openai|anthropic|google|deepmind|xai|mistral|meta|microsoft|nvidia|"
    r"claude|gpt|chatgpt|codex|gemini|grok|sonnet|opus|haiku|llama|sora|dall-?e)\b", re.I)


def is_self_launch(title: str, url: str = "") -> bool:
    """First-person launch/self-promo phrasing. The caller must ensure this is
    NOT applied to first-party/vendor-domain items.

    Yields when the same title also reports a concrete vendor event (a launch
    post that breaks real news is news first, self-promo second)."""
    t = title or ""
    if not _SELF_LAUNCH.search(t):
        return False
    if _VENDOR_EVENT.search(t) and _VENDOR_TOKEN.search(t):
        return False          # carries real vendor news — let the normal gates judge it
    return True


# --- A5: ambiguous keyword collisions -----------------------------------------
# "gemini" and "grok" are ordinary English/astrology/automotive words. The audit's
# long tail was dominated by them: r/tattoos (zodiac), r/crtgaming (a CRT model),
# r/programiranje (the 1.5 dCi engine designation), r/Rateme ("Grok gave me a 6").
# For these terms only, require a co-occurring lab/product token somewhere in the
# title or body — a real Gemini/Grok story practically always has one.
_AMBIGUOUS_TERMS = {"gemini", "grok"}
_DISAMBIGUATORS = (
    "google", "deepmind", "alphabet", "bard", "vertex", "aistudio", "ai studio",
    "xai", "x.ai", "musk", "openai", "anthropic", "claude", "chatgpt", "gpt",
    "llm", "model", "api", "token", "benchmark", "prompt", "ai ", " ai", "a.i.",
    "flash", "pro", "ultra", "sonnet", "opus", "colossus", "grokipedia",
    "multimodal", "inference", "context window", "fine-tun", "open source",
    "release", "launch", "update", "version", "agent", "chatbot", "assistant",
)


# --- A6: community housekeeping / recurring bot posts / job & referral spam ----
# The author observed that lead is still full of junk and that emoji titles are
# usually worthless. Measured on the corpus: 172 titles carry emoji, but emoji is
# a CORRELATE, not a cause, and using it directly would drop
# "🚨 Google has revealed the first details about Gemini 4" — an unreleased-model
# leak, exactly what the radar exists for — and "📰 TSLA: Tesla Q2 Profits Slide
# 5%", real financial news that earned a summary. Same trap as the r/u_* blanket
# rule that would have killed the Opus 5 scoops.
# So screen the CAUSES instead, each near-zero false positive:
_SUB_HOUSEKEEPING = re.compile(
    r"welcome to r/|introduce yourself|read this first|start here\b"
    r"|^\s*\[?(?:meta|mod\s*post|announcement)\]?\s*[:\]]", re.I)
# Recurring scheduled posts: a daily thread is a container, never an event.
_RECURRING_POST = re.compile(
    r"\bdaily (?:rng|prompt|thread|discussion|astrology|horoscope|chat)\b"
    r"|\b(?:daily|weekly|monthly)\s+\w+\s+thread\b"
    r"|\bhoroscope\b|\bastrology\b", re.I)
# Job boards and referral/invite farming. Deliberately NOT "apply now": measured,
# that catches vendor programme announcements ("Apply Now for Build with Gemini
# XPRIZE", "Apply Now: Google DeepMind AI for the Planet Accelerator").
_JOB_REFERRAL = re.compile(
    r"\bjobs?\s+hiring\b|\bhiring\s+(?:now|asap)\b|\bwork\s+from\s+home\b"
    r"|\bremote\s+jobs?\b|\bnow\s+hiring\b"
    r"|\breferral\s+(?:link|code)\b|\binvite\s+code\b|\buse\s+my\s+link\b"
    r"|\bgrab\s+\d+\s*[⚡🎁]", re.I)


def is_community_housekeeping(title: str, url: str = "") -> bool:
    """Subreddit meta posts, recurring scheduled threads, job/referral spam —
    structural containers with no event in them."""
    t = title or ""
    return bool(_SUB_HOUSEKEEPING.search(t) or _RECURRING_POST.search(t)
                or _JOB_REFERRAL.search(t))


def ambiguous_without_context(title: str, content: str = "") -> bool:
    """True when the item matched only because of an ambiguous term and carries
    no lab/product context — the zodiac / engine-code / CRT-television collisions."""
    text = f"{title or ''} {content or ''}".lower()
    if not any(term in text for term in _AMBIGUOUS_TERMS):
        return False          # not an ambiguous-term item; nothing to judge
    return not any(d in text for d in _DISAMBIGUATORS)
