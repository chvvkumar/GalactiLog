"""Per-rig PHD2 guiding aggregates behind GET /api/stats/guiding.

Two SELECTs (sessions, calibrations) and Python dict grouping: the sessions
table is a few hundred to a few thousand rows, and every figure here is a
frame-count weighted RMS or a plain sum, which is cheaper to write once in
Python than to express five ways in SQL. The rig key is the canonical
telescope from the alias map, so two spellings of one scope land in one row.

RMS weighting is delegated to phd2_metrics._weighted_rms, the same function
the session-detail night summary uses, so the Statistics page and a session
card never disagree about what a night's RMS was.
"""
from __future__ import annotations

import statistics
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.phd2 import Phd2Calibration, Phd2Session
from app.schemas.stats_guiding import (
    GuidingAltitudeBandRow, GuidingCalibrationRow, GuidingMonthlyRow,
    GuidingPierSideRow, GuidingRig, GuidingSettingsRow, GuidingStarLostReason,
    GuidingStatsResponse,
)
from app.services.normalization import load_alias_maps, normalize_equipment
from app.services.phd2_metrics import MIN_FRAMES, _weighted_rms

CALIBRATIONS_PER_RIG = 10
ALTITUDE_BANDS = ("<30", "30-60", ">60")


def altitude_band(alt: float | None) -> str | None:
    if alt is None:
        return None
    if alt < 30:
        return "<30"
    if alt < 60:
        return "30-60"
    return ">60"


def ortho_error_deg(west: float | None, north: float | None) -> float | None:
    """Departure of the RA/Dec calibration axes from 90 degrees.

    The two angles come straight from the log and can differ by any multiple
    of 180 (an axis has no preferred direction), so the difference is folded
    into [0, 180] before comparing with 90.
    """
    if west is None or north is None:
        return None
    d = abs(west - north) % 180
    return abs(d - 90)


def _pct(num: float, den: float) -> float | None:
    return 100 * num / den if den else None


def _rms_fields(rows) -> dict:
    return {
        "rms_total_arcsec": _weighted_rms(rows, "rms_total_arcsec"),
        "rms_ra_arcsec": _weighted_rms(rows, "rms_ra_arcsec"),
        "rms_dec_arcsec": _weighted_rms(rows, "rms_dec_arcsec"),
    }


def _hours(rows) -> float:
    return round(sum(r.duration_s or 0.0 for r in rows) / 3600, 2)


def _star_lost_pct(rows) -> float | None:
    return _pct(sum(r.drop_count for r in rows), sum(r.frame_count for r in rows))


def _rig(telescope: str, rows) -> GuidingRig:
    eligible = [r for r in rows if r.frame_count >= MIN_FRAMES]
    rms = _rms_fields(rows)
    ra, dec = rms["rms_ra_arcsec"], rms["rms_dec_arcsec"]
    settle_medians = [r.settle_median_s for r in rows if r.settle_median_s is not None]
    peaks_ra = [r.peak_ra_arcsec for r in eligible if r.peak_ra_arcsec is not None]
    peaks_dec = [r.peak_dec_arcsec for r in eligible if r.peak_dec_arcsec is not None]
    nights = [r.session_date for r in rows if r.session_date is not None]
    return GuidingRig(
        telescope=telescope,
        session_count=len(rows),
        gated_session_count=len(rows) - len(eligible),
        guided_hours=_hours(rows),
        **rms,
        rms_total_filtered_arcsec=_weighted_rms(rows, "rms_total_filtered_arcsec"),
        ra_dec_ratio=dec / ra if ra and dec is not None else None,
        peak_ra_arcsec=max(peaks_ra) if peaks_ra else None,
        peak_dec_arcsec=max(peaks_dec) if peaks_dec else None,
        star_lost_pct=_star_lost_pct(rows),
        unguided_minutes=sum(r.unguided_seconds or 0.0 for r in rows) / 60,
        dither_count=sum(r.dither_count for r in rows),
        settle_median_s=statistics.median(settle_medians) if settle_medians else None,
        settle_fail_pct=_pct(
            sum(r.settle_failed_count for r in rows), sum(r.settle_count for r in rows)
        ),
        exposure_ms_values=sorted({
            int(round(r.exposure_ms)) for r in rows if r.exposure_ms is not None
        }),
        first_night=min(nights).isoformat() if nights else None,
        last_night=max(nights).isoformat() if nights else None,
    )


def _exposure_key(value: float | None) -> int | None:
    return None if value is None else int(round(value))


def _calibration(telescope: str, c) -> GuidingCalibrationRow:
    scale = c.pixel_scale_arcsec

    def _rate(px_s):
        return px_s * scale if px_s is not None and scale is not None else None

    return GuidingCalibrationRow(
        telescope=telescope,
        started_at=c.started_at_utc.isoformat(),
        equipment_profile=c.equipment_profile,
        completed=bool(c.completed),
        pier_side=c.pier_side,
        dec_deg=c.dec_deg,
        west_angle_deg=c.west_angle_deg,
        north_angle_deg=c.north_angle_deg,
        ortho_error_deg=ortho_error_deg(c.west_angle_deg, c.north_angle_deg),
        west_rate_arcsec_s=_rate(c.west_rate_px_s),
        north_rate_arcsec_s=_rate(c.north_rate_px_s),
        ra_guide_speed=c.ra_guide_speed,
        dec_guide_speed=c.dec_guide_speed,
    )


