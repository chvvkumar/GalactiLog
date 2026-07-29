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


def test_phd2_scan_task_is_reexported_from_the_tasks_facade():
    """scan_phd2_logs lives in tasks_phd2.py, which autodiscover never imports.

    Celery's autodiscover_tasks(["app.worker"]) imports only app.worker.tasks,
    so a task defined in a sibling domain module is registered solely because
    the facade re-exports it. Without the re-export, run_scan would dispatch
    the task by name and the worker would reject it as unregistered.
    """
    import ast
    import pathlib

    facade = pathlib.Path(__file__).resolve().parents[1] / "app" / "worker" / "tasks.py"
    tree = ast.parse(facade.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "app.worker.tasks_phd2"
        for alias in node.names
    }
    assert "scan_phd2_logs" in imported
