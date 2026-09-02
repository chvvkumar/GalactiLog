"""API tests for the mosaic from-sessions endpoints.

GET /api/mosaics/from-sessions/prefill and POST /api/mosaics/from-sessions.
Written against the endpoint contract with mocked AsyncSession, following the
conventions of test_api_mosaics.py. The execute() mock dispatches results by
compiled statement text (FROM images / FROM mosaic_panels / FROM mosaics /
UPDATE images), so the tests do not depend on the exact number or order of
queries the implementation issues.
"""

import uuid
from datetime import date

import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user, require_admin
from app.models import UserSettings
from app.models.mosaic import Mosaic
from app.models.mosaic_panel import MosaicPanel
from app.models.mosaic_panel_session import MosaicPanelSession

PREFILL_URL = "/api/mosaics/from-sessions/prefill"
CREATE_URL = "/api/mosaics/from-sessions"


def _override_session(mock_session):
    async def _gen():
        yield mock_session
    app.dependency_overrides[get_session] = _gen


class _FrameRow:
    """Row stand-in for the prefill LIGHT-frame grouping query.

    Exposes the plausible attribute names for each column (obj/object_name,
    frame_count/frames/cnt) and supports index access / iteration in the order
    (session_date, panel_label, obj, frame_count) so the test survives either
    attribute access or tuple unpacking in the implementation.
    """

    def __init__(self, session_date, panel_label, obj, frame_count):
        self.session_date = session_date
        self.night = session_date
        self.panel_label = panel_label
        self.obj = obj
        self.object_name = obj
        self.frame_count = frame_count
        self.frames = frame_count
        self.cnt = frame_count
        self._t = (session_date, panel_label, obj, frame_count)

    def __iter__(self):
        return iter(self._t)

    def __getitem__(self, i):
        return self._t[i]


def _empty_result():
    res = MagicMock()
    res.all.return_value = []
    res.scalars.return_value.all.return_value = []
    res.scalar_one_or_none.return_value = None
    res.scalar.return_value = 0
    res.rowcount = 0
    return res


def _make_execute(
    image_rows=None,
    mosaic_obj=None,
    mosaic_rows=None,
    panel_obj=None,
    update_rowcount=0,
):
    """Build an execute() side effect that routes by statement text."""
    statements = []

    async def _execute(stmt, *args, **kwargs):
        statements.append(stmt)
        text = str(stmt)
        res = MagicMock()
        if "UPDATE images" in text:
            res.rowcount = update_rowcount
            res.scalar.return_value = update_rowcount
            return res
        if "mosaic_panel_sessions" in text:
            # Upsert / insert of session rows done via statement.
            res.rowcount = 1
            return res
        if "FROM mosaic_panels" in text:
            found = [panel_obj] if panel_obj is not None else []
            res.scalar_one_or_none.return_value = panel_obj
            res.scalars.return_value.first.return_value = panel_obj
            res.scalars.return_value.all.return_value = found
            res.all.return_value = found
            # Serves the max(sort_order) aggregate too: no existing panels.
            res.scalar_one.return_value = -1
            res.scalar.return_value = -1
            return res
        if "FROM images" in text:
            rows = image_rows or []
            res.all.return_value = rows
            res.scalars.return_value.all.return_value = rows
            res.scalar.return_value = update_rowcount
            return res
        if "FROM mosaics" in text:
            found = [mosaic_obj] if mosaic_obj is not None else []
            res.scalar_one_or_none.return_value = mosaic_obj
            res.scalars.return_value.all.return_value = found
            res.all.return_value = mosaic_rows if mosaic_rows is not None else found
            return res
        return _empty_result()

    return _execute, statements


def _settings():
    settings = MagicMock()
    settings.general = {"mosaic_keywords": ["Panel"]}
    return settings


def _make_get(mosaic_obj=None):
    """session.get side effect: settings row for UserSettings, mosaic for Mosaic."""
    settings = _settings()

    async def _get(model, *args, **kwargs):
        if model is UserSettings:
            return settings
        if model is Mosaic:
            return mosaic_obj
        return None

    return _get


def _panel(label, dates, original="same"):
    """Panel entry in the request body: final label plus per-session rows
    carrying the ORIGINAL parsed label ('same' mirrors the final label)."""
    return {
        "panel_label": label,
        "rows": [
            {
                "session_date": d,
                "original_panel_label": label if original == "same" else original,
            }
            for d in dates
        ],
    }


def _added_instances(mock_session):
    added = [c.args[0] for c in mock_session.add.call_args_list]
    for c in mock_session.add_all.call_args_list:
        added.extend(list(c.args[0]))
    return added


