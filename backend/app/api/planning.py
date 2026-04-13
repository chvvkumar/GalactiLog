"""Planning API - imaging session planning endpoints."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.api.stats import _extract_site_coords
from app.services.usno import get_night_ephemeris

router = APIRouter(prefix="/planning", tags=["planning"])


@router.get("/night")
async def get_night(date: str = Query(..., description="Date in YYYY-MM-DD format")):
    """Return astronomical twilight times and moon data for a given night.

    Observer location is derived from FITS header site coordinates.
    """
    async with async_session() as session:
        site_coords = await _extract_site_coords(session)

    if site_coords is None:
        raise HTTPException(
            status_code=400,
            detail="Observer location not available. Ensure your FITS files contain site coordinates (SITELAT/SITELONG).",
        )

    result = await asyncio.to_thread(
        get_night_ephemeris, date, site_coords.latitude, site_coords.longitude
    )
    return result
