"""Parser tests against authentic PHD2 guide-log text.

Every fixture string below is verbatim from the local corpus at
F:\\Astro Incoming\\PHD2 Logs (files PHD2_GuideLog_2026-01-19_172118.txt and
PHD2_GuideLog_2026-07-14_201333.txt), so the parser is exercised against the
exact byte layout PHD2 2.6.13/2.6.14 emits rather than an idealised sample.
"""
from datetime import datetime

import pytest

from app.services import phd2_parser
from app.services.phd2_parser import Phd2Header, apply_header_line, parse_guide_log


# Verbatim: PHD2_GuideLog_2026-01-19_172118.txt (whole file, 25 lines).
# Five stacked runs, all data-free, all repeating the same "Log enabled at".
EMPTY_STACKED_LOG = """PHD2 version 2.6.13dev8 [Windows], Log version 2.5. Log enabled at 2026-01-19 17:21:18
INFO: Guiding parameter change, MultiStar = true

Log Summary: calcnt:0 gcnt:0 gdur:0 gacnt:0
Log closed at 2026-01-19 17:21:51
PHD2 version 2.6.14 [Windows], Log version 2.5. Log enabled at 2026-01-19 17:21:18
INFO: Guiding parameter change, MultiStar = true

Log Summary: calcnt:0 gcnt:0 gdur:0 gacnt:0
Log closed at 2026-01-19 17:29:17
PHD2 version 2.6.14 [Windows], Log version 2.5. Log enabled at 2026-01-19 17:21:18
INFO: Guiding parameter change, MultiStar = true

Log Summary: calcnt:0 gcnt:0 gdur:0 gacnt:0
Log closed at 2026-01-19 18:07:05
PHD2 version 2.6.14 [Windows], Log version 2.5. Log enabled at 2026-01-19 17:21:18
INFO: Guiding parameter change, MultiStar = true

Log Summary: calcnt:0 gcnt:0 gdur:0 gacnt:0
Log closed at 2026-01-19 18:09:14
PHD2 version 2.6.14 [Windows], Log version 2.5. Log enabled at 2026-01-19 17:21:18
INFO: Guiding parameter change, MultiStar = true

Log Summary: calcnt:0 gcnt:0 gdur:0 gacnt:0
Log closed at 2026-01-19 18:21:50
"""

# Verbatim: PHD2_GuideLog_2026-07-14_201333.txt lines 64-78 (guiding header).
# Note the leading space on the Camera line - PHD2 emits it that way.
GUIDING_HEADER_LINES = [
    "Equipment Profile = AM5n_OAG_ASI174M",
    "Dither = both axes, Dither scale = 1.000, Image noise reduction = none, Guide-frame time lapse = 0, Server enabled",
    "Pixel scale = 1.54 arc-sec/px, Binning = 1, Focal length = 784 mm",
    "Search region = 15 px, Star mass tolerance = 50.0%, Multi-star mode, list size = 12",
    " Camera = ZWO ASI174MM Mini, gain = 90, full size = 1936 x 1216, have dark, dark dur = 500, no defect map, pixel size = 5.9 um",
    "Exposure = 500 ms",
    "Mount = ASI Mount (ASCOM), connected, guiding enabled, xAngle = 87.9, xRate = 3.579, yAngle = -170.3, yRate = 4.437, parity = ?/?",
    'Norm rates RA = 7.0"/s @ dec 0, Dec = 6.8"/s; ortho.err. = 11.8 deg',
    "X guide algorithm = Hysteresis, Hysteresis = 0.100, Aggression = 0.700, Minimum move = 0.250",
    "Y guide algorithm = Resist Switch, Minimum move = 0.250 Aggression = 100% FastSwitch = enabled",
    "Backlash comp = disabled, pulse = 254 ms",
    "Max RA duration = 2500, Max DEC duration = 2500, DEC guide mode = Auto",
    "RA Guide Speed = 7.5 a-s/s, Dec Guide Speed = 7.5 a-s/s, Cal Dec = 38.5, Last Cal Issue = None, Timestamp = 7/14/2026 9:42:27 PM",
    "RA = 20.22 hr, Dec = 38.5 deg, Hour angle = -4.02 hr, Pier side = West, Rotator pos = N/A, Alt = 43.7 deg, Az = 70.4 deg",
    "Lock position = 77.407, 204.420, Star position = 77.407, 204.420, HFD = 1.91 px",
]

# Verbatim: same file lines 105-114 (calibration header variant - shorter
# Mount line, short guide-speed line, Dec = -0.0 on the pointing line).
CAL_HEADER_LINES = [
    "Equipment Profile = AM5n_OAG_ASI174M",
    "Pixel scale = 1.54 arc-sec/px, Binning = 1, Focal length = 784 mm",
    " Camera = ZWO ASI174MM Mini, gain = 90, full size = 1936 x 1216, have dark, dark dur = 500, no defect map, pixel size = 5.9 um",
    "Exposure = 500 ms",
    "Mount = ASI Mount (ASCOM), Calibration Step = 450 ms, Calibration Distance = 25 px, Assume orthogonal axes = no",
    "RA Guide Speed = 7.5 a-s/s, Dec Guide Speed = 7.5 a-s/s",
    "RA = 16.53 hr, Dec = -0.0 deg, Hour angle = -0.33 hr, Pier side = West, Rotator pos = N/A, Alt = 51.0 deg, Az = 172.2 deg",
    "Lock position = 468.980, 290.926, Star position = 469.135, 291.637, HFD = 2.37 px",
]


