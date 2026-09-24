"""学出来的关系 — a per-target linear probe over the thread centroid space.

Three weeks of classification defects were each fixed with one more string
rule (comparison mentions, name collisions, language variants…). A rule can
only recognise a shape; "does this thread concern target X" is separable in
the embedding space the radar already has, and the radar already produces
labels every day: the summariser's involvement verdicts, official-domain
items (high-precision positives), and threads judged to concern a rival but
not this target (hard negatives). Offline (2026-09-25, 150–260 samples per
target): probe AUC 0.96–0.995 against a 0.79–0.96 nearest-prototype baseline;
"Introducing GPT-6 Sol" scores 0.89 for openAI and 0.25 for claude with no
rule about comparisons anywhere.

Contract:
  - trained per target, daily, from the radar's own labels; ENABLED only if
    5-fold AUC ≥ MIN_AUC with ≥ MIN_POS / MIN_NEG samples — otherwise the
    deterministic matcher stays the floor (new targets start there);
  - at apply time it does two things, both only when confident: ADD a relation
    the matcher missed (p ≥ add threshold, precision-calibrated) and VETO a
    matcher-only relation (p ≤ veto threshold, recall-calibrated) — a veto
    folds the thread under that target's chip (llm_verdict=False), never
    deletes it, same honesty as the summariser's verdict;
  - a human correction (P3.1) is the highest-grade label and will outrank all.
"""
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
from sqlmodel import select, text

from services.log_service import get_logger

logger = get_logger("relation_model")

MIN_POS, MIN_NEG, MIN_AUC = 20, 20, 0.90
ADD_PRECISION = 0.90      # add only where CV precision at that score reaches this…
ADD_FLOOR = 0.80          # …and never below this absolute probability (adds are a recall bonus)
VETO_RECALL = 0.97        # veto only below the score that still keeps this much recall…
VETO_CEIL = 0.20          # …and never above this (a veto folds a card; be sure)
BACKGROUND_NEG = 300      # threads that concern NO target — the probe must know "about nothing"
L2, ITERS, LR = 1.0, 300, 0.5


def _train_lr(X, y):
    w = np.zeros(X.shape[1]); b = 0.0
    for _ in range(ITERS):
        p = 1 / (1 + np.exp(-(X @ w + b)))
        w -= LR * (X.T @ (p - y) / len(y) + L2 * w / len(y)); b -= LR * float(np.mean(p - y))
    return w, b


