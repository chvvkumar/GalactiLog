"""Aggregation of parsed PHD2 guiding sections into storable session rows.

Pure functions over the phd2_parser dataclasses: no DB, no Celery, no HTTP.
The output field names deliberately match the Phd2Session / Phd2Frame /
Phd2Calibration column names one-for-one so the ingest task is a mechanical
splat rather than a translation layer that can drift.

Two conventions here matter for user trust:

1. RMS excludes frames inside dither and settling windows. PHD2's own on-screen
   RMS excludes them, and users will put the two numbers side by side. Without
   the exclusion every dithered session reads several times worse than PHD2
   says it was.
2. RMS is a population standard deviation (statistics.pstdev), matching PHD2's
   own definition of the figure it displays.
"""
from __future__ import annotations

import math
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import date as date_type, datetime, timezone
from zoneinfo import ZoneInfo

from app.services import phd2_parser  # noqa: F401  (documents the input types)
from app.services.session_date import compute_session_date

# Sessions shorter than this contribute their event counts (star loss, dither,
# settle) but not their RMS: a 20-frame fragment around an autofocus run gives
# a standard deviation with no statistical meaning, and roughly 70 of the 800
# sessions in the reference corpus are that short.
MIN_FRAMES = 100

# Excursion filter threshold, in session sigmas. One cable-snag spike can
# inflate a session RMS several-fold (2.6 arcsec with, 0.5 without, in the
# PHD2 analysis guide's worked example), so both figures are stored.
EXCURSION_SIGMA = 5.0


def local_to_utc(naive: datetime, tz_name: str) -> datetime:
    """Interpret a naive PHD2 wall-clock timestamp in `tz_name` and return UTC.

    An empty `tz_name` means "use whatever zone this server is in", which is
    the right default for the common single-machine install and the only
    answer available before the user configures observer_timezone.
    """
    if tz_name:
        localized = naive.replace(tzinfo=ZoneInfo(tz_name))
    else:
        localized = naive.astimezone()
    return localized.astimezone(timezone.utc)


def _windows_from_pairs(
    pairs: list[tuple[str, float]], last_time_offset: float | None
) -> list[tuple[float, float]]:
    """The dither/settle window rule, over (event type, time offset) pairs.

    Factored out so the rule has exactly one implementation. Phase 2 needs it
    against events read back from the stored JSONB rather than against parser
    objects, and two implementations of "which frames does an RMS exclude"
    would eventually disagree - at which point a per-image figure and the
    session figure printed beside it stop describing the same thing.
    """
    windows: list[tuple[float, float]] = []
    open_at: float | None = None
    for kind, t in pairs:
        if kind in ("dither", "settle_start"):
            if open_at is None:
                open_at = t
        elif kind in ("settle_done", "settle_failed"):
            if open_at is not None:
                windows.append((open_at, t))
                open_at = None
    if open_at is not None:
        end = last_time_offset if last_time_offset is not None else open_at
        windows.append((open_at, max(end, open_at)))
    return windows


def dither_settle_windows(section) -> list[tuple[float, float]]:
    """Return [(start_t, end_t)] intervals to exclude from RMS.

    A window opens on the first dither or settle-start that is not already
    inside one, and closes on the next settle-complete or settle-failed. A
    window left open at the end of the section closes at the last frame,
    because PHD2 was still settling when the section ended.
    """
    last_t = section.frames[-1].time_offset if section.frames else None
    return _windows_from_pairs(
        [(e.type, e.time_offset) for e in section.events], last_t
    )


def dither_settle_windows_from_stored(
    events: list[dict], last_time_offset: float | None
) -> list[tuple[float, float]]:
    """dither_settle_windows for events read back from Phd2Session.events.

    The stored shape is [{"type": ..., "t": ..., "detail": ...}] (written by
    compute_session_metrics); the parser shape is Phd2Event objects. Both
    reduce to the same (type, time offset) pairs, and the rule they feed has
    to stay identical in both directions: the phase-2 per-image RMS must
    exclude exactly the frames the session RMS excluded, or PHD2's own
    displayed figure matches one of ours and not the other.
    """
    return _windows_from_pairs(
        [
            (str(e.get("type") or ""), float(e.get("t") or 0.0))
            for e in (events or [])
        ],
        last_time_offset,
    )


