"""Robustness of rebuild/reference-thumbnail status and data migrations.

Covers AUD-003 (rebuild status can stick on "running" forever; killed thumbnail
run must persist partial progress and resume; /reset must clear REBUILD_KEY) and
AUD-035 (startup data migration must make durable forward progress and survive a
SoftTimeLimitExceeded instead of rolling the whole version back every boot).
"""
import os
import sys
import time
from unittest.mock import MagicMock, patch

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


def _bootstrap_tasks():
    """Import app.worker.tasks with the sync engine mocked (no DB needed)."""
    mod = sys.modules.get("app.worker.tasks")
    if mod is not None and not isinstance(mod, MagicMock):
        return mod
    sys.modules.pop("app.worker.tasks", None)
    with patch("sqlalchemy.create_engine", return_value=MagicMock()):
        import app.worker.tasks as tasks_mod
    return tasks_mod


# ---------------------------------------------------------------------------
# In-memory redis stubs
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
        if nx and key in self.strings:
            return None
        self.strings[key] = str(value)
        return True

    def get(self, key):
        return self.strings.get(key)

    def persist(self, key):
        pass

    def expire(self, key, ttl):
        pass

    def delete(self, *keys):
        for key in keys:
            self.hashes.pop(key, None)
            self.strings.pop(key, None)

    def exists(self, key):
        return 1 if (key in self.hashes or key in self.strings) else 0


class FakeAsyncRedis:
    """Async redis stub over an underlying FakeSyncRedis store."""

    def __init__(self, sync: FakeSyncRedis | None = None):
        self._s = sync or FakeSyncRedis()

    async def hgetall(self, key):
        return self._s.hgetall(key)

    async def get(self, key):
        return self._s.get(key)

    async def exists(self, key):
        return self._s.exists(key)

    async def delete(self, *keys):
        self._s.delete(*keys)


# ---------------------------------------------------------------------------
# AUD-003: rebuild stale detection + progress heartbeat + /reset
# ---------------------------------------------------------------------------

class TestRebuildStaleDetection:
    @pytest.mark.asyncio
    async def test_running_with_recent_progress_stays_running(self):
        from app.services import scan_state
        sync = FakeSyncRedis()
        scan_state.set_rebuild_running_sync(sync, "ref_thumbnails", "working")
        r = FakeAsyncRedis(sync)
        snap = await scan_state.get_rebuild_state(r)
        assert snap.state == "running"

    @pytest.mark.asyncio
    async def test_running_with_stale_progress_flips_to_stalled(self):
        from app.services import scan_state
        sync = FakeSyncRedis()
        scan_state.set_rebuild_running_sync(sync, "ref_thumbnails", "working")
        # Backdate the progress heartbeat past the stale window.
        sync.strings[scan_state.REBUILD_PROGRESS_KEY] = str(
            time.time() - scan_state.REBUILD_STALE_TIMEOUT - 10
        )
        r = FakeAsyncRedis(sync)
        snap = await scan_state.get_rebuild_state(r)
        assert snap.state == "stalled"

    @pytest.mark.asyncio
    async def test_stale_falls_back_to_started_at_when_no_progress_key(self):
        from app.services import scan_state
        sync = FakeSyncRedis()
        scan_state.set_rebuild_running_sync(sync, "full", "working")
        sync.delete(scan_state.REBUILD_PROGRESS_KEY)
        sync.hashes[scan_state.REBUILD_KEY]["started_at"] = str(
            time.time() - scan_state.REBUILD_STALE_TIMEOUT - 10
        )
        r = FakeAsyncRedis(sync)
        snap = await scan_state.get_rebuild_state(r)
        assert snap.state == "stalled"

    @pytest.mark.asyncio
    async def test_complete_state_never_marked_stalled(self):
        from app.services import scan_state
        sync = FakeSyncRedis()
        scan_state.set_rebuild_complete_sync(sync, "done", {"fetched": 5})
        r = FakeAsyncRedis(sync)
        snap = await scan_state.get_rebuild_state(r)
        assert snap.state == "complete"

    def test_running_writes_progress_heartbeat(self):
        from app.services import scan_state
        sync = FakeSyncRedis()
        scan_state.set_rebuild_running_sync(sync, "full", "start")
        assert scan_state.REBUILD_PROGRESS_KEY in sync.strings

    def test_progress_write_bumps_heartbeat(self):
        from app.services import scan_state
        sync = FakeSyncRedis()
        scan_state.set_rebuild_running_sync(sync, "full", "start")
        sync.strings[scan_state.REBUILD_PROGRESS_KEY] = "1.0"
        scan_state.set_rebuild_progress_sync(sync, "1/10")
        assert float(sync.strings[scan_state.REBUILD_PROGRESS_KEY]) > 1.0

    def test_complete_clears_progress_heartbeat(self):
        from app.services import scan_state
        sync = FakeSyncRedis()
        scan_state.set_rebuild_running_sync(sync, "full", "start")
        scan_state.set_rebuild_complete_sync(sync, "done", {})
        assert scan_state.REBUILD_PROGRESS_KEY not in sync.strings


