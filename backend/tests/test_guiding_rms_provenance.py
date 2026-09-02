"""images.guiding_rms_source: which measurement produced a frame's guiding RMS.

The column exists because two independent sources now write the same three
columns. N.I.N.A.'s sidecar CSV reports the RMS its own guider integration
saw for that sub; the PHD2 correlation computes one from the guide log's raw
sample stream. They are close but not identical measurements, and a user
comparing a frame table against PHD2's own display has to be able to tell
which one they are looking at.
"""
import os
import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker

os.environ.setdefault(
    "GALACTILOG_DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/test_catalog",
)

TEST_MARK = "zzguidingsourcetest"


def _sync_session_factory():
    url = os.environ["GALACTILOG_DATABASE_URL"].replace("+asyncpg", "+psycopg2")
    engine = create_engine(url, pool_pre_ping=True)
    try:
        conn = engine.connect()
        conn.close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"test DB not reachable: {exc}")
    return sessionmaker(bind=engine), engine


@pytest.fixture
def db():
    Session, engine = _sync_session_factory()

    def _clean():
        with Session() as s:
            s.execute(
                text("DELETE FROM images WHERE file_path LIKE :p"),
                {"p": f"%{TEST_MARK}%"},
            )
            s.commit()

    _clean()
    yield Session
    _clean()
    engine.dispose()


def test_the_column_is_declared_on_the_model():
    from sqlalchemy import String

    from app.models import Image

    column = Image.__table__.columns["guiding_rms_source"]
    assert isinstance(column.type, String)
    assert column.type.length == 20
    assert column.nullable is True


def test_no_index_is_created_for_it():
    """Two values plus NULL is far too low-cardinality for a btree to pay for
    itself, and nothing filters on it - exactly the eccentricity_source case."""
    from app.models import Image

    indexed = {
        col.name
        for index in Image.__table__.indexes
        for col in index.columns
    }
    assert "guiding_rms_source" not in indexed


def test_the_column_round_trips_through_the_database(db):
    from app.models import Image

    image_id = uuid.uuid4()
    with db() as s:
        s.add(Image(
            id=image_id,
            file_path=f"/{TEST_MARK}/a.fits",
            file_name="a.fits",
            capture_date=datetime(2026, 7, 14, 22, 0, 0, tzinfo=timezone.utc),
            session_date=date(2026, 7, 14),
            image_type="LIGHT",
            exposure_time=180.0,
            guiding_rms_arcsec=0.45,
            guiding_rms_source="phd2",
        ))
        s.commit()
    with db() as s:
        stored = s.get(Image, image_id)
        assert stored.guiding_rms_source == "phd2"


def test_existing_rows_read_back_null(db):
    """NULL is informative: it means nothing has claimed this value yet."""
    from app.models import Image

    image_id = uuid.uuid4()
    with db() as s:
        s.add(Image(
            id=image_id,
            file_path=f"/{TEST_MARK}/b.fits",
            file_name="b.fits",
            image_type="LIGHT",
        ))
        s.commit()
    with db() as s:
        assert s.get(Image, image_id).guiding_rms_source is None


def test_the_frame_response_carries_the_source():
    """A frame table that shows a guiding RMS with no provenance invites the
    user to compare two different measurements as if they were one."""
    from app.schemas.target import FrameRecord

    assert "guiding_rms_source" in FrameRecord.model_fields
    record = FrameRecord(
        timestamp="", file_name="a.fits", image_id="x", file_path="/a.fits",
    )
    assert record.guiding_rms_source is None


def test_both_frame_builders_populate_it():
    """Two call sites build a FrameRecord; a field added to one and forgotten
    on the other shows provenance on the session card and not on the rig
    breakdown beside it."""
    import inspect as _inspect

    from app.services import target_detail, target_helpers

    assert "guiding_rms_source" in _inspect.getsource(target_detail.get_session_detail)
    assert "guiding_rms_source" in _inspect.getsource(
        target_helpers.build_rig_details
    )


def test_alembic_has_a_single_head():
    import pathlib

    versions = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"
    revisions = {}
    downs = set()
    for path in versions.glob("*.py"):
        text_ = path.read_text(encoding="utf-8")
        for line in text_.splitlines():
            if line.startswith("revision = "):
                revisions[line.split("=", 1)[1].strip().strip('"')] = path.name
            if line.startswith("down_revision = "):
                downs.add(line.split("=", 1)[1].strip().strip('"'))
    heads = set(revisions) - downs
    # The invariant is one head, not a particular number: pinning the literal
    # made every new revision break this test (0024 did).
    assert len(heads) == 1, f"expected a single alembic head, got {sorted(heads)}"
