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


def test_parse_vector_matches_json():
    import json
    v = [random.uniform(-1, 1) for _ in range(64)]
    assert list(sm.parse_vector(json.dumps(v))) == [float(f) for f in __import__("numpy").float32(v)]
    for bad in ("", "[]x", "[1, , 2]", "{}", "[1, 2"):
        try:
            sm.parse_vector(bad)
            assert False, bad
        except ValueError:
            pass


def test_centroid_index_matches_pure_python():
    """The numpy index is the same space and the same answers as
    assign_thread_candidates / cosine(_center()) — only faster."""
    rnd = random.Random(7)
    dim = 32
    mean = [rnd.uniform(-0.3, 0.3) for _ in range(dim)]
    cents = [(i, [m + rnd.gauss(0, 1) for m in mean]) for i in range(1, 60)]
    cents.append((99, list(mean)))              # centres to zero → scores 0, like cosine()
    cents.append((98, [1.0] * (dim + 1)))       # other dim → never a candidate
    for m in (mean, None):
        sm.set_corpus_mean(m)
        try:
            idx = sm.CentroidIndex(cents, dim=dim, spare=1)
            for _ in range(5):
                q = [x + rnd.gauss(0, 1) for x in mean]
                want = sm.assign_thread_candidates(q, cents, floor=0.05, k=3)
                got = idx.candidates(q, floor=0.05, k=3)
                assert [t for t, _ in got] == [t for t, _ in want]
                assert all(abs(a - b) < 1e-5 for (_, a), (_, b) in zip(got, want))
            # upsert: a new thread and a moved one are found in the next query
            idx.upsert(200, cents[0][1])
            idx.upsert(2, cents[0][1])
            top = {t for t, _ in idx.candidates(cents[0][1], floor=0.05, k=3)}
            assert top == {1, 2, 200}
            # all pairs above a threshold, same as the double loop
            same_dim = [(t, v) for t, v in cents if len(v) == dim]
            want = {(a, b) for i, (a, va) in enumerate(same_dim) for b, vb in same_dim[i + 1:]
                    if sm.cosine(sm._center(va), sm._center(vb)) >= 0.3}
            got = {(a, b) for a, b, _ in sm.CentroidIndex(same_dim, dim=dim).pairs_above(0.3)}
            assert got == want
        finally:
            sm.set_corpus_mean(None)


def test_corpus_mean_is_incremental_and_self_correcting():
    """Running sum == a full recompute, across appends and a deletion."""
    import json
    from sqlmodel import delete, select
    from db.database import get_session
    from db.models import ArticleEmbedding, RawArticle, Tracker
    from services.semantic_ingest import refresh_corpus_mean

    rnd = random.Random(3)

    def full_mean(s):
        vs = [json.loads(v) for v in s.exec(select(ArticleEmbedding.vector)).all()]
        return [sum(c) / len(vs) for c in zip(*vs)]

    def add(s, t, n):
        for _ in range(n):
            a = RawArticle(tracker_id=t.id, title="x", url=f"https://e.example/{rnd.random()}", content="x")
            s.add(a); s.commit(); s.refresh(a)
            s.add(ArticleEmbedding(article_id=a.id, model_name="t", dim=8,
                                   vector=json.dumps([rnd.uniform(-1, 1) for _ in range(8)])))
        s.commit()

    def check(s, extra=()):
        refresh_corpus_mean(s, extra=extra)
        want = full_mean(s)
        if extra:
            n = len(s.exec(select(ArticleEmbedding.id)).all())
            want = [(w * n + sum(e)) / (n + len(extra)) for w, e in zip(want, zip(*extra))]
        assert all(abs(a - b) < 1e-5 for a, b in zip(sm._CORPUS_MEAN, want))

    try:
        with get_session() as s:
            s.exec(delete(ArticleEmbedding)); s.commit()
            t = Tracker(name="mean-t", tracker_type="KEYWORD", target="[]", radar_section="AI")
            s.add(t); s.commit(); s.refresh(t)
            add(s, t, 5); check(s)
            add(s, t, 3); check(s, extra=[[0.5] * 8])
            first = s.exec(select(ArticleEmbedding).order_by(ArticleEmbedding.id)).first()
            s.delete(first); s.commit(); check(s)          # deletion → full pass
            s.exec(delete(ArticleEmbedding)); s.commit()
            add(s, t, 4); check(s)                          # rebuilt table, reused ids
    finally:
        sm.set_corpus_mean(None)


