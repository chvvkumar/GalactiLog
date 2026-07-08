import pytest
from types import SimpleNamespace
from app.services.mosaic_detection import cluster_sessions_by_gap
from unittest.mock import MagicMock
from uuid import uuid4

from app.models.mosaic_suggestion import MosaicSuggestion


# _gather_target_records now selects the needed header keys as scalar columns
# instead of the whole raw_headers JSONB, so its rows are (resolved_target_id,
# OBJECT, RA, DEC, OBJCTRA, OBJCTDEC, FOCALLEN, XPIXSZ, NAXIS1, NAXIS2) tuples
# exposed as labeled attributes. This helper turns the legacy
# (target_id, header_dict) test fixtures into that row shape.
_GATHER_HEADER_KEYS = (
    "OBJECT", "RA", "DEC", "OBJCTRA", "OBJCTDEC",
    "FOCALLEN", "XPIXSZ", "NAXIS1", "NAXIS2",
)


def _hdr_rows(pairs):
    return [
        SimpleNamespace(
            resolved_target_id=tid,
            **{k: hdr.get(k) for k in _GATHER_HEADER_KEYS},
        )
        for tid, hdr in pairs
    ]


def test_single_cluster_when_gap_small():
    """All dates within gap → one cluster."""
    dates = ["2024-10-27", "2024-12-22", "2025-01-15"]
    result = cluster_sessions_by_gap(dates, gap_days=180)
    assert result == [["2024-10-27", "2024-12-22", "2025-01-15"]]


def test_two_clusters_when_gap_exceeded():
    """Dates split by a gap larger than threshold."""
    dates = ["2023-06-26", "2023-08-17", "2025-10-06", "2025-10-07"]
    result = cluster_sessions_by_gap(dates, gap_days=180)
    assert result == [
        ["2023-06-26", "2023-08-17"],
        ["2025-10-06", "2025-10-07"],
    ]


def test_single_date_is_one_cluster():
    dates = ["2024-01-01"]
    result = cluster_sessions_by_gap(dates, gap_days=90)
    assert result == [["2024-01-01"]]


def test_empty_dates():
    result = cluster_sessions_by_gap([], gap_days=90)
    assert result == []


def test_exact_gap_boundary_stays_together():
    """Gap exactly equal to threshold should NOT split."""
    dates = ["2024-01-01", "2024-07-01"]  # 182 days apart
    result = cluster_sessions_by_gap(dates, gap_days=182)
    assert result == [["2024-01-01", "2024-07-01"]]


def test_exact_gap_boundary_splits():
    """Gap one day over threshold should split."""
    dates = ["2024-01-01", "2024-07-01"]  # 182 days apart
    result = cluster_sessions_by_gap(dates, gap_days=181)
    assert result == [["2024-01-01"], ["2024-07-01"]]


