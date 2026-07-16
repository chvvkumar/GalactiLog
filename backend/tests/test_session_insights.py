"""Insight rules: MAD z-score eccentricity grading, the whole-night rig check,
and the typed insight schema.

Motivation: the eccentricity outlier rule used to be `v > median_ecc * 1.5`.
Eccentricity is bounded [0, 1], so that threshold scaled with the median's
absolute value instead of with dispersion, desensitized as frames got worse, and
became unreachable (threshold >= 1.0) once the median passed 0.667. These tests
pin the replacement to the same MAD z-score the per-frame grading table uses.
"""

import pytest
from pydantic import ValidationError

from app.schemas.target import SessionInsight
from app.services import frame_quality
from app.services.frame_quality import MIN_GROUP, Z_REJECT, count_outliers, group_baselines, mad_z
from app.services.target_helpers import (
    ecc_outlier_insight,
    session_ecc_vs_rig_insights,
)


TEL = "Esprit 150"
CAM = "ZWO ASI2600MM"
KEY = f"{TEL}|{CAM}|Ha"


def frames(eccs, telescope=TEL, camera=CAM, filter_used="Ha"):
    """Normalized frame dicts of the shape target_detail feeds the baselines."""
    return [
        {
            "telescope": telescope,
            "camera": camera,
            "filter_used": filter_used,
            "eccentricity": e,
        }
        for e in eccs
    ]


def baselines_for(*frame_lists):
    all_frames = [f for lst in frame_lists for f in lst]
    return group_baselines(all_frames)


# Eight frames, tight spread, one blown frame at 0.90.
ONE_BAD = [0.30, 0.31, 0.32, 0.33, 0.34, 0.35, 0.36, 0.90]
# Eight frames, ordinary night-to-night spread, nothing pathological.
UNIFORM = [0.30, 0.31, 0.32, 0.33, 0.34, 0.35, 0.36, 0.37]
# A high-median night with one blown frame. The old `median * 1.5` rule was
# structurally blind here: threshold would be 1.05, which eccentricity can never
# reach.
HIGH_MEDIAN_ONE_BAD = [0.68, 0.69, 0.70, 0.70, 0.71, 0.72, 0.70, 0.95]


# --- mad_z: must match frontend madZ semantics exactly -------------------------


def test_mad_z_matches_hand_computed_value():
    # value 2.8 against median 2.1, mad 0.37 -> 1.891..., the worked example in
    # frontend/src/utils/frameQuality.ts.
    z = mad_z(2.8, {"median": 2.1, "mad": 0.37, "n": 10})
    assert z == pytest.approx(0.7 / 0.37)


def test_mad_z_higher_is_better_flips_sign():
    z = mad_z(80, {"median": 100, "mad": 10, "n": 10}, higher_is_better=True)
    assert z == pytest.approx(2.0)


def test_mad_z_none_when_group_sparse():
    assert mad_z(0.9, {"median": 0.3, "mad": 0.02, "n": MIN_GROUP - 1}) is None


def test_mad_z_none_when_mad_zero():
    assert mad_z(0.9, {"median": 0.3, "mad": 0.0, "n": 50}) is None


def test_mad_z_none_when_value_or_baseline_missing():
    assert mad_z(None, {"median": 0.3, "mad": 0.02, "n": 50}) is None
    assert mad_z(0.9, None) is None
    assert mad_z(0.9, {"median": None, "mad": 0.02, "n": 50}) is None


def test_count_outliers_reports_graded_population():
    fs = frames(ONE_BAD)
    outliers, graded = count_outliers(fs, baselines_for(fs), "eccentricity")
    assert (outliers, graded) == (1, 8)


def test_count_outliers_grades_nothing_when_baseline_unusable():
    fs = frames(ONE_BAD[:6])  # n = 6 < MIN_GROUP
    outliers, graded = count_outliers(fs, baselines_for(fs), "eccentricity")
    assert (outliers, graded) == (0, 0)


