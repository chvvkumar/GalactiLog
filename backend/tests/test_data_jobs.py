"""Tests for data-migration interruption/resume and data_jobs row semantics.

Exercises run_data_migrations / _pickup_data_migration_job /
_update_data_migration_job in app.worker.tasks against a real Postgres test
DB (job-row writes use their own session/commit, independent of the
migration-work transaction, so a mocked engine cannot observe the durability
guarantees under test). Mirrors the DB-integration pattern already used by
test_data_migrations.py (_sync_session_factory) and the real-module-reimport
pattern used by test_tasks.py (_bootstrap_tasks), but forces a REAL (not
MagicMock) engine so job rows actually persist.
"""
import os
import sys
import uuid
from unittest.mock import patch

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

os.environ.setdefault(
    "GALACTILOG_DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/test_catalog",
)


def _sync_session_factory():
    """Build a sync Session bound to the test DB, or skip if unreachable.

    Same pattern as test_data_migrations.py::_sync_session_factory.
    """
    url = os.environ["GALACTILOG_DATABASE_URL"].replace("+asyncpg", "+psycopg2")
    engine = create_engine(url, pool_pre_ping=True)
    try:
        conn = engine.connect()
        conn.close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"test DB not reachable: {exc}")
    return sessionmaker(bind=engine), engine


def _load_real_tasks_module():
    """Return app.worker.tasks bound to a REAL engine, importing it fresh at
    most once for this file.

    conftest.py installs a MagicMock at sys.modules["app.worker.tasks"] to
    avoid a sync DB connection at collection time, and other test files'
    bootstrap helpers (test_tasks.py, test_rebuild_robustness.py, etc.)
    replace that with a real module whose _sync_engine is itself a MagicMock
    (they never need a live DB - every test there patches tasks_mod.Session
    directly). Neither is usable here: _pickup_data_migration_job and
    _update_data_migration_job open real Session(_sync_engine) instances with
    their own commit, and this file's assertions depend on those commits
    actually landing in Postgres.

    Reimporting the module is not enough on its own: app.worker.celery_app
    is a process-wide singleton that is never reloaded, and Celery's
    Celery.task() decorator returns the ALREADY-registered Task object for a
    name it has seen before instead of rebinding it to the freshly defined
    function (celery/app/base.py::_task_from_fun: `if name not in
    self._tasks: create ... else: task = self._tasks[name]`). So if another
    test file already imported this module (even with a mocked engine), a
    naive reimport here would silently leave tasks_mod.run_data_migrations
    bound to that OTHER module's stale function/globals, and patching
    *this* module's attributes would have no effect. Deregister every task
    this module owns first so the decorator rebuilds all of them fresh. Some
    tasks in this module use a bare custom `name=` (e.g. "regenerate_missing_
    thumbnails", not "app.worker.tasks.regenerate_missing_thumbnails"), so
    matching by the registered Task's owning module - not by a name prefix -
    is required to catch every one of them.
    """
    from unittest.mock import MagicMock as _MM

    mod = sys.modules.get("app.worker.tasks")
    if mod is not None and not isinstance(mod, _MM) and not isinstance(getattr(mod, "_sync_engine", None), _MM):
        return mod  # already a real module bound to a real engine

    _deregister_tasks_module()

    sys.modules.pop("app.worker.tasks", None)
    import app.worker.tasks as tasks_mod
    return tasks_mod


def _deregister_tasks_module():
    """Undo _load_real_tasks_module's registration so later test files that
    expect the mocked-engine convention (see module docstring) rebuild their
    own fresh, mocked-engine module instead of inheriting this file's real
    one via the "already real, just reuse it" fast path their bootstrap
    helpers use."""
    from app.worker.celery_app import celery_app

    for name, task in list(celery_app.tasks.items()):
        if getattr(task, "__module__", None) == "app.worker.tasks":
            del celery_app.tasks[name]
    sys.modules.pop("app.worker.tasks", None)


@pytest.fixture(scope="module")
def _tasks_module():
    _sync_session_factory()  # skip early if DB unreachable
    mod = _load_real_tasks_module()
    yield mod
    _deregister_tasks_module()