def _guiding_header() -> Phd2Header:
    header = Phd2Header()
    for line in GUIDING_HEADER_LINES:
        apply_header_line(header, line)
    return header


def test_empty_text_yields_no_runs():
    assert parse_guide_log("") == []


def test_stacked_empty_log_yields_five_runs_with_no_sections():
    runs = parse_guide_log(EMPTY_STACKED_LOG)
    assert len(runs) == 5
    assert [r.phd2_version for r in runs] == [
        "2.6.13dev8", "2.6.14", "2.6.14", "2.6.14", "2.6.14",
    ]
    assert all(r.sections == [] for r in runs)
    assert all(r.calibrations == [] for r in runs)
    # Every stacked run repeats the same "Log enabled at"; only "closed" moves.
    assert all(r.log_enabled_at == datetime(2026, 1, 19, 17, 21, 18) for r in runs)
    assert runs[0].log_closed_at == datetime(2026, 1, 19, 17, 21, 51)
    assert runs[-1].log_closed_at == datetime(2026, 1, 19, 18, 21, 50)


def test_log_summary_is_captured_per_run():
    runs = parse_guide_log(EMPTY_STACKED_LOG)
    assert runs[0].summary is not None
    assert runs[0].summary.calibration_count == 0
    assert runs[0].summary.guiding_count == 0
    assert runs[0].summary.guiding_duration_s == 0
    assert runs[0].summary.guiding_frame_count == 0
    assert runs[0].warnings == []


def test_guiding_header_block_is_fully_parsed():
    h = _guiding_header()
    assert h.equipment_profile == "AM5n_OAG_ASI174M"
    assert h.pixel_scale_arcsec == 1.54
    assert h.binning == 1
    assert h.focal_length_mm == 784.0
    assert h.guide_camera == "ZWO ASI174MM Mini"
    assert h.exposure_ms == 500.0
    assert h.mount_name == "ASI Mount (ASCOM)"
    assert h.x_angle_deg == 87.9
    assert h.x_rate_px_s == 3.579
    assert h.y_angle_deg == -170.3
    assert h.y_rate_px_s == 4.437
    assert h.parity == "?/?"
    assert h.norm_rate_ra == 7.0
    assert h.norm_rate_dec == 6.8
    assert h.ortho_error_deg == 11.8
    assert h.algo_ra == "Hysteresis"
    assert h.hysteresis_ra == 0.100
    assert h.aggression_ra == 0.700
    assert h.min_move_ra == 0.250
    assert h.algo_dec == "Resist Switch"
    assert h.min_move_dec == 0.250
    assert h.aggression_dec == 100.0
    assert h.backlash_comp_enabled is False
    assert h.backlash_pulse_ms == 254.0
    assert h.max_ra_duration_ms == 2500.0
    assert h.max_dec_duration_ms == 2500.0
    assert h.dec_guide_mode == "Auto"
    assert h.ra_guide_speed == 7.5
    assert h.dec_guide_speed == 7.5
    assert h.cal_dec_deg == 38.5
    assert h.last_cal_issue == "None"
    assert h.cal_timestamp == datetime(2026, 7, 14, 21, 42, 27)
    assert h.ra_hr == 20.22
    assert h.dec_deg == 38.5
    assert h.hour_angle_hr == -4.02
    assert h.pier_side == "West"
    assert h.rotator_pos == "N/A"
    assert h.alt_deg == 43.7
    assert h.az_deg == 70.4
    assert h.lock_x == 77.407
    assert h.lock_y == 204.420
    assert h.star_x == 77.407
    assert h.star_y == 204.420
    assert h.hfd_px == 1.91


def test_calibration_header_variant_is_parsed():
    header = Phd2Header()
    for line in CAL_HEADER_LINES:
        apply_header_line(header, line)
    assert header.mount_name == "ASI Mount (ASCOM)"
    # The calibration Mount line carries no xAngle/xRate.
    assert header.x_angle_deg is None
    assert header.ra_guide_speed == 7.5
    assert header.dec_guide_speed == 7.5
    assert header.last_cal_issue is None
    assert header.dec_deg == -0.0
    assert header.hfd_px == 2.37


def test_unrecognised_header_line_returns_false():
    header = Phd2Header()
    assert apply_header_line(header, "Search region = 15 px, Star mass tolerance = 50.0%") is False
    assert apply_header_line(header, "Exposure = 500 ms") is True


def test_module_exposes_the_byte_stable_csv_headers():
    assert phd2_parser.GUIDE_CSV_HEADER.startswith("Frame,Time,mount,dx,dy,")
    assert phd2_parser.GUIDE_CSV_HEADER.endswith(",StarMass,SNR,ErrorCode")
    assert phd2_parser.CAL_CSV_HEADER == "Direction,Step,dx,dy,x,y,Dist"