def test_count_outliers_uses_each_frames_own_group():
    ha = frames(ONE_BAD, filter_used="Ha")
    oiii = frames(UNIFORM, filter_used="OIII")
    bl = baselines_for(ha, oiii)
    outliers, graded = count_outliers(ha + oiii, bl, "eccentricity")
    assert (outliers, graded) == (1, 16)


# --- ecc_outlier_insight ------------------------------------------------------


def test_ecc_insight_fires_on_a_real_outlier():
    fs = frames(ONE_BAD)
    insight = ecc_outlier_insight(fs, baselines_for(fs))
    assert insight is not None
    assert insight.level == "warning"
    assert insight.kind == "eccentricity_outliers"
    assert insight.message.startswith("1 frame with eccentricity outlier")


def test_ecc_insight_pluralizes():
    fs = frames([0.30, 0.31, 0.32, 0.33, 0.34, 0.35, 0.90, 0.95])
    insight = ecc_outlier_insight(fs, baselines_for(fs))
    assert insight.message.startswith("2 frames with eccentricity outliers")


def test_ecc_insight_silent_on_a_uniform_session():
    fs = frames(UNIFORM)
    assert ecc_outlier_insight(fs, baselines_for(fs)) is None


def test_ecc_insight_fires_above_the_old_rules_reachability_ceiling():
    # median 0.70 -> the old `median * 1.5` threshold was 1.05, unreachable for a
    # [0, 1] metric, so the old rule could never fire on this night at all.
    fs = frames(HIGH_MEDIAN_ONE_BAD)
    bl = baselines_for(fs)
    assert bl[KEY]["eccentricity"]["median"] == pytest.approx(0.70)
    insight = ecc_outlier_insight(fs, bl)
    assert insight is not None
    assert insight.message.startswith("1 frame with eccentricity outlier")


def test_ecc_insight_silent_when_group_is_sparse():
    fs = frames(ONE_BAD[:6])
    assert ecc_outlier_insight(fs, baselines_for(fs)) is None


def test_ecc_insight_silent_when_mad_is_zero():
    # Eight identical frames plus one blown one: the MAD of the deviations is 0,
    # so there is no scale to divide by. madZ returns null on the frontend for
    # exactly this input; the insight must stay silent rather than invent a
    # threshold.
    fs = frames([0.30] * 8 + [0.90])
    assert baselines_for(fs)[KEY]["eccentricity"]["mad"] == 0.0
    assert ecc_outlier_insight(fs, baselines_for(fs)) is None


def test_ecc_insight_silent_without_baselines():
    assert ecc_outlier_insight(frames(ONE_BAD), None) is None
    assert ecc_outlier_insight([], {}) is None


def test_ecc_insight_threshold_agrees_with_frontend_reject_band():
    # bandForZ in frontend/src/utils/frameQuality.ts calls "reject" at z >= 3.0.
    # A frame just under that must not be described as an outlier.
    assert Z_REJECT == 3.0
    median, mad_val = 0.30, 0.02
    just_under = median + 2.9 * mad_val
    just_over = median + 3.1 * mad_val
    baseline = {"median": median, "mad": mad_val, "n": 20}
    assert mad_z(just_under, baseline) < Z_REJECT
    assert mad_z(just_over, baseline) >= Z_REJECT


def test_ecc_insight_prefix_is_applied_for_per_rig_use():
    fs = frames(ONE_BAD)
    insight = ecc_outlier_insight(fs, baselines_for(fs), prefix="[Esprit 150 / ZWO ASI2600MM] ")
    assert insight.message.startswith("[Esprit 150 / ZWO ASI2600MM] 1 frame")


# --- session_ecc_vs_rig_insights (whole-night check) --------------------------


def rig_baseline(median, mad, n=200, key=KEY):
    return {key: {"eccentricity": {"median": median, "mad": mad, "n": n}}}


