"""
Unified pipeline tracing (R2).

Both the tracker scrape pipeline and the subscription page-diff pipeline write
PipelineRun + PipelineEvent rows with the same shape (create RUNNING run →
append step-indexed events → finalize status). They previously did it with two
divergent inline implementations — one already using error classification and
the NO_NEW_ITEMS status, the other still on print() and SUCCESS/FAILED only.

PipelineTracer is the single way to write a trace, so both pipelines produce
consistent, comparable runs and future stages (semantic layer, UI) read one
schema.
"""
from datetime import datetime, timezone
from typing import Optional

from services.log_service import get_logger
from services.privacy import scrub_sensitive_info

logger = get_logger("trace")


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PipelineTracer:
    def __init__(self, session, run):
        self.session = session
        self.run = run
        self._step = 0

    @classmethod
    def start(cls, session, *, tracker_id: Optional[int] = None,
              subscription_id: Optional[int] = None, normalized_intent: Optional[str] = None):
        from db.models import PipelineRun
        run = PipelineRun(
            tracker_id=tracker_id,
            subscription_id=subscription_id,
            normalized_intent=normalized_intent,
            status="RUNNING",
            started_at=_now(),
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        return cls(session, run)

    @property
    def run_id(self):
        return self.run.id

    def event(self, stage: str, status: str = "SUCCESS", *, route_id: Optional[str] = None,
              adapter: Optional[str] = None, input_data: Optional[str] = None,
              output_summary: Optional[str] = None, error: Optional[str] = None,
              duration_ms: int = 0):
        """Append one step-indexed event. step_index auto-increments."""
        from db.models import PipelineEvent
        self._step += 1
        ev = PipelineEvent(
            run_id=self.run.id,
            step_index=self._step,
            stage=stage,
            route_id=route_id,
            adapter=adapter,
            input_data=input_data,
            output_summary=output_summary,
            status=status,
            error=error,
            duration_ms=duration_ms,
        )
        self.session.add(ev)
        self.session.commit()
        return ev

    def finish(self, status: str, *, total_routes: int = 0, total_items: int = 0,
               accepted_items: int = 0, error_summary: Optional[str] = None,
               cost_browser: bool = False, cost_llm: bool = False):
        self.run.status = status
        self.run.finished_at = _now()
        self.run.total_routes = total_routes
        self.run.total_items = total_items
        self.run.accepted_items = accepted_items
        self.run.cost_flag_browser = cost_browser
        self.run.cost_flag_llm = cost_llm
        if error_summary:
            self.run.error_summary = scrub_sensitive_info(error_summary)[:200]
        self.session.add(self.run)
        self.session.commit()
        return self.run