def _base_session(execute, mosaic_obj=None):
    mock_session = AsyncMock()
    mock_session.execute = execute
    mock_session.get = AsyncMock(side_effect=_make_get(mosaic_obj))
    mock_session.add = MagicMock()
    mock_session.add_all = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    return mock_session


# ---------------------------------------------------------------------------
# Prefill
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prefill_returns_rows_base_name_and_mosaics(viewer_user):
    """Prefill is readable by any authenticated user and returns one row per
    distinct (session_date, panel_label), the derived base_name, and the
    existing mosaics list."""
    target_id = uuid.uuid4()
    mosaic_id = uuid.uuid4()

    existing = MagicMock()
    existing.id = mosaic_id
    existing.name = "Veil Mosaic"

    image_rows = [
        _FrameRow(date(2025, 1, 1), "Panel 1", "Veil Nebula Panel 1", 10),
        _FrameRow(date(2025, 1, 2), "Panel 2", "Veil Nebula Panel 2", 12),
    ]
    execute, _ = _make_execute(
        image_rows=image_rows,
        mosaic_obj=existing,
        # The mosaics query selects (id, name) tuples.
        mosaic_rows=[(mosaic_id, "Veil Mosaic")],
    )
    mock_session = _base_session(execute)

    _override_session(mock_session)
    app.dependency_overrides[get_current_user] = lambda: viewer_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                PREFILL_URL,
                params={"target_id": str(target_id), "dates": "2025-01-01,2025-01-02"},
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        # base_name: most common panel-token base among the OBJECT headers.
        assert data["base_name"] == "Veil Nebula"
        rows = {(r["session_date"], r["panel_label"], r["frame_count"]) for r in data["rows"]}
        assert rows == {
            ("2025-01-01", "Panel 1", 10),
            ("2025-01-02", "Panel 2", 12),
        }
        assert [m["name"] for m in data["mosaics"]] == ["Veil Mosaic"]
        assert all("id" in m for m in data["mosaics"])
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST mode "new"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_new_mode_creates_mosaic_panels_sessions_and_claims(admin_user):
    """Happy path: mosaic + panel + included session rows are created and a
    claim UPDATE on images is issued; response carries the summary counts."""
    target_id = uuid.uuid4()
    execute, statements = _make_execute(mosaic_obj=None, update_rowcount=3)
    mock_session = _base_session(execute)

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(CREATE_URL, json={
                "mode": "new",
                "name": "Veil Mosaic",
                "target_id": str(target_id),
                "panels": [
                    _panel("Panel 1", ["2025-01-01"]),
                ],
            })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["name"] == "Veil Mosaic"
        assert data["panel_count"] == 1
        assert data["claimed_frames"] == 3
        assert "id" in data

        added_types = {type(o) for o in _added_instances(mock_session)}
        assert Mosaic in added_types
        assert MosaicPanel in added_types
        # Session rows: either ORM adds with status "included" or an upsert
        # statement against mosaic_panel_sessions.
        session_rows = [
            o for o in _added_instances(mock_session)
            if isinstance(o, MosaicPanelSession)
        ]
        if session_rows:
            assert all(r.status == "included" for r in session_rows)
        else:
            assert any("mosaic_panel_sessions" in str(s) for s in statements)
        # The frame claim UPDATE was issued.
        assert any("UPDATE images" in str(s) for s in statements)
        mock_session.commit.assert_awaited()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_new_mode_duplicate_name_returns_409(admin_user):
    """A case-insensitive name collision with an existing mosaic is a 409 and
    inserts nothing."""
    existing = MagicMock()
    existing.id = uuid.uuid4()
    existing.name = "veil mosaic"

    execute, statements = _make_execute(mosaic_obj=existing)
    mock_session = _base_session(execute)

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(CREATE_URL, json={
                "mode": "new",
                "name": "Veil Mosaic",
                "target_id": str(uuid.uuid4()),
                "panels": [
                    _panel("Panel 1", ["2025-01-01"]),
                ],
            })
        assert resp.status_code == 409, resp.text
        assert not _added_instances(mock_session)
        assert not any("UPDATE images" in str(s) for s in statements)
        mock_session.commit.assert_not_awaited()
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST mode "existing"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_existing_mode_unknown_mosaic_returns_404(admin_user):
    execute, _ = _make_execute(mosaic_obj=None)
    mock_session = _base_session(execute, mosaic_obj=None)

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(CREATE_URL, json={
                "mode": "existing",
                "mosaic_id": str(uuid.uuid4()),
                "target_id": str(uuid.uuid4()),
                "panels": [
                    _panel("Panel 1", ["2025-01-01"]),
                ],
            })
        assert resp.status_code == 404, resp.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_existing_mode_creates_missing_panel_and_claims(admin_user):
    """Adding to an existing mosaic where no panel matches (mosaic_id,
    panel_label) creates the panel and still claims frames."""
    mosaic_id = uuid.uuid4()
    mosaic = MagicMock(spec=Mosaic)
    mosaic.id = mosaic_id
    mosaic.name = "Veil Mosaic"

    execute, statements = _make_execute(
        mosaic_obj=mosaic, panel_obj=None, update_rowcount=2
    )
    mock_session = _base_session(execute, mosaic_obj=mosaic)

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(CREATE_URL, json={
                "mode": "existing",
                "mosaic_id": str(mosaic_id),
                "target_id": str(uuid.uuid4()),
                "panels": [
                    _panel("Panel 3", ["2025-02-01"]),
                ],
            })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["name"] == "Veil Mosaic"
        assert data["claimed_frames"] == 2

        added_types = {type(o) for o in _added_instances(mock_session)}
        assert MosaicPanel in added_types
        # No new Mosaic row in existing mode.
        assert Mosaic not in added_types
        assert any("UPDATE images" in str(s) for s in statements)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_edited_label_claims_by_original_label(admin_user):
    """Regression: when the user renames a panel ("Panel A") the claim UPDATE
    must match the frames' ORIGINAL parsed label ("Panel 1"), never the edited
    final label. "Panel A" may appear only as the SET value that stamps
    previously NULL labels."""
    execute, statements = _make_execute(mosaic_obj=None, update_rowcount=3)
    mock_session = _base_session(execute)

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(CREATE_URL, json={
                "mode": "new",
                "name": "Veil Mosaic",
                "target_id": str(uuid.uuid4()),
                "panels": [_panel("Panel A", ["2025-01-01"], original="Panel 1")],
            })
        assert resp.status_code == 200, resp.text

        # Collect WHERE-clause bind values of every UPDATE images statement.
        # The stamp update's SET value binds under the bare "panel_label" key;
        # everything else (suffixed keys) is comparison criteria.
        where_vals = []
        for s in statements:
            if "UPDATE images" not in str(s):
                continue
            for key, val in s.compile().params.items():
                if key != "panel_label":
                    where_vals.append(val)
        assert "Panel 1" in where_vals, where_vals
        assert "Panel A" not in where_vals, where_vals
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Validation and authorization
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    # mode "new" without a name.
    {
        "mode": "new",
        "target_id": str(uuid.uuid4()),
        "panels": [_panel("Panel 1", ["2025-01-01"])],
    },
    # mode "existing" without a mosaic_id.
    {
        "mode": "existing",
        "target_id": str(uuid.uuid4()),
        "panels": [_panel("Panel 1", ["2025-01-01"])],
    },
    # empty panels list.
    {
        "mode": "new",
        "name": "Veil Mosaic",
        "target_id": str(uuid.uuid4()),
        "panels": [],
    },
    # duplicate panel labels in one request.
    {
        "mode": "new",
        "name": "Veil Mosaic",
        "target_id": str(uuid.uuid4()),
        "panels": [
            _panel("Panel 1", ["2025-01-01"]),
            _panel("Panel 1", ["2025-01-02"]),
        ],
    },
    # empty panel_label.
    {
        "mode": "new",
        "name": "Veil Mosaic",
        "target_id": str(uuid.uuid4()),
        "panels": [_panel("", ["2025-01-01"])],
    },
    # empty rows.
    {
        "mode": "new",
        "name": "Veil Mosaic",
        "target_id": str(uuid.uuid4()),
        "panels": [_panel("Panel 1", [])],
    },
], ids=[
    "new-without-name",
    "existing-without-mosaic-id",
    "empty-panels",
    "duplicate-panel-labels",
    "empty-panel-label",
    "empty-rows",
])
async def test_invalid_body_returns_4xx(admin_user, body):
    execute, _ = _make_execute()
    mock_session = _base_session(execute)

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(CREATE_URL, json=body)
        assert 400 <= resp.status_code < 500, resp.text
        # Nothing persisted on a rejected request.
        mock_session.commit.assert_not_awaited()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_post_viewer_forbidden(viewer_user):
    app.dependency_overrides[get_current_user] = lambda: viewer_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(CREATE_URL, json={
                "mode": "new",
                "name": "Veil Mosaic",
                "target_id": str(uuid.uuid4()),
                "panels": [
                    _panel("Panel 1", ["2025-01-01"]),
                ],
            })
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()
