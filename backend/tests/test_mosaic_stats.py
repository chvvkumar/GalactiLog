"""Focused tests for app/services/mosaic_stats.py aggregation (PERF-6, Phase 5 Task 3).

These verify that the pattern-panel aggregation in list_mosaic_summaries
(grouped SQL on the exact Image.panel_id join, Phase 5 Task 3) yields the
same per-mosaic stats the previous ILIKE/regex-based aggregation did, for a
representative dataset covering unscoped, scoped, excluded, NULL-date, and
multi-session panels.

The DB is stubbed: a fake AsyncSession dispatches each .execute() call to canned
result rows by matching distinctive tokens in the compiled SQL. This keeps the
test independent of a live PostgreSQL while exercising the real Python
aggregation path in the service. The grouped-query rows are now keyed
directly by panel_id (Image.panel_id) instead of (resolved_target_id,
object_name), matching the exact-join rewrite.
"""

import datetime
import uuid
from unittest.mock import MagicMock

import pytest

from app.services.mosaic_stats import list_mosaic_summaries


def _row(**kwargs):
    """A result row that supports both attribute and index access like SQLAlchemy Row."""
    m = MagicMock()
    for k, v in kwargs.items():
        setattr(m, k, v)
    # index access in the order the kwargs were given
    values = list(kwargs.values())
    m.__getitem__ = lambda self, i, _v=values: _v[i]
    return m


def _make_panel(panel_id, target_id, object_pattern, *, label="P", sort_order=0):
    p = MagicMock()
    p.id = panel_id
    p.target_id = target_id
    p.object_pattern = object_pattern
    p.panel_label = label
    p.sort_order = sort_order
    p.grid_row = None
    p.grid_col = None
    p.rotation = 0
    p.flip_h = False
    target = MagicMock()
    target.primary_name = f"target-{target_id}"
    target.ra = 10.0
    target.dec = 20.0
    p.target = target
    return p


def _make_mosaic(mosaic_id, name, panels):
    m = MagicMock()
    m.id = mosaic_id
    m.name = name
    m.notes = None
    m.needs_review = False
    m.panels = panels
    return m


class _Result:
    """Mimics the slice of SQLAlchemy Result used by the service."""

    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalars(self):
        outer = self

        class _Scalars:
            def all(self_inner):
                return outer._rows

        return _Scalars()


class _FakeSession:
    """Dispatch execute() to canned results by inspecting the compiled SQL."""

    def __init__(self, *, mosaics, has_membership_ids, membership_rows,
                 grouped_rows, simple_bulk_rows, custom_rows):
        self._mosaics = mosaics
        self._has_membership_ids = has_membership_ids
        self._membership_rows = membership_rows
        self._grouped_rows = grouped_rows
        self._simple_bulk_rows = simple_bulk_rows
        self._custom_rows = custom_rows

    async def execute(self, statement, *args, **kwargs):
        sql = str(statement).lower()
        if "from mosaics" in sql and "mosaic_panels" not in sql:
            return _Result(self._mosaics)
        # bulk simple-panel aggregation (has min + max session_date)
        if "min(" in sql:
            return _Result(self._simple_bulk_rows)
        # distinct panel ids that have membership
        if "distinct" in sql and "mosaic_panel_sessions" in sql:
            return _Result([_idrow(pid) for pid in self._has_membership_ids])
        # included membership rows (panel_id, session_date) where status included
        if "mosaic_panel_sessions" in sql and "status" in sql:
            return _Result(self._membership_rows)
        # grouped pattern-panel aggregation: exact Image.panel_id join, grouped
        # by (panel_id, session_date) -- distinguished by the coalesce() used
        # only in this query (all-NULL-exposure-safe SUM).
        if "coalesce" in sql:
            return _Result(self._grouped_rows)
        # custom column values
        if "custom_column" in sql:
            return _Result(self._custom_rows)
        return _Result([])

    async def get(self, model, pk):
        """Only used by load_mosaic_keywords for the UserSettings row."""
        settings = MagicMock()
        settings.general = {"mosaic_keywords": ["Panel"]}
        return settings


def _idrow(value):
    r = MagicMock()
    r.__getitem__ = lambda self, i, _v=value: _v
    return r


def _membership_row(panel_id, session_date):
    r = MagicMock()
    r.panel_id = panel_id
    r.session_date = session_date
    return r