@pytest.fixture
def tasks_mod(_tasks_module):
    # A previous test/run may have left the lock held (e.g. a crashed prior
    # run within TTL); clear it so each test starts from a clean slate.
    _tasks_module._redis.delete(_tasks_module.DATA_MIGRATION_LOCK)
    yield _tasks_module
    _tasks_module._redis.delete(_tasks_module.DATA_MIGRATION_LOCK)


@pytest.fixture
def db():
    Session, engine = _sync_session_factory()
    yield Session
    engine.dispose()


def _cleanup_job_and_metadata(Session, job_keys, metadata_keys=()):
    from app.models.data_job import DataJob
    from app.models.app_metadata import AppMetadata

    s = Session()
    try:
        for jk in job_keys:
            s.execute(
                text("DELETE FROM data_jobs WHERE job_type = 'data_migration' AND job_key = :jk"),
                {"jk": jk},
            )
        for mk in metadata_keys:
            s.execute(text("DELETE FROM app_metadata WHERE key = :k"), {"k": mk})
        s.commit()
    finally:
        s.close()


def _get_job_row(Session, job_key):
    from app.models.data_job import DataJob

    s = Session()
    try:
        return s.execute(
            text(
                "SELECT id, status, step, total_steps, attempt_count, last_error, "
                "started_at, finished_at, heartbeat_at, message FROM data_jobs "
                "WHERE job_type = 'data_migration' AND job_key = :jk"
            ),
            {"jk": job_key},
        ).mappings().first()
    finally:
        s.close()


def _get_data_version(Session):
    from app.services.data_migrations import get_current_data_version

    s = Session()
    try:
        return get_current_data_version(s)
    finally:
        s.close()


# ---------------------------------------------------------------------------
# 1 + 2: kill mid-run, then resume
# ---------------------------------------------------------------------------

class TestInterruptionAndResume:
    """Two fake pending versions; the second raises SoftTimeLimitExceeded on
    its first invocation and succeeds on a subsequent one, modelling a worker
    killed mid-backfill and a later restart resuming it."""

    BASE_VERSION = 90000
    V1 = 90001
    V2 = 90002
    JOB_KEY = str(V2)

    @pytest.fixture(autouse=True)
    def _cleanup(self, db):
        _cleanup_job_and_metadata(db, [self.JOB_KEY], ["data_version"])
        yield
        _cleanup_job_and_metadata(db, [self.JOB_KEY], ["data_version"])

    def _fake_migrations(self):
        """Return (migrations_dict, v2_call_count_list).

        v1 always succeeds. v2 raises SoftTimeLimitExceeded on the first call
        (simulating the worker being killed mid-migration) and succeeds on
        any later call (simulating a resumed run).
        """
        calls = {"v2": 0}

        def fn_v1(session):
            return "v1 summary"

        def fn_v2(session):
            calls["v2"] += 1
            if calls["v2"] == 1:
                raise SoftTimeLimitExceeded()
            return "v2 summary"

        migrations = {
            self.V1: ("fake migration v1", fn_v1),
            self.V2: ("fake migration v2", fn_v2),
        }
        return migrations, calls

    def _patched(self, migrations):
        return patch.multiple(
            "app.services.data_migrations",
            DATA_VERSION=self.V2,
            MIGRATIONS=migrations,
        )

    def test_kill_mid_run_leaves_interrupted_job_and_partial_version(self, tasks_mod, db):
        migrations, calls = self._fake_migrations()

        with self._patched(migrations):
            result = tasks_mod.run_data_migrations.run(from_version=self.BASE_VERSION)

        assert result["status"] == "timeout"
        assert result["version"] == self.V2
        assert calls["v2"] == 1

        row = _get_job_row(db, self.JOB_KEY)
        assert row is not None
        assert row["status"] == "interrupted"
        assert row["finished_at"] is None
        assert row["step"] == 1  # v1 completed, v2 did not
        assert row["total_steps"] == 2
        assert row["heartbeat_at"] is not None
        assert row["attempt_count"] == 1

        # Completion authority: only v1 was committed to app_metadata.
        assert _get_data_version(db) == self.V1

    def test_resume_after_kill_reuses_job_row_and_completes(self, tasks_mod, db):
        migrations, calls = self._fake_migrations()

        with self._patched(migrations):
            first = tasks_mod.run_data_migrations.run(from_version=self.BASE_VERSION)
        assert first["status"] == "timeout"

        row_after_kill = _get_job_row(db, self.JOB_KEY)
        original_id = row_after_kill["id"]
        original_started_at = row_after_kill["started_at"]

        # Real deployment reads app_metadata.data_version at boot to compute
        # from_version for the next dispatch.
        resumed_from = _get_data_version(db)
        assert resumed_from == self.V1

        with self._patched(migrations), \
                patch.object(tasks_mod.smart_rebuild_targets, "apply_async"), \
                patch.object(tasks_mod.detect_mosaic_panels_task, "apply_async"):
            second = tasks_mod.run_data_migrations.run(from_version=resumed_from)

        assert second["status"] == "complete"
        assert calls["v2"] == 2  # v1 was not re-run; only v2 (the remaining version) ran

        row_after_resume = _get_job_row(db, self.JOB_KEY)
        assert row_after_resume["id"] == original_id  # same row (job_type, job_key) reused
        assert row_after_resume["started_at"] == original_started_at  # preserved, not reset
        assert row_after_resume["attempt_count"] == 2  # incremented on the second pickup
        assert row_after_resume["status"] == "succeeded"
        # Only the remaining version (v2) ran on the resumed attempt, so its
        # total_steps/step reflect that single-version run, not the original 2.
        assert row_after_resume["total_steps"] == 1
        assert row_after_resume["step"] == 1
        assert row_after_resume["finished_at"] is not None

        assert _get_data_version(db) == self.V2


