"""Response models for GET /api/stats/guiding.

The frontend Guiding section is written against these shapes in parallel;
field names, nullability and array ordering are load-bearing. Every float is
nullable: an RMS is None whenever no session in the group cleared
phd2_metrics.MIN_FRAMES, and a ratio or percentage is None when its
denominator is zero.
"""
from typing import Literal

from pydantic import BaseModel


class GuidingRig(BaseModel):
    telescope: str
    session_count: int
    gated_session_count: int
    guided_hours: float
    rms_total_arcsec: float | None = None
    rms_ra_arcsec: float | None = None
    rms_dec_arcsec: float | None = None
    rms_total_filtered_arcsec: float | None = None
    ra_dec_ratio: float | None = None
    peak_ra_arcsec: float | None = None
    peak_dec_arcsec: float | None = None
    star_lost_pct: float | None = None
    unguided_minutes: float
    dither_count: int
    settle_median_s: float | None = None
    settle_fail_pct: float | None = None
    exposure_ms_values: list[int]
    first_night: str | None = None
    last_night: str | None = None


class GuidingSettingsRow(BaseModel):
    telescope: str
    algo_ra: str | None = None
    algo_dec: str | None = None
    exposure_ms: int | None = None
    dec_guide_mode: str | None = None
    session_count: int
    guided_hours: float
    rms_total_arcsec: float | None = None
    rms_ra_arcsec: float | None = None
    rms_dec_arcsec: float | None = None
    star_lost_pct: float | None = None


class GuidingPierSideRow(BaseModel):
    telescope: str
    pier_side: str
    session_count: int
    rms_total_arcsec: float | None = None
    rms_ra_arcsec: float | None = None
    rms_dec_arcsec: float | None = None


class GuidingAltitudeBandRow(BaseModel):
    telescope: str
    band: Literal["<30", "30-60", ">60"]
    session_count: int
    rms_total_arcsec: float | None = None
    rms_ra_arcsec: float | None = None
    rms_dec_arcsec: float | None = None


class GuidingStarLostReason(BaseModel):
    telescope: str
    reason: str
    count: int


class GuidingMonthlyRow(BaseModel):
    telescope: str
    month: str
    session_count: int
    guided_hours: float
    rms_total_arcsec: float | None = None
    rms_ra_arcsec: float | None = None
    rms_dec_arcsec: float | None = None
    star_lost_pct: float | None = None


class GuidingCalibrationRow(BaseModel):
    telescope: str
    started_at: str
    equipment_profile: str | None = None
    completed: bool
    pier_side: str | None = None
    dec_deg: float | None = None
    west_angle_deg: float | None = None
    north_angle_deg: float | None = None
    ortho_error_deg: float | None = None
    west_rate_arcsec_s: float | None = None
    north_rate_arcsec_s: float | None = None
    ra_guide_speed: float | None = None
    dec_guide_speed: float | None = None


class GuidingStatsResponse(BaseModel):
    unmapped_session_count: int
    rigs: list[GuidingRig]
    settings: list[GuidingSettingsRow]
    pier_side: list[GuidingPierSideRow]
    altitude_bands: list[GuidingAltitudeBandRow]
    star_lost_reasons: list[GuidingStarLostReason]
    monthly: list[GuidingMonthlyRow]
    calibrations: list[GuidingCalibrationRow]
