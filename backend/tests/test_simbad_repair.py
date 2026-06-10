"""Tests for corrupted SIMBAD cache detection and repair."""
import pytest
from unittest.mock import MagicMock, patch


class TestRowIsCorrupted:
    def test_quote_char_in_alias_is_corrupted(self):
        from app.services.simbad_repair import _row_is_corrupted
        row = MagicMock()
        row.main_id = "NGC  6543"
        row.raw_aliases = ['"NGC 6543"', '"Cat\'s Eye"']
        assert _row_is_corrupted(row) is True

    def test_clean_aliases_not_corrupted(self):
        from app.services.simbad_repair import _row_is_corrupted
        row = MagicMock()
        row.main_id = "NGC  6543"
        row.raw_aliases = ["NGC 6543", "NAME Cat's Eye Nebula"]
        assert _row_is_corrupted(row) is False

    def test_negative_row_not_corrupted(self):
        from app.services.simbad_repair import _row_is_corrupted
        row = MagicMock()
        row.main_id = None
        row.raw_aliases = []
        assert _row_is_corrupted(row) is False


class TestRepair:
    def test_refetches_corrupted_rows(self):
        from app.services.simbad_repair import repair_corrupted_simbad_cache

        corrupted = MagicMock()
        corrupted.query_name = "NGC 6543"
        corrupted.main_id = "NGC  6543"
        corrupted.raw_aliases = ['"NGC 6543"']

        session = MagicMock()
        session.execute.return_value.scalars.return_value.all.return_value = [corrupted]

        fresh = {"main_id": "NGC  6543", "raw_aliases": ["NGC 6543", "NAME Cat's Eye Nebula"],
                 "ra": 269.6, "dec": 66.6, "object_type": "PN"}

        with patch("app.services.simbad_repair._query_simbad_raw_sync", return_value=fresh) as q, \
             patch("app.services.simbad_repair.save_simbad_cache") as save, \
             patch("app.services.simbad_repair.time.sleep"):
            summary = repair_corrupted_simbad_cache(session, limit=100, sleep=0.0)

        q.assert_called_once_with("NGC  6543")
        save.assert_called_once()
        assert summary["repaired"] == 1

    def test_skips_when_refetch_fails(self):
        from app.services.simbad_repair import repair_corrupted_simbad_cache

        corrupted = MagicMock()
        corrupted.query_name = "NGC 6543"
        corrupted.main_id = "NGC  6543"
        corrupted.raw_aliases = ['"NGC 6543"']
        session = MagicMock()
        session.execute.return_value.scalars.return_value.all.return_value = [corrupted]

        with patch("app.services.simbad_repair._query_simbad_raw_sync", return_value=None), \
             patch("app.services.simbad_repair.save_simbad_cache") as save, \
             patch("app.services.simbad_repair.time.sleep"):
            summary = repair_corrupted_simbad_cache(session, limit=100, sleep=0.0)

        save.assert_not_called()
        assert summary["repaired"] == 0
        assert summary["failed"] == 1
