"""API tests for merge endpoints after the service extraction (ARCH-1/ARCH-7).

Exercises representative merge endpoints via dependency overrides for the DB
session and admin auth, asserting response shapes/status codes are preserved.
"""

import uuid
from contextlib import asynccontextmanager

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session
from app.api.deps import require_admin, get_current_user
from app.models.target import Target
from app.services.cache import STATS_CACHE_KEY


def _make_target(name="M 31", aliases=None, merged_into_id=None):
    t = MagicMock(spec=Target)
    t.id = uuid.uuid4()
    t.primary_name = name
    t.object_type = "Galaxy"
    t.constellation = "And"
    t.aliases = aliases or []
    t.merged_into_id = merged_into_id
    t.merged_at = None
    return t


def _override_session(mock_session):
    async def _gen():
        yield mock_session
    app.dependency_overrides[get_session] = _gen


def _fake_async_redis_cm(analysis_keys=()):
    """Build a fake `async_redis()` context manager plus the mock redis client
    it yields, for asserting cache-invalidation calls (AUD-034)."""
    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock()

    async def _scan_iter(match=None):
        for k in analysis_keys:
            yield k
    mock_redis.scan_iter = _scan_iter

    @asynccontextmanager
    async def _cm():
        yield mock_redis

    return _cm, mock_redis


@pytest.mark.asyncio
async def test_merge_winner_not_found_returns_404(admin_user):
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/targets/merge",
                json={"winner_id": str(uuid.uuid4()), "loser_id": str(uuid.uuid4())},
            )
        assert resp.status_code == 404
        assert "Winner" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_merge_missing_loser_returns_400(admin_user):
    winner = _make_target()
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=winner)

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/targets/merge",
                json={"winner_id": str(winner.id)},
            )
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_merge_by_loser_name_returns_status_ok(admin_user):
    winner = _make_target(aliases=["NGC 224"])
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=winner)
    mock_session.execute = AsyncMock(return_value=MagicMock())
    mock_session.commit = AsyncMock()

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/targets/merge",
                json={"winner_id": str(winner.id), "loser_name": "Andromeda"},
            )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"status": "ok"}
        # The unresolved name should have been appended as an alias.
        assert "Andromeda" in winner.aliases
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_merge_invalidates_stats_and_analysis_cache(admin_user):
    """AUD-034: a successful merge must delete the stats cache key and every
    galactilog:analysis:* key, not just leave them to expire on TTL."""
    winner = _make_target(aliases=["NGC 224"])
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=winner)
    mock_session.execute = AsyncMock(return_value=MagicMock())
    mock_session.commit = AsyncMock()

    analysis_keys = ["galactilog:analysis:correlation:1"]
    redis_cm, mock_redis = _fake_async_redis_cm(analysis_keys)

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        with patch("app.services.cache.async_redis", redis_cm):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/targets/merge",
                    json={"winner_id": str(winner.id), "loser_name": "Andromeda"},
                )
        assert resp.status_code == 200, resp.text
    finally:
        app.dependency_overrides.clear()

    assert mock_redis.delete.await_args_list[0].args == (STATS_CACHE_KEY,)
    assert set(mock_redis.delete.await_args_list[1].args) == set(analysis_keys)


@pytest.mark.asyncio
async def test_unmerge_not_merged_returns_400(admin_user):
    loser = _make_target(merged_into_id=None)
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=loser)

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(f"/api/targets/{loser.id}/unmerge")
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_unmerge_invalidates_stats_and_analysis_cache(admin_user):
    """AUD-034: a successful unmerge must invalidate both cache families."""
    winner = _make_target(name="M 31")
    loser = _make_target(name="Andromeda", merged_into_id=winner.id)

    def _scalars_result():
        m = MagicMock()
        m.scalars.return_value.first.return_value = None  # no merge manifest
        m.scalars.return_value.all.return_value = []  # no mosaic panels
        return m

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(side_effect=[loser, winner])
    mock_session.execute = AsyncMock(side_effect=lambda *a, **kw: _scalars_result())
    mock_session.commit = AsyncMock()
    mock_session.delete = AsyncMock()

    analysis_keys = ["galactilog:analysis:distribution:2"]
    redis_cm, mock_redis = _fake_async_redis_cm(analysis_keys)

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        with patch("app.services.cache.async_redis", redis_cm):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(f"/api/targets/{loser.id}/unmerge")
        assert resp.status_code == 200, resp.text
    finally:
        app.dependency_overrides.clear()

    assert mock_redis.delete.await_args_list[0].args == (STATS_CACHE_KEY,)
    assert set(mock_redis.delete.await_args_list[1].args) == set(analysis_keys)


@pytest.mark.asyncio
async def test_unmerge_target_not_found_returns_404(admin_user):
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(f"/api/targets/{uuid.uuid4()}/unmerge")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_merge_history_obj_pseudo_target_returns_empty_list(viewer_user):
    """obj:<name> pseudo-targets have no DB row, so merge-history must return
    an empty list with HTTP 200 instead of a 422 from UUID path coercion."""
    mock_session = AsyncMock()
    # No DB access expected for a non-UUID id; fail loudly if it is attempted.
    mock_session.get = AsyncMock(side_effect=AssertionError("session.get called"))
    mock_session.execute = AsyncMock(side_effect=AssertionError("execute called"))

    _override_session(mock_session)
    app.dependency_overrides[get_current_user] = lambda: viewer_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/targets/obj:SomeName/merge-history")
        assert resp.status_code == 200, resp.text
        assert resp.json() == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_merge_history_unknown_uuid_returns_404(viewer_user):
    """A well-formed UUID with no matching row still returns 404."""
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)

    _override_session(mock_session)
    app.dependency_overrides[get_current_user] = lambda: viewer_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/targets/{uuid.uuid4()}/merge-history")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_merge_candidate_count_returns_count(viewer_user):
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = 7
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    _override_session(mock_session)
    app.dependency_overrides[get_current_user] = lambda: viewer_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/targets/merge-candidates/count")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"count": 7}
    finally:
        app.dependency_overrides.clear()


