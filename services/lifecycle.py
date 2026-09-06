"""The one place a thread's lifecycle is decided.

LEAD → CORROBORATED (≥2 independent publishers) → CONFIRMED (a member carries
the PRIMARY intake stamp). The rule used to be written inline at every site
that could change a lifecycle — thread birth, member join, provenance
promotion, a corrective migration — and the sites drifted: birth consulted the
URL floor while join read the stamp, so a keyword catch on arxiv.org was born
"confirmed" (150 threads, all paid for). Provenance is decided ONCE at intake
(docs/source_tiering.md §2); lifecycle is decided ONCE here, from stamps.
"""
from typing import Iterable, Optional

RANK = {"LEAD": 0, "CORROBORATED": 1, "CONFIRMED": 2}


def lifecycle_for(member_tiers: Iterable[Optional[str]], distinct_sources: int,
                  current: Optional[str] = None) -> str:
    """Lifecycle earned by a thread whose members carry `member_tiers` and
    which counts `distinct_sources` independent publishers. With `current`,
    the running pipeline never demotes (corrections are migrations)."""
    tiers = list(member_tiers)
    if any(t == "primary" for t in tiers):
        computed = "CONFIRMED"
    elif (distinct_sources or 0) >= 2:
        computed = "CORROBORATED"
    else:
        computed = "LEAD"
    if current and RANK.get(current, 0) > RANK[computed]:
        return current
    return computed
