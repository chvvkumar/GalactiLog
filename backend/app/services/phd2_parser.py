"""Parser for PHD2 guide logs (Log version 2.5).

Pure text in, dataclasses out: no file I/O, no database, no settings. Callers
read the whole file and hand the text over, which keeps the parser trivially
testable against fixture strings and keeps NFS latency out of the hot loop.

A single physical file often contains several stacked runs, because PHD2 was
restarted and appended to the same file (up to five observed in the local
corpus). Runs are segmented on the `PHD2 version` banner line and never on
`Log enabled at`: stacked runs repeat the *same* `Log enabled at` timestamp
while `Log closed at` advances, so segmenting on the latter would merge them.

All timestamps in the log are local wall-clock with no zone. This module
returns them as naive datetimes exactly as written; converting to UTC needs
the observer timezone setting and belongs to phd2_metrics, not here.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import datetime

LOG_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
# The "Last Cal Issue" line carries a US-locale 12-hour timestamp, which is a
# different format from every other timestamp in the file.
CAL_TIME_FORMAT = "%m/%d/%Y %I:%M:%S %p"

# Byte-stable across all ~800 guiding sections in the corpus; used as the
# state-machine trigger for CSV row parsing rather than a fuzzy prefix match.
GUIDE_CSV_HEADER = (
    "Frame,Time,mount,dx,dy,RARawDistance,DECRawDistance,RAGuideDistance,"
    "DECGuideDistance,RADuration,RADirection,DECDuration,DECDirection,"
    "XStep,YStep,StarMass,SNR,ErrorCode"
)
CAL_CSV_HEADER = "Direction,Step,dx,dy,x,y,Dist"

_TS = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"

_BANNER_RE = re.compile(
    r"^PHD2 version (\S+) \[([^\]]*)\], Log version ([\d.]+)\. Log enabled at " + _TS
)
_LOG_CLOSED_RE = re.compile(r"^Log closed at " + _TS)
_LOG_SUMMARY_RE = re.compile(
    r"^Log Summary: calcnt:(\d+) gcnt:(\d+) gdur:(\d+) gacnt:(\d+)"
)

_GUIDING_BEGINS_RE = re.compile(r"^Guiding Begins at " + _TS)
_GUIDING_ENDS_RE = re.compile(r"^Guiding Ends at " + _TS)
_CAL_BEGINS_RE = re.compile(r"^Calibration Begins at " + _TS)
_CAL_COMPLETE_RE = re.compile(r"^Calibration complete, mount = (.+?)\.?$")
# Only the West and North legs measure a rate and angle; East and South
# re-centre the star and never emit a completion line.
_AXIS_COMPLETE_RE = re.compile(
    r"^(West|North) calibration complete\. Angle = ([-\d.]+) deg, "
    r"Rate = ([-\d.]+) px/sec, Parity = (\S+)"
)

_EV_SETTLE_RE = re.compile(r"^INFO: SETTLING STATE CHANGE, (.+)$")
_EV_DITHER_RE = re.compile(r"^INFO: DITHER by (.+)$")
_EV_LOCK_RE = re.compile(r"^INFO: SET LOCK POSITION, (.+)$")
_EV_STARLOST_RE = re.compile(r"^INFO: STAR LOST during calibration, (.+)$")
_EV_PARAM_RE = re.compile(r"^INFO: Guiding parameter change, (.+)$")

_H_PROFILE_RE = re.compile(r"^Equipment Profile = (.+)$")
_H_PIXSCALE_RE = re.compile(
    r"^Pixel scale = ([\d.]+) arc-sec/px"
    r"(?:, Binning = (\d+))?(?:, Focal length = ([\d.]+) mm)?"
)
_H_CAMERA_RE = re.compile(r"^Camera = ([^,]+)")
_H_EXPOSURE_RE = re.compile(r"^Exposure = ([\d.]+) ms")
_H_MOUNT_RE = re.compile(r"^Mount = ([^,]+)")
_H_XANGLE_RE = re.compile(r"xAngle = ([-\d.]+)")
_H_XRATE_RE = re.compile(r"xRate = ([-\d.]+)")
_H_YANGLE_RE = re.compile(r"yAngle = ([-\d.]+)")
_H_YRATE_RE = re.compile(r"yRate = ([-\d.]+)")
_H_PARITY_RE = re.compile(r"parity = (\S+)")
_H_NORMRATES_RE = re.compile(
    r'^Norm rates RA = ([\d.]+)"/s.*?Dec = ([\d.]+)"/s'
    r"(?:; ortho\.err\. = ([-\d.]+) deg)?"
)
_H_XALGO_RE = re.compile(r"^X guide algorithm = ([^,]+)")
_H_YALGO_RE = re.compile(r"^Y guide algorithm = ([^,]+)")
_H_HYST_RE = re.compile(r"Hysteresis = ([\d.]+)")
_H_MINMOVE_RE = re.compile(r"Minimum move = ([\d.]+)")
_H_AGGR_RE = re.compile(r"Aggression = ([\d.]+)")
_H_BACKLASH_RE = re.compile(r"^Backlash comp = (\w+)(?:, pulse = ([\d.]+) ms)?")
_H_MAXDUR_RE = re.compile(
    r"^Max RA duration = ([\d.]+), Max DEC duration = ([\d.]+)"
    r"(?:, DEC guide mode = (\w+))?"
)
_H_SPEEDS_RE = re.compile(
    r"^RA Guide Speed = ([\d.]+) a-s/s, Dec Guide Speed = ([\d.]+) a-s/s"
)
_H_CALDEC_RE = re.compile(r"Cal Dec = ([-\d.]+)")
_H_LASTCAL_RE = re.compile(r"Last Cal Issue = ([^,]+)")
_H_CALTS_RE = re.compile(r"Timestamp = (\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2}:\d{2} [AP]M)")
_H_POINTING_RE = re.compile(
    r"^RA = ([-\d.]+) hr, Dec = ([-\d.]+) deg, Hour angle = ([-\d.]+) hr, "
    r"Pier side = (\w+), Rotator pos = ([^,]+), Alt = ([-\d.]+) deg, Az = ([-\d.]+) deg"
)
_H_LOCK_RE = re.compile(
    r"^Lock position = ([-\d.]+), ([-\d.]+), "
    r"Star position = ([-\d.]+), ([-\d.]+), HFD = ([-\d.]+) px"
)


def _f(value: str | None) -> float | None:
    """Float or None. Empty cells and the literal 'N/A' both mean absent."""
    if value is None:
        return None
    text = value.strip()
    if not text or text.upper() == "N/A":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _ts(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip(), LOG_TIME_FORMAT)
    except ValueError:
        return None


@dataclass
class Phd2Header:
    """Every header line PHD2 writes above a guiding or calibration block.

    One instance per section, never per file: one corpus file carries a
    misconfigured one-off pixel scale (0.99 arc-sec/px) in a single section's
    header, so a file-level pixel scale would silently corrupt every arcsec
    conversion in that file.
    """

    equipment_profile: str | None = None
    pixel_scale_arcsec: float | None = None
    binning: int | None = None
    focal_length_mm: float | None = None
    guide_camera: str | None = None
    exposure_ms: float | None = None
    mount_name: str | None = None
    x_angle_deg: float | None = None
    x_rate_px_s: float | None = None
    y_angle_deg: float | None = None
    y_rate_px_s: float | None = None
    parity: str | None = None
    norm_rate_ra: float | None = None
    norm_rate_dec: float | None = None
    ortho_error_deg: float | None = None
    algo_ra: str | None = None
    algo_dec: str | None = None
    min_move_ra: float | None = None
    min_move_dec: float | None = None
    # aggression_ra is the raw X-axis number (a fraction, e.g. 0.700);
    # aggression_dec is the Y-axis percentage with the '%' stripped (100.0).
    # PHD2 writes the two axes in different units on adjacent lines.
    aggression_ra: float | None = None
    aggression_dec: float | None = None
    hysteresis_ra: float | None = None
    backlash_comp_enabled: bool | None = None
    backlash_pulse_ms: float | None = None
    max_ra_duration_ms: float | None = None
    max_dec_duration_ms: float | None = None
    dec_guide_mode: str | None = None
    ra_guide_speed: float | None = None
    dec_guide_speed: float | None = None
    cal_dec_deg: float | None = None
    last_cal_issue: str | None = None
    cal_timestamp: datetime | None = None
    ra_hr: float | None = None
    dec_deg: float | None = None
    hour_angle_hr: float | None = None
    pier_side: str | None = None
    rotator_pos: str | None = None
    alt_deg: float | None = None
    az_deg: float | None = None
    lock_x: float | None = None
    lock_y: float | None = None
    star_x: float | None = None
    star_y: float | None = None
    hfd_px: float | None = None


@dataclass
class Phd2Event:
    """A non-CSV INFO line interleaved with the frame rows.

    `time_offset` is the Time value of the most recent CSV row in the same
    section (0.0 before the first row). PHD2 does not stamp INFO lines, and
    the preceding frame is the tightest bound available.
    """

    type: str
    time_offset: float
    detail: str


@dataclass
class Phd2Frame:
    """One CSV row of a guiding section. All distances are pixels.

    Arcsec conversion is the consumer's job: multiply by the section header's
    pixel scale. Nothing here is stored in arcsec, so a corrected pixel scale
    never needs a data migration.
    """

    frame_index: int
    time_offset: float
    dropped: bool
    dx: float | None
    dy: float | None
    ra_raw: float | None
    dec_raw: float | None
    ra_guide: float | None
    dec_guide: float | None
    ra_duration_ms: int
    ra_direction: str
    dec_duration_ms: int
    dec_direction: str
    star_mass: float | None
    snr: float | None
    error_code: int | None
    drop_reason: str


@dataclass
class Phd2CalibrationStep:
    direction: str
    step: int
    dx: float
    dy: float
    x: float
    y: float
    dist: float


@dataclass
class Phd2Calibration:
    started_at_local: datetime | None
    header: Phd2Header
    steps: list[Phd2CalibrationStep] = field(default_factory=list)
    west_angle_deg: float | None = None
    west_rate_px_s: float | None = None
    west_parity: str | None = None
    north_angle_deg: float | None = None
    north_rate_px_s: float | None = None
    north_parity: str | None = None
    completed: bool = False
    mount_name: str | None = None


@dataclass
class Phd2GuidingSection:
    started_at_local: datetime | None
    header: Phd2Header
    ended_at_local: datetime | None = None
    frames: list[Phd2Frame] = field(default_factory=list)
    events: list[Phd2Event] = field(default_factory=list)
    truncated: bool = False


@dataclass
class Phd2LogSummary:
    """The `Log Summary:` line at the end of a run - a free parser cross-check."""

    calibration_count: int
    guiding_count: int
    guiding_duration_s: int
    guiding_frame_count: int


@dataclass
class Phd2Run:
    """One PHD2 process lifetime within a physical log file."""

    phd2_version: str
    platform: str
    log_version: str
    log_enabled_at: datetime | None
    log_closed_at: datetime | None = None
    summary: Phd2LogSummary | None = None
    sections: list = field(default_factory=list)
    calibrations: list = field(default_factory=list)
    orphan_guiding_ends: int = 0
    warnings: list[str] = field(default_factory=list)


def apply_header_line(header: Phd2Header, raw_line: str) -> bool:
    """Fold one header line into `header`; return True when recognised.

    The line is stripped first because some PHD2 builds emit the Camera line
    with a leading space. All patterns are anchored so that `RA Guide Speed =`
    and `RA =` cannot be confused for one another.
    """
    line = raw_line.strip()

    m = _H_PROFILE_RE.match(line)
    if m:
        header.equipment_profile = m.group(1).strip()
        return True

    m = _H_PIXSCALE_RE.match(line)
    if m:
        header.pixel_scale_arcsec = _f(m.group(1))
        header.binning = int(m.group(2)) if m.group(2) else None
        header.focal_length_mm = _f(m.group(3))
        return True

    m = _H_CAMERA_RE.match(line)
    if m:
        header.guide_camera = m.group(1).strip()
        return True

    m = _H_EXPOSURE_RE.match(line)
    if m:
        header.exposure_ms = _f(m.group(1))
        return True

    m = _H_MOUNT_RE.match(line)
    if m:
        header.mount_name = m.group(1).strip()
        for attr, rx in (
            ("x_angle_deg", _H_XANGLE_RE),
            ("x_rate_px_s", _H_XRATE_RE),
            ("y_angle_deg", _H_YANGLE_RE),
            ("y_rate_px_s", _H_YRATE_RE),
        ):
            sub = rx.search(line)
            if sub:
                setattr(header, attr, _f(sub.group(1)))
        sub = _H_PARITY_RE.search(line)
        if sub:
            header.parity = sub.group(1)
        return True

    m = _H_NORMRATES_RE.match(line)
    if m:
        header.norm_rate_ra = _f(m.group(1))
        header.norm_rate_dec = _f(m.group(2))
        header.ortho_error_deg = _f(m.group(3))
        return True

    m = _H_XALGO_RE.match(line)
    if m:
        header.algo_ra = m.group(1).strip()
        sub = _H_HYST_RE.search(line)
        if sub:
            header.hysteresis_ra = _f(sub.group(1))
        sub = _H_MINMOVE_RE.search(line)
        if sub:
            header.min_move_ra = _f(sub.group(1))
        sub = _H_AGGR_RE.search(line)
        if sub:
            header.aggression_ra = _f(sub.group(1))
        return True

    m = _H_YALGO_RE.match(line)
    if m:
        header.algo_dec = m.group(1).strip()
        sub = _H_MINMOVE_RE.search(line)
        if sub:
            header.min_move_dec = _f(sub.group(1))
        sub = _H_AGGR_RE.search(line)
        if sub:
            header.aggression_dec = _f(sub.group(1))
        return True

    m = _H_BACKLASH_RE.match(line)
    if m:
        header.backlash_comp_enabled = m.group(1).lower() == "enabled"
        header.backlash_pulse_ms = _f(m.group(2))
        return True

    m = _H_MAXDUR_RE.match(line)
    if m:
        header.max_ra_duration_ms = _f(m.group(1))
        header.max_dec_duration_ms = _f(m.group(2))
        header.dec_guide_mode = m.group(3)
        return True

    m = _H_SPEEDS_RE.match(line)
    if m:
        header.ra_guide_speed = _f(m.group(1))
        header.dec_guide_speed = _f(m.group(2))
        sub = _H_CALDEC_RE.search(line)
        if sub:
            header.cal_dec_deg = _f(sub.group(1))
        sub = _H_LASTCAL_RE.search(line)
        if sub:
            header.last_cal_issue = sub.group(1).strip()
        sub = _H_CALTS_RE.search(line)
        if sub:
            try:
                header.cal_timestamp = datetime.strptime(sub.group(1), CAL_TIME_FORMAT)
            except ValueError:
                header.cal_timestamp = None
        return True

    m = _H_POINTING_RE.match(line)
    if m:
        header.ra_hr = _f(m.group(1))
        header.dec_deg = _f(m.group(2))
        header.hour_angle_hr = _f(m.group(3))
        header.pier_side = m.group(4)
        header.rotator_pos = m.group(5).strip()
        header.alt_deg = _f(m.group(6))
        header.az_deg = _f(m.group(7))
        return True

    m = _H_LOCK_RE.match(line)
    if m:
        header.lock_x = _f(m.group(1))
        header.lock_y = _f(m.group(2))
        header.star_x = _f(m.group(3))
        header.star_y = _f(m.group(4))
        header.hfd_px = _f(m.group(5))
        return True

    return False


def _parse_event(line: str, time_offset: float) -> Phd2Event | None:
    """Classify an INFO line. Unknown INFO lines return None and are dropped."""
    m = _EV_SETTLE_RE.match(line)
    if m:
        detail = m.group(1).strip()
        lowered = detail.lower()
        if lowered.startswith("settling started"):
            return Phd2Event(type="settle_start", time_offset=time_offset, detail=detail)
        if lowered.startswith("settling complete"):
            return Phd2Event(type="settle_done", time_offset=time_offset, detail=detail)
        if lowered.startswith("settling failed"):
            return Phd2Event(type="settle_failed", time_offset=time_offset, detail=detail)
        return None
    m = _EV_DITHER_RE.match(line)
    if m:
        return Phd2Event(type="dither", time_offset=time_offset, detail=m.group(1).strip())
    m = _EV_LOCK_RE.match(line)
    if m:
        return Phd2Event(type="lock_shift", time_offset=time_offset, detail=m.group(1).strip())
    m = _EV_STARLOST_RE.match(line)
    if m:
        return Phd2Event(type="star_lost", time_offset=time_offset, detail=m.group(1).strip())
    m = _EV_PARAM_RE.match(line)
    if m:
        return Phd2Event(type="param_change", time_offset=time_offset, detail=m.group(1).strip())
    return None


def _parse_frame_row(line: str) -> Phd2Frame | None:
    """Parse one guiding CSV row, or None when the row is unusable.

    A row shorter than 18 fields is a file truncated mid-write (PHD2 killed);
    the caller treats None as end-of-section rather than an error. DROP rows
    carry a 19th quoted field with the star-loss reason, which is why the row
    goes through csv.reader instead of str.split.
    """
    try:
        fields = next(csv.reader([line]))
    except (csv.Error, StopIteration):
        return None
    if len(fields) < 18:
        return None
    try:
        frame_index = int(fields[0])
        time_offset = float(fields[1])
    except ValueError:
        return None
    error_code = _f(fields[17])
    return Phd2Frame(
        frame_index=frame_index,
        time_offset=time_offset,
        dropped=fields[2].strip().strip('"').upper() == "DROP",
        dx=_f(fields[3]),
        dy=_f(fields[4]),
        ra_raw=_f(fields[5]),
        dec_raw=_f(fields[6]),
        ra_guide=_f(fields[7]),
        dec_guide=_f(fields[8]),
        ra_duration_ms=int(_f(fields[9]) or 0),
        ra_direction=fields[10].strip(),
        dec_duration_ms=int(_f(fields[11]) or 0),
        dec_direction=fields[12].strip(),
        star_mass=_f(fields[15]),
        snr=_f(fields[16]),
        error_code=int(error_code) if error_code is not None else None,
        drop_reason=fields[18].strip() if len(fields) > 18 else "",
    )


def _parse_cal_step(line: str) -> Phd2CalibrationStep | None:
    fields = line.split(",")
    if len(fields) != 7:
        return None
    try:
        return Phd2CalibrationStep(
            direction=fields[0].strip(),
            step=int(fields[1]),
            dx=float(fields[2]),
            dy=float(fields[3]),
            x=float(fields[4]),
            y=float(fields[5]),
            dist=float(fields[6]),
        )
    except ValueError:
        return None


def _crosscheck_summaries(runs: list[Phd2Run]) -> None:
    """Compare parsed counts against the run's own `Log Summary` line.

    Free self-test: PHD2 writes how many calibrations and guiding sections it
    believes it emitted. A mismatch is recorded as a warning rather than an
    error because a run killed before its summary is written is normal.
    """
    for run in runs:
        if run.summary is None:
            continue
        if len(run.sections) != run.summary.guiding_count:
            run.warnings.append(
                f"Log Summary gcnt:{run.summary.guiding_count} but parsed "
                f"{len(run.sections)} guiding sections"
            )
        if len(run.calibrations) != run.summary.calibration_count:
            run.warnings.append(
                f"Log Summary calcnt:{run.summary.calibration_count} but parsed "
                f"{len(run.calibrations)} calibration blocks"
            )


def parse_guide_log(text: str) -> list[Phd2Run]:
    """Parse a whole guide-log file into its stacked runs.

    Returns an empty list for a file with no `PHD2 version` banner at all;
    callers treat that as a data-free log rather than an error.
    """
    runs: list[Phd2Run] = []
    run: Phd2Run | None = None
    section: Phd2GuidingSection | None = None
    calibration: Phd2Calibration | None = None
    mode = "none"  # none | guide_header | guide_rows | cal_header | cal_rows
    last_t = 0.0

    def _abandon_section() -> None:
        # A section still open when the file/run/next-block starts was cut
        # short: PHD2 was killed, or the run boundary swallowed its end line.
        nonlocal section
        if section is not None and section.ended_at_local is None:
            section.truncated = True
        section = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        m = _BANNER_RE.match(line)
        if m:
            _abandon_section()
            calibration = None
            mode = "none"
            run = Phd2Run(
                phd2_version=m.group(1),
                platform=m.group(2),
                log_version=m.group(3),
                log_enabled_at=_ts(m.group(4)),
            )
            runs.append(run)
            continue

        if run is None:
            continue

        m = _LOG_CLOSED_RE.match(line)
        if m:
            _abandon_section()
            calibration = None
            mode = "none"
            run.log_closed_at = _ts(m.group(1))
            continue

        m = _LOG_SUMMARY_RE.match(line)
        if m:
            run.summary = Phd2LogSummary(
                calibration_count=int(m.group(1)),
                guiding_count=int(m.group(2)),
                guiding_duration_s=int(m.group(3)),
                guiding_frame_count=int(m.group(4)),
            )
            continue

        m = _GUIDING_BEGINS_RE.match(line)
        if m:
            _abandon_section()
            calibration = None
            section = Phd2GuidingSection(
                started_at_local=_ts(m.group(1)), header=Phd2Header()
            )
            run.sections.append(section)
            mode = "guide_header"
            last_t = 0.0
            continue

        m = _GUIDING_ENDS_RE.match(line)
        if m:
            if section is None:
                run.orphan_guiding_ends += 1
            else:
                section.ended_at_local = _ts(m.group(1))
                section = None
            mode = "none"
            continue

        m = _CAL_BEGINS_RE.match(line)
        if m:
            _abandon_section()
            calibration = Phd2Calibration(
                started_at_local=_ts(m.group(1)), header=Phd2Header()
            )
            run.calibrations.append(calibration)
            mode = "cal_header"
            continue

        m = _CAL_COMPLETE_RE.match(line)
        if m:
            if calibration is not None:
                calibration.completed = True
                calibration.mount_name = m.group(1).strip()
                calibration = None
            mode = "none"
            continue

        m = _AXIS_COMPLETE_RE.match(line)
        if m:
            if calibration is not None:
                axis = m.group(1).lower()
                setattr(calibration, f"{axis}_angle_deg", _f(m.group(2)))
                setattr(calibration, f"{axis}_rate_px_s", _f(m.group(3)))
                setattr(calibration, f"{axis}_parity", m.group(4))
            continue

        if line == GUIDE_CSV_HEADER:
            mode = "guide_rows"
            continue

        if line == CAL_CSV_HEADER:
            mode = "cal_rows"
            continue

        if line.startswith("INFO:"):
            event = _parse_event(line, last_t)
            if event is not None and section is not None:
                section.events.append(event)
            continue

        if mode == "guide_rows" and section is not None:
            frame = _parse_frame_row(line)
            if frame is None:
                section.truncated = True
                mode = "none"
                continue
            last_t = frame.time_offset
            section.frames.append(frame)
            continue

        if mode == "cal_rows" and calibration is not None:
            step = _parse_cal_step(line)
            if step is not None:
                calibration.steps.append(step)
            continue

        if mode == "guide_header" and section is not None:
            apply_header_line(section.header, raw_line)
            continue

        if mode == "cal_header" and calibration is not None:
            apply_header_line(calibration.header, raw_line)
            continue

    _abandon_section()
    _crosscheck_summaries(runs)
    return runs
