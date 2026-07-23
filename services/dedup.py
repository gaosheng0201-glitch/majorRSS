"""P0.5 — cheap deterministic near-duplicate pre-filter at intake.

Catches near-verbatim re-syndication (the same headline across outlets) so it
doesn't cost an embed + fusion, WITHOUT over-merging serial/versioned content —
the failure mode the 2026-07-23 audit found (monthly "Developer Update - July/
May/April", "anthropic-sdk v0.117.1" vs ".0", degenerate "ChatGPT"). The audit's
decisive finding: the over-merge control is NOT the similarity threshold but an
IDENTITY GUARD — block a title merge whenever the titles' differing tokens carry
a version tag or a date/period, or a title is too short to trust on its own.

~3-4% of volume: a safety net, not a cost lever (the real dedup is the vector
layer, which merges same-event-different-wording that lexical methods can't).
See docs/radar_quality_roadmap.md P0.5.
"""
import re

_PUB_SUFFIX = re.compile(r"\s+[-|–—]\s+[^-|–—]{2,40}$")   # trailing " - Publisher"
_WS = re.compile(r"\s+")
_NONWORD = re.compile(r"[^\w一-鿿]+", re.UNICODE)
_VERSION = re.compile(r"v?\d+(?:\.\d+)+")   # full version: v0.117.1, 1.26.07, 3.6
_DATEISH = re.compile(
    r"\b(?:20\d\d|q[1-4]|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|"
    r"january|february|march|april|june|july|august|september|october|november|december)\b|"
    r"\d{1,2}月|\d{4}年", re.I)
_MIN_TOKENS = 3
# Audit-verified safe config: exact normalized-title ∪ Jaccard ≥ 0.8, with the
# identity guard doing the over-merge control (NOT the threshold). See P0.5.
NEAR_DUP_THRESHOLD = 0.8


def normalize_title(t: str) -> str:
    """Lower-case, drop the trailing ' - Publisher' aggregator suffix, strip
    punctuation. Two outlets' copies of one headline collapse to the same string."""
    t = (t or "").lower().strip()
    t = _PUB_SUFFIX.sub("", t)
    t = _NONWORD.sub(" ", t)
    return _WS.sub(" ", t).strip()


def _tokens(t: str):
    return [w for w in normalize_title(t).split() if len(w) > 1]


def _jaccard(a, b) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _signal_tokens(title: str):
    """Version + date/period tokens in the RAW title (before the ' - Publisher'
    suffix is stripped), so a distinguishing 'July' / 'v0.117.1' isn't lost."""
    t = (title or "").lower()
    return set(m.group(0) for m in _VERSION.finditer(t)) | \
           set(m.group(0) for m in _DATEISH.finditer(t))


def _guard_blocks(title_a: str, title_b: str, ta, tb) -> bool:
    """A distinguishing signal says these are DIFFERENT items despite similar
    titles → do not merge (the audit's over-merge classes)."""
    if len(ta) < _MIN_TOKENS or len(tb) < _MIN_TOKENS:
        return True                                   # degenerate — don't merge on title alone
    if _signal_tokens(title_a) != _signal_tokens(title_b):
        return True                                   # differ by version / date → serial siblings
    return False


def is_near_duplicate(title_a: str, title_b: str, threshold: float = NEAR_DUP_THRESHOLD) -> bool:
    """Safe near-duplicate? True only when the titles are near-verbatim AND no
    version/date/degeneracy signal distinguishes them (identity guard)."""
    na, nb = normalize_title(title_a), normalize_title(title_b)
    if not na or not nb:
        return False
    ta, tb = _tokens(title_a), _tokens(title_b)
    if na != nb and _jaccard(ta, tb) < threshold:
        return False
    return not _guard_blocks(title_a, title_b, ta, tb)
