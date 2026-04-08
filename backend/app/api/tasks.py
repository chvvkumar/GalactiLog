from fastapi import APIRouter, Depends

from app.api.deps import require_admin
from app.models.user import User
from app.worker.celery_app import celery_app

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/{task_id}/status")
async def get_task_status(task_id: str, user: User = Depends(require_admin)):
    result = celery_app.AsyncResult(task_id)
    response = {"task_id": task_id, "state": result.state, "result": None}
    if result.state == "SUCCESS":
        response["result"] = result.result
    elif result.state == "FAILURE":
        response["result"] = {"error": str(result.result)}
    return response
