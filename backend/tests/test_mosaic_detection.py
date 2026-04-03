import pytest
from app.services.mosaic_detection import cluster_sessions_by_gap


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
