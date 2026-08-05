"""PHD2 guiding endpoints: session list, frame series, equipment profiles.

Auth follows the project's structural choke point: this application has no
global auth middleware and no router-level dependency list, so every endpoint
declares `user: User = Depends(get_current_user)` itself. An endpoint that
omits it is public.
"""
import logging
import uuid
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_session
from app.models.phd2 import Phd2Frame, Phd2Session
from app.models.user import User
from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
from app.schemas.phd2 import (
    Phd2EventPoint, Phd2FramePoint, Phd2FramesResponse, Phd2ProfileInfo,
    Phd2ProfilesResponse, Phd2SessionListResponse, Phd2SessionSummary,
)
from app.services import phd2_profiles
from app.services.normalization import load_telescope_match_set
from app.services.phd2_metrics import MIN_FRAMES, select_phd2_night_rows

router = APIRouter(prefix="/phd2", tags=["phd2"])
logger = logging.getLogger(__name__)


async def _profile_map(session: AsyncSession) -> dict[str, str]:
    row = (
        await session.execute(
            select(UserSettings).where(UserSettings.id == SETTINGS_ROW_ID)
        )
    ).scalar_one_or_none()
    general = (row.general if row else {}) or {}
    return phd2_profiles.telescope_map(general.get("phd2_profile_map"))


@router.get("/sessions", response_model=Phd2SessionListResponse)
async def list_phd2_sessions(
    session_date: date_type = Query(..., description="Imaging night, YYYY-MM-DD"),
    telescope: str | None = Query(None, description="images.telescope value"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Guiding sessions for one night, optionally narrowed to one rig.

    Sessions are never merged: two PHD2 instances on two rigs produce
    overlapping wall-clock sessions with different pixel scales, and a caller
    that wants one rig says so.

    `telescope` is the value the session detail reports under
    `equipment.telescope`, and is resolved against the equipment alias map
    before matching: the profile map holds whichever name was on offer when
    the profile was mapped, which is not necessarily the canonical one, and
    grouping equipment later never rewrites it.

    Narrowing uses the same rule as the session-detail night summary: rows
    mapped to this telescope, or, when the night's sole profile is unmapped,
    that profile's rows. A profile mapped to a different rig is never returned
    here; the user already said where it belongs. A strict equality filter
    disagreed with that rule for every install whose profile map is still
    empty: the summary strip rendered through the fallback while this route
    returned nothing, so the card showed guiding numbers above an empty graph.
    """
    query = (
        select(Phd2Session)
        .where(Phd2Session.session_date == session_date)
        .order_by(Phd2Session.started_at_utc)
    )
    rows = (await session.execute(query)).scalars().all()
    if telescope:
        wanted = await load_telescope_match_set(session, [telescope])
        rows = select_phd2_night_rows(rows, wanted)
    return Phd2SessionListResponse(sessions=[
        Phd2SessionSummary(
            id=str(row.id),
            started_at=row.started_at_utc,
            ended_at=row.ended_at_utc,
            duration_s=row.duration_s,
            frame_count=row.frame_count,
            equipment_profile=row.equipment_profile or "",
            telescope=row.telescope,
            pixel_scale_arcsec=row.pixel_scale_arcsec,
            rms_ra_arcsec=row.rms_ra_arcsec,
            rms_dec_arcsec=row.rms_dec_arcsec,
            rms_total_arcsec=row.rms_total_arcsec,
            peak_ra_arcsec=row.peak_ra_arcsec,
            peak_dec_arcsec=row.peak_dec_arcsec,
            drop_count=row.drop_count,
            max_drop_run=row.max_drop_run,
            unguided_seconds=row.unguided_seconds,
            dither_count=row.dither_count,
            settle_count=row.settle_count,
            settle_failed_count=row.settle_failed_count,
            settle_median_s=row.settle_median_s,
            snr_mean=row.snr_mean,
            star_mass_mean=row.star_mass_mean,
            last_cal_issue=row.last_cal_issue,
            pier_side=row.pier_side,
            gated=row.frame_count < MIN_FRAMES,
        )
        for row in rows
    ])


@router.get("/sessions/{id}/frames", response_model=Phd2FramesResponse)
async def get_phd2_session_frames(
    id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """The full frame series and event markers for one guiding session.

    Pixels are converted to arcsec here using the session's own pixel scale.
    Frames are stored in pixels precisely so a corrected pixel scale changes
    this response without touching a single stored row.
    """
    parent = (
        await session.execute(
            select(Phd2Session).where(Phd2Session.id == id)
        )
    ).scalar_one_or_none()
    if parent is None:
        raise HTTPException(status_code=404, detail="PHD2 session not found")

    scale = parent.pixel_scale_arcsec
    rows = (
        await session.execute(
            select(Phd2Frame)
            .where(Phd2Frame.session_id == id)
            .order_by(Phd2Frame.time_offset)
        )
    ).scalars().all()

    def _arcsec(value):
        if value is None or scale is None:
            return None
        return round(value * scale, 6)

    return Phd2FramesResponse(
        pixel_scale_arcsec=scale,
        started_at=parent.started_at_utc,
        frames=[
            Phd2FramePoint(
                t=row.time_offset,
                ra=_arcsec(row.ra_raw),
                dec=_arcsec(row.dec_raw),
                ra_pulse_ms=row.ra_duration_ms,
                ra_dir=row.ra_direction,
                dec_pulse_ms=row.dec_duration_ms,
                dec_dir=row.dec_direction,
                snr=row.snr,
                mass=row.star_mass,
                dropped=row.dropped,
            )
            for row in rows
        ],
        events=[
            Phd2EventPoint(
                type=event.get("type", ""),
                t=float(event.get("t", 0.0)),
                detail=event.get("detail", ""),
            )
            for event in (parent.events or [])
        ],
    )


@router.get("/profiles", response_model=Phd2ProfilesResponse)
async def list_phd2_profiles(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Every equipment profile seen in the ingested logs, with mapping status.

    Drives the settings screen where profiles are mapped onto telescope names.
    The helper metadata (guide camera, focal length, pixel scale) is a
    per-column maximum across the profile's sessions, not one representative
    session: the columns are near-constant for a given profile, and an
    aggregate needs no correlated subquery to pick a row.
    """
    query = (
        select(
            Phd2Session.equipment_profile,
            func.max(Phd2Session.guide_camera),
            func.max(Phd2Session.focal_length_mm),
            func.max(Phd2Session.pixel_scale_arcsec),
            func.count(Phd2Session.id),
            func.min(Phd2Session.session_date),
            func.max(Phd2Session.session_date),
        )
        .where(Phd2Session.equipment_profile.isnot(None))
        .group_by(Phd2Session.equipment_profile)
        .order_by(Phd2Session.equipment_profile)
    )
    rows = (await session.execute(query)).all()
    mapping = await _profile_map(session)
    return Phd2ProfilesResponse(profiles=[
        Phd2ProfileInfo(
            name=name,
            guide_camera=camera,
            focal_length_mm=focal,
            pixel_scale_arcsec=scale,
            session_count=count,
            first_seen=first_seen,
            last_seen=last_seen,
            mapped_telescope=mapping.get(name),
        )
        for name, camera, focal, scale, count, first_seen, last_seen in rows
    ])