def _in_windows(t: float, windows: list[tuple[float, float]]) -> bool:
    """True when frame time `t` falls inside an excluded window.

    The lower bound is exclusive and the upper bound inclusive, because the
    parser stamps an un-timestamped INFO line with the time of the *preceding*
    CSV row. A frame at exactly `start` was therefore written before the
    dither began and is still a legitimately guided sample, while a frame at
    exactly `end` was written while PHD2 was still settling.
    """
    return any(start < t <= end for start, end in windows)


def _rms(values: list[float]) -> float | None:
    if not values:
        return None
    return statistics.pstdev(values)


def _filtered(values: list[float]) -> list[float]:
    """Drop values further than EXCURSION_SIGMA sigmas from zero, once."""
    sigma = _rms(values)
    if not sigma:
        return list(values)
    limit = EXCURSION_SIGMA * sigma
    return [v for v in values if abs(v) <= limit]


def _scale(value: float | None, pixel_scale: float | None) -> float | None:
    if value is None or pixel_scale is None:
        return None
    return round(value * pixel_scale, 6)


@dataclass
class Phd2SessionMetrics:
    """Field-for-field mirror of the Phd2Session columns the parser can fill.

    Excluded on purpose: id and log_id (assigned by the caller), telescope
    (resolved from the profile map, which is a settings concern), insights
    (phase 3), run_index/section_index (positional, known only to the caller).
    """

    started_at_local: datetime
    started_at_utc: datetime
    ended_at_utc: datetime | None
    duration_s: float
    session_date: date_type | None
    equipment_profile: str | None
    pixel_scale_arcsec: float | None
    focal_length_mm: float | None
    guide_camera: str | None
    exposure_ms: float | None
    mount_name: str | None
    dec_guide_mode: str | None
    algo_ra: str | None
    algo_dec: str | None
    min_move_ra: float | None
    min_move_dec: float | None
    aggression_ra: float | None
    ortho_error_deg: float | None
    last_cal_issue: str | None
    pier_side: str | None
    alt_deg: float | None
    az_deg: float | None
    dec_deg: float | None
    hour_angle_hr: float | None
    frame_count: int
    drop_count: int
    max_drop_run: int
    unguided_seconds: float
    rms_ra_arcsec: float | None
    rms_dec_arcsec: float | None
    rms_total_arcsec: float | None
    rms_ra_filtered_arcsec: float | None
    rms_dec_filtered_arcsec: float | None
    rms_total_filtered_arcsec: float | None
    peak_ra_arcsec: float | None
    peak_dec_arcsec: float | None
    snr_mean: float | None
    snr_min: float | None
    star_mass_mean: float | None
    pulse_count_ra_west: int
    pulse_count_ra_east: int
    pulse_count_dec_north: int
    pulse_count_dec_south: int
    pulse_total_ms_ra: int
    pulse_total_ms_dec: int
    dither_count: int
    settle_count: int
    settle_failed_count: int
    settle_median_s: float | None
    star_lost_reasons: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    truncated: bool = False


def _drop_metrics(frames) -> tuple[int, int, float]:
    """Return (drop_count, max_drop_run, unguided_seconds).

    Run length matters more than raw count: a star reappearing many minutes
    later is probably a different star and the target is likely off-frame, so
    the elapsed unguided time is the number worth surfacing.
    """
    drop_count = 0
    max_run = 0
    unguided = 0.0
    run_start_index: int | None = None
    for i, frame in enumerate(frames):
        if frame.dropped:
            drop_count += 1
            if run_start_index is None:
                run_start_index = i
            continue
        if run_start_index is not None:
            max_run = max(max_run, i - run_start_index)
            before = frames[run_start_index - 1] if run_start_index > 0 else frames[run_start_index]
            unguided += frame.time_offset - before.time_offset
            run_start_index = None
    if run_start_index is not None:
        max_run = max(max_run, len(frames) - run_start_index)
        before = frames[run_start_index - 1] if run_start_index > 0 else frames[run_start_index]
        unguided += frames[-1].time_offset - before.time_offset
    return drop_count, max_run, round(unguided, 3)