def test_whole_night_insight_fires_when_every_frame_is_bad():
    # A night where all frames are elongated. Per-frame z sees nothing (the
    # session median moves with them); only the rig baseline catches it.
    fs = frames([0.68, 0.70, 0.71, 0.72, 0.69, 0.73, 0.70, 0.71])
    session = group_baselines(fs)
    assert ecc_outlier_insight(fs, session) is None

    out = session_ecc_vs_rig_insights(session, rig_baseline(0.35, 0.03))
    assert len(out) == 1
    assert out[0].level == "warning"
    assert out[0].kind == "eccentricity_vs_rig"
    assert "0.70" in out[0].message and "0.35" in out[0].message


def test_whole_night_insight_silent_on_a_normal_night():
    fs = frames(UNIFORM)
    out = session_ecc_vs_rig_insights(group_baselines(fs), rig_baseline(0.33, 0.03))
    assert out == []


def test_whole_night_insight_silent_when_rig_baseline_sparse():
    fs = frames([0.70] * 8)
    out = session_ecc_vs_rig_insights(
        group_baselines(fs), rig_baseline(0.35, 0.03, n=MIN_GROUP - 1)
    )
    assert out == []


def test_whole_night_insight_silent_when_rig_mad_zero():
    fs = frames([0.70] * 8)
    out = session_ecc_vs_rig_insights(group_baselines(fs), rig_baseline(0.35, 0.0))
    assert out == []


def test_whole_night_insight_silent_when_rig_group_missing():
    fs = frames([0.70] * 8)
    out = session_ecc_vs_rig_insights(group_baselines(fs), {})
    assert out == []
    assert session_ecc_vs_rig_insights(group_baselines(fs), None) == []


def test_whole_night_insight_needs_more_than_a_couple_of_frames():
    fs = frames([0.70, 0.71])  # n = 2 < MIN_SESSION_MEDIAN_FRAMES
    assert session_ecc_vs_rig_insights(group_baselines(fs), rig_baseline(0.35, 0.03)) == []


def test_whole_night_insight_is_not_gated_on_min_group():
    # The dispersion comes from the rig baseline, not the session, so a short but
    # clearly-bad night is still reportable.
    fs = frames([0.70, 0.71, 0.72])
    out = session_ecc_vs_rig_insights(group_baselines(fs), rig_baseline(0.35, 0.03))
    assert len(out) == 1


def test_whole_night_insight_reports_each_train_filter_group():
    ha = frames([0.70] * 8, filter_used="Ha")
    oiii = frames([0.34] * 8, filter_used="OIII")
    rig = {
        f"{TEL}|{CAM}|Ha": {"eccentricity": {"median": 0.35, "mad": 0.03, "n": 200}},
        f"{TEL}|{CAM}|OIII": {"eccentricity": {"median": 0.35, "mad": 0.03, "n": 200}},
    }
    out = session_ecc_vs_rig_insights(group_baselines(ha + oiii), rig)
    assert len(out) == 1
    assert "Ha" in out[0].message


def test_whole_night_insight_labels_the_group_readably():
    fs = frames([0.70] * 8)
    out = session_ecc_vs_rig_insights(group_baselines(fs), rig_baseline(0.35, 0.03))
    assert out[0].message.startswith(f"[{TEL} / {CAM} / Ha]")


# --- typed schema -------------------------------------------------------------


def test_insight_requires_a_known_level():
    with pytest.raises(ValidationError):
        SessionInsight(level="critical", kind="sensor_temp", message="x")


def test_insight_requires_a_known_kind():
    with pytest.raises(ValidationError):
        SessionInsight(level="warning", kind="not_a_kind", message="x")


def test_insight_requires_kind_to_be_present():
    with pytest.raises(ValidationError):
        SessionInsight(level="warning", message="x")


def test_insight_accepts_every_level_the_backend_emits():
    for level in ("info", "good", "warning"):
        assert SessionInsight(level=level, kind="sensor_temp", message="x").level == level


def test_insight_kind_survives_serialization():
    si = SessionInsight(level="warning", kind="eccentricity_vs_rig", message="x")
    assert si.model_dump() == {
        "level": "warning",
        "kind": "eccentricity_vs_rig",
        "message": "x",
    }


def test_z_reject_is_shared_not_duplicated():
    # The insight text and the frontend cell colours must key off one constant.
    assert frame_quality.Z_REJECT == 3.0
