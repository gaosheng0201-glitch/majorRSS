"""
Semantic vector operations (R3) — the layer that turns an aggregator into a
radar. Relevance, dedup and thread clustering all run on embeddings, so most
content never reaches a generation model (愿景 token 经济 + 减噪核心).

Engine-agnostic brute-force cosine by default: a personal radar holds at most a
few tens of thousands of vectors, well within numpy/pure-python millisecond
range, and it works identically on SQLite and Postgres. pgvector / sqlite-vec
are optional accelerations layered on later, never required.

All functions are pure math over lists of floats — fully deterministic and
unit-testable with synthetic vectors (including the multilingual same-event
case, where a multilingual embedder places zh/en/ja reports of one event close
together → one thread).
"""
import math
from typing import List, Optional, Tuple

# Tuning knobs (cosine similarity, 0..1 for normalized vectors).
DEFAULT_RELEVANCE_THRESHOLD = 0.35   # raw-space (bag-of-words fallback embedder)
# With a real embedder the relevance check MUST run in the mean-centered space,
# same as clustering — in raw space every AI headline scores 0.48–0.72 against an
# AI profile, so 0.35 gated NOTHING (measured: 0/1590 articles, the gate was
# dead). This is a JUNK FLOOR, not a signal selector: calibration (2026-07-23,
# 21 known-noise / 64 known-signal items) put known signal at 0.066+ centered
# ("Musk's xAI sues…" 0.066, "Gemini 3.6 Flash available" 0.086) and clear junk
# at −0.04…0.05 ("Claude refuses revising my email", device-help posts). 0.05
# gates 156/1614 unambiguous off-topic items with ZERO measured signal loss;
# anything more aggressive (0.07+) starts eating real scoops. Editorial
# discrimination beyond this floor is P5's job, not a cosine threshold's.
RELEVANCE_THRESHOLD_CENTERED = 0.05
DEFAULT_DUPLICATE_THRESHOLD = 0.90

# Thread clustering runs in a MEAN-CENTERED space when a corpus mean is set (see
# set_corpus_mean). Real embedding models are anisotropic — every same-entity
# headline collapses into a narrow cone (raw cosine 0.6–0.9 for unrelated AI
# news), so a raw-cosine threshold over-merges distinct events into one giant
# thread. Subtracting the corpus mean removes that common component and spreads
# events apart (measured: same-event ≈0.33 vs different-event ≈-0.16), which
# needs a much lower threshold. The raw threshold is kept for the bag-of-words
# fallback embedder (no mean set), where centering doesn't apply.
THREAD_THRESHOLD_RAW = 0.62
THREAD_THRESHOLD_CENTERED = 0.18
DEFAULT_THREAD_THRESHOLD = THREAD_THRESHOLD_RAW  # back-compat for callers/tests

# Candidate floor for LLM-arbitrated clustering (centered space). In the
# mean-centered space, same-event pairs — INCLUDING cross-language (zh/en/ja)
# reports of one event — are positive (~0.19–0.33) while different events are
# negative (~-0.15…-0.48). So any positive-ish neighbour is a merge CANDIDATE the
# arbiter should judge; a hard cosine threshold (0.18) wrongly excluded marginal
# cross-language pairs (愿景 #6: cross-language same-event must merge). The
# arbiter is the real decider; embedding only proposes candidates above this floor.
THREAD_CANDIDATE_FLOOR = 0.05

# Above this centered similarity a merge is near-identical — embedding is
# confident enough to skip the LLM event-arbiter. Between the thread threshold
# and this, a merge is plausible-but-risky (same entity, maybe different event),
# so an LLM confirms it's the same event (services/semantic_ingest).
THREAD_HIGH_CONFIDENCE = 0.55

# Global corpus mean for anisotropy correction, maintained by the ingest layer.
_CORPUS_MEAN: Optional[List[float]] = None


def set_corpus_mean(mean: Optional[List[float]]) -> None:
    """Set (or clear with None) the corpus mean subtracted before thread-cosine.
    The ingest layer recomputes it each cycle over all stored embeddings."""
    global _CORPUS_MEAN
    _CORPUS_MEAN = list(mean) if mean else None


def cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def max_similarity(vec: List[float], refs: List[List[float]]) -> float:
    """Highest cosine of vec against any reference vector (0 if none)."""
    best = 0.0
    for r in refs:
        s = cosine(vec, r)
        if s > best:
            best = s
    return best


