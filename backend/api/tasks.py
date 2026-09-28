from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/{task_id}")
def get_task(task_id: int):
    """Status and result of a background run (services/task_runner.py) or a
    queued job: {id, job_type, status, result, error, started_at, finished_at}.
    status: PENDING | RUNNING | COMPLETED | FAILED | SKIPPED."""
    from services.task_runner import get
    t = get(task_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return t
