"""Live background-job listing for the nav job monitor.

Serves the registry that app.worker.job_registry's Celery signals maintain:
every queued or running task not already covered by the richer scan/rebuild
status sources. Read-only; the registry cleans itself up via task_postrun
and entry TTLs.
"""
from fastapi import APIRouter, Depends

from app.api.deps import require_admin
from app.config import async_redis
from app.models.user import User
from app.schemas.tasks import JobEntry, JobsResponse
from app.worker.job_registry import JOB_ENTRY_PREFIX, JOBS_ACTIVE_SET

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _as_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@router.get("", response_model=JobsResponse)
async def list_jobs(user: User = Depends(require_admin)) -> JobsResponse:
    async with async_redis() as r:
        task_ids = sorted(await r.smembers(JOBS_ACTIVE_SET))
        if not task_ids:
            return JobsResponse(jobs=[])
        pipe = r.pipeline()
        for task_id in task_ids:
            pipe.hgetall(JOB_ENTRY_PREFIX + task_id)
        entries = await pipe.execute()

        jobs: list[JobEntry] = []
        orphans: list[str] = []
        for task_id, entry in zip(task_ids, entries):
            # An id whose hash TTL-expired (worker SIGKILL, Redis restart) is
            # stale set residue; drop it here so it cannot accumulate.
            if not entry or "name" not in entry:
                orphans.append(task_id)
                continue
            jobs.append(JobEntry(
                task_id=task_id,
                name=entry["name"],
                state=entry.get("state", "queued"),
                queued_at=_as_float(entry.get("queued_at")),
                started_at=_as_float(entry.get("started_at")),
                eta=entry.get("eta"),
            ))
        if orphans:
            await r.srem(JOBS_ACTIVE_SET, *orphans)

    # Running first, then longest-queued first: the panel renders in order.
    jobs.sort(key=lambda j: (
        0 if j.state == "running" else 1,
        j.started_at or j.queued_at or 0.0,
    ))
    return JobsResponse(jobs=jobs)
