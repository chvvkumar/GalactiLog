"""Real-DB tests for Phase 5 Task 4: surfacing available (unconfigured) panel
labels on an accepted mosaic's detail response.

Once a mosaic has MosaicPanel rows, the offline detection job never re-scans
that target for new panel tokens (mosaic_detection.py's `_gather_target_records`
excludes targets already in a MosaicPanel). Ingest-time parsing (Task 1/2)
still stamps Image.panel_label on every new frame regardless, leaving
Image.panel_id NULL when no MosaicPanel matches yet. GET /{mosaic_id} must
surface those NULL-panel_id labels as `available_panel_labels` so an admin can
see a new panel label exists without needing the batch job to re-run.
"""
import os
import sys
import uuid
from datetime import date
from unittest.mock import MagicMock

os.environ.setdefault("GALACTILOG_DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_catalog")
os.environ.setdefault("GALACTILOG_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("GALACTILOG_FITS_DATA_PATH", "/tmp/test_fits")
os.environ.setdefault("GALACTILOG_THUMBNAILS_PATH", "/tmp/test_thumbnails")
os.environ.setdefault("GALACTILOG_JWT_SECRET", "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2")
os.environ.setdefault("GALACTILOG_HTTPS", "false")
for _mod in ("fitsio",):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
sys.modules.setdefault("app.worker.tasks", MagicMock())

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user
from app.models.user import User, UserRole
from app.models import Target, Image, Mosaic, MosaicPanel

TEST_DB_URL = os.environ["GALACTILOG_DATABASE_URL"]


def _img(**kw):
    defaults = dict(
        id=uuid.uuid4(),
        file_path=f"/data/{uuid.uuid4()}.fits",
        file_name="x.fits",
        image_type="LIGHT",
        raw_headers={},
    )
    defaults.update(kw)
    return Image(**defaults)


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(TEST_DB_URL, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM images"))
        await conn.execute(text("DELETE FROM mosaic_panel_sessions"))
        await conn.execute(text("DELETE FROM mosaic_panels"))
        await conn.execute(text("DELETE FROM mosaics"))
        await conn.execute(text("DELETE FROM targets"))

    yield Session

    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM images"))
        await conn.execute(text("DELETE FROM mosaic_panel_sessions"))
        await conn.execute(text("DELETE FROM mosaic_panels"))
        await conn.execute(text("DELETE FROM mosaics"))
        await conn.execute(text("DELETE FROM targets"))
    await engine.dispose()


@pytest_asyncio.fixture
async def api_client(db):
    Session = db

    async def _override_session():
        async with Session() as s:
            yield s

    def _override_user():
        u = MagicMock(spec=User)
        u.id = uuid.uuid4()
        u.username = "tester"
        u.role = UserRole.admin
        u.is_active = True
        return u

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


async def _seed_mosaic_with_panels(s):
    target = Target(primary_name="NGC 1499 available", aliases=[])
    s.add(target)
    await s.flush()

    mosaic = Mosaic(name="NGC 1499 mosaic")
    s.add(mosaic)
    await s.flush()

    panel_1 = MosaicPanel(
        mosaic_id=mosaic.id, target_id=target.id,
        panel_label="Panel 1", object_pattern="%NGC 1499%Panel%1%",
    )
    panel_2 = MosaicPanel(
        mosaic_id=mosaic.id, target_id=target.id,
        panel_label="Panel 2", object_pattern="%NGC 1499%Panel%2%",
    )
    s.add_all([panel_1, panel_2])
    await s.flush()

    # Frame belonging to the existing Panel 1 -- resolved at ingest time.
    s.add(_img(
        resolved_target_id=target.id, exposure_time=100.0,
        panel_id=panel_1.id, panel_label="Panel 1",
        raw_headers={"OBJECT": "NGC 1499 Panel 1"},
        session_date=date(2026, 1, 1),
    ))

    return target, mosaic, panel_1, panel_2


@pytest.mark.asyncio
async def test_new_panel_label_without_backing_panel_is_surfaced(api_client, db):
    Session = db
    async with Session() as s:
        target, mosaic, panel_1, panel_2 = await _seed_mosaic_with_panels(s)

        # Newly-ingested frame carrying a panel token never seen before --
        # panel_label set, panel_id left NULL (no matching MosaicPanel row).
        s.add(_img(
            resolved_target_id=target.id, exposure_time=200.0,
            panel_id=None, panel_label="Panel 3",
            raw_headers={"OBJECT": "NGC 1499 Panel 3"},
            session_date=date(2026, 1, 2),
        ))
        await s.commit()
        mosaic_id, target_id = mosaic.id, target.id

    resp = await api_client.get(f"/api/mosaics/{mosaic_id}")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Each entry carries the target_id the label was seen on, so the client
    # can promote it via POST /mosaics/{mosaic_id}/panels.
    assert data["available_panel_labels"] == [
        {"label": "Panel 3", "target_id": str(target_id)}
    ]
    # Existing panels/response shape unaffected.
    assert len(data["panels"]) == 2
    assert data["total_frames"] == 1


@pytest.mark.asyncio
async def test_no_duplicates_when_multiple_images_share_new_label(api_client, db):
    Session = db
    async with Session() as s:
        target, mosaic, panel_1, panel_2 = await _seed_mosaic_with_panels(s)

        for i in range(3):
            s.add(_img(
                resolved_target_id=target.id, exposure_time=50.0,
                panel_id=None, panel_label="Panel 5",
                raw_headers={"OBJECT": "NGC 1499 Panel 5"},
                session_date=date(2026, 1, 3 + i),
            ))
        await s.commit()
        mosaic_id, target_id = mosaic.id, target.id

    resp = await api_client.get(f"/api/mosaics/{mosaic_id}")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["available_panel_labels"] == [
        {"label": "Panel 5", "target_id": str(target_id)}
    ]


@pytest.mark.asyncio
async def test_empty_list_when_every_label_already_has_a_panel(api_client, db):
    Session = db
    async with Session() as s:
        target, mosaic, panel_1, panel_2 = await _seed_mosaic_with_panels(s)

        # Frame for the other existing panel -- panel_id set, no new label.
        s.add(_img(
            resolved_target_id=target.id, exposure_time=100.0,
            panel_id=panel_2.id, panel_label="Panel 2",
            raw_headers={"OBJECT": "NGC 1499 Panel 2"},
            session_date=date(2026, 1, 5),
        ))
        await s.commit()
        mosaic_id = mosaic.id

    resp = await api_client.get(f"/api/mosaics/{mosaic_id}")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["available_panel_labels"] == []


@pytest.mark.asyncio
async def test_sorted_and_deduplicated_across_multiple_new_labels(api_client, db):
    Session = db
    async with Session() as s:
        target, mosaic, panel_1, panel_2 = await _seed_mosaic_with_panels(s)

        s.add(_img(
            resolved_target_id=target.id, exposure_time=10.0,
            panel_id=None, panel_label="Panel 9",
            raw_headers={"OBJECT": "NGC 1499 Panel 9"},
            session_date=date(2026, 1, 6),
        ))
        s.add(_img(
            resolved_target_id=target.id, exposure_time=10.0,
            panel_id=None, panel_label="Panel 4",
            raw_headers={"OBJECT": "NGC 1499 Panel 4"},
            session_date=date(2026, 1, 7),
        ))
        s.add(_img(
            resolved_target_id=target.id, exposure_time=10.0,
            panel_id=None, panel_label="Panel 4",
            raw_headers={"OBJECT": "NGC 1499 Panel 4"},
            session_date=date(2026, 1, 8),
        ))
        await s.commit()
        mosaic_id, target_id = mosaic.id, target.id

    resp = await api_client.get(f"/api/mosaics/{mosaic_id}")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["available_panel_labels"] == [
        {"label": "Panel 4", "target_id": str(target_id)},
        {"label": "Panel 9", "target_id": str(target_id)},
    ]


@pytest.mark.asyncio
async def test_promoting_available_label_via_add_panel_removes_it(api_client, db):
    """The promotion path: POST /{mosaic_id}/panels with the surfaced
    (label, target_id) creates a real MosaicPanel, retro-links the frames
    that were ingested before the panel existed (so its stats are non-zero
    immediately), and the label no longer appears as available."""
    Session = db
    async with Session() as s:
        target, mosaic, panel_1, panel_2 = await _seed_mosaic_with_panels(s)

        # Two frames for the new label, one token-bearing frame with a
        # DIFFERENT label, and one unlabeled frame -- only the first two may
        # be claimed by the promotion.
        s.add(_img(
            resolved_target_id=target.id, exposure_time=200.0,
            panel_id=None, panel_label="Panel 3",
            raw_headers={"OBJECT": "NGC 1499 Panel 3"},
            session_date=date(2026, 1, 2),
        ))
        s.add(_img(
            resolved_target_id=target.id, exposure_time=300.0,
            panel_id=None, panel_label="Panel 3",
            raw_headers={"OBJECT": "NGC 1499 Panel 3"},
            session_date=date(2026, 1, 3),
        ))
        s.add(_img(
            resolved_target_id=target.id, exposure_time=50.0,
            panel_id=None, panel_label="Panel 8",
            raw_headers={"OBJECT": "NGC 1499 Panel 8"},
            session_date=date(2026, 1, 4),
        ))
        s.add(_img(
            resolved_target_id=target.id, exposure_time=60.0,
            panel_id=None, panel_label=None,
            raw_headers={"OBJECT": "NGC 1499"},
            session_date=date(2026, 1, 5),
        ))
        await s.commit()
        mosaic_id, target_id = mosaic.id, target.id

    resp = await api_client.get(f"/api/mosaics/{mosaic_id}")
    entry = next(
        e for e in resp.json()["available_panel_labels"] if e["label"] == "Panel 3"
    )

    resp = await api_client.post(
        f"/api/mosaics/{mosaic_id}/panels",
        json={"target_id": entry["target_id"], "panel_label": entry["label"]},
    )
    assert resp.status_code == 200, resp.text
    new_panel_id = resp.json()["panel_id"]

    resp = await api_client.get(f"/api/mosaics/{mosaic_id}")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Promoted label is gone; the sibling label is still available.
    assert data["available_panel_labels"] == [
        {"label": "Panel 8", "target_id": str(target_id)}
    ]
    assert len(data["panels"]) == 3
    # Retro-link makes the promoted panel's stats non-zero immediately.
    promoted = next(p for p in data["panels"] if p["panel_label"] == "Panel 3")
    assert promoted["panel_id"] == new_panel_id
    assert promoted["total_frames"] == 2
    assert promoted["total_integration_seconds"] == 500.0

    # The frames themselves now carry the new panel_id; the other-label and
    # unlabeled frames were not claimed.
    async with Session() as s:
        rows = (await s.execute(
            select(Image.panel_label, Image.panel_id)
            .where(Image.resolved_target_id == target_id)
        )).all()
    by_label: dict = {}
    for label, pid in rows:
        by_label.setdefault(label, []).append(pid)
    assert len(by_label["Panel 3"]) == 2
    assert all(str(pid) == new_panel_id for pid in by_label["Panel 3"])
    assert by_label["Panel 8"] == [None]
    assert by_label[None] == [None]


@pytest.mark.asyncio
async def test_create_mosaic_retro_links_existing_frames(api_client, db):
    """POST /mosaics with panels claims already-ingested matching frames the
    same way add_panel does, so a hand-created mosaic starts with stats."""
    Session = db
    async with Session() as s:
        target = Target(primary_name="Heart create", aliases=[])
        s.add(target)
        await s.flush()
        s.add(_img(
            resolved_target_id=target.id, exposure_time=150.0,
            panel_id=None, panel_label="Panel 1",
            raw_headers={"OBJECT": "Heart create Panel 1"},
            session_date=date(2026, 2, 1),
        ))
        await s.commit()
        target_id = target.id

    resp = await api_client.post(
        "/api/mosaics",
        json={
            "name": "Heart create mosaic",
            "panels": [{"target_id": str(target_id), "panel_label": "Panel 1"}],
        },
    )
    assert resp.status_code == 200, resp.text
    mosaic_id = resp.json()["id"]

    resp = await api_client.get(f"/api/mosaics/{mosaic_id}")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["available_panel_labels"] == []
    assert data["panels"][0]["total_frames"] == 1
    assert data["panels"][0]["total_integration_seconds"] == 150.0
