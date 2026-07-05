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
DEFAULT_RELEVANCE_THRESHOLD = 0.35
DEFAULT_DUPLICATE_THRESHOLD = 0.90
DEFAULT_THREAD_THRESHOLD = 0.62


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


def relevance_score(vec: List[float], profile_vecs: List[List[float]]) -> float:
    """How on-topic an item is: max cosine against the target's profile vectors
    (target name + entity aliases + keep-keywords, all embedded)."""
    return max_similarity(vec, profile_vecs)


def is_relevant(vec: List[float], profile_vecs: List[List[float]],
                threshold: float = DEFAULT_RELEVANCE_THRESHOLD) -> bool:
    if not profile_vecs:
        return True  # no profile → don't filter (fail open)
    return relevance_score(vec, profile_vecs) >= threshold


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
                  threshold: float = DEFAULT_THREAD_THRESHOLD) -> Tuple[Optional[int], float]:
    """Nearest story thread whose centroid cosine ≥ threshold, else (None, best).
    None means 'start a new thread'. Returns (thread_id_or_None, best_similarity)."""
    best_id, best_sim = None, 0.0
    for tid, c in thread_centroids:
        s = cosine(vec, c)
        if s > best_sim:
            best_id, best_sim = tid, s
    if best_sim >= threshold:
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
