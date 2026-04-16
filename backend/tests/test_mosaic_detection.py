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


def _make_target(primary_name, aliases=None):
    t = MagicMock()
    t.id = uuid4()
    t.primary_name = primary_name
    t.aliases = aliases or []
    t.merged_into_id = None
    return t


@pytest.mark.asyncio
async def test_detect_creates_separate_suggestions_per_campaign():
    """Two temporally distinct campaigns for the same base name → two suggestions."""
    from datetime import date

    t1 = _make_target("Heart Nebula Panel 1")
    t2 = _make_target("Heart Nebula Panel 2")

    mock_session = AsyncMock()

    mock_settings = MagicMock()
    mock_settings.general = {"mosaic_keywords": ["Panel"]}
    mock_session.get.return_value = mock_settings

    in_mosaic_result = MagicMock()
    in_mosaic_result.all.return_value = []

    targets_result = MagicMock()
    targets_result.scalars.return_value.all.return_value = [t1, t2]

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
        targets_result,
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
