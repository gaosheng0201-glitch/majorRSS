"""
Alert engine (R5, 愿景 #2).

Default is a quiet dashboard. An alert is created only when an increment earns
interruption:
  - RESONANCE                     — a thread went resonant (media+social
                                    converging: the cross-source signal).
  - CONFIRMED_HIGH_ATTENTION      — a high-attention target's thread reached
                                    CONFIRMED (a first-party source landed).
  - CORROBORATED_HIGH_ATTENTION   — a high-attention target's thread reached
                                    CORROBORATED (≥2 independent sources).

Idempotent per (thread, reason): a thread never re-alerts for the same reason.
Every alert stores its trigger reason so the UI can answer "why am I being
interrupted?". Actual OS notification delivery is the desktop layer's job; this
produces the alert rows and marks them undelivered.
"""
from datetime import datetime, timezone, timedelta

from sqlmodel import select

from services.log_service import get_logger

logger = get_logger("alerts")


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _existing_reason(session, thread_id: int, reason: str) -> bool:
    from db.models import RadarAlert
    return session.exec(
        select(RadarAlert).where(RadarAlert.thread_id == thread_id, RadarAlert.reason == reason)
    ).first() is not None


def _synthesize(thread, articles) -> tuple:
    """Return (title, summary_with_citations). Uses the provider when available;
    otherwise a deterministic citation list so alerts are never empty and always
    traceable to sources (愿景 溯源)."""
    citations = "\n".join(f"- {a.title or a.url} ({a.url})" for a in articles[:8])
    title = thread.title or (articles[0].title if articles else "Update")
    try:
        from services.llm_provider import get_provider
        provider = get_provider()
        if provider.supports_generation:
            from llm.processor import get_target_language, _record_usage
            lang = get_target_language()
            body = "\n\n".join(f"[{i+1}] {a.title}\n{(a.content or '')[:800]}" for i, a in enumerate(articles[:8]))
            system = (
                f"You are an intelligence analyst. Summarize what is NEW about this story in 2-3 sentences in {lang}. "
                "Be factual, attribute claims, prefer primary sources. Do not invent facts not present in the inputs."
            )
            text, usage = provider.generate(f"STORY: {title}\n\nSOURCES:\n{body}", system=system, temperature=0.2)
            _record_usage(provider.name, "AlertSynthesis", usage)
            return title, f"{text}\n\n**来源 Sources:**\n{citations}"
    except Exception as e:
        logger.warning(f"Alert synthesis failed, using citation-only summary: {e}")
    # Citation-only fallback (pure-RSS): still traceable, no fabricated prose.
    return title, f"{thread.distinct_source_count} sources reporting.\n\n**Sources:**\n{citations}"


def evaluate_alerts(window_hours: int = 48, synthesize: bool = True) -> dict:
    """Scan recently-updated threads and create alerts for those that cross a
    trigger. Returns a summary dict."""
    from db.database import get_session
    from db.models import StoryThread, Tracker, RawArticle, RadarAlert

    created = 0
    cutoff = _now() - timedelta(hours=window_hours)
    with get_session() as session:
        threads = session.exec(
            select(StoryThread).where(StoryThread.last_update_at >= cutoff)
        ).all()

        for th in threads:
            # 目标即查询: high attention belongs to ANY target the thread concerns.
            from services import thread_targets as tt
            _rows = tt.rows_for(session, [th.id])[th.id]
            _related = [session.get(Tracker, r.tracker_id) for r in _rows if r.llm_verdict is not False]
            high = any(t is not None and t.is_high_attention for t in _related)

            triggers = []
            if th.is_resonant:
                triggers.append("RESONANCE")
            if high and th.lifecycle == "CONFIRMED":
                triggers.append("CONFIRMED_HIGH_ATTENTION")
            elif high and th.lifecycle == "CORROBORATED":
                triggers.append("CORROBORATED_HIGH_ATTENTION")

            for reason in triggers:
                if _existing_reason(session, th.id, reason):
                    continue
                articles = session.exec(
                    select(RawArticle).where(RawArticle.thread_id == th.id).order_by(RawArticle.created_at.desc())
                ).all()
                title, summary = _synthesize(th, articles) if synthesize else (th.title, None)
                alert = RadarAlert(
                    thread_id=th.id,
                    tracker_id=tt.primary_target_id(_rows, th.tracker_id),
                    reason=reason,
                    title=title,
                    summary=summary,
                    distinct_source_count=th.distinct_source_count,
                    lifecycle=th.lifecycle,
                    delivered=False,
                    is_read=False,
                )
                session.add(alert)
                session.commit()
                created += 1
                logger.info(f"Alert created: thread {th.id} [{reason}] — {title}")

    return {"alerts_created": created}


