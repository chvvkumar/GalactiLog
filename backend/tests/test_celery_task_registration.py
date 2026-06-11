"""Regression test: every task referenced by beat_schedule must be registered.

celery_app.autodiscover_tasks(["app.worker"]) only imports each package's
`tasks` module. Tasks defined in sibling modules (prune_activity, drain_logs)
are only registered if those modules are imported when the Celery app loads.
If they are not, beat dispatches the task by name and the worker rejects it with
"Received unregistered task of type ...", so the task never runs.
"""
from app.worker.celery_app import celery_app


def test_sibling_module_beat_tasks_are_registered():
    # These beat-scheduled tasks live in modules NOT named `tasks`, so
    # autodiscover_tasks(["app.worker"]) never imports them. celery_app must
    # import them explicitly, or beat dispatches the task by name and the worker
    # rejects it as "unregistered task". Importing celery_app alone must register
    # them. (auto_scan_tick lives in app.worker.tasks, which autodiscover imports
    # at worker boot; it is excluded here because importing tasks.py pulls in the
    # FITS stack, which is unavailable in the test environment.)
    registered = set(celery_app.tasks.keys())
    expected = {
        "app.worker.prune_activity.prune_activity_events",
        "app.worker.drain_logs.drain_app_logs",
    }
    missing = expected - registered
    assert not missing, f"Sibling-module beat tasks not registered: {sorted(missing)}"
