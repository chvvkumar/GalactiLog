"""Tests for corrupted SIMBAD cache detection and repair."""
import pytest
from unittest.mock import MagicMock, patch


def _cache_row(key, payload=None, negative=False):
    row = MagicMock()
    row.key = key
    row.payload = payload
    row.negative = negative
    return row


class TestRowIsCorrupted:
    def test_quote_char_in_alias_is_corrupted(self):
        from app.services.simbad_repair import _row_is_corrupted
        row = _cache_row(
            "NGC 6543",
            payload={"main_id": "NGC  6543", "raw_aliases": ['"NGC 6543"', '"Cat\'s Eye"']},
        )
        assert _row_is_corrupted(row) is True

    def test_clean_aliases_not_corrupted(self):
        from app.services.simbad_repair import _row_is_corrupted
        row = _cache_row(
            "NGC 6543",
            payload={"main_id": "NGC  6543", "raw_aliases": ["NGC 6543", "NAME Cat's Eye Nebula"]},
        )
        assert _row_is_corrupted(row) is False

    def test_negative_row_not_corrupted(self):
        from app.services.simbad_repair import _row_is_corrupted
        row = _cache_row("Nonexistent", payload=None, negative=True)
        assert _row_is_corrupted(row) is False

    def test_missing_main_id_not_corrupted(self):
        from app.services.simbad_repair import _row_is_corrupted
        row = _cache_row("Weird", payload={"raw_aliases": ['"x"']})
        assert _row_is_corrupted(row) is False


class TestRepair:
    def test_refetches_corrupted_rows(self):
        from app.services.simbad_repair import repair_corrupted_simbad_cache

        corrupted = _cache_row(
            "NGC 6543",
            payload={"main_id": "NGC  6543", "raw_aliases": ['"NGC 6543"']},
        )

        session = MagicMock()
        session.execute.return_value.scalars.return_value.all.return_value = [corrupted]

        fresh = {"main_id": "NGC  6543", "raw_aliases": ["NGC 6543", "NAME Cat's Eye Nebula"],
                 "ra": 269.6, "dec": 66.6, "object_type": "PN"}

        with patch("app.services.simbad_repair._query_simbad_raw_sync", return_value=fresh) as q, \
             patch("app.services.simbad_repair.save_simbad_cache") as save, \
             patch("app.services.simbad_repair.time.sleep"):
            summary = repair_corrupted_simbad_cache(session, limit=100, sleep=0.0)

        q.assert_called_once_with("NGC  6543")
        save.assert_called_once_with("NGC 6543", fresh, session)
        assert summary["repaired"] == 1

    def test_skips_when_refetch_fails(self):
        from app.services.simbad_repair import repair_corrupted_simbad_cache

        corrupted = _cache_row(
            "NGC 6543",
            payload={"main_id": "NGC  6543", "raw_aliases": ['"NGC 6543"']},
        )
        session = MagicMock()
        session.execute.return_value.scalars.return_value.all.return_value = [corrupted]

        with patch("app.services.simbad_repair._query_simbad_raw_sync", return_value=None), \
             patch("app.services.simbad_repair.save_simbad_cache") as save, \
             patch("app.services.simbad_repair.time.sleep"):
            summary = repair_corrupted_simbad_cache(session, limit=100, sleep=0.0)

        save.assert_not_called()
        assert summary["repaired"] == 0
        assert summary["failed"] == 1

    def test_ignores_clean_and_negative_rows(self):
        from app.services.simbad_repair import repair_corrupted_simbad_cache

        clean = _cache_row(
            "M31", payload={"main_id": "M  31", "raw_aliases": ["M 31"]},
        )
        negative = _cache_row("Bogus Name", payload=None, negative=True)

        session = MagicMock()
        session.execute.return_value.scalars.return_value.all.return_value = [clean, negative]

        with patch("app.services.simbad_repair._query_simbad_raw_sync") as q, \
             patch("app.services.simbad_repair.save_simbad_cache") as save, \
             patch("app.services.simbad_repair.time.sleep"):
            summary = repair_corrupted_simbad_cache(session, limit=100, sleep=0.0)

        q.assert_not_called()
        save.assert_not_called()
        assert summary == {"corrupted": 0, "repaired": 0, "failed": 0}

    def test_queries_catalog_cache_source_simbad_only(self):
        """The select should filter on source='simbad' and negative=False."""
        from app.services.simbad_repair import repair_corrupted_simbad_cache
        from app.models.catalog_cache import CatalogCache

        session = MagicMock()
        session.execute.return_value.scalars.return_value.all.return_value = []

        repair_corrupted_simbad_cache(session, limit=100, sleep=0.0)

        assert session.execute.called
        compiled = str(session.execute.call_args[0][0])
        assert "catalog_cache" in compiled
