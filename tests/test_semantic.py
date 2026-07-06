"""Semantic vector ops — relevance gate, dedup, thread clustering, resonance."""
import math
import random

from services import semantic as sm
from services.llm_provider import hashing_embed


def test_cosine_identity_and_orthogonality():
    assert abs(sm.cosine([1, 2, 3], [1, 2, 3]) - 1.0) < 1e-9
    assert abs(sm.cosine([1, 0], [0, 1])) < 1e-9
    assert sm.cosine([], [1, 2]) == 0.0


def test_hashing_embed_similarity():
    a = hashing_embed("apple siri ajax llm architecture rebuild developer")
    b = hashing_embed("apple siri ajax llm architecture rebuild workflow")
    c = hashing_embed("bitcoin ethereum defi protocol staking yield crypto")
    assert sm.cosine(a, b) > 0.6
    assert sm.cosine(a, c) < 0.2


def test_relevance_gate():
    profile = [hashing_embed("apple siri apple intelligence ai assistant")]
    on = hashing_embed("apple siri gets new ai assistant features")
    off = hashing_embed("stock market crude oil prices fall today")
    assert sm.is_relevant(on, profile, threshold=0.2)
    assert not sm.is_relevant(off, profile, threshold=0.2)
    # No profile -> fail open (don't filter).
    assert sm.is_relevant(off, [], threshold=0.9)


def test_dedup():
    a = hashing_embed("apple siri ajax llm architecture rebuild developer")
    c = hashing_embed("bitcoin ethereum defi protocol staking yield")
    existing = [(1, a), (2, c)]
    dup = hashing_embed("apple siri ajax llm architecture rebuild developer")
    assert sm.find_duplicate(dup, existing, threshold=0.85) == 1
    novel = hashing_embed("totally unrelated new content here now")
    assert sm.find_duplicate(novel, existing, threshold=0.85) is None


def test_multilingual_same_event_clusters():
    """A real multilingual embedder places zh/en/ja reports of one event close;
    simulate with near-identical vectors and verify assign_thread merges them."""
    random.seed(0)
    e1 = [0.0] * 8; e1[0] = 1.0
    e2 = [0.0] * 8; e2[4] = 1.0

    def jitter(v, eps=0.02):
        return [x + random.uniform(-eps, eps) for x in v]

    centroids = []
    tid, _ = sm.assign_thread(jitter(e1), centroids, threshold=0.6)
    assert tid is None  # first report starts a thread
    centroids.append((100, jitter(e1)))
    tid, _ = sm.assign_thread(jitter(e1), centroids, threshold=0.6)
    assert tid == 100  # same event -> same thread
    tid, _ = sm.assign_thread(jitter(e2), centroids, threshold=0.6)
    assert tid is None  # different event -> new thread


def test_resonance_score_and_decay():
    assert not sm.is_resonant(1, 0.1)
    assert sm.is_resonant(5, 1.0)
    assert not sm.is_resonant(2, 72.0)  # decays as thread ages
    # floor avoids divide-by-tiny spikes
    assert sm.resonance_score(3, 0.0) == 3 / 0.5
