"""Per-rig PHD2 guiding aggregates behind GET /api/stats/guiding.

One SELECT and Python dict grouping: the sessions table is a few hundred to a
few thousand rows, and every figure here is a frame-count weighted RMS or a
plain sum, which is cheaper to write once in Python than to express three ways
in SQL. The rig key is the canonical telescope from the alias map, so two
spellings of one scope land in one row.

RMS weighting is delegated to phd2_metrics._weighted_rms, the same function
the session-detail night summary uses, so the Statistics page and a session
card never disagree about what a night's RMS was.
"""
from __future__ import annotations

import statistics
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.phd2 import Phd2Session
from app.schemas.stats_guiding import (
    GuidingAltitudeBandRow, GuidingRig, GuidingStatsResponse,
)
from app.services.normalization import load_alias_maps, normalize_equipment
from app.services.phd2_metrics import MIN_FRAMES, _weighted_rms

ALTITUDE_BANDS = ("<30", "30-60", ">60")


def altitude_band(alt: float | None) -> str | None:
    if alt is None:
        return None
    if alt < 30:
        return "<30"
    if alt < 60:
        return "30-60"
    return ">60"


def _rms_fields(rows) -> dict:
    return {
        "rms_total_arcsec": _weighted_rms(rows, "rms_total_arcsec"),
        "rms_ra_arcsec": _weighted_rms(rows, "rms_ra_arcsec"),
        "rms_dec_arcsec": _weighted_rms(rows, "rms_dec_arcsec"),
    }


def _rig(telescope: str, rows) -> GuidingRig:
    rms = _rms_fields(rows)
    ra, dec = rms["rms_ra_arcsec"], rms["rms_dec_arcsec"]
    settle_medians = [r.settle_median_s for r in rows if r.settle_median_s is not None]
    return GuidingRig(
        telescope=telescope,
        session_count=len(rows),
        gated_session_count=sum(1 for r in rows if r.frame_count < MIN_FRAMES),
        guided_hours=round(sum(r.duration_s or 0.0 for r in rows) / 3600, 2),
        **rms,
        rms_total_filtered_arcsec=_weighted_rms(rows, "rms_total_filtered_arcsec"),
        ra_dec_ratio=dec / ra if ra and dec is not None else None,
        settle_median_s=statistics.median(settle_medians) if settle_medians else None,
        exposure_ms_values=sorted({
            int(round(r.exposure_ms)) for r in rows if r.exposure_ms is not None
        }),
    )


async def compute_guiding_stats(session: AsyncSession) -> GuidingStatsResponse:
    _, _, tel_map = await load_alias_maps(session)

    S = Phd2Session
    session_rows = (await session.execute(select(
        S.telescope, S.duration_s, S.frame_count, S.settle_median_s,
        S.rms_ra_arcsec, S.rms_dec_arcsec, S.rms_total_arcsec,
        S.rms_total_filtered_arcsec, S.exposure_ms, S.alt_deg,
    ))).all()

    by_rig: dict[str, list] = defaultdict(list)
    by_band: dict[tuple[str, str], list] = defaultdict(list)
    unmapped = 0

    for r in session_rows:
        if r.telescope is None:
            unmapped += 1
            continue
        tel = normalize_equipment(r.telescope, tel_map)
        by_rig[tel].append(r)
        band = altitude_band(r.alt_deg)
        if band is not None:
            by_band[(tel, band)].append(r)

    return GuidingStatsResponse(
        unmapped_session_count=unmapped,
        rigs=[_rig(tel, rows) for tel, rows in sorted(by_rig.items())],
        altitude_bands=[
            GuidingAltitudeBandRow(telescope=tel, band=band,
                                   session_count=len(rows), **_rms_fields(rows))
            for (tel, band), rows in sorted(
                by_band.items(), key=lambda kv: (kv[0][0], ALTITUDE_BANDS.index(kv[0][1]))
            )
        ],
    )
