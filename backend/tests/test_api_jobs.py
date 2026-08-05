"""GET /api/jobs and the Redis write helpers behind it (job_registry)."""
import uuid

import pytest
import redis as redis_mod
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.api.deps import require_admin
from app.config import settings
from app.worker.job_registry import (
    JOB_ENTRY_PREFIX, JOBS_ACTIVE_SET, SUPPRESSED_TASKS,
    clear_entry, record_queued, record_running,
)


@pytest.fixture
def r():
    client = redis_mod.from_url(settings.redis_url, decode_responses=True)
    _wipe(client)
    yield client
    _wipe(client)
    client.close()


def _wipe(client):
    ids = client.smembers(JOBS_ACTIVE_SET)
    if ids:
        client.delete(*(JOB_ENTRY_PREFIX + i for i in ids))
    client.delete(JOBS_ACTIVE_SET)


def _tid() -> str:
    return str(uuid.uuid4())


def test_record_queued_writes_entry_with_ttl(r):
    tid = _tid()
    record_queued(r, tid, "app.worker.tasks.correlate_phd2_images", eta="2026-08-05T21:00:00+00:00")
    entry = r.hgetall(JOB_ENTRY_PREFIX + tid)
    assert entry["state"] == "queued"
    assert entry["name"] == "app.worker.tasks.correlate_phd2_images"
    assert entry["eta"] == "2026-08-05T21:00:00+00:00"
    assert float(entry["queued_at"]) > 0
    assert r.ttl(JOB_ENTRY_PREFIX + tid) > 0
    assert r.sismember(JOBS_ACTIVE_SET, tid)


def test_record_running_upgrades_state_and_survives_missing_publish(r):
    tid = _tid()
    record_queued(r, tid, "recompute_session_dates")
    record_running(r, tid, "recompute_session_dates")
    entry = r.hgetall(JOB_ENTRY_PREFIX + tid)
    assert entry["state"] == "running"
    assert float(entry["started_at"]) > 0
    assert float(entry["queued_at"]) > 0  # publish-time field kept

    # No publish record at all (long countdown expired, or lost): prerun
    # alone must still produce a complete row.
    orphan = _tid()
    record_running(r, orphan, "app.worker.tasks.backfill_dark_hours")
    entry = r.hgetall(JOB_ENTRY_PREFIX + orphan)
    assert entry["name"] == "app.worker.tasks.backfill_dark_hours"
    assert entry["state"] == "running"
    assert r.sismember(JOBS_ACTIVE_SET, orphan)


def test_clear_entry_removes_hash_and_set_member(r):
    tid = _tid()
    record_queued(r, tid, "detect_mosaic_panels_task")
    clear_entry(r, tid)
    assert not r.exists(JOB_ENTRY_PREFIX + tid)
    assert not r.sismember(JOBS_ACTIVE_SET, tid)


def test_scan_and_rebuild_families_are_suppressed():
    # These are surfaced by the richer scan/rebuild status sources; the
    # registry must not double-report them, and ingest_file especially must
    # not write one Redis entry per scanned file.
    for name in (
        "app.worker.tasks.run_scan",
        "app.worker.tasks.ingest_file",
        "app.worker.tasks.scan_phd2_logs",
        "app.worker.tasks.rebuild_targets",
        "app.worker.tasks.smart_rebuild_targets",
    ):
        assert name in SUPPRESSED_TASKS
    assert "app.worker.tasks.correlate_phd2_images" not in SUPPRESSED_TASKS


@pytest.mark.asyncio
async def test_list_jobs_returns_running_before_queued(r):
    running = _tid()
    queued = _tid()
    record_queued(r, queued, "app.worker.tasks.correlate_phd2_images")
    record_running(r, running, "recompute_session_dates")

    app.dependency_overrides[require_admin] = lambda: None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/jobs")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    jobs = resp.json()["jobs"]
    assert [j["task_id"] for j in jobs] == [running, queued]
    assert jobs[0]["state"] == "running"
    assert jobs[1]["state"] == "queued"
    assert jobs[1]["queued_at"] is not None


@pytest.mark.asyncio
async def test_list_jobs_drops_orphaned_set_members(r):
    # A set member whose hash TTL-expired must be removed, not returned.
    stale = _tid()
    live = _tid()
    r.sadd(JOBS_ACTIVE_SET, stale)
    record_queued(r, live, "detect_filename_targets")

    app.dependency_overrides[require_admin] = lambda: None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/jobs")
    finally:
        app.dependency_overrides.clear()

    jobs = resp.json()["jobs"]
    assert [j["task_id"] for j in jobs] == [live]
    assert not r.sismember(JOBS_ACTIVE_SET, stale)


@pytest.mark.asyncio
async def test_list_jobs_requires_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/jobs")
    assert resp.status_code in (401, 403)
