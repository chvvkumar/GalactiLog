"""Tests that backfill_catalog_identity reuses the shared matcher and links."""
import sys
import pytest
from unittest.mock import MagicMock, patch


def _bootstrap_tasks():
    mod = sys.modules.get("app.worker.tasks")
    if mod is not None and not isinstance(mod, MagicMock):
        return mod
    sys.modules.pop("app.worker.tasks", None)
    with patch("sqlalchemy.create_engine", return_value=MagicMock()):
        import app.worker.tasks as tasks_mod
    return tasks_mod


class TestBackfillCatalogIdentity:
    def test_task_is_registered(self):
        tasks = _bootstrap_tasks()
        assert hasattr(tasks, "backfill_catalog_identity")

    def test_runs_cache_repair_then_links_matches(self):
        tasks = _bootstrap_tasks()

        existing = MagicMock()
        existing.id = "cats-eye"
        resolved = {"catalog_id": "NGC 6543", "primary_name": "NGC 6543", "aliases": []}

        with patch.object(tasks, "repair_corrupted_simbad_cache",
                          return_value={"corrupted": 1, "repaired": 1, "failed": 0}) as repair, \
             patch.object(tasks, "Session") as Session, \
             patch.object(tasks, "resolve_target_name_cached", return_value=resolved), \
             patch.object(tasks, "match_target_by_identity", return_value=existing), \
             patch.object(tasks, "set_rebuild_running_sync"), \
             patch.object(tasks, "set_rebuild_progress_sync"), \
             patch.object(tasks, "set_rebuild_complete_sync"), \
             patch.object(tasks, "is_cancel_requested_sync", return_value=False), \
             patch.object(tasks, "clear_cancel_sync"), \
             patch("time.sleep"):
            db = Session.return_value.__enter__.return_value
            # One distinct unlinked OBJECT name with 196 images.
            db.execute.return_value.all.return_value = [("NGC 6543", 196)]
            result = tasks.backfill_catalog_identity.run()

        repair.assert_called_once()
        assert result["linked"] == 1

    def test_leaves_unresolvable_orphaned(self):
        tasks = _bootstrap_tasks()
        with patch.object(tasks, "repair_corrupted_simbad_cache",
                          return_value={"corrupted": 0, "repaired": 0, "failed": 0}), \
             patch.object(tasks, "Session") as Session, \
             patch.object(tasks, "resolve_target_name_cached", return_value=None), \
             patch.object(tasks, "match_target_by_identity", return_value=None), \
             patch.object(tasks, "set_rebuild_running_sync"), \
             patch.object(tasks, "set_rebuild_progress_sync"), \
             patch.object(tasks, "set_rebuild_complete_sync"), \
             patch.object(tasks, "is_cancel_requested_sync", return_value=False), \
             patch.object(tasks, "clear_cancel_sync"), \
             patch("time.sleep"):
            db = Session.return_value.__enter__.return_value
            db.execute.return_value.all.return_value = [("Comet 12P", 4)]
            result = tasks.backfill_catalog_identity.run()
        assert result["linked"] == 0
        assert result["skipped"] == 1