# ---------------------------------------------------------------------------
# 3: failure vs interruption
# ---------------------------------------------------------------------------

class TestFailureIsDistinctFromInterruption:
    BASE_VERSION = 90100
    V1 = 90101
    V2 = 90102
    JOB_KEY = str(V2)

    @pytest.fixture(autouse=True)
    def _cleanup(self, db):
        _cleanup_job_and_metadata(db, [self.JOB_KEY], ["data_version"])
        yield
        _cleanup_job_and_metadata(db, [self.JOB_KEY], ["data_version"])

    def test_plain_exception_marks_failed_not_interrupted(self, tasks_mod, db):
        def fn_v1(session):
            return "v1 summary"

        def fn_v2(session):
            raise ValueError("boom: bad migration data")

        migrations = {
            self.V1: ("fake migration v1", fn_v1),
            self.V2: ("fake migration v2 (fails)", fn_v2),
        }

        with patch.multiple(
            "app.services.data_migrations", DATA_VERSION=self.V2, MIGRATIONS=migrations,
        ):
            result = tasks_mod.run_data_migrations.run(from_version=self.BASE_VERSION)

        assert result["status"] == "error"
        assert result["version"] == self.V2

        row = _get_job_row(db, self.JOB_KEY)
        assert row is not None
        assert row["status"] == "failed"
        assert row["last_error"] is not None and "boom" in row["last_error"]
        assert row["finished_at"] is not None  # failure is terminal, unlike interruption

        # Version pointer stays at the last successfully committed version.
        assert _get_data_version(db) == self.V1


# ---------------------------------------------------------------------------
# 4a: dispatch INSERT ... ON CONFLICT DO NOTHING (backend/entrypoint.sh)
# ---------------------------------------------------------------------------

# entrypoint.sh registers the pending job row at boot, before enqueueing
# run_data_migrations, so the row is visible to the API/operators from the
# moment the upgrade is scheduled. It intentionally never writes status/
# started_at/attempt_count on conflict: those belong to the worker's pickup
# step, and an existing row (running/succeeded/failed/interrupted from a
# prior boot) must be left completely untouched by a later dispatch. This is
# the exact SQL entrypoint.sh executes.
_DISPATCH_INSERT_SQL = """
    INSERT INTO data_jobs (job_type, job_key, status)
    VALUES ('data_migration', :job_key, 'pending')
    ON CONFLICT (job_type, job_key) DO NOTHING
"""