def _settle_metrics(events) -> tuple[int, int, int, float | None]:
    """Return (dither_count, settle_count, settle_failed_count, median_s)."""
    dither = sum(1 for e in events if e.type == "dither")
    started: float | None = None
    durations: list[float] = []
    settle_count = 0
    failed = 0
    for event in events:
        if event.type == "settle_start":
            started = event.time_offset
        elif event.type in ("settle_done", "settle_failed"):
            settle_count += 1
            if event.type == "settle_failed":
                failed += 1
            if started is not None:
                durations.append(event.time_offset - started)
                started = None
    median = round(statistics.median(durations), 3) if durations else None
    return dither, settle_count, failed, median


def compute_session_metrics(
    section,
    *,
    tz_name: str,
    observer_longitude: float | None,
    use_imaging_night: bool,
) -> Phd2SessionMetrics:
    """Reduce one parsed guiding section to its stored aggregate row."""
    header = section.header
    pixel_scale = header.pixel_scale_arcsec
    frames = section.frames

    started_utc = local_to_utc(section.started_at_local, tz_name)
    ended_utc = (
        local_to_utc(section.ended_at_local, tz_name)
        if section.ended_at_local is not None
        else None
    )
    if ended_utc is not None:
        duration = (ended_utc - started_utc).total_seconds()
    elif frames:
        duration = frames[-1].time_offset
    else:
        duration = 0.0

    windows = dither_settle_windows(section)
    guided = [
        f for f in frames
        if not f.dropped and not _in_windows(f.time_offset, windows)
    ]
    ra_vals = [f.ra_raw for f in guided if f.ra_raw is not None]
    dec_vals = [f.dec_raw for f in guided if f.dec_raw is not None]

    rms_ra = _scale(_rms(ra_vals), pixel_scale)
    rms_dec = _scale(_rms(dec_vals), pixel_scale)
    rms_total = (
        round(math.hypot(rms_ra, rms_dec), 6)
        if rms_ra is not None and rms_dec is not None
        else None
    )
    rms_ra_f = _scale(_rms(_filtered(ra_vals)), pixel_scale)
    rms_dec_f = _scale(_rms(_filtered(dec_vals)), pixel_scale)
    rms_total_f = (
        round(math.hypot(rms_ra_f, rms_dec_f), 6)
        if rms_ra_f is not None and rms_dec_f is not None
        else None
    )
    peak_ra = _scale(max((abs(v) for v in ra_vals), default=None), pixel_scale)
    peak_dec = _scale(max((abs(v) for v in dec_vals), default=None), pixel_scale)

    drop_count, max_run, unguided = _drop_metrics(frames)
    reasons = Counter(
        (f.drop_reason or "unknown") for f in frames if f.dropped
    )

    # SNR and star mass include DROP rows: PHD2 still reports them there, and a
    # collapsing SNR trend during a star-loss burst is the whole diagnostic.
    snr_vals = [f.snr for f in frames if f.snr is not None]
    mass_vals = [f.star_mass for f in frames if f.star_mass is not None]

    # Pulses count over every non-dropped frame including dither windows: the
    # corrections issued to chase a dither are real mount commands.
    pulsed = [f for f in frames if not f.dropped]
    dither_count, settle_count, settle_failed, settle_median = _settle_metrics(section.events)

    return Phd2SessionMetrics(
        started_at_local=section.started_at_local,
        started_at_utc=started_utc,
        ended_at_utc=ended_utc,
        duration_s=round(duration, 3),
        session_date=compute_session_date(
            started_utc,
            use_imaging_night=use_imaging_night,
            longitude=observer_longitude,
        ),
        equipment_profile=header.equipment_profile,
        pixel_scale_arcsec=pixel_scale,
        focal_length_mm=header.focal_length_mm,
        guide_camera=header.guide_camera,
        exposure_ms=header.exposure_ms,
        mount_name=header.mount_name,
        dec_guide_mode=header.dec_guide_mode,
        algo_ra=header.algo_ra,
        algo_dec=header.algo_dec,
        min_move_ra=header.min_move_ra,
        min_move_dec=header.min_move_dec,
        aggression_ra=header.aggression_ra,
        ortho_error_deg=header.ortho_error_deg,
        last_cal_issue=header.last_cal_issue,
        pier_side=header.pier_side,
        alt_deg=header.alt_deg,
        az_deg=header.az_deg,
        dec_deg=header.dec_deg,
        hour_angle_hr=header.hour_angle_hr,
        frame_count=len(frames),
        drop_count=drop_count,
        max_drop_run=max_run,
        unguided_seconds=unguided,
        rms_ra_arcsec=rms_ra,
        rms_dec_arcsec=rms_dec,
        rms_total_arcsec=rms_total,
        rms_ra_filtered_arcsec=rms_ra_f,
        rms_dec_filtered_arcsec=rms_dec_f,
        rms_total_filtered_arcsec=rms_total_f,
        peak_ra_arcsec=peak_ra,
        peak_dec_arcsec=peak_dec,
        snr_mean=round(statistics.fmean(snr_vals), 4) if snr_vals else None,
        snr_min=min(snr_vals) if snr_vals else None,
        star_mass_mean=round(statistics.fmean(mass_vals), 4) if mass_vals else None,
        pulse_count_ra_west=sum(1 for f in pulsed if f.ra_direction == "W"),
        pulse_count_ra_east=sum(1 for f in pulsed if f.ra_direction == "E"),
        pulse_count_dec_north=sum(1 for f in pulsed if f.dec_direction == "N"),
        pulse_count_dec_south=sum(1 for f in pulsed if f.dec_direction == "S"),
        pulse_total_ms_ra=sum(f.ra_duration_ms for f in pulsed),
        pulse_total_ms_dec=sum(f.dec_duration_ms for f in pulsed),
        dither_count=dither_count,
        settle_count=settle_count,
        settle_failed_count=settle_failed,
        settle_median_s=settle_median,
        star_lost_reasons=dict(reasons),
        events=[
            {"type": e.type, "t": e.time_offset, "detail": e.detail}
            for e in section.events
        ],
        truncated=section.truncated,
    )


