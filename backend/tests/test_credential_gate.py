"""Integration-level fresh-vs-existing install matrix for the Phase 9 startup
credential fail-fast gate (see app.config.missing_all_credentials).

Task 1 (commit de8800a) put the boolean decision logic in
missing_all_credentials() and unit-tested the 8-combination signal matrix
with plain booleans (backend/tests/test_config.py). Those tests never touch
a database, a real filesystem secret, or a real env var - they prove the
boolean algebra is correct, not that the three signals are actually computed
correctly against a real install. This file drives the decision against
realistic install states instead: a real migrated test DB for the admin-row
signal, a real tmp_path file for the JWT-secret-file signal, and a real
monkeypatched env var for the password signal.

Coverage gap (documented, not fixed here): unlike jwt_secret_file_exists,
there is no importable production function for the admin-row signal -
entrypoint.sh computes it inline via a python -c heredoc
(`SELECT EXISTS (SELECT 1 FROM users WHERE role = 'admin')`, see
entrypoint.sh's HAS_ADMIN_USER probe). Task 1's brief flagged this as
something Task 2 should escalate rather than silently work around by
shelling out to entrypoint.sh (which is Linux/Docker-only, see
container_perms.sh). The tests below therefore reproduce entrypoint.sh's
exact SQL locally (_has_admin_user_row) so the *query itself* gets real-DB
coverage, and combine its result with missing_all_credentials() to prove
the full signal-computation-plus-decision pipeline behaves correctly. If a
future task extracts that SQL into an importable app.services function,
these tests should be updated to call it directly instead of duplicating it.

Requires a real Postgres (test:test@localhost:5432/test_catalog) with the
Alembic schema applied. When the DB is unreachable the whole module skips,
matching the environment-dependent convention of the other DB-backed tests
(see test_merge_reversibility.py).
"""
import os
import sys
import uuid
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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import missing_all_credentials
from app.models import User, UserRole

TEST_DB_URL = os.environ["GALACTILOG_DATABASE_URL"]

# Mirrors entrypoint.sh's HAS_ADMIN_USER probe exactly (see entrypoint.sh
# around the "admin user existence check" run_db_probe call). Kept as plain
# SQL, not the ORM, so this test exercises the identical query the real gate
# runs rather than a semantically-similar-but-different ORM query.
_ADMIN_ROW_QUERY = text("SELECT EXISTS (SELECT 1 FROM users WHERE role = 'admin')")


async def _has_admin_user_row(session) -> bool:
    result = await session.execute(_ADMIN_ROW_QUERY)
    return bool(result.scalar())


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(TEST_DB_URL, poolclass=None)
    try:
        async with engine.begin() as conn:
            # Same deletion order as test_merge_reversibility.py's db_session
            # fixture: users has FK dependents (custom_columns.created_by
            # etc.) left over from other test modules sharing this DB, so
            # those must be cleared first or the users delete violates the
            # FK constraint.
            for tbl in (
                "merge_manifests", "custom_column_values", "custom_columns",
                "session_notes", "merge_candidates", "images", "targets", "users",
            ):
                await conn.execute(text(f"DELETE FROM {tbl}"))
    except Exception as e:  # DB unreachable in this environment -> skip module.
        await engine.dispose()
        pytest.skip(f"Test DB unavailable: {e}")

    Session = async_sessionmaker(engine, expire_on_commit=False)
    yield Session
    await engine.dispose()


def _user(role, username=None):
    return User(
        id=uuid.uuid4(),
        username=username or f"user-{uuid.uuid4().hex[:8]}",
        password_hash="x",
        role=role,
        is_active=True,
    )


# ---------------------------------------------------------------------------
# Fresh vs existing install matrix
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fresh_install_empty_db_no_env_no_file_refuses(db_session, tmp_path):
    """Truly fresh install: empty migrated DB, no password env, no secret
    file on disk -> the gate must refuse to boot."""
    secret_file = tmp_path / ".jwt_secret"
    async with db_session() as s:
        has_admin = await _has_admin_user_row(s)

    assert has_admin is False
    assert missing_all_credentials(
        admin_password_env="",
        jwt_secret_env="",
        jwt_secret_file_exists=secret_file.exists(),
        has_admin_user=has_admin,
    ) is True