@pytest.mark.asyncio
async def test_pattern_panel_aggregation_matches_reference():
    """The grouped-SQL aggregation must reproduce the old per-frame totals."""
    t1 = uuid.uuid4()
    t2 = uuid.uuid4()

    # Panel A: unscoped pattern panel (no membership) on target t1
    pa = _make_panel(uuid.uuid4(), t1, "%Veil%Panel%1%", label="Panel 1", sort_order=0)
    # Panel B: scoped pattern panel (membership, some included) on target t2
    pb = _make_panel(uuid.uuid4(), t2, "%Veil%Panel%2%", label="Panel 2", sort_order=1)

    mosaic = _make_mosaic(uuid.uuid4(), "Veil", [pa, pb])

    d1 = datetime.date(2026, 1, 1)
    d2 = datetime.date(2026, 1, 2)
    d3 = datetime.date(2026, 1, 3)

    # Grouped rows: (panel_id, session_date, integration, frames) -- pre-
    # aggregated per (panel_id, session_date) via the exact Image.panel_id
    # join, as the service now queries.
    grouped_rows = [
        # Panel A (unscoped): two sessions + one NULL-date group
        _row(panel_id=pa.id, session_date=d1, integration=300.0, frames=3),
        _row(panel_id=pa.id, session_date=d2, integration=200.0, frames=2),
        _row(panel_id=pa.id, session_date=None, integration=100.0, frames=1),
        # Panel B: d1 included, d3 NOT included (excluded)
        _row(panel_id=pb.id, session_date=d1, integration=600.0, frames=6),
        _row(panel_id=pb.id, session_date=d3, integration=900.0, frames=9),
    ]

    # Panel B has membership records; only d1 is "included".
    has_membership_ids = [pb.id]
    membership_rows = [_membership_row(pb.id, d1)]

    session = _FakeSession(
        mosaics=[mosaic],
        has_membership_ids=has_membership_ids,
        membership_rows=membership_rows,
        grouped_rows=grouped_rows,
        simple_bulk_rows=[],
        custom_rows=[],
    )

    summaries = await list_mosaic_summaries(session)

    # --- Reference computation mirroring the OLD per-frame logic ---
    # Panel A (unscoped): counts ALL matching frames regardless of session.
    a_integration = 300.0 + 200.0 + 100.0
    a_frames = 3 + 2 + 1
    a_dates = sorted(["2026-01-01", "2026-01-02"])  # NULL date excluded from min/max
    # Panel B (scoped to d1 only): only the d1 group counts.
    b_integration = 600.0
    b_frames = 6
    b_dates = ["2026-01-01"]

    expected_total_int = a_integration + b_integration
    expected_total_frames = a_frames + b_frames
    expected_first = min(a_dates[0], b_dates[0])
    expected_last = max(a_dates[-1], b_dates[-1])

    # completion: per-panel integration normalized to the max panel
    panel_ints = [a_integration, b_integration]
    max_panel = max(panel_ints)
    completion = sum(min(pi / max_panel, 1.0) for pi in panel_ints) / len(panel_ints) * 100

    assert len(summaries) == 1
    s = summaries[0]
    assert s.total_integration_seconds == expected_total_int
    assert s.total_frames == expected_total_frames
    assert s.first_session == expected_first
    assert s.last_session == expected_last
    assert s.completion_pct == round(completion, 1)
    assert s.panel_count == 2


@pytest.mark.asyncio
async def test_scoped_panel_with_no_included_dates_contributes_zero():
    """A panel with membership but zero included sessions must add nothing."""
    t1 = uuid.uuid4()
    pa = _make_panel(uuid.uuid4(), t1, "%M31%Panel%1%", label="Panel 1", sort_order=0)
    mosaic = _make_mosaic(uuid.uuid4(), "M31", [pa])

    d1 = datetime.date(2026, 2, 1)
    grouped_rows = [
        _row(panel_id=pa.id, session_date=d1, integration=500.0, frames=5),
    ]

    # Panel has membership but NO included rows -> all sessions excluded.
    session = _FakeSession(
        mosaics=[mosaic],
        has_membership_ids=[pa.id],
        membership_rows=[],  # no included dates
        grouped_rows=grouped_rows,
        simple_bulk_rows=[],
        custom_rows=[],
    )

    summaries = await list_mosaic_summaries(session)
    s = summaries[0]
    assert s.total_integration_seconds == 0
    assert s.total_frames == 0
    assert s.first_session is None
    assert s.last_session is None
    assert s.completion_pct == 0


@pytest.mark.asyncio
async def test_all_null_exposure_group_integration_is_zero():
    """A grouped row where every frame has NULL exposure_time must yield 0.0
    integration (not NULL) while still counting the frames.

    The optimized query uses func.sum(coalesce(exposure_time, 0.0)), so an
    all-NULL group returns 0.0 from SQL rather than NULL. This fixture models
    that coalesced DB output and locks the resulting summary.
    """
    t1 = uuid.uuid4()
    pa = _make_panel(uuid.uuid4(), t1, "%Rosette%Panel%1%", label="Panel 1", sort_order=0)
    mosaic = _make_mosaic(uuid.uuid4(), "Rosette", [pa])

    d1 = datetime.date(2026, 3, 1)
    d2 = datetime.date(2026, 3, 2)
    # d1 group: all frames NULL exposure -> coalesced SUM is 0.0, but 4 frames.
    # d2 group: normal exposure to confirm mixed mosaics still sum correctly.
    grouped_rows = [
        _row(panel_id=pa.id, session_date=d1, integration=0.0, frames=4),
        _row(panel_id=pa.id, session_date=d2, integration=120.0, frames=1),
    ]

    session = _FakeSession(
        mosaics=[mosaic],
        has_membership_ids=[],          # unscoped: count all matching frames
        membership_rows=[],
        grouped_rows=grouped_rows,
        simple_bulk_rows=[],
        custom_rows=[],
    )

    summaries = await list_mosaic_summaries(session)
    s = summaries[0]
    # integration is exactly the non-null group's total; the all-NULL group adds 0.0.
    assert s.total_integration_seconds == 120.0
    # frames still counts the NULL-exposure frames.
    assert s.total_frames == 5
    assert s.first_session == "2026-03-01"
    assert s.last_session == "2026-03-02"