ENTITY_SPIKE_MIN_THREADS = 3      # was 2 in the standalone TrendScan
ENTITY_SPIKE_DEDUP_HOURS = 24     # was 12
ENTITY_SPIKE_MAX_PER_RUN = 3      # was unbounded: measured 39 syntheses / 300k tokens a day


def evaluate_entity_spikes(window_hours: int = 12, synthesize: bool = True) -> dict:
    """The former standalone TrendScan, folded in (author, 2026-09-24): an
    entity named by the summaries of several distinct refined threads within
    the window is a cross-thread signal — the one kind of resonance a single
    thread cannot show. Tighter than before: three threads not two, one alert
    per entity per day, at most three syntheses per run. Writes TrendAlert
    (the dashboard's existing feed) so nothing downstream changes."""
    import json
    from db.database import get_session
    from db.models import StoryThread, TrendAlert
    from sqlmodel import select
    cutoff = _now() - timedelta(hours=window_hours)
    dedup_cut = _now() - timedelta(hours=ENTITY_SPIKE_DEDUP_HOURS)
    made = 0
    with get_session() as session:
        threads = session.exec(select(StoryThread)
                               .where(StoryThread.validity_category.in_(["[VALID_NEWS]", "VALID_NEWS"]))
                               .where(StoryThread.summary.is_not(None))
                               .where(StoryThread.summarized_at >= cutoff)).all()
        by_entity = {}
        for th in threads:
            try:
                ents = json.loads(th.key_entities or "[]")
            except Exception:
                continue
            for e in ents:
                k = (e or "").strip().upper()
                if k:
                    by_entity.setdefault(k, {"name": e.strip(), "threads": {}})["threads"][th.id] = th
        spikes = sorted(((d for d in by_entity.values() if len(d["threads"]) >= ENTITY_SPIKE_MIN_THREADS)),
                        key=lambda d: -len(d["threads"]))
        for d in spikes:
            if made >= ENTITY_SPIKE_MAX_PER_RUN:
                break
            if session.exec(select(TrendAlert).where(TrendAlert.entity_name == d["name"],
                                                     TrendAlert.created_at >= dedup_cut)).first():
                continue
            ths = list(d["threads"].values())
            text = None
            if synthesize:
                try:
                    from services.llm_provider import get_provider
                    from llm.processor import _record_usage, get_target_language
                    p = get_provider()
                    if getattr(p, "supports_generation", False):
                        body = "\n---\n".join(f"{t.title}\n{(t.summary or '')[:800]}" for t in ths[:6])
                        text, usage = p.generate(
                            body, temperature=0.2, thinking_level="low",
                            system=(f"Several distinct stories in the last {window_hours} hours involve "
                                    f"'{d['name']}'. In one short paragraph, in {get_target_language()}, say "
                                    "what is happening with it across these stories — facts only, no hype."))
                        _record_usage(p.name, "EntitySpike", usage)
                except Exception as e:
                    logger.warning(f"Entity-spike synthesis failed for {d['name']}: {e}")
            session.add(TrendAlert(entity_name=d["name"], alert_summary=text or f"{d['name']}: {len(ths)} stories",
                                   related_article_ids=",".join(str(t.id) for t in ths)))
            session.commit()
            made += 1
            logger.info(f"Entity spike: '{d['name']}' across {len(ths)} threads")
    return {"spikes": len(spikes), "alerts": made}


def get_undelivered_alerts(limit: int = 20) -> list:
    """Alerts not yet pushed as OS notifications (for the desktop delivery poll)."""
    from db.database import get_session
    from db.models import RadarAlert
    with get_session() as session:
        return session.exec(
            select(RadarAlert).where(RadarAlert.delivered == False)
            .order_by(RadarAlert.created_at.desc()).limit(limit)
        ).all()