def test_detect_creates_separate_suggestions_per_campaign():
    """Two temporally distinct campaigns for the same base name → two suggestions.

    Drives the name+position pipeline end-to-end through the DB orchestrator
    with a mocked session. Each target supplies LIGHT-frame headers carrying a
    distinct sky center so the position path confirms the name grouping.
    """
    from datetime import date

    t1 = uuid4()
    t2 = uuid4()

    mock_session = MagicMock()

    mock_settings = MagicMock()
    mock_settings.general = {"mosaic_keywords": ["Panel"]}
    mock_session.get.return_value = mock_settings

    # _gather_target_records: in-mosaic panel target_ids (none)
    in_mosaic_result = MagicMock()
    in_mosaic_result.all.return_value = []

    # _gather_target_records: unmerged target ids
    target_ids_result = MagicMock()
    target_ids_result.all.return_value = [(t1,), (t2,)]

    # _gather_target_records: (resolved_target_id, raw_headers) rows.
    # Two distinct centers ~1.5 deg apart so positions are distinct.
    headers_result = MagicMock()
    headers_result.all.return_value = _hdr_rows([
        (t1, {"OBJECT": "Heart Nebula Panel 1", "RA": 38.0, "DEC": 61.0,
              "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
        (t2, {"OBJECT": "Heart Nebula Panel 2", "RA": 39.5, "DEC": 61.0,
              "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
    ])

    rejected_result = MagicMock()
    rejected_result.all.return_value = []  # no dismissed suggestions

    delete_result = MagicMock()

    existing_result = MagicMock()
    existing_result.all.return_value = []

    p1_dates = MagicMock()
    p1_dates.all.return_value = [
        (date(2023, 6, 26), "Heart Nebula Panel 1"),
        (date(2023, 8, 17), "Heart Nebula Panel 1"),
        (date(2025, 10, 6), "Heart Nebula Panel 1"),
    ]

    p2_dates = MagicMock()
    p2_dates.all.return_value = [
        (date(2023, 6, 27), "Heart Nebula Panel 2"),
        (date(2023, 8, 18), "Heart Nebula Panel 2"),
        (date(2025, 10, 6), "Heart Nebula Panel 2"),
    ]

    mock_session.execute = MagicMock(side_effect=[
        in_mosaic_result,
        target_ids_result,
        headers_result,
        rejected_result,
        delete_result,
        existing_result,
        p1_dates,
        p2_dates,
    ])

    from app.services.mosaic_detection import detect_mosaic_panels
    count = detect_mosaic_panels(mock_session, gap_days=180)

    added = [call.args[0] for call in mock_session.add.call_args_list
             if isinstance(call.args[0], MosaicSuggestion)]
    assert len(added) == 2
    names = sorted(s.suggested_name for s in added)
    assert names == [
        "Heart Nebula (Jun 2023 - Aug 2023)",
        "Heart Nebula (Oct 2025)",
    ]
    # New hybrid fields are persisted on each suggestion.
    for s in added:
        assert s.confidence in ("high", "low")
        assert s.discovery_source in ("name", "position", "both")
        assert isinstance(s.flags, list)
        assert s.geometry is not None and "panels" in s.geometry


def test_detect_single_target_two_panel_objects():
    """Veil case end-to-end: ONE target whose frames carry two distinct
    panel-token OBJECTs at two distinct sky centers yields a 2-panel suggestion.
    """
    from datetime import date

    tid = uuid4()

    mock_session = MagicMock()

    mock_settings = MagicMock()
    mock_settings.general = {"mosaic_keywords": ["Panel"]}
    mock_session.get.return_value = mock_settings

    in_mosaic_result = MagicMock()
    in_mosaic_result.all.return_value = []

    target_ids_result = MagicMock()
    target_ids_result.all.return_value = [(tid,)]

    # Same target id on every row; two distinct OBJECTs ~0.8 deg apart so each
    # OBJECT's robust center is distinct (NOT the target overall median).
    headers_result = MagicMock()
    headers_result.all.return_value = _hdr_rows([
        (tid, {"OBJECT": "Veil Nebula Panel 1", "RA": 311.0, "DEC": 31.0,
               "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
        (tid, {"OBJECT": "Veil Nebula Panel 1", "RA": 311.01, "DEC": 31.0,
               "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
        (tid, {"OBJECT": "Veil Nebula Panel 2", "RA": 311.8, "DEC": 31.0,
               "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
        (tid, {"OBJECT": "Veil Nebula Panel 2", "RA": 311.79, "DEC": 31.0,
               "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
    ])

    rejected_result = MagicMock()
    rejected_result.all.return_value = []

    delete_result = MagicMock()

    existing_result = MagicMock()
    existing_result.all.return_value = []

    p1_dates = MagicMock()
    p1_dates.all.return_value = [(date(2024, 8, 1), "Veil Nebula Panel 1")]
    p2_dates = MagicMock()
    p2_dates.all.return_value = [(date(2024, 8, 2), "Veil Nebula Panel 2")]

    mock_session.execute = MagicMock(side_effect=[
        in_mosaic_result,
        target_ids_result,
        headers_result,
        rejected_result,
        delete_result,
        existing_result,
        p1_dates,
        p2_dates,
    ])

    from app.services.mosaic_detection import detect_mosaic_panels
    count = detect_mosaic_panels(mock_session, gap_days=0)

    added = [call.args[0] for call in mock_session.add.call_args_list
             if isinstance(call.args[0], MosaicSuggestion)]
    assert len(added) == 1
    s = added[0]
    assert s.base_name == "Veil Nebula"
    assert sorted(s.panel_labels) == ["Panel 1", "Panel 2"]
    # Both panels point at the SAME target id.
    assert list(s.target_ids) == [tid, tid]
    # Per-panel centers are distinct in the persisted geometry.
    ras = sorted(p["ra"] for p in s.geometry["panels"])
    assert ras[0] != ras[1]
    assert s.confidence == "high"


def _compile_sql(stmt):
    try:
        return str(stmt.compile(compile_kwargs={"literal_binds": True}))
    except Exception:
        return str(stmt)


def test_detect_clears_all_pending_including_legacy_null_base():
    """Re-detection deletes ALL pending suggestions (status='pending'),
    including legacy rows with NULL base_name, before regenerating."""
    from datetime import date

    tid = uuid4()
    mock_session = MagicMock()

    mock_settings = MagicMock()
    mock_settings.general = {"mosaic_keywords": ["Panel"]}
    mock_session.get.return_value = mock_settings

    in_mosaic_result = MagicMock()
    in_mosaic_result.all.return_value = []
    target_ids_result = MagicMock()
    target_ids_result.all.return_value = [(tid,)]
    headers_result = MagicMock()
    headers_result.all.return_value = _hdr_rows([
        (tid, {"OBJECT": "Heart Nebula Panel 1", "RA": 38.0, "DEC": 61.0,
               "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
        (tid, {"OBJECT": "Heart Nebula Panel 2", "RA": 39.5, "DEC": 61.0,
               "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
    ])
    existing_result = MagicMock()
    existing_result.all.return_value = []
    rejected_result = MagicMock()
    rejected_result.all.return_value = []
    delete_result = MagicMock()
    p1_dates = MagicMock()
    p1_dates.all.return_value = [(date(2024, 1, 1), "Heart Nebula Panel 1")]
    p2_dates = MagicMock()
    p2_dates.all.return_value = [(date(2024, 1, 2), "Heart Nebula Panel 2")]

    executed = []

    def _exec(stmt, *a, **k):
        executed.append(stmt)
        # Sequence: in_mosaic, target_ids, headers, SELECT rejected sigs,
        # DELETE(all pending), existing_mosaics, p1_dates, p2_dates
        idx = len(executed)
        if idx == 1:
            return in_mosaic_result
        if idx == 2:
            return target_ids_result
        if idx == 3:
            return headers_result
        if idx == 4:
            return rejected_result  # SELECT rejected dedup_signatures
        if idx == 5:
            return delete_result    # the unconditional pending delete
        if idx == 6:
            return existing_result
        if idx == 7:
            return p1_dates
        return p2_dates

    mock_session.execute = MagicMock(side_effect=_exec)

    from app.services.mosaic_detection import detect_mosaic_panels
    detect_mosaic_panels(mock_session, gap_days=0)

    # There must be exactly one DELETE on mosaic_suggestions, filtered only by
    # status='pending' (no base_name filter, so legacy NULL-base rows go too).
    deletes = [
        _compile_sql(s) for s in executed
        if "DELETE FROM mosaic_suggestions" in _compile_sql(s).upper().replace(
            "DELETE FROM MOSAIC_SUGGESTIONS", "DELETE FROM mosaic_suggestions"
        )
    ]
    # Robust: find any compiled stmt that is a DELETE on the suggestions table.
    delete_sql = [
        _compile_sql(s) for s in executed
        if _compile_sql(s).lower().startswith("delete from mosaic_suggestions")
    ]
    assert len(delete_sql) == 1
    sql = delete_sql[0].lower()
    assert "status" in sql and "pending" in sql
    assert "base_name" not in sql


def test_detect_dedupes_duplicate_suggested_names():
    """Two gap-split campaigns of one base that both fall within the same month
    resolve to the same '<base> (Mon YYYY)' name; the run must disambiguate them
    so accepting both cannot violate the unique mosaic name constraint.

    gap_days=5: each panel's two sessions (Jan 1-2 and Jan 20-21, 2024) split
    into two campaigns, both rendering suffix '(Jan 2024)'.
    """
    from datetime import date

    t1 = uuid4()
    t2 = uuid4()
    mock_session = MagicMock()

    mock_settings = MagicMock()
    mock_settings.general = {"mosaic_keywords": ["Panel"]}
    mock_session.get.return_value = mock_settings

    in_mosaic_result = MagicMock()
    in_mosaic_result.all.return_value = []
    target_ids_result = MagicMock()
    target_ids_result.all.return_value = [(t1,), (t2,)]
    headers_result = MagicMock()
    headers_result.all.return_value = _hdr_rows([
        (t1, {"OBJECT": "Foo Panel 1", "RA": 10.0, "DEC": 20.0,
              "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
        (t2, {"OBJECT": "Foo Panel 2", "RA": 11.5, "DEC": 20.0,
              "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
    ])
    rejected_result = MagicMock()
    rejected_result.all.return_value = []
    delete_result = MagicMock()
    existing_result = MagicMock()
    existing_result.all.return_value = []

    # Each panel has two date clusters >5 days apart, both inside Jan 2024.
    d1 = MagicMock()
    d1.all.return_value = [
        (date(2024, 1, 1), "Foo Panel 1"), (date(2024, 1, 20), "Foo Panel 1"),
    ]
    d2 = MagicMock()
    d2.all.return_value = [
        (date(2024, 1, 2), "Foo Panel 2"), (date(2024, 1, 21), "Foo Panel 2"),
    ]

    mock_session.execute = MagicMock(side_effect=[
        in_mosaic_result, target_ids_result, headers_result,
        rejected_result, delete_result, existing_result, d1, d2,
    ])

    from app.services.mosaic_detection import detect_mosaic_panels
    detect_mosaic_panels(mock_session, gap_days=5)

    added = [call.args[0] for call in mock_session.add.call_args_list
             if isinstance(call.args[0], MosaicSuggestion)]
    names = [s.suggested_name for s in added]
    # Two campaigns emitted, with distinct (disambiguated) names.
    assert len(added) == 2
    assert len(names) == len(set(names))
    assert any(n == "Foo (Jan 2024)" for n in names)


def test_unique_name_helper_disambiguates():
    """The name-uniqueness helper appends a deterministic suffix on collision."""
    from app.services.mosaic_detection import _unique_name

    used: set[str] = set()
    a = _unique_name("California Nebula (Jan 2024)", used)
    b = _unique_name("California Nebula (Jan 2024)", used)
    c = _unique_name("California Nebula (Jan 2024)", used)
    assert a == "California Nebula (Jan 2024)"
    assert b == "California Nebula (Jan 2024) (#2)"
    assert c == "California Nebula (Jan 2024) (#3)"
    assert len({a, b, c}) == 3


def test_detect_skips_dismissed_signature_but_creates_others():
    """A rejected suggestion's signature suppresses its re-creation; unrelated
    groups are still created."""
    from datetime import date
    from app.services.mosaic_detection import (
        compute_dedup_signature, detect_mosaic_panels,
    )

    h1, h2 = uuid4(), uuid4()   # Heart panels (will be dismissed)
    w1, w2 = uuid4(), uuid4()   # Wizard panels (should still appear)

    # Heart's signature as it will be computed at persist time (raw uuids).
    heart_sig = compute_dedup_signature(
        "Heart Nebula", [h1, h2], ["Panel 1", "Panel 2"]
    )

    mock_session = MagicMock()
    mock_settings = MagicMock()
    mock_settings.general = {"mosaic_keywords": ["Panel"]}
    mock_session.get.return_value = mock_settings

    in_mosaic_result = MagicMock()
    in_mosaic_result.all.return_value = []
    target_ids_result = MagicMock()
    target_ids_result.all.return_value = [(h1,), (h2,), (w1,), (w2,)]
    headers_result = MagicMock()
    headers_result.all.return_value = _hdr_rows([
        (h1, {"OBJECT": "Heart Nebula Panel 1", "RA": 38.0, "DEC": 61.0,
              "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
        (h2, {"OBJECT": "Heart Nebula Panel 2", "RA": 39.5, "DEC": 61.0,
              "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
        (w1, {"OBJECT": "Wizard Nebula Panel 1", "RA": 350.0, "DEC": 60.0,
              "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
        (w2, {"OBJECT": "Wizard Nebula Panel 2", "RA": 351.5, "DEC": 60.0,
              "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
    ])
    rejected_result = MagicMock()
    # Dismissal covered exactly the dates the regenerated Heart campaign will
    # have (2024-01-01, 2024-01-02), so it stays suppressed (AUD-033: a
    # dismissal only suppresses a re-run whose dates it already covers).
    rejected_result.all.return_value = [
        (heart_sig, {"Panel 1": ["2024-01-01"], "Panel 2": ["2024-01-02"]}),
    ]
    delete_result = MagicMock()
    existing_result = MagicMock()
    existing_result.all.return_value = []
    # Date queries: Heart p1, Heart p2, Wizard p1, Wizard p2 (gap_days=0).
    dq_objects = [
        "Heart Nebula Panel 1", "Heart Nebula Panel 2",
        "Wizard Nebula Panel 1", "Wizard Nebula Panel 2",
    ]
    dq = [MagicMock() for _ in range(4)]
    for i, m in enumerate(dq):
        m.all.return_value = [(date(2024, 1, 1 + i), dq_objects[i])]

    mock_session.execute = MagicMock(side_effect=[
        in_mosaic_result, target_ids_result, headers_result,
        rejected_result, delete_result, existing_result, *dq,
    ])

    detect_mosaic_panels(mock_session, gap_days=0)

    added = [call.args[0] for call in mock_session.add.call_args_list
             if isinstance(call.args[0], MosaicSuggestion)]
    bases = sorted(s.base_name for s in added)
    assert bases == ["Wizard Nebula"]  # Heart suppressed, Wizard created
    assert added[0].dedup_signature == compute_dedup_signature(
        "Wizard Nebula", [w1, w2], ["Panel 1", "Panel 2"]
    )


def test_detect_resurfaces_dismissed_signature_with_genuinely_new_dates():
    """AUD-033 regression: a dismissed suggestion's dedup_signature is
    date-independent (same base/target/panel-label set), so a later,
    date-separated re-shoot of the identical panel set would previously be
    silently suppressed forever. The fix scopes suppression to the dates the
    dismissal actually covered: a regenerated campaign whose dates are NOT a
    subset of the dismissed dates (i.e. it has genuinely new dates) must
    resurface."""
    from datetime import date
    from app.services.mosaic_detection import (
        compute_dedup_signature, detect_mosaic_panels,
    )

    h1, h2 = uuid4(), uuid4()

    heart_sig = compute_dedup_signature(
        "Heart Nebula", [h1, h2], ["Panel 1", "Panel 2"]
    )

    mock_session = MagicMock()
    mock_settings = MagicMock()
    mock_settings.general = {"mosaic_keywords": ["Panel"]}
    mock_session.get.return_value = mock_settings

    in_mosaic_result = MagicMock()
    in_mosaic_result.all.return_value = []
    target_ids_result = MagicMock()
    target_ids_result.all.return_value = [(h1,), (h2,)]
    headers_result = MagicMock()
    headers_result.all.return_value = _hdr_rows([
        (h1, {"OBJECT": "Heart Nebula Panel 1", "RA": 38.0, "DEC": 61.0,
              "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
        (h2, {"OBJECT": "Heart Nebula Panel 2", "RA": 39.5, "DEC": 61.0,
              "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
    ])
    # Dismissed back in 2024, covering only the 2024 dates.
    rejected_result = MagicMock()
    rejected_result.all.return_value = [
        (heart_sig, {"Panel 1": ["2024-01-01"], "Panel 2": ["2024-01-02"]}),
    ]
    delete_result = MagicMock()
    existing_result = MagicMock()
    existing_result.all.return_value = []

    # Re-shot in 2026: same signature (same base/targets/panel labels), but
    # brand new dates the dismissal never covered.
    p1_dates = MagicMock()
    p1_dates.all.return_value = [(date(2026, 6, 1), "Heart Nebula Panel 1")]
    p2_dates = MagicMock()
    p2_dates.all.return_value = [(date(2026, 6, 2), "Heart Nebula Panel 2")]

    mock_session.execute = MagicMock(side_effect=[
        in_mosaic_result, target_ids_result, headers_result,
        rejected_result, delete_result, existing_result,
        p1_dates, p2_dates,
    ])

    detect_mosaic_panels(mock_session, gap_days=0)

    added = [call.args[0] for call in mock_session.add.call_args_list
             if isinstance(call.args[0], MosaicSuggestion)]
    # Must resurface: the 2026 dates are not covered by the 2024 dismissal.
    assert len(added) == 1
    assert added[0].base_name == "Heart Nebula"
    assert added[0].dedup_signature == heart_sig


def test_detect_resurfaces_when_panel_set_changed():
    """A dismissed signature whose panel set has materially changed (an added
    panel) no longer matches, so the suggestion resurfaces."""
    from datetime import date
    from app.services.mosaic_detection import (
        compute_dedup_signature, detect_mosaic_panels,
    )

    h1, h2, h3 = uuid4(), uuid4(), uuid4()

    # Previously dismissed when it was only a 2-panel mosaic.
    old_sig = compute_dedup_signature(
        "Heart Nebula", [h1, h2], ["Panel 1", "Panel 2"]
    )

    mock_session = MagicMock()
    mock_settings = MagicMock()
    mock_settings.general = {"mosaic_keywords": ["Panel"]}
    mock_session.get.return_value = mock_settings

    in_mosaic_result = MagicMock()
    in_mosaic_result.all.return_value = []
    target_ids_result = MagicMock()
    target_ids_result.all.return_value = [(h1,), (h2,), (h3,)]
    headers_result = MagicMock()
    headers_result.all.return_value = _hdr_rows([
        (h1, {"OBJECT": "Heart Nebula Panel 1", "RA": 38.0, "DEC": 61.0,
              "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
        (h2, {"OBJECT": "Heart Nebula Panel 2", "RA": 39.5, "DEC": 61.0,
              "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
        (h3, {"OBJECT": "Heart Nebula Panel 3", "RA": 41.0, "DEC": 61.0,
              "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
    ])
    rejected_result = MagicMock()
    rejected_result.all.return_value = [
        (old_sig, {"Panel 1": ["2024-01-01"], "Panel 2": ["2024-01-02"]}),
    ]
    delete_result = MagicMock()
    existing_result = MagicMock()
    existing_result.all.return_value = []
    dq_objects = ["Heart Nebula Panel 1", "Heart Nebula Panel 2", "Heart Nebula Panel 3"]
    dq = [MagicMock() for _ in range(3)]
    for i, m in enumerate(dq):
        m.all.return_value = [(date(2024, 1, 1 + i), dq_objects[i])]

    mock_session.execute = MagicMock(side_effect=[
        in_mosaic_result, target_ids_result, headers_result,
        rejected_result, delete_result, existing_result, *dq,
    ])

    detect_mosaic_panels(mock_session, gap_days=0)

    added = [call.args[0] for call in mock_session.add.call_args_list
             if isinstance(call.args[0], MosaicSuggestion)]
    # The now-3-panel group has a different signature, so it resurfaces.
    assert len(added) == 1
    s = added[0]
    assert s.base_name == "Heart Nebula"
    assert sorted(s.panel_labels) == ["Panel 1", "Panel 2", "Panel 3"]
    assert s.dedup_signature != old_sig


def test_detect_panel_1_vs_panel_12_no_cross_contamination():
    """AUD-008 regression: the ILIKE pre-filter built for panel "1"
    ("%Veil Nebula%Panel%1%") also matches OBJECT "Veil Nebula Panel 12"
    because the trailing "%" imposes no boundary after the digit. Simulate
    that DB-side over-match by including a spurious "Panel 12" row (imaged in
    September) in panel "1"'s date query results, and assert the re-parse
    step in detect_mosaic_panels strips it out so panel 1's session_dates
    only reflect its genuine June frames, with no bleed into panel 12's
    September-only dates."""
    from datetime import date

    p1, p12 = uuid4(), uuid4()

    mock_session = MagicMock()
    mock_settings = MagicMock()
    mock_settings.general = {"mosaic_keywords": ["Panel"]}
    mock_session.get.return_value = mock_settings

    in_mosaic_result = MagicMock()
    in_mosaic_result.all.return_value = []
    target_ids_result = MagicMock()
    target_ids_result.all.return_value = [(p1,), (p12,)]
    headers_result = MagicMock()
    headers_result.all.return_value = _hdr_rows([
        (p1, {"OBJECT": "Veil Nebula Panel 1", "RA": 311.0, "DEC": 31.0,
              "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
        (p12, {"OBJECT": "Veil Nebula Panel 12", "RA": 312.5, "DEC": 31.0,
               "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
    ])
    rejected_result = MagicMock()
    rejected_result.all.return_value = []
    delete_result = MagicMock()
    existing_result = MagicMock()
    existing_result.all.return_value = []

    # Panel "1"'s date query: a genuine June frame plus a spurious September
    # row that only ILIKE (not the real panel token) would have matched --
    # this is exactly the DB-side over-match the fix must filter out.
    p1_dates = MagicMock()
    p1_dates.all.return_value = [
        (date(2024, 6, 15), "Veil Nebula Panel 1"),
        (date(2024, 9, 20), "Veil Nebula Panel 12"),
    ]
    # Panel "12"'s date query: only its genuine September frame.
    p12_dates = MagicMock()
    p12_dates.all.return_value = [
        (date(2024, 9, 20), "Veil Nebula Panel 12"),
    ]

    mock_session.execute = MagicMock(side_effect=[
        in_mosaic_result, target_ids_result, headers_result,
        rejected_result, delete_result, existing_result,
        p1_dates, p12_dates,
    ])

    from app.services.mosaic_detection import detect_mosaic_panels
    count = detect_mosaic_panels(mock_session, gap_days=0)

    added = [call.args[0] for call in mock_session.add.call_args_list
             if isinstance(call.args[0], MosaicSuggestion)]
    assert len(added) == 1
    s = added[0]
    assert sorted(s.panel_labels) == ["Panel 1", "Panel 12"]
    # Panel "1" must NOT absorb panel "12"'s September date.
    assert s.session_dates["Panel 1"] == ["2024-06-15"]
    assert s.session_dates["Panel 12"] == ["2024-09-20"]