class TestResetClearsRebuild:
    @pytest.mark.asyncio
    async def test_reset_scan_clears_rebuild_keys(self):
        from app.services import scan_state
        sync = FakeSyncRedis()
        scan_state.set_rebuild_running_sync(sync, "full", "stuck")
        assert scan_state.REBUILD_KEY in sync.hashes
        r = FakeAsyncRedis(sync)
        await scan_state.reset_scan(r)
        assert scan_state.REBUILD_KEY not in sync.hashes
        assert scan_state.REBUILD_PROGRESS_KEY not in sync.strings


# ---------------------------------------------------------------------------
# AUD-003 + AUD-035: task time-limit exemptions
# ---------------------------------------------------------------------------

class TestTaskTimeLimits:
    def test_maintenance_tasks_have_generous_limits(self):
        from app.worker.celery_app import celery_app
        ann = celery_app.conf.task_annotations
        for name in (
            "app.worker.tasks.generate_reference_thumbnails",
            "app.worker.tasks.rebuild_targets",
            "app.worker.tasks.retry_unresolved",
            "app.worker.tasks.run_data_migrations",
            "app.worker.tasks.backfill_dark_hours",
        ):
            assert name in ann, f"{name} missing a task_annotations override"
            # Must be well above the global 660s hard limit.
            assert ann[name]["time_limit"] > 660


# ---------------------------------------------------------------------------
# AUD-003: killed thumbnail run persists partial progress + terminal state
# ---------------------------------------------------------------------------

def _thumbnail_targets(n):
    targets = []
    for i in range(n):
        t = MagicMock()
        t.reference_thumbnail_path = None
        targets.append(t)
    return targets


def _run_thumbnails(tasks, targets, fetch):
    session = MagicMock()
    session.execute.return_value.scalars.return_value.all.return_value = targets
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=session)
    cm.__exit__ = MagicMock(return_value=False)
    captured = {}

    def _capture_complete(r, message, details):
        captured["message"] = message
        captured["details"] = details

    with patch.object(tasks, "Session", return_value=cm), \
         patch("app.services.skyview.fetch_reference_thumbnail", side_effect=fetch), \
         patch.object(tasks, "clear_cancel_sync"), \
         patch.object(tasks, "set_rebuild_running_sync"), \
         patch.object(tasks, "set_rebuild_progress_sync"), \
         patch.object(tasks, "set_rebuild_complete_sync", side_effect=_capture_complete), \
         patch.object(tasks, "set_rebuild_cancelled_sync"), \
         patch.object(tasks, "is_cancel_requested_sync", return_value=False), \
         patch.object(tasks, "_invalidate_stats_cache"), \
         patch.object(tasks, "_activity_session"), \
         patch.object(tasks, "_emit_activity_sync"), \
         patch("time.sleep"):
        result = tasks.generate_reference_thumbnails.run()
    return result, session, captured


class TestThumbnailPartialProgress:
    def test_commits_in_chunks(self):
        tasks = _bootstrap_tasks()
        targets = _thumbnail_targets(25)
        result, session, captured = _run_thumbnails(
            tasks, targets, fetch=lambda t, d: "thumb.png"
        )
        # 25 targets, chunk of 10 -> commits at 10 and 20, plus the final
        # commit after the loop => at least 3 commits, not a single end commit.
        assert session.commit.call_count >= 3
        assert result["fetched"] == 25
        assert result["timed_out"] is False

    def test_soft_time_limit_leaves_terminal_state_and_partial_progress(self):
        tasks = _bootstrap_tasks()
        targets = _thumbnail_targets(25)
        calls = {"n": 0}

        def fetch(target, output_dir):
            calls["n"] += 1
            if calls["n"] == 12:
                raise tasks.SoftTimeLimitExceeded()
            return "thumb.png"

        result, session, captured = _run_thumbnails(tasks, targets, fetch=fetch)
        # Terminal "complete" state written (never left at "running").
        assert result["timed_out"] is True
        assert "paused" in captured["message"].lower()
        # The chunk commit at target 10 persisted partial work before the kill.
        assert session.commit.called
        assert result["fetched"] == 11

    def test_resume_query_skips_targets_with_thumbnails(self):
        """Non-force runs only select targets whose thumbnail path is NULL, so a
        re-run after a partial kill continues instead of starting over."""
        tasks = _bootstrap_tasks()
        targets = _thumbnail_targets(3)
        _run_thumbnails(tasks, targets, fetch=lambda t, d: "thumb.png")
        # Every fetched target got its path recorded, so the next run's
        # reference_thumbnail_path IS NULL filter excludes them.
        assert all(t.reference_thumbnail_path == "thumb.png" for t in targets)


