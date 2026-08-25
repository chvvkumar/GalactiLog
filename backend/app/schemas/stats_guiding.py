"""Response models for GET /api/stats/guiding.

The frontend Guiding section is written against these shapes; field names,
nullability and array ordering are load-bearing. Every float is nullable: an
RMS is None whenever no session in the group cleared phd2_metrics.MIN_FRAMES,
and a ratio is None when its denominator is zero.
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
    settle_median_s: float | None = None
    exposure_ms_values: list[int]


class GuidingAltitudeBandRow(BaseModel):
    telescope: str
    band: Literal["<30", "30-60", ">60"]
    session_count: int
    rms_total_arcsec: float | None = None
    rms_ra_arcsec: float | None = None
    rms_dec_arcsec: float | None = None


class GuidingStatsResponse(BaseModel):
    unmapped_session_count: int
    rigs: list[GuidingRig]
    altitude_bands: list[GuidingAltitudeBandRow]
