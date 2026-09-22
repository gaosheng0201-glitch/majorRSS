"""接地词汇刷新 — the planner reads the target's own recent leads and names the
terms a serious follower would add: versions, codenames, drugs and trial IDs,
opponents, events, people. Author's framing (2026-09-22): "search the related
content first, then let the model think about which terms are involved."

Why a model, and why grounded:
  - Rules recognise SHAPES ("Name 4.5"); a model recognises MEANING — it knows
    "Axoltis Phase II" is a trial and "Skimaki" is a codename without a regex
    per topic. That is what makes this work for topics nobody anticipated.
  - Asked from memory, a model's knowledge is stale (it offered "Gemini 3" as
    Gemini's successor). Fed the target's own titles, it is current by
    construction.

Guards (the model proposes, the data decides):
  - every accepted term must appear VERBATIM in the titles it was shown;
  - in at least MIN_SUPPORT of them; not already an alias; not a generic word;
  - bounded per run. Accepted terms become aliases (routes and the matcher
    derive from aliases), logged, never asked. Runs once per target per day
    in maintenance — planning cadence, zero runtime tokens.
"""
import json
import re
from typing import List, Optional

from pydantic import BaseModel, Field

from services.log_service import get_logger

logger = get_logger("vocab")

MIN_SUPPORT = 2
# Whether a term is applied or only suggested is the MODEL's call per term
# (author, 2026-09-22: "let the model judge"): `scope="core"` — the term names
# the target's own story (its version, its drug, its trial, its official event)
# — is applied; `scope="context"` — related, but would also pull in news that
# is not about the target (a rival, a teammate, a venue) — is suggested. A
# fixed rule by kind got this wrong both ways: a sponsor company is core to a
# disease target, a teammate is context to a player target.
MAX_TERMS_PER_RUN = 6
TITLE_SAMPLE = 80
WINDOW_DAYS = 14
_GENERIC = {"ai", "model", "models", "news", "update", "google", "openai", "anthropic", "microsoft",
            "apple", "the", "new", "launch", "release", "test", "pro", "flash", "ultra", "api"}


class VocabTerm(BaseModel):
    term: str = Field(description="Exact phrase as it appears in the titles")
    kind: str = Field(default="other", description="version | codename | product | drug | trial | person | org | event | place | other")
    scope: str = Field(default="context", description="'core' if the term names the TARGET'S OWN story (its next version, its codename, a drug or trial FOR it, its official event) so news under this name is always about the target; 'context' if it is related but news under this name would often NOT be about the target (a rival, a teammate, a venue, a partner)")
    reason: str = Field(default="")


class VocabProposal(BaseModel):
    terms: List[VocabTerm] = Field(default=[])


_SYSTEM = (
    "You maintain the watch vocabulary of a personal intelligence radar target. You are given "
    "the target's profile and a sample of recent headlines its radar collected. Propose the "
    "NAMED THINGS in these headlines that a serious follower of this target would want to watch "
    "by name from now on — upcoming versions and codenames, drugs/therapies and trial identifiers, "
    "opponents/rivals, events, key people or organisations, places — anything a search for the "
    "target's current aliases would MISS. Rules: (1) copy each term EXACTLY as it appears in a "
    "headline; (2) never propose a term that is already an alias, the target's own name, or a "
    "generic word; (3) prefer specific over broad; (4) at most 8 terms; (5) skip headlines that "
    "are not about this target. For each term decide `scope`: 'core' means the term names the "
    "target's own story — watching it can only bring news about the target; 'context' means it is "
    "related but would also bring news that is not about the target."
)


def _profile(t) -> dict:
    try:
        return json.loads(t.fetch_policy) if t.fetch_policy else {}
    except Exception:
        return {}


def _recent_titles(session, tracker_id: int) -> List[str]:
    from datetime import datetime, timedelta
    from sqlmodel import select
    from db.models import RawArticle, StoryThread, ThreadTarget
    cutoff = datetime.utcnow() - timedelta(days=WINDOW_DAYS)
    tids = session.exec(select(ThreadTarget.thread_id).where(ThreadTarget.tracker_id == tracker_id,
                                                              ThreadTarget.llm_verdict.is_not(False))).all()
    if not tids:
        return []
    rows = session.exec(select(RawArticle.title).where(
        RawArticle.thread_id.in_(tids), RawArticle.created_at >= cutoff)
        .order_by(RawArticle.created_at.desc()).limit(TITLE_SAMPLE * 3)).all()
    seen, out = set(), []
    for t in rows:
        t = (t or "").strip()
        k = re.sub(r"\s+", " ", t.lower())
        if t and k not in seen:
            seen.add(k); out.append(t)
        if len(out) >= TITLE_SAMPLE:
            break
    return out


