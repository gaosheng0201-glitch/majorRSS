"""User-started runs as background tasks (engineering_baseline §3.3).

"Run and trace", the trial run and "check this monitor now" used to scrape
inside the HTTP request: the UI held a request open for up to three minutes
(some call sites still on the 15 s default and timing out while the run
continued), and "run and trace" then read back the newest run of that target
— which a scheduled scrape could have written instead.

Now the endpoint validates its input, hands the work to this small pool and
returns a task id at once; the client polls GET /tasks/{id} for status and
the result. The work is recorded in TaskRequest (job types USER_*, never
retried: a user can press the button again), so a task outlives a lost poll,
and the scheduler's poller never picks these up. Two workers: user runs don't
queue behind the scheduled scrapes, and each worker keeps its pooled browser
between runs (services/browser_pool.py is thread-local).
"""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

from services.log_service import get_logger

logger = get_logger("tasks")

USER_PREFIX = "USER_"
# Tasks RUNNING from before this moment were cut off by a restart.
PROCESS_STARTED = datetime.now(timezone.utc).replace(tzinfo=None)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="usertask")


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def submit(job_type: str, fn: Callable[[], Any], target_type: str = "", target_id: str = "") -> int:
    """Start `fn` in the background; return the TaskRequest id to poll."""
    from db.database import get_session
    from db.models import TaskRequest
    with get_session() as s:
        task = TaskRequest(job_type=USER_PREFIX + job_type, target_type=target_type,
                           target_id=str(target_id), status="RUNNING", started_at=_now(),
                           max_retries=0)
        s.add(task); s.commit(); s.refresh(task)
        task_id = task.id

    def run():
        from fastapi.encoders import jsonable_encoder
        status, payload, error = "COMPLETED", None, None
        try:
            payload = json.dumps({"result": jsonable_encoder(fn())})
        except Exception as e:
            logger.error(f"Task {task_id} ({job_type}) failed: {e}", exc_info=e)
            status, error = "FAILED", str(getattr(e, "detail", None) or e)[:1000]
        with get_session() as s:
            t = s.get(TaskRequest, task_id)
            if t is not None:
                t.status, t.finished_at, t.error = status, _now(), error
                if payload is not None:
                    t.payload = payload
                s.add(t); s.commit()

    _executor.submit(run)
    return task_id


def get(task_id: int):
    """{id, job_type, status, result, error} or None."""
    from db.database import get_session
    from db.models import TaskRequest
    with get_session() as s:
        t = s.get(TaskRequest, task_id)
        if t is None:
            return None
        result = None
        if t.payload:
            try:
                result = json.loads(t.payload).get("result")
            except Exception:
                result = None
        return {"id": t.id, "job_type": t.job_type, "status": t.status,
                "result": result, "error": t.error,
                "started_at": t.started_at, "finished_at": t.finished_at}
