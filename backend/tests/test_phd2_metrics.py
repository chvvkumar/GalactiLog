"""Aggregation tests: PHD2-parity RMS, drop runs, pulses, settle, night rollup."""
import math
from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.services import phd2_parser
from app.services.phd2_metrics import (
    EXCURSION_SIGMA, MIN_FRAMES, aggregate_night, build_frame_rows,
    compute_session_metrics, dither_settle_windows, local_to_utc,
)


def _frame(index, t, ra, dec, *, dropped=False, ra_ms=0, ra_dir="",
           dec_ms=0, dec_dir="", snr=30.0, mass=1700.0, reason=""):
    return phd2_parser.Phd2Frame(
        frame_index=index, time_offset=t, dropped=dropped,
        dx=ra, dy=dec, ra_raw=ra, dec_raw=dec, ra_guide=0.0, dec_guide=0.0,
        ra_duration_ms=ra_ms, ra_direction=ra_dir,
        dec_duration_ms=dec_ms, dec_direction=dec_dir,
        star_mass=mass, snr=snr, error_code=0, drop_reason=reason,
    )


def _section(frames, events=(), *, pixel_scale=2.0):
    header = phd2_parser.Phd2Header(
        equipment_profile="AM5n_OAG_ASI174M",
        pixel_scale_arcsec=pixel_scale,
        focal_length_mm=784.0,
        guide_camera="ZWO ASI174MM Mini",
        exposure_ms=500.0,
        dec_guide_mode="Auto",
        algo_ra="Hysteresis",
        algo_dec="Resist Switch",
        min_move_ra=0.25,
        min_move_dec=0.25,
        aggression_ra=0.7,
        ortho_error_deg=11.8,
        last_cal_issue="None",
        pier_side="West",
        alt_deg=43.7,
        az_deg=70.4,
        dec_deg=38.5,
        hour_angle_hr=-4.02,
        mount_name="ASI Mount (ASCOM)",
    )
    return phd2_parser.Phd2GuidingSection(
        started_at_local=datetime(2026, 7, 14, 21, 42, 27),
        header=header,
        ended_at_local=datetime(2026, 7, 14, 21, 44, 27),
        frames=list(frames),
        events=list(events),
    )


def _metrics(section, tz_name="America/New_York"):
    return compute_session_metrics(
        section, tz_name=tz_name, observer_longitude=-80.0, use_imaging_night=True
    )


def test_local_to_utc_uses_the_named_zone():
    naive = datetime(2026, 7, 14, 21, 42, 27)
    assert local_to_utc(naive, "America/New_York") == datetime(
        2026, 7, 15, 1, 42, 27, tzinfo=timezone.utc
    )


def test_local_to_utc_with_empty_setting_uses_server_local_zone():
    naive = datetime(2026, 7, 14, 21, 42, 27)
    expected = naive.astimezone().astimezone(timezone.utc)
    assert local_to_utc(naive, "") == expected


def test_dither_settle_window_spans_dither_to_settle_done():
    events = [
        phd2_parser.Phd2Event(type="dither", time_offset=10.0, detail="x"),
        phd2_parser.Phd2Event(type="settle_start", time_offset=10.0, detail="Settling started"),
        phd2_parser.Phd2Event(type="settle_done", time_offset=14.0, detail="Settling complete"),
    ]
    section = _section([_frame(i, float(i), 0.0, 0.0) for i in range(1, 21)], events)
    assert dither_settle_windows(section) == [(10.0, 14.0)]


def test_unclosed_settle_window_runs_to_the_end_of_the_section():
    events = [
        phd2_parser.Phd2Event(type="settle_start", time_offset=5.0, detail="Settling started"),
    ]
    section = _section([_frame(i, float(i), 0.0, 0.0) for i in range(1, 11)], events)
    assert dither_settle_windows(section) == [(5.0, 10.0)]


def test_rms_excludes_dither_and_settle_frames_for_phd2_parity():
    # Ten quiet frames at +/-1 px, then a settle window whose frames are wild.
    frames = [_frame(i, float(i), 1.0 if i % 2 else -1.0, 0.0) for i in range(1, 11)]
    frames += [_frame(i, float(i), 50.0, 50.0) for i in range(11, 15)]
    events = [
        phd2_parser.Phd2Event(type="dither", time_offset=10.0, detail="d"),
        phd2_parser.Phd2Event(type="settle_done", time_offset=14.0, detail="Settling complete"),
    ]
    m = _metrics(_section(frames, events, pixel_scale=2.0))
    # 1 px std dev * 2.0 arcsec/px, with the dither excursion excluded.
    assert m.rms_ra_arcsec == 2.0
    assert m.rms_dec_arcsec == 0.0
    assert m.rms_total_arcsec == 2.0
    assert m.peak_ra_arcsec == 2.0


