"""GET /api/stats/guiding: per-rig PHD2 guiding aggregates for the Statistics page.

Auth follows the project's structural choke point: no global middleware, so
the endpoint declares `user: User = Depends(get_current_user)` itself.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_session
from app.models.user import User
from app.schemas.stats_guiding import GuidingStatsResponse
from app.services.cache import GUIDING_STATS_CACHE_KEY, GUIDING_STATS_CACHE_TTL, cached_json
from app.services.phd2_stats import compute_guiding_stats

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/guiding", response_model=GuidingStatsResponse)
async def get_guiding_stats(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    async def _compute():
        return (await compute_guiding_stats(session)).model_dump(mode="json")

    return await cached_json(GUIDING_STATS_CACHE_KEY, GUIDING_STATS_CACHE_TTL, _compute)