# ---------------------------------------------------------------------------
# AUD-003: rebuild_targets / retry_unresolved land in a terminal state on timeout
# ---------------------------------------------------------------------------

def _run_rebuild_family(tasks, task, object_names, resolve_side_effect):
    session = MagicMock()
    session.execute.return_value.all.return_value = object_names
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=session)
    cm.__exit__ = MagicMock(return_value=False)
    captured = {}

    def _capture_complete(r, message, details):
        captured["message"] = message
        captured["details"] = details

    with patch.object(tasks, "Session", return_value=cm), \
         patch.object(tasks, "resolve_target", side_effect=resolve_side_effect), \
         patch.object(tasks, "clear_cancel_sync"), \
         patch.object(tasks, "set_rebuild_running_sync"), \
         patch.object(tasks, "set_rebuild_progress_sync"), \
         patch.object(tasks, "set_rebuild_complete_sync", side_effect=_capture_complete), \
         patch.object(tasks, "set_rebuild_cancelled_sync"), \
         patch.object(tasks, "is_cancel_requested_sync", return_value=False), \
         patch.object(tasks, "_activity_session"), \
         patch.object(tasks, "_emit_activity_sync"), \
         patch.object(tasks, "_redis", MagicMock()), \
         patch("time.sleep"):
        result = task.run()
    return result, captured


class TestRebuildFamilyTimeout:
    def test_rebuild_targets_timeout_sets_complete(self):
        tasks = _bootstrap_tasks()

        def resolve(*a, **k):
            raise tasks.SoftTimeLimitExceeded()

        result, captured = _run_rebuild_family(
            tasks, tasks.rebuild_targets, [("M31", 10), ("M42", 5)], resolve
        )
        assert result["status"] == "timeout"
        assert "paused" in captured["message"].lower()

    def test_retry_unresolved_timeout_sets_complete(self):
        tasks = _bootstrap_tasks()

        def resolve(*a, **k):
            raise tasks.SoftTimeLimitExceeded()

        result, captured = _run_rebuild_family(
            tasks, tasks.retry_unresolved, [("M31", 10)], resolve
        )
        assert result["status"] == "timeout"
        assert "paused" in captured["message"].lower()


# ---------------------------------------------------------------------------
# AUD-035: run_data_migrations survives SoftTimeLimitExceeded with durable state
# ---------------------------------------------------------------------------

def _run_migrations(tasks, pending):
    import app.services.data_migrations as dm
    session = MagicMock()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=session)
    cm.__exit__ = MagicMock(return_value=False)
    events = []

    def _emit(*a, **k):
        events.append(k.get("event_type"))

    fake_redis = MagicMock()
    fake_redis.set.return_value = True

    with patch.object(tasks, "Session", return_value=cm), \
         patch.object(tasks, "_redis", fake_redis), \
         patch.object(tasks, "_activity_session"), \
         patch.object(tasks, "_emit_activity_sync", side_effect=_emit), \
         patch.object(dm, "get_pending_migrations", return_value=pending), \
         patch.object(dm, "set_data_version") as set_ver, \
         patch.object(tasks.smart_rebuild_targets, "apply_async"), \
         patch.object(tasks.detect_mosaic_panels_task, "apply_async"):
        result = tasks.run_data_migrations.run(0)
    return result, session, set_ver, events