def build_frame_rows(section) -> list[dict]:
    """Return Phd2Frame insert dicts (no id, no session_id) for one section."""
    return [
        {
            "frame_index": f.frame_index,
            "time_offset": f.time_offset,
            "dx": f.dx,
            "dy": f.dy,
            "ra_raw": f.ra_raw,
            "dec_raw": f.dec_raw,
            "ra_guide": f.ra_guide,
            "dec_guide": f.dec_guide,
            "ra_duration_ms": f.ra_duration_ms,
            "ra_direction": f.ra_direction,
            "dec_duration_ms": f.dec_duration_ms,
            "dec_direction": f.dec_direction,
            "star_mass": f.star_mass,
            "snr": f.snr,
            "error_code": f.error_code,
            "dropped": f.dropped,
        }
        for f in section.frames
    ]


def build_calibration_row(
    calibration,
    *,
    tz_name: str,
    observer_longitude: float | None,
    use_imaging_night: bool,
) -> dict:
    """Return Phd2Calibration insert kwargs (no id, no log_id, no telescope)."""
    header = calibration.header
    started_utc = local_to_utc(calibration.started_at_local, tz_name)
    return {
        "started_at_local": calibration.started_at_local,
        "started_at_utc": started_utc,
        "session_date": compute_session_date(
            started_utc,
            use_imaging_night=use_imaging_night,
            longitude=observer_longitude,
        ),
        "equipment_profile": header.equipment_profile,
        "pixel_scale_arcsec": header.pixel_scale_arcsec,
        "focal_length_mm": header.focal_length_mm,
        "guide_camera": header.guide_camera,
        "mount_name": calibration.mount_name or header.mount_name,
        "ra_guide_speed": header.ra_guide_speed,
        "dec_guide_speed": header.dec_guide_speed,
        "dec_deg": header.dec_deg,
        "hour_angle_hr": header.hour_angle_hr,
        "pier_side": header.pier_side,
        "alt_deg": header.alt_deg,
        "az_deg": header.az_deg,
        "west_angle_deg": calibration.west_angle_deg,
        "west_rate_px_s": calibration.west_rate_px_s,
        "west_parity": calibration.west_parity,
        "north_angle_deg": calibration.north_angle_deg,
        "north_rate_px_s": calibration.north_rate_px_s,
        "north_parity": calibration.north_parity,
        "completed": calibration.completed,
        "steps": [
            {
                "direction": s.direction, "step": s.step,
                "dx": s.dx, "dy": s.dy, "x": s.x, "y": s.y, "dist": s.dist,
            }
            for s in calibration.steps
        ],
    }


