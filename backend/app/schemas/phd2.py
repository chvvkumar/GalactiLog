"""Response models for /api/phd2 and the session-detail night summary.

These shapes are a contract with the frontend, which is written against them
in parallel. Field names and nullability are load-bearing: renaming one here
silently breaks a chart there.
"""
from datetime import date, datetime

from pydantic import BaseModel


class Phd2SessionSummary(BaseModel):
    """One guiding session as shown on a session card or in the guide list.

    RMS values are returned even for gated sessions; `gated` says the sample
    is too small to compare (frame_count < phd2_metrics.MIN_FRAMES) so the UI
    can show the number with a caveat rather than hiding it.
    """

    id: str
    started_at: datetime
    ended_at: datetime | None = None
    duration_s: float
    frame_count: int
    equipment_profile: str
    telescope: str | None = None
    pixel_scale_arcsec: float | None = None
    rms_ra_arcsec: float | None = None
    rms_dec_arcsec: float | None = None
    rms_total_arcsec: float | None = None
    peak_ra_arcsec: float | None = None
    peak_dec_arcsec: float | None = None
    drop_count: int
    max_drop_run: int
    unguided_seconds: float
    dither_count: int
    settle_count: int
    settle_failed_count: int
    settle_median_s: float | None = None
    snr_mean: float | None = None
    star_mass_mean: float | None = None
    last_cal_issue: str | None = None
    pier_side: str | None = None
    gated: bool


class Phd2SessionListResponse(BaseModel):
    sessions: list[Phd2SessionSummary]


class Phd2FramePoint(BaseModel):
    """One guide-graph point. ra/dec are arcsec, converted from stored pixels."""

    t: float
    ra: float | None = None
    dec: float | None = None
    ra_pulse_ms: int
    ra_dir: str
    dec_pulse_ms: int
    dec_dir: str
    snr: float | None = None
    mass: float | None = None
    dropped: bool


class Phd2EventPoint(BaseModel):
    """A marker on the guide graph.

    `type` is one of: dither, settle_start, settle_done, settle_failed,
    star_lost, param_change, lock_shift.
    """

    type: str
    t: float
    detail: str


class Phd2FramesResponse(BaseModel):
    pixel_scale_arcsec: float | None = None
    started_at: datetime
    frames: list[Phd2FramePoint]
    events: list[Phd2EventPoint]


class Phd2ProfileInfo(BaseModel):
    """A PHD2 equipment profile as seen in the corpus, for the mapping UI.

    The guide camera, focal length and pixel scale are echoed from the log
    headers so a user can tell two similarly named profiles apart without
    opening a log.
    """

    name: str
    guide_camera: str | None = None
    focal_length_mm: float | None = None
    pixel_scale_arcsec: float | None = None
    session_count: int
    first_seen: date | None = None
    last_seen: date | None = None
    mapped_telescope: str | None = None


class Phd2ProfilesResponse(BaseModel):
    profiles: list[Phd2ProfileInfo]


class Phd2NightSummary(BaseModel):
    """Night+rig guiding rollup attached to a session-detail response.

    RMS figures are frame-count weighted across the sessions long enough to
    mean anything; gated_session_count reports how many were left out. Event
    counts include every session regardless of length. settle_median_s is the
    median of the per-session medians, not a pooled median over every settle
    in the night.
    """

    session_count: int
    gated_session_count: int
    frame_count: int
    rms_ra_arcsec: float | None = None
    rms_dec_arcsec: float | None = None
    rms_total_arcsec: float | None = None
    drop_count: int
    max_drop_run: int
    unguided_seconds: float
    dither_count: int
    settle_failed_count: int
    settle_median_s: float | None = None
    cal_issues: list[str] = []
    profiles: list[str] = []
