import pytest
from app.services.mosaic_detection import cluster_sessions_by_gap
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.models.mosaic_suggestion import MosaicSuggestion


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


@pytest.mark.asyncio
async def test_detect_creates_separate_suggestions_per_campaign():
    """Two temporally distinct campaigns for the same base name → two suggestions.

    Drives the name+position pipeline end-to-end through the DB orchestrator
    with a mocked session. Each target supplies LIGHT-frame headers carrying a
    distinct sky center so the position path confirms the name grouping.
    """
    from datetime import date

    t1 = uuid4()
    t2 = uuid4()

    mock_session = AsyncMock()

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
    headers_result.all.return_value = [
        (t1, {"OBJECT": "Heart Nebula Panel 1", "RA": 38.0, "DEC": 61.0,
              "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
        (t2, {"OBJECT": "Heart Nebula Panel 2", "RA": 39.5, "DEC": 61.0,
              "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
    ]

    stale_result = MagicMock()
    stale_result.all.return_value = []

    existing_result = MagicMock()
    existing_result.all.return_value = []

    p1_dates = MagicMock()
    p1_dates.scalars.return_value.all.return_value = [
        date(2023, 6, 26), date(2023, 8, 17),
        date(2025, 10, 6),
    ]

    p2_dates = MagicMock()
    p2_dates.scalars.return_value.all.return_value = [
        date(2023, 6, 27), date(2023, 8, 18),
        date(2025, 10, 6),
    ]

    mock_session.execute = AsyncMock(side_effect=[
        in_mosaic_result,
        target_ids_result,
        headers_result,
        stale_result,
        existing_result,
        p1_dates,
        p2_dates,
    ])

    from app.services.mosaic_detection import detect_mosaic_panels
    count = await detect_mosaic_panels(mock_session, gap_days=180)

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


@pytest.mark.asyncio
async def test_detect_single_target_two_panel_objects():
    """Veil case end-to-end: ONE target whose frames carry two distinct
    panel-token OBJECTs at two distinct sky centers yields a 2-panel suggestion.
    """
    from datetime import date

    tid = uuid4()

    mock_session = AsyncMock()

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
    headers_result.all.return_value = [
        (tid, {"OBJECT": "Veil Nebula Panel 1", "RA": 311.0, "DEC": 31.0,
               "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
        (tid, {"OBJECT": "Veil Nebula Panel 1", "RA": 311.01, "DEC": 31.0,
               "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
        (tid, {"OBJECT": "Veil Nebula Panel 2", "RA": 311.8, "DEC": 31.0,
               "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
        (tid, {"OBJECT": "Veil Nebula Panel 2", "RA": 311.79, "DEC": 31.0,
               "FOCALLEN": 448, "XPIXSZ": 3.76, "NAXIS1": 4144}),
    ]

    stale_result = MagicMock()
    stale_result.all.return_value = []

    existing_result = MagicMock()
    existing_result.all.return_value = []

    p1_dates = MagicMock()
    p1_dates.scalars.return_value.all.return_value = [date(2024, 8, 1)]
    p2_dates = MagicMock()
    p2_dates.scalars.return_value.all.return_value = [date(2024, 8, 2)]

    mock_session.execute = AsyncMock(side_effect=[
        in_mosaic_result,
        target_ids_result,
        headers_result,
        stale_result,
        existing_result,
        p1_dates,
        p2_dates,
    ])

    from app.services.mosaic_detection import detect_mosaic_panels
    count = await detect_mosaic_panels(mock_session, gap_days=0)

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