def _make_candidate(status="accepted", method="orphan", suggested_target_id=None, source_name="Foo"):
    from app.models.merge_candidate import MergeCandidate
    c = MagicMock(spec=MergeCandidate)
    c.id = uuid.uuid4()
    c.status = status
    c.method = method
    c.suggested_target_id = suggested_target_id
    c.source_name = source_name
    return c


@pytest.mark.asyncio
async def test_revert_merge_candidate_invalidates_stats_and_analysis_cache(admin_user):
    """AUD-034: reverting an accepted merge candidate must invalidate both
    cache families, same as merge/unmerge."""
    winner = _make_target(name="M 31")
    winner.user_defined = True  # skip the empty-winner delete branch
    candidate = _make_candidate(suggested_target_id=winner.id)

    def _count_result():
        m = MagicMock()
        m.scalar_one.return_value = 3
        return m

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(side_effect=[candidate, winner])
    mock_session.execute = AsyncMock(side_effect=lambda *a, **kw: _count_result())
    mock_session.commit = AsyncMock()

    analysis_keys = ["galactilog:analysis:boxplot:3"]
    redis_cm, mock_redis = _fake_async_redis_cm(analysis_keys)

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        with patch("app.services.cache.async_redis", redis_cm):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(f"/api/targets/merge-candidates/{candidate.id}/revert")
        assert resp.status_code == 200, resp.text
    finally:
        app.dependency_overrides.clear()

    assert mock_redis.delete.await_args_list[0].args == (STATS_CACHE_KEY,)
    assert set(mock_redis.delete.await_args_list[1].args) == set(analysis_keys)


def _no_conflict_session():
    """Session whose scalar lookups find nothing (no name/identity conflicts)."""
    mock_session = AsyncMock()
    empty = MagicMock()
    empty.scalars.return_value.first.return_value = None
    empty.scalars.return_value.all.return_value = []
    empty.rowcount = 0
    mock_session.execute = AsyncMock(return_value=empty)
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    return mock_session


@pytest.mark.asyncio
async def test_orphan_create_invalidates_stats_and_analysis_cache(admin_user, monkeypatch):
    """AUD-034: creating a target from an orphan candidate resolves previously
    unresolved frames onto it, changing stats figures; both cache families
    must be invalidated."""
    candidate = _make_candidate(status="pending", source_name="Jupiter")

    mock_session = _no_conflict_session()
    mock_session.get = AsyncMock(return_value=candidate)

    analysis_keys = ["galactilog:analysis:matrix:5"]
    redis_cm, mock_redis = _fake_async_redis_cm(analysis_keys)

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    monkeypatch.setattr("app.api.merges._enrich_new_target", lambda target_id: None)
    try:
        with patch("app.services.cache.async_redis", redis_cm):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/targets/orphan-create", json={
                    "candidate_id": str(uuid.uuid4()),
                    "primary_name": "Jupiter",
                    "user_defined": True,
                })
        assert resp.status_code == 200, resp.text
    finally:
        app.dependency_overrides.clear()

    assert mock_redis.delete.await_args_list[0].args == (STATS_CACHE_KEY,)
    assert set(mock_redis.delete.await_args_list[1].args) == set(analysis_keys)


@pytest.mark.asyncio
async def test_custom_create_invalidates_stats_and_analysis_cache(admin_user, monkeypatch):
    """AUD-034: creating a custom target retro-links pending orphan images,
    changing stats figures; both cache families must be invalidated."""
    mock_session = _no_conflict_session()

    analysis_keys = ["galactilog:analysis:correlation:6"]
    redis_cm, mock_redis = _fake_async_redis_cm(analysis_keys)

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    monkeypatch.setattr("app.api.merges._enrich_new_target", lambda target_id: None)
    try:
        with patch("app.services.cache.async_redis", redis_cm):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/targets/custom", json={
                    "primary_name": "Jupiter",
                    "object_type": "Planet",
                    "user_defined": True,
                })
        assert resp.status_code == 200, resp.text
    finally:
        app.dependency_overrides.clear()

    assert mock_redis.delete.await_args_list[0].args == (STATS_CACHE_KEY,)
    assert set(mock_redis.delete.await_args_list[1].args) == set(analysis_keys)


@pytest.mark.asyncio
async def test_rename_target_invalidates_stats_and_analysis_cache(admin_user):
    """AUD-034: renaming a target (identity update, no re-resolve) must
    invalidate both cache families since it changes the name shown on the
    Statistics top-targets list and calendar."""
    target = _make_target(name="NGC 7000")
    target.catalog_id = None
    target.common_name = None
    target.object_type = "Emission Nebula"
    target.name_locked = False

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=target)
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    analysis_keys = ["galactilog:analysis:timeseries:4"]
    redis_cm, mock_redis = _fake_async_redis_cm(analysis_keys)

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        with patch("app.services.cache.async_redis", redis_cm):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.put(
                    f"/api/targets/{target.id}/identity",
                    json={"primary_name": "North America Nebula"},
                )
        assert resp.status_code == 200, resp.text
    finally:
        app.dependency_overrides.clear()

    assert mock_redis.delete.await_args_list[0].args == (STATS_CACHE_KEY,)
    assert set(mock_redis.delete.await_args_list[1].args) == set(analysis_keys)