# Verbatim: PHD2_GuideLog_2026-07-14_201333.txt lines 1-100, trimmed to the
# first calibration block's West/East legs and the first guiding section.
FULL_SAMPLE_LOG = """PHD2 version 2.6.14 [Windows], Log version 2.5. Log enabled at 2026-07-14 20:13:33
INFO: Guiding parameter change, MultiStar = true

Calibration Begins at 2026-07-14 21:41:21
Equipment Profile = AM5n_OAG_ASI174M
Pixel scale = 1.54 arc-sec/px, Binning = 1, Focal length = 784 mm
 Camera = ZWO ASI174MM Mini, gain = 90, full size = 1936 x 1216, have dark, dark dur = 500, no defect map, pixel size = 5.9 um
Exposure = 500 ms
Mount = ASI Mount (ASCOM), Calibration Step = 450 ms, Calibration Distance = 25 px, Assume orthogonal axes = no
RA Guide Speed = 7.5 a-s/s, Dec Guide Speed = 7.5 a-s/s
RA = 20.22 hr, Dec = 38.5 deg, Hour angle = -4.04 hr, Pier side = West, Rotator pos = N/A, Alt = 43.5 deg, Az = 70.3 deg
Lock position = 86.486, 202.175, Star position = 86.496, 202.920, HFD = 2.38 px
Direction,Step,dx,dy,x,y,Dist
West,0,0.000,0.000,86.217,202.308,0.000
West,1,0.175,1.175,86.042,201.133,1.188
West,2,0.078,3.452,86.139,198.856,3.453
West calibration complete. Angle = 87.9 deg, Rate = 3.579 px/sec, Parity = N/A
East,3,0.950,25.755,85.267,176.554,25.772
East,0,5.969,-2.244,80.248,204.552,6.377
Backlash,0,0.000,0.000,80.248,204.552,0.000
North,0,0.000,0.000,77.909,203.756,0.000
North,1,1.472,-0.332,76.437,204.089,1.509
North calibration complete. Angle = -170.3 deg, Rate = 4.437 px/sec, Parity = N/A
South,3,25.587,4.380,52.322,199.377,25.959
South,0,7.805,0.977,70.104,202.780,7.866
Calibration complete, mount = ASI Mount (ASCOM).

Guiding Begins at 2026-07-14 21:42:27
Equipment Profile = AM5n_OAG_ASI174M
Pixel scale = 1.54 arc-sec/px, Binning = 1, Focal length = 784 mm
 Camera = ZWO ASI174MM Mini, gain = 90, full size = 1936 x 1216, have dark, dark dur = 500, no defect map, pixel size = 5.9 um
Exposure = 500 ms
Mount = ASI Mount (ASCOM), connected, guiding enabled, xAngle = 87.9, xRate = 3.579, yAngle = -170.3, yRate = 4.437, parity = ?/?
Norm rates RA = 7.0"/s @ dec 0, Dec = 6.8"/s; ortho.err. = 11.8 deg
X guide algorithm = Hysteresis, Hysteresis = 0.100, Aggression = 0.700, Minimum move = 0.250
Y guide algorithm = Resist Switch, Minimum move = 0.250 Aggression = 100% FastSwitch = enabled
Backlash comp = disabled, pulse = 254 ms
Max RA duration = 2500, Max DEC duration = 2500, DEC guide mode = Auto
RA Guide Speed = 7.5 a-s/s, Dec Guide Speed = 7.5 a-s/s, Cal Dec = 38.5, Last Cal Issue = None, Timestamp = 7/14/2026 9:42:27 PM
RA = 20.22 hr, Dec = 38.5 deg, Hour angle = -4.02 hr, Pier side = West, Rotator pos = N/A, Alt = 43.7 deg, Az = 70.4 deg
Lock position = 77.407, 204.420, Star position = 77.407, 204.420, HFD = 1.91 px
Frame,Time,mount,dx,dy,RARawDistance,DECRawDistance,RAGuideDistance,DECGuideDistance,RADuration,RADirection,DECDuration,DECDirection,XStep,YStep,StarMass,SNR,ErrorCode
INFO: SETTLING STATE CHANGE, Settling started
1,1.228,"Mount",0.330,0.544,0.556,-0.189,0.350,0.000,98,W,0,,,,1713,28.59,1
2,2.093,"Mount",0.524,0.132,0.151,-0.477,0.000,0.000,0,,0,,,,1702,28.36,0
3,3.149,"Mount",-0.139,-0.706,-0.710,-0.035,-0.448,0.000,125,E,0,,,,1888,29.97,1
INFO: SETTLING STATE CHANGE, Settling complete
7,7.381,"Mount",-1.050,0.681,0.642,1.183,0.388,1.183,108,W,267,S,,,1961,30.61,1
INFO: DITHER by 3.4, -1.2, new lock pos = 80.807, 203.220
9067,9716.891,"DROP",,,,,,,,,,,,,929,19.23,7,"Star lost - mass changed"
INFO: SET LOCK POSITION, new lock pos = 77.407, 204.420
Guiding Ends at 2026-07-14 21:42:46

Log Summary: calcnt:1 gcnt:1 gdur:19 gacnt:5
Log closed at 2026-07-14 21:43:00
"""