class TestDispatchInsertDoesNotDisturbExistingRow:
    """A restart (or a duplicate boot-time dispatch) must not clobber a row a
    worker has already picked up or finished, since it carries no status/
    started_at/attempt_count of its own to merge in."""

    JOB_KEY = "90250"

    @pytest.fixture(autouse=True)
    def _cleanup(self, db):
        _cleanup_job_and_metadata(db, [self.JOB_KEY])
        yield
        _cleanup_job_and_metadata(db, [self.JOB_KEY])

    def test_dispatch_against_existing_running_row_is_a_no_op(self, tasks_mod, db):
        tasks_mod._pickup_data_migration_job(self.JOB_KEY, total_steps=3, message="picked up")
        before = _get_job_row(db, self.JOB_KEY)
        assert before["status"] == "running"
        assert before["attempt_count"] == 1
        assert before["started_at"] is not None

        s = db()
        try:
            s.execute(text(_DISPATCH_INSERT_SQL), {"job_key": self.JOB_KEY})
            s.commit()
        finally:
            s.close()

        after = _get_job_row(db, self.JOB_KEY)
        assert after["id"] == before["id"]  # no duplicate row inserted
        assert after["status"] == "running"  # NOT reset to 'pending'
        assert after["started_at"] == before["started_at"]
        assert after["attempt_count"] == before["attempt_count"]
        assert after["step"] == before["step"]

    def test_dispatch_against_no_existing_row_creates_pending_placeholder(self, tasks_mod, db):
        assert _get_job_row(db, self.JOB_KEY) is None

        s = db()
        try:
            s.execute(text(_DISPATCH_INSERT_SQL), {"job_key": self.JOB_KEY})
            s.commit()
        finally:
            s.close()

        row = _get_job_row(db, self.JOB_KEY)
        assert row is not None
        assert row["status"] == "pending"
        assert row["attempt_count"] == 0  # untouched until a worker picks it up


# ---------------------------------------------------------------------------
# 4b: pickup upsert semantics against an existing running row
# ---------------------------------------------------------------------------

class TestPickupUpsertSemantics:
    """_pickup_data_migration_job upserts on (job_type, job_key) via
    ON CONFLICT DO UPDATE. A second pickup against an already-running row
    (e.g. a resumed run after an interruption) must not reset started_at
    (so a resumed run keeps its original start time) while still recording
    the new attempt."""

    JOB_KEY = "90201"

    @pytest.fixture(autouse=True)
    def _cleanup(self, db):
        _cleanup_job_and_metadata(db, [self.JOB_KEY])
        yield
        _cleanup_job_and_metadata(db, [self.JOB_KEY])

    def test_second_pickup_preserves_started_at_and_increments_attempt(self, tasks_mod, db):
        tasks_mod._pickup_data_migration_job(self.JOB_KEY, total_steps=3, message="first pickup")
        first_row = _get_job_row(db, self.JOB_KEY)
        assert first_row["status"] == "running"
        assert first_row["attempt_count"] == 1
        assert first_row["started_at"] is not None

        # Advance step to simulate in-progress work, so we can confirm the
        # second pickup resets progress counters for the new attempt.
        s = db()
        try:
            s.execute(
                text("UPDATE data_jobs SET step = 2 WHERE job_type='data_migration' AND job_key=:jk"),
                {"jk": self.JOB_KEY},
            )
            s.commit()
        finally:
            s.close()

        tasks_mod._pickup_data_migration_job(self.JOB_KEY, total_steps=5, message="second pickup")
        second_row = _get_job_row(db, self.JOB_KEY)

        assert second_row["id"] == first_row["id"]  # unique (job_type, job_key) - no duplicate row
        assert second_row["status"] == "running"
        assert second_row["started_at"] == first_row["started_at"]  # NOT reset
        assert second_row["attempt_count"] == 2  # incremented, not left untouched
        assert second_row["step"] == 0  # progress reseeded for the new attempt
        assert second_row["total_steps"] == 5


# ---------------------------------------------------------------------------
# 5: job-row writes survive a rolled-back migration-work transaction
# ---------------------------------------------------------------------------