def _weighted_rms(rows, attr: str) -> float | None:
    """Frame-count-weighted RMS across sessions long enough to mean anything."""
    num = 0.0
    den = 0
    for row in rows:
        value = getattr(row, attr)
        if value is None or row.frame_count < MIN_FRAMES:
            continue
        num += row.frame_count * value * value
        den += row.frame_count
    if den == 0:
        return None
    return round(math.sqrt(num / den), 6)


def select_phd2_night_rows(rows, telescopes: set[str]) -> list:
    """Pick the guiding sessions that belong to this night's rig.

    `telescopes` holds every name that means this rig: the canonical one and
    all of its aliases, which is what `normalization.equipment_match_set`
    produces. A row's `telescope` column is written from the profile map,
    whose values are whatever the user picked when they mapped the profile, so
    neither side of this comparison can be assumed canonical and the caller
    resolves both into one set. A raw-string comparison missed a night shot on
    "SVBony SV503 80mm" whose profile was mapped to "SVBony 80ED".

    Rows whose profile maps to one of those telescopes are used directly. The
    fallback fires only when the night's sole profile is *unmapped*, which the
    null `telescope` column identifies exactly: an unmapped profile is the
    pre-configuration state and attributing it is a helpful guess, whereas a
    profile mapped to a different rig is a decision the user already made, and
    overriding it would put the guided rig's numbers on the other rig's card.
    Two unmapped profiles on one night attribute nothing: guessing which rig a
    target used would attach wrong guiding numbers to real data, which is worse
    than showing none.

    Lives here rather than beside its first caller because both the night
    summary and the /phd2/sessions route have to answer this question the same
    way; when they did not, a card showed a populated guiding panel above an
    empty guide graph.
    """
    rows = list(rows)
    if not rows:
        return []
    matched = [r for r in rows if r.telescope and r.telescope in telescopes]
    if matched:
        return matched
    if any(r.telescope for r in rows):
        return []
    profiles = {r.equipment_profile for r in rows}
    if len(profiles) == 1:
        return rows
    return []


def aggregate_night(rows) -> dict:
    """Roll a night's (or a night+rig's) sessions up into one summary dict.

    Event counts include every session, however short: a star-loss burst
    inside a 30-frame fragment is still a real star-loss burst. RMS figures
    exclude sessions under MIN_FRAMES, and the count of those excluded
    sessions is reported so the UI can say why the number moved.
    """
    rows = list(rows)
    gated = [r for r in rows if r.frame_count < MIN_FRAMES]
    settle_medians = [
        r.settle_median_s for r in rows if r.settle_median_s is not None
    ]
    issues = sorted({
        r.last_cal_issue for r in rows
        if r.last_cal_issue and r.last_cal_issue.lower() != "none"
    })
    profiles = sorted({r.equipment_profile for r in rows if r.equipment_profile})
    return {
        "session_count": len(rows),
        "gated_session_count": len(gated),
        "frame_count": sum(r.frame_count for r in rows),
        "rms_ra_arcsec": _weighted_rms(rows, "rms_ra_arcsec"),
        "rms_dec_arcsec": _weighted_rms(rows, "rms_dec_arcsec"),
        "rms_total_arcsec": _weighted_rms(rows, "rms_total_arcsec"),
        "drop_count": sum(r.drop_count for r in rows),
        "max_drop_run": max((r.max_drop_run for r in rows), default=0),
        "unguided_seconds": round(sum(r.unguided_seconds for r in rows), 3),
        "dither_count": sum(r.dither_count for r in rows),
        "settle_failed_count": sum(r.settle_failed_count for r in rows),
        "settle_median_s": (
            round(statistics.median(settle_medians), 3) if settle_medians else None
        ),
        "cal_issues": issues,
        "profiles": profiles,
    }