class TestDataMigrationTimeout:
    def test_soft_time_limit_pauses_without_stamping_version(self):
        tasks = _bootstrap_tasks()

        def timeout_migration(session):
            raise tasks.SoftTimeLimitExceeded()

        pending = [(11, "HyperLEDA galaxies", timeout_migration)]
        result, session, set_ver, events = _run_migrations(tasks, pending)

        assert result["status"] == "timeout"
        assert result["version"] == 11
        # Rolled back the uncommitted tail gracefully.
        session.rollback.assert_called()
        # Version NOT stamped for the timed-out migration.
        set_ver.assert_not_called()
        # A terminal activity event is always written (never a silent loop).
        assert "data_upgrade_paused" in events

    def test_prior_committed_migration_persists_before_timeout(self):
        tasks = _bootstrap_tasks()

        def ok_migration(session):
            return "ok"

        def timeout_migration(session):
            raise tasks.SoftTimeLimitExceeded()

        pending = [
            (10, "Messier fix", ok_migration),
            (11, "HyperLEDA galaxies", timeout_migration),
        ]
        result, session, set_ver, events = _run_migrations(tasks, pending)

        assert result["status"] == "timeout"
        assert result["version"] == 11
        # v10 was stamped + committed before v11 timed out; v11 was not stamped.
        set_ver.assert_called_once()
        assert set_ver.call_args.args[1] == 10


# ---------------------------------------------------------------------------
# Soft-limit signal must propagate through broad except clauses (defense in depth)
# ---------------------------------------------------------------------------

class TestSoftLimitPropagation:
    def test_v11_hyperleda_loop_reraises_soft_limit(self):
        """A SoftTimeLimitExceeded landing inside the HyperLEDA enricher must
        propagate out of the v11 migration loop, not be swallowed by its broad
        except, so the runner writes the data_upgrade_paused event."""
        from celery.exceptions import SoftTimeLimitExceeded
        import app.services.data_migrations as dm

        target = MagicMock()
        target.object_type = "G"
        target.catalog_id = "NGC 1234"
        session = MagicMock()
        session.execute.return_value.scalars.return_value.all.return_value = [target]

        with patch("app.services.hyperleda.enrich_target_from_hyperleda",
                   side_effect=SoftTimeLimitExceeded()), \
             patch("app.services.hyperleda.get_cached_hyperleda", return_value=None), \
             patch("app.services.hyperleda._is_galaxy_type", return_value=True), \
             patch("time.sleep"):
            with pytest.raises(SoftTimeLimitExceeded):
                dm._migrate_v11_hyperleda_galaxies(session)

    def test_v11_paused_event_reaches_runner(self):
        """End to end through the runner: soft limit inside the v11 enricher
        still produces the terminal data_upgrade_paused activity event."""
        from celery.exceptions import SoftTimeLimitExceeded
        import app.services.data_migrations as dm
        tasks = _bootstrap_tasks()

        target = MagicMock()
        target.object_type = "G"
        target.catalog_id = "NGC 1234"

        def v11(session):
            session.execute.return_value.scalars.return_value.all.return_value = [target]
            with patch("app.services.hyperleda.enrich_target_from_hyperleda",
                       side_effect=SoftTimeLimitExceeded()), \
                 patch("app.services.hyperleda.get_cached_hyperleda", return_value=None), \
                 patch("app.services.hyperleda._is_galaxy_type", return_value=True), \
                 patch("time.sleep"):
                return dm._migrate_v11_hyperleda_galaxies(session)

        pending = [(11, "HyperLEDA galaxies", v11)]
        result, session, set_ver, events = _run_migrations(tasks, pending)
        assert result["status"] == "timeout"
        assert "data_upgrade_paused" in events
        set_ver.assert_not_called()

    def test_fetch_reference_thumbnail_reraises_soft_limit(self):
        """skyview.fetch_reference_thumbnail must not swallow the soft-limit
        signal as a fetch failure; generate_reference_thumbnails needs it to
        write its terminal state."""
        import httpx
        from celery.exceptions import SoftTimeLimitExceeded
        from app.services.skyview import fetch_reference_thumbnail

        target = MagicMock()
        target.ra = 10.0
        target.dec = 41.0
        target.size_major = None

        with patch.object(httpx, "Client", side_effect=SoftTimeLimitExceeded()):
            with pytest.raises(SoftTimeLimitExceeded):
                fetch_reference_thumbnail(target, "/tmp/test_thumbnails/reference")

    def test_fetch_reference_thumbnail_still_swallows_http_errors(self):
        import httpx
        from app.services.skyview import fetch_reference_thumbnail

        target = MagicMock()
        target.ra = 10.0
        target.dec = 41.0
        target.size_major = None

        with patch.object(httpx, "Client", side_effect=httpx.ConnectError("boom")):
            assert fetch_reference_thumbnail(target, "/tmp/test_thumbnails/reference") is None
