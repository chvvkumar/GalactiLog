from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .targets import router as targets_router
from .scan import router as scan_router
from .stats import router as stats_router
from .settings import router as settings_router
from .merges import router as merges_router
from .auth import router as auth_router
from .analysis import router as analysis_router
from app.database import async_session
from app.config import async_redis

api_router = APIRouter(prefix="/api")
api_router.include_router(targets_router)
api_router.include_router(scan_router)
api_router.include_router(stats_router)
api_router.include_router(settings_router)
api_router.include_router(merges_router)
api_router.include_router(auth_router)
api_router.include_router(analysis_router)


@api_router.get("/health")
async def health():
    checks = {"postgres": "ok", "redis": "ok"}

    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        checks["postgres"] = "unavailable"

    try:
        async with async_redis() as r:
            await r.ping()
    except Exception:
        checks["redis"] = "unavailable"

    healthy = all(v == "ok" for v in checks.values())
    status_code = 200 if healthy else 503
    return JSONResponse(
        content={"status": "ok" if healthy else "degraded", **checks},
        status_code=status_code,
    )