@pytest.mark.asyncio
async def test_existing_install_via_real_admin_row_boots(db_session, tmp_path):
    """An admin user row already exists in the DB (no password env, no
    secret file) -> boot, driven by a real INSERT + real SELECT against the
    users table rather than a mocked boolean."""
    secret_file = tmp_path / ".jwt_secret"
    async with db_session() as s:
        s.add(_user(UserRole.admin, "admin"))
        await s.commit()

    async with db_session() as s:
        has_admin = await _has_admin_user_row(s)

    assert has_admin is True
    assert missing_all_credentials(
        admin_password_env="",
        jwt_secret_env="",
        jwt_secret_file_exists=secret_file.exists(),
        has_admin_user=has_admin,
    ) is False


@pytest.mark.asyncio
async def test_existing_install_via_persisted_secret_file_boots(db_session, tmp_path):
    """A persisted JWT secret file already exists on disk (no password env,
    no admin row) -> boot."""
    secret_file = tmp_path / ".jwt_secret"
    secret_file.write_text("deadbeef" * 8, encoding="utf-8")

    async with db_session() as s:
        has_admin = await _has_admin_user_row(s)

    assert has_admin is False
    assert missing_all_credentials(
        admin_password_env="",
        jwt_secret_env="",
        jwt_secret_file_exists=secret_file.exists(),
        has_admin_user=has_admin,
    ) is False


@pytest.mark.asyncio
async def test_existing_install_via_password_env_boots(monkeypatch, db_session, tmp_path):
    """GALACTILOG_ADMIN_PASSWORD is set (no admin row, no secret file) ->
    boot. Uses a real monkeypatched env var, matching how settings.admin_password
    is actually populated in production rather than a hardcoded literal."""
    monkeypatch.setenv("GALACTILOG_ADMIN_PASSWORD", "hunter2")
    secret_file = tmp_path / ".jwt_secret"

    async with db_session() as s:
        has_admin = await _has_admin_user_row(s)

    assert has_admin is False
    assert missing_all_credentials(
        admin_password_env=os.environ["GALACTILOG_ADMIN_PASSWORD"],
        jwt_secret_env="",
        jwt_secret_file_exists=secret_file.exists(),
        has_admin_user=has_admin,
    ) is False


@pytest.mark.asyncio
async def test_viewer_only_row_does_not_count_as_admin_row(db_session, tmp_path):
    """Known edge case (coordinator ruling): a viewer-only row, with no other
    signal present, must NOT satisfy the admin-row check - the gate still
    refuses. This documents that a viewer account alone cannot rescue a
    fresh install from the credential gate; an operator must still set
    GALACTILOG_ADMIN_PASSWORD or otherwise provision an admin."""
    secret_file = tmp_path / ".jwt_secret"
    async with db_session() as s:
        s.add(_user(UserRole.viewer, "viewer"))
        await s.commit()

    async with db_session() as s:
        has_admin = await _has_admin_user_row(s)

    assert has_admin is False
    assert missing_all_credentials(
        admin_password_env="",
        jwt_secret_env="",
        jwt_secret_file_exists=secret_file.exists(),
        has_admin_user=has_admin,
    ) is True


@pytest.mark.asyncio
async def test_admin_row_alongside_viewer_row_still_boots(db_session, tmp_path):
    """Sanity check on the query itself: once a real admin row exists
    alongside an unrelated viewer row, EXISTS still finds the admin row (no
    false negative from the presence of a non-admin row)."""
    secret_file = tmp_path / ".jwt_secret"
    async with db_session() as s:
        s.add(_user(UserRole.viewer, "viewer"))
        s.add(_user(UserRole.admin, "admin"))
        await s.commit()

    async with db_session() as s:
        has_admin = await _has_admin_user_row(s)

    assert has_admin is True
    assert missing_all_credentials(
        admin_password_env="",
        jwt_secret_env="",
        jwt_secret_file_exists=secret_file.exists(),
        has_admin_user=has_admin,
    ) is False
