"""Structural assertions for migration 0007 (catalog_id_normalized)."""
import importlib.util
from pathlib import Path

import pytest

_MIG = (
    Path(__file__).resolve().parent.parent
    / "alembic" / "versions" / "0007_targets_catalog_id_normalized.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("mig0007", _MIG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_file_exists():
    assert _MIG.exists()


def test_revision_chains_off_0006():
    mod = _load()
    assert mod.revision == "0007"
    assert mod.down_revision == "0006"


def test_has_upgrade_and_downgrade():
    mod = _load()
    assert callable(mod.upgrade)
    assert callable(mod.downgrade)


def test_uses_guarded_column_helper():
    src = _MIG.read_text(encoding="utf-8")
    assert "_column_exists" in src
    # Unique index must be guarded so re-running upgrade is safe.
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_targets_catalog_id_normalized" in src
    # Dedupe must run before the index is created.
    assert src.index("merged_into_id") < src.index("CREATE UNIQUE INDEX")