# Guiding block killed mid-CSV: no "Guiding Ends", no "Log closed", and the
# final row is cut off after the 6th field. Two corpus files end this way.
TRUNCATED_LOG = """PHD2 version 2.6.14 [Windows], Log version 2.5. Log enabled at 2026-07-14 20:13:33

Guiding Begins at 2026-07-14 21:42:27
Equipment Profile = AM5n_OAG_ASI174M
Pixel scale = 1.54 arc-sec/px, Binning = 1, Focal length = 784 mm
Exposure = 500 ms
Frame,Time,mount,dx,dy,RARawDistance,DECRawDistance,RAGuideDistance,DECGuideDistance,RADuration,RADirection,DECDuration,DECDirection,XStep,YStep,StarMass,SNR,ErrorCode
1,1.228,"Mount",0.330,0.544,0.556,-0.189,0.350,0.000,98,W,0,,,,1713,28.59,1
2,2.093,"Mount",0.524,0.132,0.151,-0.477,0.000,0.000,0,,0,,,,1702,28.36,0
3,3.149,"Mount",-0.139,-0.706,-0.7
"""

# A "Guiding Ends" with no matching "Guiding Begins" - happens at run
# boundaries when PHD2 was restarted mid-session.
ORPHAN_END_LOG = """PHD2 version 2.6.14 [Windows], Log version 2.5. Log enabled at 2026-07-14 20:13:33
Guiding Ends at 2026-07-14 20:14:00

Log Summary: calcnt:0 gcnt:0 gdur:0 gacnt:0
Log closed at 2026-07-14 20:15:00
"""

# Calibration killed before the "Calibration complete" line (5 of 37 in
# the corpus), with a STAR LOST info line inside the block.
ABORTED_CAL_LOG = """PHD2 version 2.6.14 [Windows], Log version 2.5. Log enabled at 2026-07-14 20:13:33

Calibration Begins at 2026-07-14 21:41:21
Equipment Profile = ASI220mm_30F5_AM5
Pixel scale = 3.20 arc-sec/px, Binning = 1, Focal length = 150 mm
Direction,Step,dx,dy,x,y,Dist
West,0,0.000,0.000,86.217,202.308,0.000
West,1,0.175,1.175,86.042,201.133,1.188
INFO: STAR LOST during calibration, Mass= 0, SNR= 0.00, Error= 4, Status=Star lost - low HFD
Log closed at 2026-07-14 21:45:00
"""


def test_full_sample_yields_one_calibration_and_one_guiding_section():
    runs = parse_guide_log(FULL_SAMPLE_LOG)
    assert len(runs) == 1
    run = runs[0]
    assert len(run.calibrations) == 1
    assert len(run.sections) == 1
    assert run.warnings == []


def test_calibration_block_captures_steps_axes_and_completion():
    cal = parse_guide_log(FULL_SAMPLE_LOG)[0].calibrations[0]
    assert cal.started_at_local == datetime(2026, 7, 14, 21, 41, 21)
    assert cal.header.equipment_profile == "AM5n_OAG_ASI174M"
    assert cal.header.pixel_scale_arcsec == 1.54
    assert [s.direction for s in cal.steps] == [
        "West", "West", "West", "East", "East", "Backlash", "North", "North",
        "South", "South",
    ]
    assert cal.steps[1].dx == 0.175
    assert cal.steps[1].dist == 1.188
    assert cal.west_angle_deg == 87.9
    assert cal.west_rate_px_s == 3.579
    assert cal.west_parity == "N/A"
    assert cal.north_angle_deg == -170.3
    assert cal.north_rate_px_s == 4.437
    assert cal.completed is True
    assert cal.mount_name == "ASI Mount (ASCOM)"


def test_aborted_calibration_is_marked_incomplete():
    run = parse_guide_log(ABORTED_CAL_LOG)[0]
    assert len(run.calibrations) == 1
    cal = run.calibrations[0]
    assert cal.completed is False
    assert cal.mount_name is None
    assert len(cal.steps) == 2
    assert cal.west_angle_deg is None


def test_guiding_section_frames_are_parsed_with_directions_and_pulses():
    section = parse_guide_log(FULL_SAMPLE_LOG)[0].sections[0]
    assert section.started_at_local == datetime(2026, 7, 14, 21, 42, 27)
    assert section.ended_at_local == datetime(2026, 7, 14, 21, 42, 46)
    assert section.truncated is False
    assert len(section.frames) == 5
    first = section.frames[0]
    assert first.frame_index == 1
    assert first.time_offset == 1.228
    assert first.dropped is False
    assert first.dx == 0.330
    assert first.ra_raw == 0.556
    assert first.dec_raw == -0.189
    assert first.ra_guide == 0.350
    assert first.ra_duration_ms == 98
    assert first.ra_direction == "W"
    assert first.dec_duration_ms == 0
    assert first.dec_direction == ""
    assert first.star_mass == 1713.0
    assert first.snr == 28.59
    assert first.error_code == 1
    both_axes = section.frames[3]
    assert both_axes.frame_index == 7
    assert both_axes.dec_duration_ms == 267
    assert both_axes.dec_direction == "S"