class TestJobRowIndependentOfWorkTransaction:
    BASE_VERSION = 90300
    V1 = 90301
    JOB_KEY = str(V1)
    MARKER_KEY = "test_rollback_marker_90301"

    @pytest.fixture(autouse=True)
    def _cleanup(self, db):
        _cleanup_job_and_metadata(db, [self.JOB_KEY], ["data_version", self.MARKER_KEY])
        yield
        _cleanup_job_and_metadata(db, [self.JOB_KEY], ["data_version", self.MARKER_KEY])

    def test_failed_migration_rolls_back_work_but_not_job_row(self, tasks_mod, db):
        from app.models.app_metadata import AppMetadata

        def fn_v1(session):
            # Uncommitted write in the migration-work session/transaction.
            session.add(AppMetadata(key=self.MARKER_KEY, value={"touched": True}))
            session.flush()
            raise RuntimeError("migration blew up after writing")

        migrations = {self.V1: ("fake migration that rolls back", fn_v1)}

        with patch.multiple(
            "app.services.data_migrations", DATA_VERSION=self.V1, MIGRATIONS=migrations,
        ):
            result = tasks_mod.run_data_migrations.run(from_version=self.BASE_VERSION)

        assert result["status"] == "error"

        # The migration-work session's write was rolled back...
        s = db()
        try:
            marker = s.execute(
                text("SELECT 1 FROM app_metadata WHERE key = :k"), {"k": self.MARKER_KEY}
            ).first()
        finally:
            s.close()
        assert marker is None, "uncommitted migration-work write must be rolled back"

        # ...but the job-row failure record, written in its own session/commit,
        # is durable and visible.
        row = _get_job_row(db, self.JOB_KEY)
        assert row is not None
        assert row["status"] == "failed"
        assert row["last_error"] is not None
        assert row["finished_at"] is not None


# ---------------------------------------------------------------------------
# 6: fresh-run happy path + percent derivation
# ---------------------------------------------------------------------------

class TestFreshRunHappyPath:
    BASE_VERSION = 90400
    V1 = 90401
    V2 = 90402
    JOB_KEY = str(V2)

    @pytest.fixture(autouse=True)
    def _cleanup(self, db):
        _cleanup_job_and_metadata(db, [self.JOB_KEY], ["data_version"])
        yield
        _cleanup_job_and_metadata(db, [self.JOB_KEY], ["data_version"])

    def test_pending_versions_run_in_order_with_incrementing_step(self, tasks_mod, db):
        order = []

        def fn_v1(session):
            order.append(self.V1)
            return "v1 summary"

        def fn_v2(session):
            order.append(self.V2)
            return "v2 summary"

        migrations = {
            self.V1: ("fake migration v1", fn_v1),
            self.V2: ("fake migration v2", fn_v2),
        }

        step_snapshots = []
        original_update = tasks_mod._update_data_migration_job

        def spy(job_key, **values):
            original_update(job_key, **values)
            if "step" in values:
                step_snapshots.append(values["step"])

        with patch.multiple(
            "app.services.data_migrations", DATA_VERSION=self.V2, MIGRATIONS=migrations,
        ), patch.object(tasks_mod, "_update_data_migration_job", side_effect=spy), \
                patch.object(tasks_mod.smart_rebuild_targets, "apply_async"), \
                patch.object(tasks_mod.detect_mosaic_panels_task, "apply_async"):
            result = tasks_mod.run_data_migrations.run(from_version=self.BASE_VERSION)

        assert result["status"] == "complete"
        assert order == [self.V1, self.V2]  # ran in ascending version order
        # One update per completed version (step=1, then step=2), plus the
        # final terminal "succeeded" update which re-stamps step=total_steps.
        assert step_snapshots == [1, 2, 2]

        row = _get_job_row(db, self.JOB_KEY)
        assert row["status"] == "succeeded"
        assert row["step"] == 2
        assert row["total_steps"] == 2
        assert row["finished_at"] is not None
        assert _get_data_version(db) == self.V2

    def test_percent_derivation_via_data_job_item(self):
        from app.schemas.data_job import DataJobItem

        base = dict(
            id=uuid.uuid4(), job_type="data_migration", job_key="x",
            attempt_count=1, enqueued_at=None,
        )

        # enqueued_at is required (non-optional datetime); use a real value.
        import datetime
        base["enqueued_at"] = datetime.datetime.now(datetime.timezone.utc)

        start = DataJobItem(status="running", step=0, total_steps=2, **base)
        mid = DataJobItem(status="running", step=1, total_steps=2, **base)
        done = DataJobItem(status="succeeded", step=2, total_steps=2, **base)
        no_total = DataJobItem(status="pending", step=None, total_steps=None, **base)

        assert start.percent == 0.0
        assert mid.percent == 50.0
        assert done.percent == 100.0
        assert no_total.percent is None


# ---------------------------------------------------------------------------
# 7: job-row bookkeeping failures must never affect migration outcomes
# ---------------------------------------------------------------------------