def test_excursion_filtered_rms_drops_multi_sigma_outliers():
    frames = [_frame(i, float(i), 1.0 if i % 2 else -1.0, 0.0) for i in range(1, 101)]
    frames.append(_frame(101, 101.0, 200.0, 0.0))
    m = _metrics(_section(frames, pixel_scale=1.0))
    assert m.rms_ra_arcsec > 10.0        # the excursion dominates the raw figure
    assert m.rms_ra_filtered_arcsec < 1.5  # and is removed from the filtered one
    assert EXCURSION_SIGMA == 5.0


def test_rms_is_none_without_a_pixel_scale():
    section = _section([_frame(i, float(i), 1.0, 0.0) for i in range(1, 6)])
    section.header.pixel_scale_arcsec = None
    m = _metrics(section)
    assert m.rms_ra_arcsec is None
    assert m.rms_total_arcsec is None
    assert m.frame_count == 5


def test_drop_runs_and_unguided_seconds():
    frames = [
        _frame(1, 1.0, 0.1, 0.1),
        _frame(2, 2.0, None, None, dropped=True, reason="Star lost - mass changed"),
        _frame(3, 3.0, None, None, dropped=True, reason="Star lost - mass changed"),
        _frame(4, 4.0, None, None, dropped=True, reason="Star lost - low SNR"),
        _frame(5, 5.0, 0.1, 0.1),
        _frame(6, 6.0, None, None, dropped=True, reason="Star lost - low SNR"),
        _frame(7, 7.0, 0.1, 0.1),
    ]
    m = _metrics(_section(frames))
    assert m.frame_count == 7
    assert m.drop_count == 4
    assert m.max_drop_run == 3
    # First run: frame 1 (t=1) to frame 5 (t=5) = 4 s. Second: 5 -> 7 = 2 s.
    assert m.unguided_seconds == 6.0
    assert m.star_lost_reasons == {
        "Star lost - mass changed": 2, "Star lost - low SNR": 2,
    }


def test_pulse_tallies_count_every_non_dropped_frame():
    frames = [
        _frame(1, 1.0, 0.5, 0.0, ra_ms=98, ra_dir="W"),
        _frame(2, 2.0, -0.5, 0.0, ra_ms=125, ra_dir="E"),
        _frame(3, 3.0, 0.0, 0.6, dec_ms=267, dec_dir="S"),
        _frame(4, 4.0, 0.0, -0.6, dec_ms=105, dec_dir="N"),
        _frame(5, 5.0, 0.0, 0.0),
    ]
    m = _metrics(_section(frames))
    assert m.pulse_count_ra_west == 1
    assert m.pulse_count_ra_east == 1
    assert m.pulse_count_dec_north == 1
    assert m.pulse_count_dec_south == 1
    assert m.pulse_total_ms_ra == 223
    assert m.pulse_total_ms_dec == 372


def test_settle_counts_and_median_duration():
    events = [
        phd2_parser.Phd2Event(type="dither", time_offset=1.0, detail="a"),
        phd2_parser.Phd2Event(type="settle_start", time_offset=1.0, detail="Settling started"),
        phd2_parser.Phd2Event(type="settle_done", time_offset=3.0, detail="Settling complete"),
        phd2_parser.Phd2Event(type="dither", time_offset=5.0, detail="b"),
        phd2_parser.Phd2Event(type="settle_start", time_offset=5.0, detail="Settling started"),
        phd2_parser.Phd2Event(type="settle_failed", time_offset=11.0, detail="Settling failed"),
    ]
    section = _section([_frame(i, float(i), 0.0, 0.0) for i in range(1, 13)], events)
    m = _metrics(section)
    assert m.dither_count == 2
    assert m.settle_count == 2
    assert m.settle_failed_count == 1
    assert m.settle_median_s == 4.0
    assert [e["type"] for e in m.events] == [
        "dither", "settle_start", "settle_done", "dither", "settle_start", "settle_failed",
    ]
    assert m.events[0] == {"type": "dither", "t": 1.0, "detail": "a"}