def test_drop_row_with_nineteen_fields_keeps_its_reason():
    section = parse_guide_log(FULL_SAMPLE_LOG)[0].sections[0]
    drop = section.frames[-1]
    assert drop.frame_index == 9067
    assert drop.dropped is True
    assert drop.ra_raw is None
    assert drop.dec_raw is None
    assert drop.snr == 19.23
    assert drop.error_code == 7
    assert drop.drop_reason == "Star lost - mass changed"


def test_events_are_typed_and_stamped_with_the_preceding_frame_time():
    section = parse_guide_log(FULL_SAMPLE_LOG)[0].sections[0]
    assert [(e.type, e.time_offset) for e in section.events] == [
        ("settle_start", 0.0),
        ("settle_done", 3.149),
        ("dither", 7.381),
        ("lock_shift", 9716.891),
    ]
    assert section.events[2].detail == "3.4, -1.2, new lock pos = 80.807, 203.220"


def test_star_lost_during_calibration_is_an_event_on_no_section():
    # The STAR LOST line sits inside a calibration block, so it is recognised
    # but has no guiding section to attach to and is dropped rather than
    # crashing the parse.
    run = parse_guide_log(ABORTED_CAL_LOG)[0]
    assert run.sections == []
    assert len(run.calibrations) == 1


def test_truncated_final_row_and_missing_log_closed_are_tolerated():
    runs = parse_guide_log(TRUNCATED_LOG)
    assert len(runs) == 1
    run = runs[0]
    assert run.log_closed_at is None
    section = run.sections[0]
    assert section.ended_at_local is None
    assert section.truncated is True
    # Only the two complete rows survive; the cut-off row is discarded.
    assert [f.frame_index for f in section.frames] == [1, 2]


def test_orphan_guiding_ends_is_counted_not_fatal():
    run = parse_guide_log(ORPHAN_END_LOG)[0]
    assert run.sections == []
    assert run.orphan_guiding_ends == 1


def test_log_summary_mismatch_produces_a_warning():
    mismatched = FULL_SAMPLE_LOG.replace(
        "Log Summary: calcnt:1 gcnt:1 gdur:19 gacnt:5",
        "Log Summary: calcnt:2 gcnt:3 gdur:19 gacnt:5",
    )
    run = parse_guide_log(mismatched)[0]
    assert any("gcnt:3" in w for w in run.warnings)
    assert any("calcnt:2" in w for w in run.warnings)


# --- A-M3: a corrupt row must not silently swallow the rest of a section ----

CORRUPT_MID_SECTION = """PHD2 version 2.6.14 [Windows], Log version 2.5. Log enabled at 2026-07-14 20:13:33

Guiding Begins at 2026-07-14 21:42:27
Equipment Profile = AM5n_OAG_ASI174M
Pixel scale = 1.54 arc-sec/px, Binning = 1, Focal length = 784 mm
Exposure = 500 ms
Frame,Time,mount,dx,dy,RARawDistance,DECRawDistance,RAGuideDistance,DECGuideDistance,RADuration,RADirection,DECDuration,DECDirection,XStep,YStep,StarMass,SNR,ErrorCode
1,1.228,"Mount",0.330,0.544,0.556,-0.189,0.350,0.000,98,W,0,,,,1713,28.59,1
2,2.093,"Mount",0.524
3,3.001,"Mount",0.524,0.132,0.151,-0.477,0.000,0.000,0,,0,,,,1702,28.36,0
4,4.001,"Mount",0.524,0.132,0.151,-0.477,0.000,0.000,0,,0,,,,1702,28.36,0
Guiding Ends at 2026-07-14 21:42:46

Log Summary: calcnt:0 gcnt:1 gdur:19 gacnt:4
Log closed at 2026-07-14 21:43:00
"""


def test_rows_discarded_after_a_corrupt_row_are_counted():
    """The old behaviour set truncated=True and dropped every following row in
    silence. A corrupt row two lines into a 5000-row section then cost a whole
    night's samples with nothing to say so."""
    runs = parse_guide_log(CORRUPT_MID_SECTION)
    section = runs[0].sections[0]
    assert section.truncated is True
    assert len(section.frames) == 1
    # the malformed row plus the two good rows that followed it
    assert section.discarded_rows == 3


def test_the_discard_count_reaches_the_run_warnings():
    runs = parse_guide_log(CORRUPT_MID_SECTION)
    assert any(
        "discarded" in w and "3" in w for w in runs[0].warnings
    ), runs[0].warnings


def test_a_clean_section_discards_nothing_and_warns_about_nothing():
    runs = parse_guide_log(CORRUPT_MID_SECTION.replace(
        '2,2.093,"Mount",0.524\n',
        '2,2.093,"Mount",0.524,0.132,0.151,-0.477,0.000,0.000,0,,0,,,,1702,28.36,0\n',
    ))
    section = runs[0].sections[0]
    assert section.discarded_rows == 0
    assert not any("discarded" in w for w in runs[0].warnings)


def test_the_section_end_line_still_closes_a_discarding_section():
    """Discard mode must not swallow structural lines: the section still has
    to end where PHD2 says it ended."""
    runs = parse_guide_log(CORRUPT_MID_SECTION)
    assert runs[0].sections[0].ended_at_local is not None


# --- A-M6: a CSV header that is close but not exact --------------------------