def _auc(scores, y):
    pos, neg = scores[y == 1], scores[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    return float(np.mean([(p > n) + 0.5 * (p == n) for p in pos for n in neg]))


def _sigmoid(z):
    return 1 / (1 + np.exp(-z))


def _corpus_mean(session) -> Optional[np.ndarray]:
    vecs = []
    for (c,) in session.exec(text("SELECT centroid FROM storythread WHERE centroid IS NOT NULL")).all():
        try:
            vecs.append(np.array(json.loads(c), dtype=np.float32))
        except Exception:
            pass
    if not vecs:
        return None
    dim = max(set(len(v) for v in vecs), key=lambda d: sum(1 for v in vecs if len(v) == d))
    return np.mean(np.stack([v for v in vecs if len(v) == dim]), axis=0)


def featurize(centroid_json: str, mean: np.ndarray) -> Optional[np.ndarray]:
    try:
        v = np.array(json.loads(centroid_json), dtype=np.float32)
    except Exception:
        return None
    if mean is None or len(v) != len(mean):
        return None
    v = v - mean
    return v / (np.linalg.norm(v) + 1e-9)


def _labels(session, tracker_id: int, all_target_ids: List[int]) -> Tuple[set, set]:
    """Positives: verdict True, or a primary member on the target's own domain.
    Negatives: verdict False, or concerns another target with no relation here."""
    from db.models import ThreadTarget, Tracker
    from services.target_profile import TargetProfile
    from services.provenance import domain
    rel: Dict[int, Dict[int, Optional[bool]]] = {}
    for r in session.exec(select(ThreadTarget)).all():
        rel.setdefault(r.thread_id, {})[r.tracker_id] = r.llm_verdict
    pos = {tid for tid, m in rel.items() if m.get(tracker_id) is True}
    neg = {tid for tid, m in rel.items() if m.get(tracker_id) is False}
    t = session.get(Tracker, tracker_id)
    doms = set(TargetProfile.from_tracker(t).official_domains) if t else set()
    if doms:
        for th_id, url in session.exec(text("SELECT thread_id, url FROM rawarticle WHERE thread_id IS NOT NULL AND source_tier='primary'")).all():
            d = domain(url or "")
            if any(d == x or d.endswith("." + x) for x in doms):
                pos.add(th_id)
    for tid, m in rel.items():
        if tracker_id not in m and any(m.get(o) is True for o in all_target_ids if o != tracker_id):
            neg.add(tid)
    # Background negatives: recent threads with no relation to any target. The
    # first dry run trained on rival-only negatives and then "added" VS Code
    # release notes to three targets at 0.4 — a mid score meant nothing because
    # the probe had never seen a thread about nothing it watches.
    bg = [tid for (tid,) in session.exec(text(
        "SELECT id FROM storythread WHERE centroid IS NOT NULL AND id NOT IN (SELECT thread_id FROM threadtarget) "
        "ORDER BY last_update_at DESC LIMIT :n").bindparams(n=BACKGROUND_NEG)).all()]
    neg.update(bg)
    return pos, neg - pos


def train_target(session, tracker_id: int, all_target_ids: List[int], mean: np.ndarray) -> dict:
    from db.models import StoryThread, TargetModel
    pos, neg = _labels(session, tracker_id, all_target_ids)
    ids = list(pos) + list(neg)
    cent = dict(session.exec(select(StoryThread.id, StoryThread.centroid).where(StoryThread.id.in_(ids))).all()) if ids else {}
    P = [featurize(cent[i], mean) for i in pos if cent.get(i)]
    N = [featurize(cent[i], mean) for i in neg if cent.get(i)]
    P = [x for x in P if x is not None]; N = [x for x in N if x is not None]
    row = session.exec(select(TargetModel).where(TargetModel.tracker_id == tracker_id)).first() or TargetModel(tracker_id=tracker_id)
    if len(P) < MIN_POS or len(N) < MIN_NEG:
        row.enabled = False; row.n_pos, row.n_neg = len(P), len(N); row.trained_at = datetime.utcnow()
        session.add(row); return {"tracker_id": tracker_id, "enabled": False, "reason": "too few labels", "n_pos": len(P), "n_neg": len(N)}
    X = np.stack(P + N); y = np.array([1] * len(P) + [0] * len(N), dtype=np.float32)
    rng = np.random.default_rng(0); idx = rng.permutation(len(y)); folds = np.array_split(idx, 5)
    cv = np.zeros(len(y))
    for f in folds:
        tr = np.setdiff1d(idx, f); w, b = _train_lr(X[tr], y[tr]); cv[f] = _sigmoid(X[f] @ w + b)
    auc = _auc(cv, y)
    # thresholds from CV scores: add where precision ≥ ADD_PRECISION; veto below the score keeping VETO_RECALL
    order = np.argsort(-cv); add_t = 1.01
    tp = fp = 0
    for i in order:
        tp += y[i] == 1; fp += y[i] == 0
        if tp / (tp + fp) >= ADD_PRECISION and tp >= 5:
            add_t = float(cv[i])
    pos_scores = np.sort(cv[y == 1]); veto_t = float(pos_scores[max(0, int((1 - VETO_RECALL) * len(pos_scores)) - 1)]) if len(pos_scores) else 0.0
    w, b = _train_lr(X, y)
    row.weights = json.dumps([round(float(x), 6) for x in w]); row.bias = float(b)
    row.auc = auc; row.add_threshold = min(max(add_t, ADD_FLOOR), 0.99); row.veto_threshold = max(min(veto_t, VETO_CEIL), 0.0)
    row.n_pos, row.n_neg = len(P), len(N); row.enabled = bool(auc >= MIN_AUC); row.trained_at = datetime.utcnow()
    session.add(row)
    return {"tracker_id": tracker_id, "enabled": row.enabled, "auc": round(auc, 3), "n_pos": len(P), "n_neg": len(N),
            "add_t": round(row.add_threshold, 2), "veto_t": round(row.veto_threshold, 2)}


def train_all() -> List[dict]:
    from db.database import get_session
    from db.models import Tracker
    out = []
    with get_session() as session:
        ids = [t.id for t in session.exec(select(Tracker).where(Tracker.is_active == True)).all()]  # noqa: E712
        mean = _corpus_mean(session)
        if mean is None:
            return out
        for tid in ids:
            try:
                out.append(train_target(session, tid, ids, mean))
            except Exception as e:
                logger.warning(f"Probe training failed for tracker {tid}: {e}")
        session.commit()
    logger.info("Relation probes trained: " + ", ".join(f"{r['tracker_id']}:{'on' if r['enabled'] else 'off'}" + (f"(auc {r['auc']})" if 'auc' in r else '') for r in out))
    return out


class Probes:
    """Enabled probes loaded once per pass; scores a centroid for every target."""
    def __init__(self, session):
        from db.models import TargetModel
        self.mean = _corpus_mean(session)
        self.models = {}
        for m in session.exec(select(TargetModel).where(TargetModel.enabled == True)).all():  # noqa: E712
            try:
                self.models[m.tracker_id] = (np.array(json.loads(m.weights), dtype=np.float32), m.bias, m.add_threshold, m.veto_threshold)
            except Exception:
                pass

    def score(self, centroid_json: str) -> Dict[int, float]:
        x = featurize(centroid_json, self.mean) if self.mean is not None else None
        if x is None:
            return {}
        return {tid: float(_sigmoid(x @ w + b)) for tid, (w, b, _a, _v) in self.models.items()}

    def apply(self, session, thread) -> Tuple[int, int]:
        """Add confident relations the matcher missed; veto matcher-only ones the
        probe is confident against. Returns (added, vetoed)."""
        from db.models import ThreadTarget
        if not self.models or not thread.centroid:
            return 0, 0
        scores = self.score(thread.centroid)
        rows = {r.tracker_id: r for r in session.exec(select(ThreadTarget).where(ThreadTarget.thread_id == thread.id)).all()}
        added = vetoed = 0
        for tid, p in scores.items():
            _w, _b, add_t, veto_t = self.models[tid]
            r = rows.get(tid)
            if r is None and p >= add_t:
                session.add(ThreadTarget(thread_id=thread.id, tracker_id=tid, source="model", llm_verdict=None, score=p)); added += 1
            elif r is not None:
                r.score = p
                if r.llm_verdict is None and r.source in ("match", "route") and p <= veto_t:
                    r.llm_verdict = False; vetoed += 1
                session.add(r)
        return added, vetoed
