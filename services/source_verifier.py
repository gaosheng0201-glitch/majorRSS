"""Existence checks for planner-suggested sources (P4.0c guard).

The planner names sources it believes exist; models invent URLs, handles and
subreddits with total confidence. Nothing a model suggested reaches the
runtime until it answered here — a suggestion that fails stays visible in the
proposal card (unchecked) so the user can overrule, but is never auto-selected.

Checks are positive-proof only: a 429, a timeout or an anti-bot page all mean
"unknown", which is recorded as unverified, never as "dead".

X handles are checked through FxTwitter's public profile endpoint — it needs
no X account (measured alive 2026-08-26 while every nitter mirror was gone),
and a profile lookup is not timeline scraping, so the X-side C&D that killed
nitter has no bearing on it.
"""
import concurrent.futures
from typing import List

import feedparser
import requests

from services.http_client import DEFAULT_UA

TIMEOUT_SECONDS = 6
_HEADERS = {"User-Agent": DEFAULT_UA, "Accept": "*/*"}


def _get(url: str) -> requests.Response:
    return requests.get(url, headers=_HEADERS, timeout=TIMEOUT_SECONDS, allow_redirects=True)


def _rss_alive(url: str) -> bool:
    r = _get(url)
    if r.status_code != 200:
        return False
    fp = feedparser.parse(r.content)
    return bool(fp.entries) or bool(getattr(fp.feed, "title", ""))


def _page_alive(url: str) -> bool:
    r = _get(url)
    return r.status_code == 200 and len(r.content) > 500


def _twitter_handle_alive(handle: str) -> bool:
    r = _get(f"https://api.fxtwitter.com/{handle}")
    if r.status_code != 200:
        return False
    try:
        return r.json().get("code") == 200
    except Exception:
        return False


def _subreddit_alive(name: str) -> bool:
    r = _get(f"https://www.reddit.com/r/{name}/new.rss")
    return r.status_code == 200 and bool(feedparser.parse(r.content).entries)


def verify_one(s: dict) -> bool:
    kind = (s.get("kind") or "").lower()
    value = (s.get("value") or "").strip()
    if not value:
        return False
    try:
        if kind == "rss":
            return _rss_alive(value)
        if kind in ("page_monitor", "registry"):
            return _page_alive(value)
        if kind == "account":
            if (s.get("platform") or "twitter").lower() in ("twitter", "x"):
                return _twitter_handle_alive(value)
            return False            # no account-free probe for other platforms
        if kind == "subreddit":
            return _subreddit_alive(value)
    except Exception:
        return False
    return False


def verify_suggestions(suggestions: List[dict], max_workers: int = 6) -> List[dict]:
    """Run existence checks in parallel; stamp `verified` and default
    `selected` = verified. Returns the same dicts, mutated and in order."""
    if not suggestions:
        return suggestions
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(verify_one, suggestions))
    for s, ok in zip(suggestions, results):
        s["verified"] = bool(ok)
        s["selected"] = bool(ok)
    return suggestions