def _key(term: str) -> str:
    """Comparison key: case, punctuation and dash variants folded ("GPT-6 Astra"
    and "GPT‑6 Astra" with a non-breaking hyphen are one term)."""
    return re.sub(r"[^0-9a-z\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]+", "", (term or "").lower())


def _contains(term: str, text: str) -> bool:
    return re.search(r"(?<![0-9A-Za-z])" + re.escape(term) + r"(?![0-9A-Za-z])", text, re.I) is not None \
        if re.search(r"[A-Za-z0-9]", term) else term.lower() in text.lower()


def _other_targets_aliases(session, tracker_id: int) -> set:
    """Aliases of every OTHER active target — a rival's product showing up in
    comparison headlines must not become this target's vocabulary (first dry
    run: the openAI target proposed "Claude Opus 5.5")."""
    from sqlmodel import select
    from db.models import Tracker
    from services.target_profile import TargetProfile
    out = set()
    for t in session.exec(select(Tracker).where(Tracker.is_active == True)).all():  # noqa: E712
        if t.id == tracker_id:
            continue
        prof = TargetProfile.from_tracker(t)
        out.update(a.lower() for a in ([prof.name] + prof.entities) if a)
    return out


def propose_terms(tracker, titles: List[str], provider=None, foreign_aliases: Optional[set] = None) -> List[dict]:
    """Model proposal, then the data decides. Returns accepted term dicts,
    each with `auto` — whether it is applied or only suggested."""
    if not titles:
        return []
    if provider is None:
        from services.llm_provider import get_provider
        provider = get_provider()
    if not getattr(provider, "supports_generation", False):
        return []
    from services.target_profile import TargetProfile
    prof = TargetProfile.from_tracker(tracker)
    existing = {a.lower() for a in ([prof.name] + prof.entities)}
    prompt = (f"TARGET: {prof.describe()}\n\nRECENT HEADLINES ({len(titles)}):\n" +
              "\n".join(f"- {t}" for t in titles))
    text, usage = provider.generate(prompt, system=_SYSTEM, schema=VocabProposal, temperature=0.2)
    try:
        from llm.processor import _record_usage
        _record_usage(getattr(provider, "name", "unknown"), "VocabRefresh", usage)
    except Exception:
        pass
    try:
        proposal = VocabProposal(**json.loads(text))
    except Exception as e:
        logger.warning(f"Vocab proposal unparsable for {tracker.name}: {e}")
        return []
    accepted, seen = [], set()
    for vt in proposal.terms:
        term = (vt.term or "").strip().strip('"“”')
        low = term.lower()
        if len(term) < 3 or low in existing or low in seen or low in _GENERIC:
            continue
        if any(low == e or (e in low and len(low) - len(e) <= 2) for e in existing):
            continue
        fk = _key(term)
        if foreign_aliases and any(fk == _key(f) or _key(f) in fk for f in foreign_aliases if len(_key(f)) >= 4):
            continue          # another target's name or product
        support = sum(1 for t in titles if _contains(term, t))
        if support < MIN_SUPPORT:
            continue
        seen.add(low)
        accepted.append({"term": term, "kind": vt.kind, "scope": vt.scope, "reason": vt.reason[:120],
                         "support": support, "auto": (vt.scope or "context") == "core"})
        if len(accepted) >= MAX_TERMS_PER_RUN:
            break
    return accepted


def apply_terms(session, tracker, accepted: List[dict]) -> List[str]:
    policy = _profile(tracker)
    ip = policy.get("intent_plan") or {}
    have = {str(e).lower() for e in policy.get("entities") or []}
    added = []
    for a in accepted:
        if a["term"].lower() in have or not a.get("auto", False):
            continue
        policy.setdefault("entities", []).append(a["term"])
        ip.setdefault("entities", []).append({"text": a["term"], "lang": "en", "regions": ["US"],
                                              "role": a.get("kind", "other")})
        have.add(a["term"].lower()); added.append(a["term"])
    policy["intent_plan"] = ip
    tracker.fetch_policy = json.dumps(policy)
    session.add(tracker)
    return added