class TestBookkeepingFailuresDoNotAffectOutcome:
    """Job rows are observability only. A failed bookkeeping write must never
    block real migration work (pickup) or misreport succeeded work as failed
    (success-path progress update). Both helpers swallow-and-log their own
    errors, and the runner's success-path bookkeeping sits outside the
    migration try/except; these tests force real DB-level failures inside the
    helpers by breaking _data_migration_job_session, the only session source
    the job-row helpers use (the migration-work session and _activity_session
    are separate code paths and stay healthy)."""

    BASE_VERSION = 90500
    V1 = 90501
    V2 = 90502
    JOB_KEY = str(V2)

    @pytest.fixture(autouse=True)
    def _cleanup(self, db):
        _cleanup_job_and_metadata(db, [self.JOB_KEY], ["data_version"])
        yield
        _cleanup_job_and_metadata(db, [self.JOB_KEY], ["data_version"])

    def _migrations(self):
        order = []

        def fn_v1(session):
            order.append(self.V1)
            return "v1 summary"

        def fn_v2(session):
            order.append(self.V2)
            return "v2 summary"

        return {
            self.V1: ("fake migration v1", fn_v1),
            self.V2: ("fake migration v2", fn_v2),
        }, order

    def _patched(self, migrations):
        return patch.multiple(
            "app.services.data_migrations", DATA_VERSION=self.V2, MIGRATIONS=migrations,
        )

    def test_success_path_bookkeeping_failure_does_not_demote_run(self, tasks_mod, db):
        """Pickup succeeds, then every later job-row write hits a DB error.
        The run must still complete: both versions committed to app_metadata,
        no failed job status, and no data_upgrade_failed activity emitted for
        work that actually succeeded."""
        from unittest.mock import MagicMock

        migrations, order = self._migrations()

        real_session_factory = tasks_mod._data_migration_job_session
        call_count = {"n": 0}

        def flaky_job_session():
            call_count["n"] += 1
            if call_count["n"] > 1:  # first call = pickup; all later writes fail
                raise RuntimeError("bookkeeping DB unavailable")
            return real_session_factory()

        emit_spy = MagicMock()

        with self._patched(migrations), \
                patch.object(tasks_mod, "_data_migration_job_session", flaky_job_session), \
                patch.object(tasks_mod, "_emit_activity_sync", emit_spy), \
                patch.object(tasks_mod.smart_rebuild_targets, "apply_async"), \
                patch.object(tasks_mod.detect_mosaic_panels_task, "apply_async"):
            result = tasks_mod.run_data_migrations.run(from_version=self.BASE_VERSION)

        # The run itself completed, all versions ran in order, and the
        # version pointer (completion authority) advanced to the target.
        assert result["status"] == "complete"
        assert order == [self.V1, self.V2]
        assert _get_data_version(db) == self.V2
        assert call_count["n"] > 1  # the failing path was actually exercised

        # No failure was reported for succeeded work.
        emitted_types = [c.kwargs.get("event_type") for c in emit_spy.call_args_list]
        assert "data_upgrade_failed" not in emitted_types
        assert "data_upgrade_complete" in emitted_types

        # The job row (written by the successful pickup) was never marked
        # failed - the broken bookkeeping writes were dropped, not misapplied.
        row = _get_job_row(db, self.JOB_KEY)
        assert row is not None
        assert row["status"] == "running"  # stale, but never "failed"
        assert row["last_error"] is None

    def test_pickup_failure_does_not_block_migrations(self, tasks_mod, db):
        """If the pickup upsert itself raises, the run proceeds without any
        job-row tracking and still migrates to completion."""
        migrations, order = self._migrations()

        def broken_job_session():
            raise RuntimeError("data_jobs table unreachable")

        with self._patched(migrations), \
                patch.object(tasks_mod, "_data_migration_job_session", broken_job_session), \
                patch.object(tasks_mod.smart_rebuild_targets, "apply_async"), \
                patch.object(tasks_mod.detect_mosaic_panels_task, "apply_async"):
            result = tasks_mod.run_data_migrations.run(from_version=self.BASE_VERSION)

        assert result["status"] == "complete"
        assert order == [self.V1, self.V2]
        assert _get_data_version(db) == self.V2

        # No job row exists (pickup never landed) - and that must not have
        # mattered to the migration outcome.
        assert _get_job_row(db, self.JOB_KEY) is None
