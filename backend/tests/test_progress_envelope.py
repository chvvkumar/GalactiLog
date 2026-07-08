"""Tests for the shared structured-progress envelope helper (Phase 3, Task 1
of docs/retrofit-roadmap.md).

Covers write/read round-trips for both existing Redis hashes the helper is
designed to layer onto (scan:state, rebuild:status), percent computation
including the total_steps == 0 edge case, and that writing an envelope
doesn't disturb the mechanism-specific fields already on that hash.
"""
import os
import sys
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("GALACTILOG_DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_catalog")
os.environ.setdefault("GALACTILOG_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("GALACTILOG_FITS_DATA_PATH", "/tmp/test_fits")
os.environ.setdefault("GALACTILOG_THUMBNAILS_PATH", "/tmp/test_thumbnails")
os.environ.setdefault("GALACTILOG_JWT_SECRET", "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2")
os.environ.setdefault("GALACTILOG_HTTPS", "false")
for _mod in ("fitsio",):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

from app.services.progress_envelope import get_progress, get_progress_sync, set_progress
from app.schemas.scan import ProgressEnvelope


# ---------------------------------------------------------------------------
# In-memory redis stubs (same shape as test_rebuild_robustness.py's)
# ---------------------------------------------------------------------------

class FakeSyncRedis:
    """Minimal synchronous redis supporting the hash/string ops used here."""

    def __init__(self):
        self.hashes: dict[str, dict] = {}
        self.strings: dict[str, str] = {}

    def hset(self, key, field=None, value=None, mapping=None):
        h = self.hashes.setdefault(key, {})
        if mapping:
            for k, v in mapping.items():
                h[k] = str(v)
        if field is not None:
            h[field] = str(value)

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def set(self, key, value, ex=None, nx=False):
        self.strings[key] = str(value)
        return True

    def get(self, key):
        return self.strings.get(key)

    def persist(self, key):
        pass

    def expire(self, key, ttl):
        pass


class FakeAsyncRedis:
    """Async redis stub over an underlying FakeSyncRedis store."""

    def __init__(self, sync: FakeSyncRedis):
        self._s = sync

    async def hgetall(self, key):
        return self._s.hgetall(key)


# ---------------------------------------------------------------------------
# set_progress / get_progress round-trips
# ---------------------------------------------------------------------------

class TestSetGetProgressRoundTrip:
    def test_round_trip_sync_reader(self):
        r = FakeSyncRedis()
        set_progress(r, "scan:state", task="scan", step=3, total_steps=10, message="Ingesting 3/10")
        env = get_progress_sync(r, "scan:state")
        assert env.task == "scan"
        assert env.step == 3
        assert env.total_steps == 10
        assert env.message == "Ingesting 3/10"
        assert env.percent == 30.0

    @pytest.mark.asyncio
    async def test_round_trip_async_reader(self):
        sync = FakeSyncRedis()
        set_progress(
            sync, "rebuild:status", task="rebuild", step=1, total_steps=4,
            message="Resolving 1/4 object names...",
        )
        r = FakeAsyncRedis(sync)
        env = await get_progress(r, "rebuild:status")
        assert env.task == "rebuild"
        assert env.percent == 25.0
        assert env.message == "Resolving 1/4 object names..."

    def test_percent_rounds_to_one_decimal(self):
        r = FakeSyncRedis()
        set_progress(r, "scan:state", task="scan", step=1, total_steps=3, message="1/3")
        env = get_progress_sync(r, "scan:state")
        assert env.percent == 33.3

    def test_total_steps_zero_yields_zero_percent_not_error(self):
        r = FakeSyncRedis()
        set_progress(r, "scan:state", task="scan", step=0, total_steps=0, message="starting")
        env = get_progress_sync(r, "scan:state")
        assert env.percent == 0.0

    def test_missing_hash_returns_empty_envelope_without_error(self):
        r = FakeSyncRedis()
        env = get_progress_sync(r, "scan:state")
        assert env.task == ""
        assert env.step == 0
        assert env.total_steps == 0
        assert env.percent == 0.0
        assert env.message == ""

    def test_does_not_disturb_unrelated_hash_fields(self):
        """set_progress layers onto an existing hash without clobbering the
        mechanism's own state fields (e.g. scan_state's completed/failed
        counters)."""
        r = FakeSyncRedis()
        r.hset("scan:state", mapping={"state": "ingesting", "completed": 2, "failed": 0, "total": 10})
        set_progress(r, "scan:state", task="scan", step=2, total_steps=10, message="2/10")
        h = r.hgetall("scan:state")
        assert h["state"] == "ingesting"
        assert h["completed"] == "2"
        assert h["failed"] == "0"
        assert h["total"] == "10"
        env = get_progress_sync(r, "scan:state")
        assert env.step == 2
        assert env.total_steps == 10

    def test_rebuild_message_field_shared_with_existing_rebuild_status(self):
        """On rebuild:status, the envelope's `message` field is the same
        field RebuildStatus.message already reads/writes -- no duplicate
        message storage for the same hash."""
        r = FakeSyncRedis()
        from app.services import scan_state
        scan_state.set_rebuild_running_sync(r, "full", "starting")
        set_progress(r, "rebuild:status", task="rebuild", step=2, total_steps=5, message="Resolving 2/5 object names...")
        rebuild = scan_state._parse_rebuild(r.hgetall("rebuild:status"))
        assert rebuild.message == "Resolving 2/5 object names..."


# ---------------------------------------------------------------------------
# ProgressEnvelope (schemas.scan) percent derivation
# ---------------------------------------------------------------------------

class TestProgressEnvelopeModel:
    def test_for_progress_computes_percent(self):
        env = ProgressEnvelope.for_progress(task="rebuild", step=5, total_steps=20, message="working")
        assert env.percent == 25.0

    def test_for_progress_zero_total_steps(self):
        env = ProgressEnvelope.for_progress(task="rebuild", step=0, total_steps=0, message="starting")
        assert env.percent == 0.0

    def test_for_progress_full_completion(self):
        env = ProgressEnvelope.for_progress(task="scan", step=10, total_steps=10, message="done")
        assert env.percent == 100.0
