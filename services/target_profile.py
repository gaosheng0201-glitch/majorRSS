"""What a target IS — one definition, three views.

Three consumers each used to rebuild "the target" from Tracker fields in their
own way: the relevance gate embedded one term list (semantic_ingest), the
cross-target matcher parsed entities/domains/ignores a second way
(attribution), and the summariser was handed a third string (processor). Any
one of them could drift — and the summariser's view was simply missing, which
is how a Claude result in number theory became "a person named Claude".

TargetProfile is built once from a Tracker (planned data first, legacy fields
as fallback) and offers:
  terms()    — embedding anchors for the relevance gate
  describe() — the summariser's briefing
  matcher()  — the deterministic cross-target visibility matcher
"""
import json
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TargetProfile:
    tracker_id: Optional[int]
    name: str
    entities: List[str] = field(default_factory=list)
    official_domains: List[str] = field(default_factory=list)
    keep_keywords: List[str] = field(default_factory=list)
    ignore_keywords: List[str] = field(default_factory=list)
    intent: str = ""
    raw_terms: List[str] = field(default_factory=list)

    @classmethod
    def from_tracker(cls, t) -> "TargetProfile":
        try:
            policy = json.loads(t.fetch_policy) if getattr(t, "fetch_policy", None) else {}
        except Exception:
            policy = {}
        if not isinstance(policy, dict):
            policy = {}
        ip = policy.get("intent_plan") or {}
        if not isinstance(ip, dict):
            ip = {}
        entities = [str(e) for e in (policy.get("entities") or []) if e]
        name = getattr(t, "name", "") or ""
        # Legacy term harvest (the relevance gate's historical anchors): name +
        # every list-shaped signal in target / normalized_intent / fetch_policy.
        raw = [name] if name else []
        for fld in ("target", "normalized_intent", "fetch_policy"):
            val = getattr(t, fld, None)
            if not val:
                continue
            try:
                data = json.loads(val)
            except Exception:
                raw.append(str(val))
                continue
            if isinstance(data, list):
                raw += [str(x) for x in data]
            elif isinstance(data, dict):
                for k in ("topic", "entities", "keep_keywords", "keywords"):
                    v = data.get(k)
                    if isinstance(v, list):
                        raw += [str(x) for x in v]
                    elif isinstance(v, str):
                        raw.append(v)
                for sig in data.get("signals", []) or []:
                    if isinstance(sig, dict) and sig.get("value"):
                        raw.append(str(sig["value"]))
        return cls(
            tracker_id=getattr(t, "id", None), name=name, entities=entities,
            official_domains=[str(d).lower() for d in (ip.get("official_domains") or []) if d],
            keep_keywords=[str(k) for k in (policy.get("keep_keywords") or []) if k],
            ignore_keywords=[str(k) for k in (policy.get("ignore_keywords") or []) if k],
            intent=str(ip.get("rationale") or ip.get("lane_reason") or "")[:200],
            raw_terms=raw,
        )

    def terms(self, cap: int = 20) -> List[str]:
        """Embedding anchors: deduped, no URLs (URLs are poor topic anchors)."""
        seen, out = set(), []
        for t in self.raw_terms:
            t = t.strip()
            if not t or t.startswith("http") or t in seen:
                continue
            seen.add(t)
            out.append(t)
        return out[:cap]

    def describe(self) -> str:
        """The summariser's briefing: name, aliases, own domains, intent."""
        parts = [f"name: {self.name}"]
        if self.entities:
            parts.append("aliases: " + ", ".join(self.entities[:8]))
        if self.official_domains:
            parts.append("official domains: " + ", ".join(self.official_domains[:6]))
        if self.intent:
            parts.append("intent: " + self.intent)
        return "; ".join(parts)

    def matcher(self):
        """Cross-target visibility matcher (services/attribution.TrackerProfile)."""
        from services.attribution import TrackerProfile
        ents = list(self.entities)
        if self.name and self.name not in ents:
            ents = [self.name] + ents
        return TrackerProfile(self.tracker_id, ents, self.official_domains, self.ignore_keywords)