async def compute_guiding_stats(session: AsyncSession) -> GuidingStatsResponse:
    _, _, tel_map = await load_alias_maps(session)

    S = Phd2Session
    session_rows = (await session.execute(select(
        S.telescope, S.session_date, S.duration_s, S.frame_count, S.drop_count,
        S.unguided_seconds, S.dither_count, S.settle_count, S.settle_failed_count,
        S.settle_median_s, S.peak_ra_arcsec, S.peak_dec_arcsec,
        S.rms_ra_arcsec, S.rms_dec_arcsec, S.rms_total_arcsec,
        S.rms_total_filtered_arcsec, S.exposure_ms, S.algo_ra, S.algo_dec,
        S.dec_guide_mode, S.pier_side, S.alt_deg, S.star_lost_reasons,
    ))).all()

    C = Phd2Calibration
    cal_rows = (await session.execute(select(
        C.telescope, C.started_at_utc, C.equipment_profile, C.completed,
        C.pier_side, C.dec_deg, C.west_angle_deg, C.north_angle_deg,
        C.west_rate_px_s, C.north_rate_px_s, C.pixel_scale_arcsec,
        C.ra_guide_speed, C.dec_guide_speed,
    ).where(C.telescope.is_not(None)).order_by(C.started_at_utc.desc()))).all()

    by_rig: dict[str, list] = defaultdict(list)
    by_settings: dict[tuple, list] = defaultdict(list)
    by_pier: dict[tuple[str, str], list] = defaultdict(list)
    by_band: dict[tuple[str, str], list] = defaultdict(list)
    by_month: dict[tuple[str, str], list] = defaultdict(list)
    reasons: dict[tuple[str, str], int] = defaultdict(int)
    unmapped = 0

    for r in session_rows:
        if r.telescope is None:
            unmapped += 1
            continue
        tel = normalize_equipment(r.telescope, tel_map)
        by_rig[tel].append(r)
        by_settings[(tel, r.algo_ra, r.algo_dec, _exposure_key(r.exposure_ms), r.dec_guide_mode)].append(r)
        if r.pier_side is not None:
            by_pier[(tel, r.pier_side)].append(r)
        band = altitude_band(r.alt_deg)
        if band is not None:
            by_band[(tel, band)].append(r)
        if r.session_date is not None:
            by_month[(tel, r.session_date.strftime("%Y-%m"))].append(r)
        for reason, count in (r.star_lost_reasons or {}).items():
            reasons[(tel, reason)] += int(count)

    settings = [
        GuidingSettingsRow(
            telescope=tel, algo_ra=algo_ra, algo_dec=algo_dec,
            exposure_ms=exposure_ms, dec_guide_mode=dec_mode,
            session_count=len(rows), guided_hours=_hours(rows),
            **_rms_fields(rows), star_lost_pct=_star_lost_pct(rows),
        )
        for (tel, algo_ra, algo_dec, exposure_ms, dec_mode), rows in by_settings.items()
    ]
    settings.sort(key=lambda s: (
        s.telescope, s.rms_total_arcsec is None, s.rms_total_arcsec or 0.0,
    ))

    cals_by_rig: dict[str, list] = defaultdict(list)
    for c in cal_rows:
        tel = normalize_equipment(c.telescope, tel_map)
        if len(cals_by_rig[tel]) < CALIBRATIONS_PER_RIG:
            cals_by_rig[tel].append(_calibration(tel, c))

    return GuidingStatsResponse(
        unmapped_session_count=unmapped,
        rigs=[_rig(tel, rows) for tel, rows in sorted(by_rig.items())],
        settings=settings,
        pier_side=[
            GuidingPierSideRow(telescope=tel, pier_side=side,
                               session_count=len(rows), **_rms_fields(rows))
            for (tel, side), rows in sorted(by_pier.items())
        ],
        altitude_bands=[
            GuidingAltitudeBandRow(telescope=tel, band=band,
                                   session_count=len(rows), **_rms_fields(rows))
            for (tel, band), rows in sorted(
                by_band.items(), key=lambda kv: (kv[0][0], ALTITUDE_BANDS.index(kv[0][1]))
            )
        ],
        star_lost_reasons=[
            GuidingStarLostReason(telescope=tel, reason=reason, count=count)
            for (tel, reason), count in sorted(
                reasons.items(), key=lambda kv: (kv[0][0], -kv[1], kv[0][1])
            )
        ],
        monthly=[
            GuidingMonthlyRow(telescope=tel, month=month, session_count=len(rows),
                              guided_hours=_hours(rows), **_rms_fields(rows),
                              star_lost_pct=_star_lost_pct(rows))
            for (tel, month), rows in sorted(by_month.items())
        ],
        calibrations=[c for tel in sorted(cals_by_rig) for c in cals_by_rig[tel]],
    )
