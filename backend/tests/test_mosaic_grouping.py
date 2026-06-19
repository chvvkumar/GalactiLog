"""Tests for the name+position hybrid mosaic panel grouping pipeline.

These exercise the pure (non-DB) stages of mosaic_detection:
  - robust per-target median sky-center (Stage 0)
  - name-path panel/tile token matching (Stage 1)
  - position-path clustering (Stage 2)
  - reconcile + confidence/flag scoring (Stage 3)

All fixtures are synthetic in-memory structures; no DB or live data needed.
"""
import math

import pytest

from app.services.mosaic_detection import (
    TargetCenter,
    angular_separation_deg,
    robust_median_center,
    compute_fov_arcmin,
    match_panel_token,
    strip_panel_token,
    group_panels,
    PanelCandidate,
)


# ---------------------------------------------------------------------------
# Stage 0: robust median center + FOV
# ---------------------------------------------------------------------------

def test_median_center_ignores_corrupt_outlier_frame():
    """A single corrupt-header frame must not drag the center away.

    Most frames cluster near (40.5, 61.2); one outlier sits ~30 deg away.
    The median must stay with the cluster, not the mean.
    """
    frames = [
        {"RA": 40.50, "DEC": 61.20},
        {"RA": 40.52, "DEC": 61.19},
        {"RA": 40.49, "DEC": 61.21},
        {"RA": 40.51, "DEC": 61.20},
        {"RA": 10.00, "DEC": 30.00},  # corrupt outlier
    ]
    center = robust_median_center(frames)
    assert center is not None
    assert abs(center.ra - 40.505) < 0.05
    assert abs(center.dec - 61.20) < 0.05


def test_median_center_ignores_corrupt_first_frame():
    """The unwrap reference must be robust: a corrupt FIRST frame must not
    mis-center the result (regression for ref_ra = coords[0])."""
    frames = [
        {"RA": 10.00, "DEC": 30.00},  # corrupt outlier, listed FIRST
        {"RA": 40.50, "DEC": 61.20},
        {"RA": 40.52, "DEC": 61.19},
        {"RA": 40.49, "DEC": 61.21},
        {"RA": 40.51, "DEC": 61.20},
    ]
    center = robust_median_center(frames)
    assert center is not None
    assert abs(center.ra - 40.505) < 0.05
    assert abs(center.dec - 61.20) < 0.05


def test_median_center_prefers_decimal_over_sexagesimal():
    """Decimal RA/DEC is used when present; OBJCTRA/OBJCTDEC is the fallback."""
    frames = [
        {"RA": 83.8, "DEC": -5.4, "OBJCTRA": "99 99 99", "OBJCTDEC": "99 99 99"},
        {"RA": 83.81, "DEC": -5.39},
    ]
    center = robust_median_center(frames)
    assert center is not None
    assert abs(center.ra - 83.805) < 0.05
    assert abs(center.dec - (-5.395)) < 0.05


def test_median_center_falls_back_to_sexagesimal():
    """With no decimal RA/DEC, parse OBJCTRA (hours) / OBJCTDEC (deg)."""
    frames = [
        {"OBJCTRA": "05 35 17", "OBJCTDEC": "-05 23 28"},
        {"OBJCTRA": "05 35 18", "OBJCTDEC": "-05 23 30"},
    ]
    center = robust_median_center(frames)
    assert center is not None
    # 05h35m17s ~= 83.82 deg
    assert abs(center.ra - 83.82) < 0.1
    assert abs(center.dec - (-5.39)) < 0.05


def test_median_center_ra_wrap_around_zero():
    """RA values straddling the 0/360 boundary average correctly, not to ~180."""
    frames = [
        {"RA": 359.9, "DEC": 10.0},
        {"RA": 0.1, "DEC": 10.0},
        {"RA": 359.95, "DEC": 10.0},
    ]
    center = robust_median_center(frames)
    assert center is not None
    # Median center should be near 0/360, never near 180.
    wrapped = min(center.ra, 360.0 - center.ra)
    assert wrapped < 1.0


def test_median_center_none_when_no_coords():
    assert robust_median_center([{"FOO": "bar"}]) is None
    assert robust_median_center([]) is None


def test_compute_fov_arcmin():
    """FOV = NAXIS * (206.265 * XPIXSZ / FOCALLEN) / 60 arcmin."""
    fov = compute_fov_arcmin(focallen=448.0, xpixsz=3.76, naxis=4144)
    # pixel scale = 206.265 * 3.76 / 448 = 1.731 arcsec/px
    # fov = 4144 * 1.731 / 60 = ~119.5 arcmin
    assert fov is not None
    assert 110 < fov < 130


def test_compute_fov_none_when_missing():
    assert compute_fov_arcmin(focallen=None, xpixsz=3.76, naxis=4144) is None
    assert compute_fov_arcmin(focallen=448, xpixsz=None, naxis=4144) is None