def _center(v: List[float]) -> List[float]:
    """Subtract the corpus mean when set (anisotropy correction); no-op on a
    dimension mismatch or when no mean is set (fallback embedder)."""
    m = _CORPUS_MEAN
    if m and len(m) == len(v):
        return [x - mx for x, mx in zip(v, m)]
    return v


def relevance_score(vec: List[float], profile_vecs: List[List[float]]) -> float:
    """How on-topic an item is: max cosine against the target's profile vectors
    (target name + entity aliases + keep-keywords, all embedded). Runs in the
    mean-centered space when a corpus mean is set — same correction as thread
    clustering, and for the same reason: raw cosines on a real embedder sit in a
    0.48–0.72 cone against any same-domain profile, so a raw threshold either
    gates nothing or everything. NOTE: scores can be negative in centered space;
    compare against active_relevance_threshold(), not the raw constant."""
    cv = _center(vec)
    best = -1.0
    for r in profile_vecs:
        s = cosine(cv, _center(r))
        if s > best:
            best = s
    return best if profile_vecs else 0.0


def active_relevance_threshold() -> float:
    """The relevance gate matching the active space: centered when a corpus mean
    is set (real embedder), raw otherwise (bag-of-words fallback)."""
    return RELEVANCE_THRESHOLD_CENTERED if _CORPUS_MEAN else DEFAULT_RELEVANCE_THRESHOLD


def is_relevant(vec: List[float], profile_vecs: List[List[float]],
                threshold: Optional[float] = None) -> bool:
    if not profile_vecs:
        return True  # no profile → don't filter (fail open)
    thr = threshold if threshold is not None else active_relevance_threshold()
    return relevance_score(vec, profile_vecs) >= thr


def find_duplicate(vec: List[float], existing: List[Tuple[int, List[float]]],
                   threshold: float = DEFAULT_DUPLICATE_THRESHOLD) -> Optional[int]:
    """Return the id of a near-identical existing item (cosine ≥ threshold), or
    None. `existing` is [(id, vector), ...]."""
    best_id, best_sim = None, threshold
    for _id, v in existing:
        s = cosine(vec, v)
        if s >= best_sim:
            best_id, best_sim = _id, s
    return best_id


def assign_thread(vec: List[float], thread_centroids: List[Tuple[int, List[float]]],
                  threshold: Optional[float] = None) -> Tuple[Optional[int], float]:
    """Nearest story thread whose (centered) centroid cosine ≥ threshold, else
    (None, best). None means 'start a new thread'. When a corpus mean is set the
    comparison runs in the anisotropy-corrected space (both the article vector
    and each centroid get the mean subtracted); centering is linear so a centroid
    stored as the raw mean of raw members centers correctly. Threshold defaults
    to the centered/raw knob matching the active space."""
    m = _CORPUS_MEAN
    centered = bool(m) and len(m) == len(vec)
    thr = threshold if threshold is not None else (
        THREAD_THRESHOLD_CENTERED if centered else THREAD_THRESHOLD_RAW)

    cv = _center(vec)
    best_id, best_sim = None, 0.0
    for tid, c in thread_centroids:
        s = cosine(cv, _center(c))
        if s > best_sim:
            best_id, best_sim = tid, s
    if best_sim >= thr:
        return best_id, best_sim
    return None, best_sim


def update_centroid(centroid: Optional[List[float]], count: int, new_vec: List[float]) -> List[float]:
    """Incremental mean of member vectors (running centroid) so a thread's
    center tracks its contents without recomputing over all members."""
    if not centroid or count <= 0:
        return list(new_vec)
    return [(c * count + v) / (count + 1) for c, v in zip(centroid, new_vec)]


# Resonance (愿景 #2): "everyone is talking about it" — many INDEPENDENT sources
# converging on one thread in a short window. This is the cross-source
# importance signal, distinct from a single loud source. Cheap (pure counting).
DEFAULT_RESONANCE_THRESHOLD = 2.0  # distinct sources per hour


def resonance_score(distinct_sources: int, hours_since_first_seen: float) -> float:
    """Distinct sources per hour since the thread began. High = a story broke
    across many outlets fast (media + social converging). Media and social are
    counted as distinct sources upstream, so cross-medium agreement scores
    higher than one medium repeating itself."""
    if distinct_sources <= 1:
        return 0.0
    window = max(hours_since_first_seen, 0.5)  # floor avoids divide-by-tiny spikes
    return distinct_sources / window


def is_resonant(distinct_sources: int, hours_since_first_seen: float,
                threshold: float = DEFAULT_RESONANCE_THRESHOLD) -> bool:
    return resonance_score(distinct_sources, hours_since_first_seen) >= threshold