NEAR_MISS_HEADER = CORRUPT_MID_SECTION.replace(
    "Frame,Time,mount,dx,dy,RARawDistance",
    "Frame,Time,mount,dx,dy,dz,RARawDistance",
)


def test_a_near_miss_csv_header_is_reported_loudly():
    """The header match is a byte comparison against the 2.5 layout. A PHD2
    release that adds one column would otherwise never enter row mode: every
    frame dropped, frame_count 0, no error, no warning, nothing to debug."""
    runs = parse_guide_log(NEAR_MISS_HEADER)
    assert runs[0].sections[0].frames == []
    assert any(
        "does not match" in w and "Frame,Time" in w for w in runs[0].warnings
    ), runs[0].warnings


def test_the_exact_header_produces_no_such_warning():
    runs = parse_guide_log(CORRUPT_MID_SECTION)
    assert not any("does not match" in w for w in runs[0].warnings)


def test_a_calibration_header_near_miss_is_reported_too():
    text = CORRUPT_MID_SECTION.replace(
        "Frame,Time,mount,dx,dy,RARawDistance",
        "Direction,Step,dx,dy,x,y,Dist,Extra\nFrame,Time,mount,dx,dy,RARawDistance",
    )
    runs = parse_guide_log(text)
    assert any("Direction,Step" in w for w in runs[0].warnings), runs[0].warnings


# --- TZ-A: the PHD2 build embedded in an ASIAIR ------------------------------
#
# Verbatim: W:\Astro\Incoming\2024\Okie-Tex 2024\ASIAIR\log\
# PHD2_GuideLog_2024-09-16_201229.txt, lines 1-30 and 32-52, joined. The blank
# line between the two guiding sections is dropped so the second section ends
# mid-CSV, which is how every one of the ten ASIAIR files in the corpus really
# ends: the ASIAIR kills PHD2 rather than closing the log.
#
# Three shapes here differ from every desktop build, and each one is a silent
# data loss until the parser is taught about it:
#   1. the banner carries no version and no platform tag,
#   2. the pointing line omits RA, Alt and Az,
#   3. the max-duration line is prefixed with "Calibration step = ".
# The one departure from the bytes on disk: the file's "Equipment Profile" and
# "Mount" lines end in a trailing space, dropped here so no editor silently
# rewrites the fixture. apply_header_line strips every line before matching, so
# the two forms are indistinguishable to the parser.
ASIAIR_SAMPLE_LOG = """PHD2 version, Log version 2.5. Log enabled at 2024-09-16 20:12:29

Guiding Begins at 2024-09-16 20:12:31
Dither = both axes, Dither scale = 1.000, Image noise reduction = none, Guide-frame time lapse = 0, Server enabled
Pixel scale = 6.45 arc-sec/px, Binning = 1, Focal length = 120 mm
Search region = 50 px, Star mass tolerance = 50.0%
Equipment Profile =
Camera = ZWO ASI120MM Mini, gain = 48, full size = 1280 x 960, have dark, dark dur = 2000, no defect map, pixel size = 3.8 um
Exposure = 2000 ms
Mount = iOptron CEM26/GEM28/HEM27,  connected, guiding enabled, xAngle = -76.2, xRate = 0.693, yAngle = 13.3, yRate = 1.180, parity = +/+,
X guide algorithm = Hysteresis, Hysteresis = 0.100, Aggression = 0.700, Minimum move = 0.100
Y guide algorithm = Resist Switch, Minimum move = 0.100 Aggression = 100% FastSwitch = enabled
Backlash comp = disabled, pulse = 0 ms
Calibration step = phdlab_placeholder, Max RA duration = 2000, Max DEC duration = 2000, DEC guide mode = Auto
RA Guide Speed = 7.5 a-s/s, Dec Guide Speed = 7.5 a-s/s, Cal Dec = 31.7, Last Cal Issue = None, Timestamp = Unknown
Dec = 57.6 deg, Hour angle = -2.77 hr, Pier side = West, Rotator pos = N/A
Lock position = 876.966, 96.832, Star position = 877.037, 96.694, HFD = 5.05 px
Frame,Time,mount,dx,dy,RARawDistance,DECRawDistance,RAGuideDistance,DECGuideDistance,RADuration,RADirection,DECDuration,DECDirection,XStep,YStep,StarMass,SNR,ErrorCode
INFO: SETTLING STATE CHANGE, Settling started
1,2.385,"Mount",0.186,-0.295,0.331,0.108,0.209,0.000,301,W,0,,,,2669,34.05,0
2,4.265,"Mount",0.142,-0.202,0.230,0.088,0.159,0.000,230,W,0,,,,2504,32.75,0
3,6.335,"Mount",0.135,-0.277,0.301,0.063,0.201,0.000,290,W,0,,,,2690,34.10,0
INFO: SETTLING STATE CHANGE, Settling complete
4,8.353,"Mount",0.166,-0.296,0.327,0.089,0.220,0.000,317,W,0,,,,2577,33.18,0
5,10.230,"Mount",0.311,-0.119,0.190,0.272,0.135,0.000,195,W,0,,,,2659,34.01,0
6,12.554,"Mount",0.263,-0.286,0.341,0.185,0.224,0.185,323,W,157,S,,,2669,33.96,0
7,14.578,"Mount",0.220,-0.366,0.408,0.123,0.273,0.123,393,W,105,S,,,2487,33.17,0
8,16.559,"Mount",0.245,-0.280,0.330,0.168,0.227,0.168,328,W,143,S,,,2647,33.92,0
9,18.593,"Mount",0.274,-0.370,0.425,0.174,0.283,0.174,409,W,148,S,,,2665,33.86,0
Guiding Ends at 2024-09-16 20:12:51
Guiding Begins at 2024-09-16 20:12:59
Dither = both axes, Dither scale = 1.000, Image noise reduction = none, Guide-frame time lapse = 0, Server enabled
Pixel scale = 6.45 arc-sec/px, Binning = 1, Focal length = 120 mm
Search region = 50 px, Star mass tolerance = 50.0%
Equipment Profile =
Camera = ZWO ASI120MM Mini, gain = 48, full size = 1280 x 960, have dark, dark dur = 2000, no defect map, pixel size = 3.8 um
Exposure = 2000 ms
Mount = iOptron CEM26/GEM28/HEM27,  connected, guiding enabled, xAngle = -76.2, xRate = 0.693, yAngle = 13.3, yRate = 1.180, parity = +/+,
X guide algorithm = Hysteresis, Hysteresis = 0.100, Aggression = 0.700, Minimum move = 0.100
Y guide algorithm = Resist Switch, Minimum move = 0.100 Aggression = 100% FastSwitch = enabled
Backlash comp = disabled, pulse = 0 ms
Calibration step = phdlab_placeholder, Max RA duration = 2000, Max DEC duration = 2000, DEC guide mode = Auto
RA Guide Speed = 7.5 a-s/s, Dec Guide Speed = 7.5 a-s/s, Cal Dec = 31.7, Last Cal Issue = None, Timestamp = Unknown
Dec = 57.6 deg, Hour angle = -2.76 hr, Pier side = West, Rotator pos = N/A
Lock position = 877.595, 96.360, Star position = 877.644, 96.201, HFD = 4.61 px
Frame,Time,mount,dx,dy,RARawDistance,DECRawDistance,RAGuideDistance,DECGuideDistance,RADuration,RADirection,DECDuration,DECDirection,XStep,YStep,StarMass,SNR,ErrorCode
INFO: SETTLING STATE CHANGE, Settling started
1,2.297,"Mount",0.158,-0.216,0.248,0.100,0.156,0.000,225,W,0,,,,2831,35.11,0
2,4.409,"Mount",0.182,-0.376,0.408,0.084,0.268,0.000,387,W,0,,,,2672,34.14,0
3,6.243,"Mount",0.202,-0.159,0.203,0.156,0.147,0.000,212,W,0,,,,2771,34.70,0
INFO: SETTLING STATE CHANGE, Settling complete
"""

