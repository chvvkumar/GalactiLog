"""Tests for the data migrations module."""
import pytest

from app.services.data_migrations import (
    DATA_VERSION,
    MIGRATIONS,
    get_pending_migrations,
)


class TestGetPendingMigrations:
    def test_returns_all_when_at_zero(self):
        pending = get_pending_migrations(0)
        assert len(pending) == len(MIGRATIONS)
        assert pending[0][0] == 1  # first version

    def test_returns_none_when_current(self):
        pending = get_pending_migrations(DATA_VERSION)
        assert len(pending) == 0

    def test_returns_subset_when_partially_migrated(self):
        if DATA_VERSION < 2:
            pytest.skip("Only one migration exists")
        pending = get_pending_migrations(1)
        assert all(ver > 1 for ver, _, _ in pending)

    def test_migrations_are_sequential(self):
        versions = sorted(MIGRATIONS.keys())
        for i, ver in enumerate(versions):
            assert ver == i + 1, f"Migration versions must be sequential: gap at {ver}"

    def test_all_migrations_are_callable(self):
        for ver, (desc, func) in MIGRATIONS.items():
            assert callable(func), f"Migration v{ver} is not callable"
            assert isinstance(desc, str) and len(desc) > 0, f"Migration v{ver} has no description"

    def test_data_version_matches_latest_migration(self):
        assert DATA_VERSION == max(MIGRATIONS.keys()), \
            "DATA_VERSION must equal the highest migration version"