def test_idle_cycle_parses_no_vectors_and_survives_restart(monkeypatch):
    """The regression guard for §7.5: a cycle with nothing new must not re-read
    stored vectors — not in the same process, and not after a relaunch (the
    running sum is persisted beside the DB)."""
    import json
    from datetime import datetime, timedelta
    from sqlmodel import delete
    from db.database import get_session
    from db.models import ArticleEmbedding, RawArticle, StoryThread, Tracker
    from services import semantic_ingest as si

    calls = []
    real = sm.parse_vector
    monkeypatch.setattr(sm, "parse_vector", lambda s: calls.append(1) or real(s))
    try:
        with get_session() as s:
            s.exec(delete(ArticleEmbedding)); s.exec(delete(StoryThread)); s.commit()
            t = Tracker(name="idle-t", tracker_type="KEYWORD", target="[]", radar_section="AI")
            s.add(t); s.commit(); s.refresh(t)
            for i in range(4):
                a = RawArticle(tracker_id=t.id, title=f"x{i}", url=f"https://i.example/{i}", content="x")
                s.add(a); s.commit(); s.refresh(a)
                s.add(ArticleEmbedding(article_id=a.id, model_name="t", dim=4, vector=json.dumps([i, 1.0, 0.0, 0.5])))
                s.add(StoryThread(tracker_id=t.id, title=f"th{i}", centroid=json.dumps([i, 1.0, 0.0, 0.5]),
                                  member_count=1, first_seen_at=datetime.utcnow(), last_update_at=datetime.utcnow()))
            s.commit()
            cutoff = datetime.utcnow() - timedelta(days=1)
            si.refresh_corpus_mean(s); si.load_centroids(s, cutoff, prune=True)
            first, mean = len(calls), sm._CORPUS_MEAN
            assert first == 8
            si.refresh_corpus_mean(s); si.load_centroids(s, cutoff, prune=True)
            assert len(calls) == first                      # idle: nothing parsed
            si._mean_state.clear()                          # "relaunch"
            si.refresh_corpus_mean(s)
            assert len(calls) == first and sm._CORPUS_MEAN == mean
    finally:
        sm.set_corpus_mean(None)


def test_merge_pass_skips_only_when_its_answer_cannot_change():
    import json
    from datetime import datetime
    from sqlmodel import delete
    from db.database import get_session
    from db.models import ArticleEmbedding, StoryThread, ThreadPairVerdict, ThreadTarget, RawArticle
    from services import thread_merge as tm

    class Arb:
        n = 0
        def generate(self, prompt, **kw):
            Arb.n += 1
            return "different", {}

    def thread(s, title, v):
        s.add(StoryThread(title=title, centroid=json.dumps(v), member_count=1,
                          first_seen_at=datetime.utcnow(), last_update_at=datetime.utcnow()))
        s.commit()

    try:
        with get_session() as s:
            s.exec(delete(ThreadPairVerdict)); s.exec(delete(ThreadTarget)); s.exec(delete(ArticleEmbedding))
            s.exec(delete(RawArticle)); s.exec(delete(StoryThread)); s.commit()
            thread(s, "a", [1.0, 0.0, 0.0]); thread(s, "b", [0.99, 0.05, 0.0])
        tm._last_pass.clear()
        assert tm.run_merge_pass(arbiter=Arb())["pairs"] == 1 and Arb.n == 1
        assert tm.run_merge_pass(arbiter=Arb()).get("skipped") == "unchanged" and Arb.n == 1
        with get_session() as s:
            thread(s, "c", [0.98, 0.1, 0.0])                # new input → the pass runs again
        assert tm.run_merge_pass(arbiter=Arb())["pairs"] == 2 and Arb.n == 3
    finally:
        sm.set_corpus_mean(None)