def test_header_echo_and_timing_columns():
    section = _section([_frame(1, 1.0, 0.1, 0.1)])
    m = _metrics(section)
    assert m.equipment_profile == "AM5n_OAG_ASI174M"
    assert m.pixel_scale_arcsec == 2.0
    assert m.focal_length_mm == 784.0
    assert m.guide_camera == "ZWO ASI174MM Mini"
    assert m.exposure_ms == 500.0
    assert m.dec_guide_mode == "Auto"
    assert m.algo_ra == "Hysteresis"
    assert m.algo_dec == "Resist Switch"
    assert m.min_move_ra == 0.25
    assert m.min_move_dec == 0.25
    assert m.aggression_ra == 0.7
    assert m.ortho_error_deg == 11.8
    assert m.last_cal_issue == "None"
    assert m.pier_side == "West"
    assert m.alt_deg == 43.7
    assert m.az_deg == 70.4
    assert m.dec_deg == 38.5
    assert m.hour_angle_hr == -4.02
    assert m.mount_name == "ASI Mount (ASCOM)"
    assert m.started_at_local == datetime(2026, 7, 14, 21, 42, 27)
    assert m.started_at_utc == datetime(2026, 7, 15, 1, 42, 27, tzinfo=timezone.utc)
    assert m.ended_at_utc == datetime(2026, 7, 15, 1, 44, 27, tzinfo=timezone.utc)
    assert m.duration_s == 120.0
    assert m.session_date == date(2026, 7, 14)


def test_build_frame_rows_matches_the_model_column_names():
    rows = build_frame_rows(_section([
        _frame(1, 1.228, 0.556, -0.189, ra_ms=98, ra_dir="W"),
        _frame(9067, 9716.891, None, None, dropped=True, reason="Star lost - mass changed"),
    ]))
    assert rows[0] == {
        "frame_index": 1, "time_offset": 1.228, "dx": 0.556, "dy": -0.189,
        "ra_raw": 0.556, "dec_raw": -0.189, "ra_guide": 0.0, "dec_guide": 0.0,
        "ra_duration_ms": 98, "ra_direction": "W",
        "dec_duration_ms": 0, "dec_direction": "",
        "star_mass": 1700.0, "snr": 30.0, "error_code": 0, "dropped": False,
    }
    assert rows[1]["dropped"] is True
    assert rows[1]["ra_raw"] is None


def _night_row(frame_count, rms_ra, rms_dec, rms_total, profile="P1", issue=None):
    return SimpleNamespace(
        frame_count=frame_count,
        rms_ra_arcsec=rms_ra, rms_dec_arcsec=rms_dec, rms_total_arcsec=rms_total,
        drop_count=2, max_drop_run=1, unguided_seconds=3.0,
        dither_count=1, settle_failed_count=1, settle_median_s=4.0,
        last_cal_issue=issue, equipment_profile=profile,
    )


def test_aggregate_night_weights_by_frame_count_and_gates_short_sessions():
    rows = [
        _night_row(400, 1.0, 1.0, math.sqrt(2)),
        _night_row(100, 3.0, 3.0, math.sqrt(18)),
        _night_row(10, 99.0, 99.0, 140.0, profile="P2", issue="Orthogonality"),
    ]
    out = aggregate_night(rows)
    assert MIN_FRAMES == 100
    assert out["session_count"] == 3
    assert out["gated_session_count"] == 1
    assert out["frame_count"] == 510
    # sqrt((400*1 + 100*9) / 500) = sqrt(2.6); the 10-frame session is excluded.
    assert out["rms_ra_arcsec"] == round(math.sqrt(2.6), 6)
    assert out["drop_count"] == 6
    assert out["max_drop_run"] == 1
    assert out["unguided_seconds"] == 9.0
    assert out["dither_count"] == 3
    assert out["settle_failed_count"] == 3
    assert out["settle_median_s"] == 4.0
    assert out["cal_issues"] == ["Orthogonality"]
    assert out["profiles"] == ["P1", "P2"]


def test_aggregate_night_with_only_gated_sessions_reports_no_rms():
    out = aggregate_night([_night_row(10, 1.0, 1.0, 1.4)])
    assert out["gated_session_count"] == 1
    assert out["rms_ra_arcsec"] is None
    assert out["rms_total_arcsec"] is None
    assert out["frame_count"] == 10