def _propose_for(session, tracker_id: int, provider=None):
    from db.models import Tracker
    t = session.get(Tracker, tracker_id)
    if not t or not t.is_active:
        return None, [], []
    titles = _recent_titles(session, tracker_id)
    accepted = propose_terms(t, titles, provider=provider,
                             foreign_aliases=_other_targets_aliases(session, tracker_id))
    return t, titles, accepted


def _commit_for(session, t, titles, accepted, dry_run: bool) -> dict:
    added = [] if dry_run else apply_terms(session, t, accepted)
    suggested = [] if dry_run else _suggest(session, t, [a for a in accepted if not a.get("auto")])
    if added or suggested:
        session.commit()
        logger.info(f"Vocab refresh: '{t.name}' learned {added}; suggested {suggested}")
    return {"tracker": t.name, "titles": len(titles), "accepted": accepted, "added": added,
            "suggested": suggested}


def refresh_target_vocabulary(tracker_id: int, provider=None, dry_run: bool = False) -> dict:
    from db.database import get_session
    with get_session() as session:
        t, titles, accepted = _propose_for(session, tracker_id, provider)
        if t is None:
            return {"tracker": tracker_id, "accepted": [], "added": [], "suggested": []}
        return _commit_for(session, t, titles, accepted, dry_run)


def refresh_all(provider=None, dry_run: bool = False) -> List[dict]:
    """Two phases: every target proposes, then a term proposed by several
    targets goes to the one with the most support — a rival's product seen in
    comparison headlines (claude's leads saying "GPT-6 Astra" 3 times, openAI's
    11 times) belongs to the rival."""
    from db.database import get_session
    from db.models import Tracker
    from sqlmodel import select
    with get_session() as s:
        ids = [t.id for t in s.exec(select(Tracker).where(Tracker.is_active == True)).all()]  # noqa: E712
    proposals = {}
    with get_session() as session:
        for tid in ids:
            try:
                t, titles, accepted = _propose_for(session, tid, provider)
            except Exception as e:
                logger.warning(f"Vocab refresh failed for tracker {tid}: {e}")
                continue
            if t is not None:
                proposals[tid] = (t, titles, accepted)
        best = {}
        for tid, (_t, _titles, accepted) in proposals.items():
            for a in accepted:
                k = _key(a["term"])
                if k not in best or a["support"] > best[k][1]:
                    best[k] = (tid, a["support"])
        out = []
        for tid, (t, titles, accepted) in proposals.items():
            kept = [a for a in accepted if best[_key(a["term"])][0] == tid]
            out.append(_commit_for(session, t, titles, kept, dry_run))
    return out


def _suggest(session, tracker, items: List[dict]) -> List[str]:
    """People / organisations / places go to the radar's emergent line as
    pending terms (accept = alias, dismiss = sticky), like accounts."""
    from datetime import datetime
    from sqlmodel import select
    from db.models import EmergentSource
    out = []
    for a in items:
        key = a["term"].lower()
        if session.exec(select(EmergentSource).where(EmergentSource.tracker_id == tracker.id,
                                                     EmergentSource.kind == "term",
                                                     EmergentSource.value_key == key)).first():
            continue
        session.add(EmergentSource(tracker_id=tracker.id, kind="term", value=a["term"], value_key=key,
                                   thread_count=a["support"], sample_titles=json.dumps([a.get("reason", "")]),
                                   status="pending", first_seen_at=datetime.utcnow(), updated_at=datetime.utcnow()))
        out.append(a["term"])
    return out


def refresh_all(provider=None, dry_run: bool = False) -> List[dict]:
    from db.database import get_session
    from db.models import Tracker
    from sqlmodel import select
    with get_session() as s:
        ids = [t.id for t in s.exec(select(Tracker).where(Tracker.is_active == True)).all()]  # noqa: E712
    out = []
    for tid in ids:
        try:
            out.append(refresh_target_vocabulary(tid, provider=provider, dry_run=dry_run))
        except Exception as e:
            logger.warning(f"Vocab refresh failed for tracker {tid}: {e}")
    return out