# Verbatim pointing line from the same file. No RA, no Alt, no Az.
ASIAIR_POINTING_LINE = (
    "Dec = 57.6 deg, Hour angle = -2.77 hr, Pier side = West, Rotator pos = N/A"
)
# Verbatim pointing line from PHD2_GuideLog_2026-07-14_201333.txt: all seven
# fields, which is what all but ten files in the 177-file corpus emit.
DESKTOP_POINTING_LINE = (
    "RA = 20.22 hr, Dec = 38.5 deg, Hour angle = -4.02 hr, Pier side = West, "
    "Rotator pos = N/A, Alt = 43.7 deg, Az = 70.4 deg"
)


def test_asiair_banner_without_version_or_platform_is_parsed():
    """The ASIAIR writes "PHD2 version, Log version 2.5." with the version left
    blank and no platform tag. Ten corpus files carry it, and every one of them
    parsed to zero runs until the banner pattern allowed the omission."""
    runs = parse_guide_log(ASIAIR_SAMPLE_LOG)
    assert len(runs) == 1
    run = runs[0]
    # Absent, not invented: nothing in the file says which build wrote it.
    assert run.phd2_version is None
    assert run.platform is None
    # Everything the banner does carry survives.
    assert run.log_version == "2.5"
    assert run.log_enabled_at == datetime(2024, 9, 16, 20, 12, 29)


def test_desktop_banner_still_carries_its_version_and_platform():
    """Two versions including a dev build, so the optional-version banner
    pattern cannot quietly start discarding the version it used to capture."""
    runs = parse_guide_log(EMPTY_STACKED_LOG)
    assert [r.phd2_version for r in runs] == [
        "2.6.13dev8", "2.6.14", "2.6.14", "2.6.14", "2.6.14",
    ]
    assert [r.platform for r in runs] == ["Windows"] * 5
    assert parse_guide_log(FULL_SAMPLE_LOG)[0].phd2_version == "2.6.14"
    assert parse_guide_log(FULL_SAMPLE_LOG)[0].platform == "Windows"


def test_pointing_line_without_ra_alt_and_az_is_parsed():
    header = Phd2Header()
    assert apply_header_line(header, ASIAIR_POINTING_LINE) is True
    assert header.dec_deg == 57.6
    assert header.hour_angle_hr == -2.77
    assert header.pier_side == "West"
    assert header.rotator_pos == "N/A"
    # Absent in the file, so absent here. Nothing is fabricated.
    assert header.ra_hr is None
    assert header.alt_deg is None
    assert header.az_deg is None


