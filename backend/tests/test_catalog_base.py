"""Tests for shared catalog-service helpers in catalog_base."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.services.catalog_base import (
    parse_float,
    parse_int,
    load_catalog_csv,
    find_target_by_ngc,
    match_ngc_catalog,
)


class TestParseFloat:
    def test_none(self):
        assert parse_float(None) is None

    def test_blank(self):
        assert parse_float("") is None
        assert parse_float("   ") is None

    def test_non_numeric(self):
        assert parse_float("abc") is None

    def test_valid(self):
        assert parse_float("3.14") == 3.14
        assert parse_float("  -2.5 ") == -2.5
        assert parse_float("10") == 10.0


class TestParseInt:
    def test_none(self):
        assert parse_int(None) is None

    def test_blank(self):
        assert parse_int("") is None
        assert parse_int("   ") is None

    def test_non_numeric(self):
        assert parse_int("abc") is None
        assert parse_int("3.14") is None  # int() rejects float strings

    def test_valid(self):
        assert parse_int("42") == 42
        assert parse_int("  -7 ") == -7


def _row_reader_session():
    """Return a MagicMock Session whose execute is callable and counts calls."""
    session = MagicMock()
    return session


class TestLoadCatalogCsv:
    def test_missing_file_returns_zero(self, tmp_path):
        session = MagicMock()
        logger = MagicMock()
        missing = tmp_path / "nope.csv"
        result = load_catalog_csv(
            session,
            csv_path=missing,
            model=MagicMock(),
            key_field="id",
            conflict_index="id",
            build_entry=lambda row: {"id": row["id"]},
            label="Test",
            logger=logger,
        )
        assert result == 0
        session.execute.assert_not_called()
        session.flush.assert_not_called()
        logger.error.assert_called_once()

    def test_loads_rows_and_skips_blank_keys(self, tmp_path, monkeypatch):
        csv_file = tmp_path / "cat.csv"
        csv_file.write_text(
            "id,name\nA,alpha\n,blank-key\nB,beta\n", encoding="utf-8"
        )
        session = MagicMock()
        logger = MagicMock()
        seen = []

        def build_entry(row):
            seen.append(row["id"])
            return {"id": row["id"], "name": row["name"]}

        # Avoid building a real pg_insert statement against a fake model.
        monkeypatch.setattr(
            "app.services.catalog_base.pg_insert", lambda model: MagicMock()
        )

        result = load_catalog_csv(
            session,
            csv_path=csv_file,
            model=MagicMock(),
            key_field="id",
            conflict_index="id",
            build_entry=build_entry,
            label="Test",
            logger=logger,
        )

        assert result == 2  # blank-key row skipped
        assert seen == ["A", "B"]
        assert session.execute.call_count == 2
        session.flush.assert_called_once()

    def test_build_entry_returning_none_skips_row(self, tmp_path, monkeypatch):
        csv_file = tmp_path / "cat.csv"
        csv_file.write_text("id\nA\nB\n", encoding="utf-8")
        session = MagicMock()
        logger = MagicMock()

        monkeypatch.setattr(
            "app.services.catalog_base.pg_insert", lambda model: MagicMock()
        )

        result = load_catalog_csv(
            session,
            csv_path=csv_file,
            model=MagicMock(),
            key_field="id",
            conflict_index="id",
            build_entry=lambda row: None if row["id"] == "A" else {"id": row["id"]},
            label="Test",
            logger=logger,
        )

        assert result == 1
        assert session.execute.call_count == 1


def _make_execute_returning(*result_objects):
    """Build a side_effect for session.execute returning queued result wrappers.

    Each positional arg is a callable producing the value for the next
    ``execute(...)`` result wrapper. The wrapper supports both
    ``.scalar_one_or_none()`` and ``.scalars().first()/.all()``.
    """
    queue = list(result_objects)

    def execute(_stmt):
        spec = queue.pop(0)
        return spec

    return execute


def _result(scalar_one=None, scalars_first=None, scalars_all=None):
    wrapper = MagicMock()
    wrapper.scalar_one_or_none.return_value = scalar_one
    scalars_obj = MagicMock()
    scalars_obj.first.return_value = scalars_first
    scalars_obj.all.return_value = scalars_all or []
    wrapper.scalars.return_value = scalars_obj
    return wrapper


class TestFindTargetByNgc:
    def test_found_by_catalog_id(self):
        session = MagicMock()
        target = MagicMock()
        session.execute.return_value = _result(scalar_one=target)
        assert find_target_by_ngc(session, "NGC 7000") is target
        # Only one query needed when catalog_id matches.
        assert session.execute.call_count == 1

    def test_found_by_alias(self):
        session = MagicMock()
        target = MagicMock()
        session.execute.side_effect = [
            _result(scalar_one=None),
            _result(scalars_first=target),
        ]
        assert find_target_by_ngc(session, "NGC 7000") is target
        assert session.execute.call_count == 2

    def test_not_found(self):
        session = MagicMock()
        session.execute.side_effect = [
            _result(scalar_one=None),
            _result(scalars_first=None),
        ]
        assert find_target_by_ngc(session, "NGC 7000") is None


class TestMatchNgcCatalog:
    @pytest.fixture(autouse=True)
    def _stub_select(self, monkeypatch):
        # match_ngc_catalog / find_target_by_ngc call select(model).where(...);
        # with a MagicMock model the real select() raises. The statement value
        # is irrelevant here since session.execute is mocked, so return a
        # chainable stub for both the bare and .where() forms.
        def fake_select(model):
            stmt = MagicMock()
            stmt.where.return_value = stmt
            return stmt

        monkeypatch.setattr(
            "app.services.catalog_base.select", fake_select
        )

    def test_matches_and_counts(self, monkeypatch):
        session = MagicMock()
        logger = MagicMock()

        entry1 = MagicMock()
        entry1.ngc_ic_id = "NGC0007"
        entry2 = MagicMock()
        entry2.ngc_ic_id = "NGC0008"

        target = MagicMock()
        target.id = 99

        # First execute: select(model).scalars().all() -> entries.
        # Then for each entry, find_target_by_ngc issues a catalog_id query.
        session.execute.side_effect = [
            _result(scalars_all=[entry1, entry2]),
            _result(scalar_one=target),   # entry1 catalog_id hit
            _result(scalar_one=target),   # entry2 catalog_id hit
        ]

        captured = []
        monkeypatch.setattr(
            "app.services.catalog_base.upsert_membership",
            lambda session, **kw: captured.append(kw),
        )

        result = match_ngc_catalog(
            session,
            model=MagicMock(),
            catalog_name="testcat",
            ngc_field="ngc_ic_id",
            get_catalog_number=lambda e: "NUM",
            build_metadata=lambda e: {"k": "v"},
            label="Test",
            logger=logger,
        )

        assert result == 2
        assert len(captured) == 2
        assert captured[0]["catalog_name"] == "testcat"
        assert captured[0]["catalog_number"] == "NUM"
        assert captured[0]["metadata"] == {"k": "v"}
        session.flush.assert_called_once()

    def test_require_ngc_skips_empty(self, monkeypatch):
        session = MagicMock()
        logger = MagicMock()

        entry = MagicMock()
        entry.ngc_ic_id = None

        session.execute.side_effect = [_result(scalars_all=[entry])]

        monkeypatch.setattr(
            "app.services.catalog_base.upsert_membership",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not match")),
        )

        result = match_ngc_catalog(
            session,
            model=MagicMock(),
            catalog_name="testcat",
            ngc_field="ngc_ic_id",
            get_catalog_number=lambda e: "NUM",
            build_metadata=lambda e: {},
            label="Test",
            logger=logger,
            require_ngc=True,
        )

        assert result == 0

    def test_require_ngc_false_still_matches_empty(self, monkeypatch):
        session = MagicMock()
        logger = MagicMock()

        entry = MagicMock()
        entry.ngc_id = ""  # falsy but require_ngc=False should still process

        target = MagicMock()
        target.id = 1
        session.execute.side_effect = [
            _result(scalars_all=[entry]),
            _result(scalar_one=target),
        ]

        captured = []
        monkeypatch.setattr(
            "app.services.catalog_base.upsert_membership",
            lambda session, **kw: captured.append(kw),
        )
        # normalize_ngc_name("") -> "" ; find_target_by_ngc will query.
        result = match_ngc_catalog(
            session,
            model=MagicMock(),
            catalog_name="h400",
            ngc_field="ngc_id",
            get_catalog_number=lambda e: "H400",
            build_metadata=lambda e: {},
            label="Test",
            logger=logger,
            require_ngc=False,
        )

        assert result == 1
        assert len(captured) == 1

    def test_no_target_no_match(self, monkeypatch):
        session = MagicMock()
        logger = MagicMock()

        entry = MagicMock()
        entry.ngc_ic_id = "NGC0007"

        session.execute.side_effect = [
            _result(scalars_all=[entry]),
            _result(scalar_one=None),     # catalog_id miss
            _result(scalars_first=None),  # alias miss
        ]

        monkeypatch.setattr(
            "app.services.catalog_base.upsert_membership",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not match")),
        )

        result = match_ngc_catalog(
            session,
            model=MagicMock(),
            catalog_name="testcat",
            ngc_field="ngc_ic_id",
            get_catalog_number=lambda e: "NUM",
            build_metadata=lambda e: {},
            label="Test",
            logger=logger,
        )

        assert result == 0