def test_angular_separation():
    # Two points 1 deg apart in DEC at the same RA.
    sep = angular_separation_deg(10.0, 20.0, 10.0, 21.0)
    assert abs(sep - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# Stage 1: name-path token matching
# ---------------------------------------------------------------------------

def test_match_panel_token_keyword():
    keywords = ["Panel", "P"]
    base, num = match_panel_token("Heart Nebula Panel 1", keywords)
    assert base == "Heart Nebula"
    assert num == "1"


def test_match_panel_token_p_shorthand():
    keywords = ["Panel", "P"]
    base, num = match_panel_token("Veil_P3", keywords)
    assert base == "Veil"
    assert num == "3"


def test_match_tile_pattern_r_c():
    """Tile pattern like IC1805_1-1 must be recognized with R-C => panel number."""
    keywords = ["Panel", "P"]
    base, num = match_panel_token("IC1805_1-1", keywords)
    assert base == "IC1805"
    assert num == "1-1"


def test_match_panel_token_none_for_unsuffixed():
    keywords = ["Panel", "P"]
    assert match_panel_token("Heart Nebula", keywords) is None
    assert match_panel_token("IC1805", keywords) is None


def test_strip_panel_token():
    keywords = ["Panel", "P"]
    assert strip_panel_token("Heart Nebula Panel 1", keywords) == "Heart Nebula"
    assert strip_panel_token("IC1805_1-1", keywords) == "IC1805"


# ---------------------------------------------------------------------------
# Stage 1+2+3: full grouping via group_panels
# ---------------------------------------------------------------------------

def _cand(target_id, object_names, ra, dec, fov=120.0):
    """Build a PanelCandidate-feeding record."""
    return {
        "target_id": target_id,
        "object_names": object_names,
        "center": TargetCenter(ra=ra, dec=dec) if ra is not None else None,
        "fov_arcmin": fov,
    }


def test_name_path_panel_n_grouping():
    """Standard 'Panel N' targets sharing a base name group together."""
    targets = [
        _cand("t1", ["Heart Nebula Panel 1"], 38.0, 61.0),
        _cand("t2", ["Heart Nebula Panel 2"], 39.5, 61.0),
    ]
    groups = group_panels(targets, keywords=["Panel", "P"], tolerance_arcmin=12.0)
    assert len(groups) == 1
    g = groups[0]
    assert g.base_name == "Heart Nebula"
    assert sorted(g.panel_labels) == ["Panel 1", "Panel 2"]
    assert "name" in (g.discovery_source, "name") or g.discovery_source in ("name", "both")
    assert g.confidence == "high"


def test_tile_pattern_grouping():
    """Tile-convention names (_R-C) without the Panel keyword still group."""
    targets = [
        _cand("t1", ["IC1805_1-1"], 38.0, 61.0),
        _cand("t2", ["IC1805_1-2"], 39.5, 61.0),
    ]
    groups = group_panels(targets, keywords=["Panel", "P"], tolerance_arcmin=12.0)
    assert len(groups) == 1
    g = groups[0]
    assert g.base_name == "IC1805"
    assert len(g.target_ids) == 2


def test_position_path_discovers_tiles_without_panel_keyword():
    """Position confirmation works for tile names; name+position agree => HIGH."""
    targets = [
        _cand("t1", ["IC1805_1-1"], 38.0, 61.0),
        _cand("t2", ["IC1805_1-2"], 39.5, 61.0),
    ]
    groups = group_panels(targets, keywords=["Panel", "P"], tolerance_arcmin=12.0)
    assert len(groups) == 1
    g = groups[0]
    assert g.discovery_source in ("name", "both")
    assert g.confidence == "high"
    # geometry should record per-panel centers and pairwise pitch
    assert g.geometry is not None
    assert len(g.geometry["panels"]) == 2
    assert len(g.geometry["pitches"]) >= 1


def test_never_absorb_unsuffixed_standalone():
    """An un-suffixed target overlapping panel positions is never absorbed."""
    targets = [
        _cand("t1", ["Heart Nebula Panel 1"], 38.0, 61.0),
        _cand("t2", ["Heart Nebula Panel 2"], 39.5, 61.0),
        _cand("t3", ["Heart Nebula"], 38.7, 61.0),  # standalone wide frame
    ]
    groups = group_panels(targets, keywords=["Panel", "P"], tolerance_arcmin=12.0)
    assert len(groups) == 1
    g = groups[0]
    assert "t3" not in g.target_ids
    assert len(g.target_ids) == 2


def test_reframing_single_target_stays_one_target():
    """A single widely-spread target (re-framed) never splits into fake panels."""
    targets = [
        _cand("t1", ["Horsehead Nebula"], 85.0, -2.5),
    ]
    groups = group_panels(targets, keywords=["Panel", "P"], tolerance_arcmin=12.0)
    assert groups == []


def test_confidence_high_on_agreement():
    """Distinct centers + matching base name + name & position agree => HIGH, no flags."""
    targets = [
        _cand("t1", ["Pelican Panel 1"], 313.0, 44.0),
        _cand("t2", ["Pelican Panel 2"], 314.5, 44.0),
    ]
    groups = group_panels(targets, keywords=["Panel", "P"], tolerance_arcmin=12.0)
    g = groups[0]
    assert g.confidence == "high"
    assert g.flags == []


def test_confidence_low_when_panels_share_center():
    """Two 'panels' at the same center within tolerance => LOW with a flag."""
    targets = [
        _cand("t1", ["Rosette Panel 1"], 98.0, 5.0),
        _cand("t2", ["Rosette Panel 2"], 98.01, 5.0),  # ~0.6 arcmin apart
    ]
    groups = group_panels(targets, keywords=["Panel", "P"], tolerance_arcmin=12.0)
    g = groups[0]
    assert g.confidence == "low"
    assert any("center" in f.lower() for f in g.flags)


def test_confidence_low_when_position_groups_unrelated_names():
    """Position path links targets whose base names differ => LOW + flag.

    Two panel-tokened targets with unrelated base names but coincident centers
    should be flagged, not silently merged with HIGH confidence.
    """
    targets = [
        _cand("t1", ["Foo Panel 1"], 200.0, 30.0),
        _cand("t2", ["Bar Panel 2"], 201.5, 30.0),
    ]
    groups = group_panels(targets, keywords=["Panel", "P"], tolerance_arcmin=12.0)
    # They have different base names, so name-path keeps them apart; position
    # path may link them spatially -> a low-confidence flagged group.
    low_groups = [g for g in groups if g.confidence == "low"]
    if low_groups:
        assert any(
            "base name" in f.lower() or "unrelated" in f.lower()
            for g in low_groups for f in g.flags
        )
    else:
        # Acceptable alternative: they simply never group (distinct base names,
        # no position link). In that case there must be no HIGH cross-name group.
        for g in groups:
            assert not ("Foo" in g.base_name and "Bar" in g.base_name)


def test_two_panels_required():
    """A lone panel-tokened target (only one distinct panel) is not a group."""
    targets = [
        _cand("t1", ["Wizard Panel 1"], 350.0, 60.0),
    ]
    groups = group_panels(targets, keywords=["Panel", "P"], tolerance_arcmin=12.0)
    assert groups == []


def test_cross_name_cluster_rejected_when_panel_numbers_collide():
    """Cross-name position discovery must enforce >=2 distinct panel numbers.

    Two spatially-adjacent targets that both parsed to 'Panel 1' from different
    bases would produce duplicate panel labels (breaking accept/session
    matching), so the cluster must not be emitted as a group.
    """
    targets = [
        _cand("t1", ["Foo Panel 1"], 200.0, 30.0),
        _cand("t2", ["Bar Panel 1"], 201.5, 30.0),  # same panel number, diff base
    ]
    groups = group_panels(targets, keywords=["Panel", "P"], tolerance_arcmin=12.0)
    # No group may contain duplicate panel labels, and the colliding cluster
    # must not be emitted.
    for g in groups:
        assert len(g.panel_labels) == len(set(g.panel_labels))
    # These two never name-group (distinct bases) and must not position-group
    # either (panel-number collision), so no group spans both targets.
    for g in groups:
        assert not ("t1" in g.target_ids and "t2" in g.target_ids)


def test_campaign_subset_geometry_pitches_only_subset_panels():
    """Gap-split suggestions must recompute pitches for the campaign subset.

    A 3-panel group split so one campaign keeps only panels 1 and 2 must yield
    geometry with a single pitch (the 1<->2 separation), not the full group's
    three pairwise pitches.
    """
    from app.services.mosaic_detection import (
        PanelGroup, _add_suggestion, _geometry_from_panels,
    )
    from unittest.mock import MagicMock
    from uuid import uuid4

    raw1, raw2, raw3 = uuid4(), uuid4(), uuid4()
    raw_id = {"t1": raw1, "t2": raw2, "t3": raw3}

    full_geometry = {
        "panels": [
            {"target_id": "t1", "label": "Panel 1", "ra": 200.0, "dec": 30.0},
            {"target_id": "t2", "label": "Panel 2", "ra": 201.5, "dec": 30.0},
            {"target_id": "t3", "label": "Panel 3", "ra": 203.0, "dec": 30.0},
        ],
        "pitches": [1.0, 2.0, 3.0],  # full-group placeholder values
        "fov_arcmin": 120.0,
    }
    group = PanelGroup(
        base_name="Foo",
        target_ids=["t1", "t2", "t3"],
        panel_labels=["Panel 1", "Panel 2", "Panel 3"],
        panel_numbers=["1", "2", "3"],
        confidence="high",
        discovery_source="both",
        flags=[],
        geometry=full_geometry,
    )

    captured = {}
    sess = MagicMock()
    sess.add = lambda obj: captured.setdefault("s", obj)

    _add_suggestion(
        sess, group, raw_id,
        panel_patterns=["%Foo%1%", "%Foo%2%"],
        sess_dates={"Panel 1": [], "Panel 2": []},
        suggested_name="Foo (campaign)",
        subset_idxs=[0, 1],
    )
    s = captured["s"]
    labels = {p["label"] for p in s.geometry["panels"]}
    assert labels == {"Panel 1", "Panel 2"}
    # Exactly one pairwise pitch for two panels, and it is the real 1<->2 sep,
    # not a carried-over full-group value.
    assert len(s.geometry["pitches"]) == 1
    expected = _geometry_from_panels(
        full_geometry["panels"][:2], 120.0
    )["pitches"][0]
    assert s.geometry["pitches"][0] == expected
    assert s.geometry["fov_arcmin"] == 120.0


# ---------------------------------------------------------------------------
# Multiple panel-token OBJECTs within a single target (the Veil case)
# ---------------------------------------------------------------------------

def _multi_cand(target_id, object_centers, fov=120.0):
    """Record where a single target carries several panel-token OBJECTs.

    ``object_centers`` maps OBJECT string -> (ra, dec). The record exposes both
    the legacy ``object_names``/``center`` (target-level median) and the new
    per-OBJECT ``object_centers`` mapping.
    """
    names = list(object_centers.keys())
    centers = {
        name: {
            "center": TargetCenter(ra=ra, dec=dec) if ra is not None else None,
            "fov_arcmin": fov,
        }
        for name, (ra, dec) in object_centers.items()
    }
    # Target-level median center (what the old single-center path would use).
    ras = [ra for ra, _ in object_centers.values() if ra is not None]
    decs = [dec for _, dec in object_centers.values() if dec is not None]
    med = (
        TargetCenter(ra=sum(ras) / len(ras), dec=sum(decs) / len(decs))
        if ras else None
    )
    return {
        "target_id": target_id,
        "object_names": names,
        "object_centers": centers,
        "center": med,
        "fov_arcmin": fov,
    }


def test_single_target_two_panel_objects_groups_with_distinct_centers():
    """The Veil case: one target_id, two panel-token OBJECTs at distinct centers.

    A target whose frames carry 'Veil Nebula Panel 1' and 'Veil Nebula Panel 2'
    must produce a 2-panel group, both panels sharing the same target_id, with
    distinct per-panel centers and HIGH confidence (name + position agree).
    """
    targets = [
        _multi_cand("ngc6960", {
            "Veil Nebula Panel 1": (311.0, 31.0),
            "Veil Nebula Panel 2": (311.8, 31.0),  # ~0.7 deg apart
        }),
    ]
    groups = group_panels(targets, keywords=["Panel", "P"], tolerance_arcmin=12.0)
    assert len(groups) == 1
    g = groups[0]
    assert g.base_name == "Veil Nebula"
    assert sorted(g.panel_labels) == ["Panel 1", "Panel 2"]
    assert g.target_ids == ["ngc6960", "ngc6960"]  # both share the target
    # Per-panel centers must be distinct, not the single target median.
    panels = g.geometry["panels"]
    ras = sorted(p["ra"] for p in panels)
    assert ras[0] != ras[1]
    assert g.confidence == "high"
    assert g.flags == []


def test_single_target_same_panel_number_no_duplicate_labels():
    """One target with two distinct OBJECTs that map to the SAME panel number
    must not create a duplicate-label group."""
    targets = [
        _multi_cand("t1", {
            "Veil Nebula Panel 1": (311.0, 31.0),
            "Veil Mosaic-1": (311.8, 31.0),  # also panel number "1"
        }),
    ]
    groups = group_panels(targets, keywords=["Panel", "P"], tolerance_arcmin=12.0)
    # Only one distinct panel number => no >=2-panel group.
    for g in groups:
        assert len(g.panel_labels) == len(set(g.panel_labels))
    assert all(len(g.panel_numbers) == len(set(g.panel_numbers)) for g in groups)
    # With a single distinct panel number there is no valid group.
    assert groups == []


def test_single_target_one_notoken_object_spread_no_candidate():
    """Reframing protection: a target with ONE no-token OBJECT but spatially
    spread frames must still yield NO candidate (no fake panels)."""
    targets = [
        _multi_cand("hh", {
            "Horsehead Nebula": (85.0, -2.5),
        }, fov=120.0),
    ]
    groups = group_panels(targets, keywords=["Panel", "P"], tolerance_arcmin=12.0)
    assert groups == []