def test_full_desktop_pointing_line_is_still_parsed_in_full():
    header = Phd2Header()
    assert apply_header_line(header, DESKTOP_POINTING_LINE) is True
    assert header.ra_hr == 20.22
    assert header.dec_deg == 38.5
    assert header.hour_angle_hr == -4.02
    assert header.pier_side == "West"
    assert header.rotator_pos == "N/A"
    assert header.alt_deg == 43.7
    assert header.az_deg == 70.4


def test_asiair_max_duration_line_survives_its_calibration_step_prefix():
    """The ASIAIR prefixes the max-duration line with a placeholder calibration
    step; desktop builds start the line at "Max RA duration". Without the
    optional prefix all three fields were dropped on all 74 ASIAIR sections."""
    header = Phd2Header()
    assert apply_header_line(
        header,
        "Calibration step = phdlab_placeholder, Max RA duration = 2000, "
        "Max DEC duration = 2000, DEC guide mode = Auto",
    ) is True
    assert header.max_ra_duration_ms == 2000.0
    assert header.max_dec_duration_ms == 2000.0
    assert header.dec_guide_mode == "Auto"


def test_asiair_sample_yields_both_of_its_guiding_sections():
    run = parse_guide_log(ASIAIR_SAMPLE_LOG)[0]
    assert len(run.sections) == 2
    first, second = run.sections
    assert first.started_at_local == datetime(2024, 9, 16, 20, 12, 31)
    assert first.ended_at_local == datetime(2024, 9, 16, 20, 12, 51)
    assert first.truncated is False
    assert [f.frame_index for f in first.frames] == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert first.header.pixel_scale_arcsec == 6.45
    assert first.header.guide_camera == "ZWO ASI120MM Mini"
    assert first.header.dec_deg == 57.6
    assert first.header.ra_hr is None
    # The ASIAIR kills PHD2 rather than closing the log, so the last section of
    # every one of the ten files ends mid-CSV with no "Guiding Ends".
    assert second.truncated is True
    assert [f.frame_index for f in second.frames] == [1, 2, 3]
    assert run.log_closed_at is None


# --- TZ-A: unreadable is not the same thing as empty -------------------------

# A guide log whose banner never appeared: the head of the file was lost. It
# has PHD2 guide-log content but the parser has no run to hang it on.
HEADLESS_LOG = """Guiding Begins at 2024-09-16 20:12:31
Pixel scale = 6.45 arc-sec/px, Binning = 1, Focal length = 120 mm
Frame,Time,mount,dx,dy,RARawDistance,DECRawDistance,RAGuideDistance,DECGuideDistance,RADuration,RADirection,DECDuration,DECDirection,XStep,YStep,StarMass,SNR,ErrorCode
1,2.385,"Mount",0.186,-0.295,0.331,0.108,0.209,0.000,301,W,0,,,,2669,34.05,0
Guiding Ends at 2024-09-16 20:12:51
"""

# A banner shape no released PHD2 writes today. This is the class of defect the
# ASIAIR banner was for a year: unmatched, zero runs, no complaint.
UNKNOWN_BANNER_LOG = """PHD2 version 3.0.0 (Windows) :: Log version 3.0 :: enabled 2027-01-01 00:00:00
Guiding Begins at 2027-01-01 00:00:01
Guiding Ends at 2027-01-01 00:10:01
"""


def test_a_file_with_no_phd2_content_at_all_is_empty_not_unreadable():
    assert parse_guide_log("") == []
    assert parse_guide_log("\n\n   \n") == []
    assert parse_guide_log("not a guide log at all\n") == []


def test_a_banner_only_log_with_no_sections_is_empty_not_unreadable():
    """Five stacked runs and not one guiding section. The parser understood the
    file perfectly; there is simply nothing in it."""
    runs = parse_guide_log(EMPTY_STACKED_LOG)
    assert len(runs) == 5
    assert all(r.sections == [] for r in runs)


def test_guide_log_content_the_parser_cannot_place_raises_rather_than_reading_empty():
    with pytest.raises(phd2_parser.Phd2UnreadableLog):
        parse_guide_log(HEADLESS_LOG)


def test_an_unrecognised_banner_shape_raises_rather_than_reading_empty():
    with pytest.raises(phd2_parser.Phd2UnreadableLog):
        parse_guide_log(UNKNOWN_BANNER_LOG)


def test_the_unreadable_error_quotes_the_line_it_could_not_place():
    """The message is what reaches the user through parse_error, so it has to
    name the evidence rather than say "unreadable" and stop."""
    with pytest.raises(phd2_parser.Phd2UnreadableLog) as excinfo:
        parse_guide_log(UNKNOWN_BANNER_LOG)
    assert "PHD2 version 3.0.0 (Windows)" in str(excinfo.value)


def test_the_unreadable_error_is_catchable_as_a_value_error():
    """Callers that only ever want "this file yielded nothing usable" should
    not have to import the parser's exception to get it."""
    assert issubclass(phd2_parser.Phd2UnreadableLog, ValueError)
