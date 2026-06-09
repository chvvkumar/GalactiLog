"""Tests for the Caldwell catalog service public functions."""
from unittest.mock import MagicMock

import pytest

import app.services.caldwell as caldwell


def _result(scalar_one=None, scalars_all=None):
    wrapper = MagicMock()
    wrapper.scalar_one_or_none.return_value = scalar_one
    scalars_obj = MagicMock()
    scalars_obj.all.return_value = scalars_all or []
    scalars_obj.first.return_value = None
    wrapper.scalars.return_value = scalars_obj
    return wrapper


def test_load_caldwell_csv_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(caldwell, "CSV_PATH", tmp_path / "missing.csv")
    session = MagicMock()
    assert caldwell.load_caldwell_csv(session) == 0
    session.execute.assert_not_called()


def test_load_caldwell_csv_parses_rows(monkeypatch, tmp_path):
    csv_file = tmp_path / "caldwell.csv"
    csv_file.write_text(
        "catalog_id,ngc_ic_id,object_type,constellation,common_name\n"
        "C14,NGC0869,OCl,Per,Double Cluster\n"
        ",NGC1234,,,blank id skipped\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(caldwell, "CSV_PATH", csv_file)
    monkeypatch.setattr(
        "app.services.catalog_base.pg_insert", lambda model: MagicMock()
    )
    session = MagicMock()
    assert caldwell.load_caldwell_csv(session) == 1
    session.flush.assert_called_once()


def test_match_caldwell_targets_builds_metadata(monkeypatch):
    entry = MagicMock()
    entry.catalog_id = "C14"
    entry.ngc_ic_id = "NGC 869"

    target = MagicMock()
    target.id = 7

    session = MagicMock()
    session.execute.side_effect = [
        _result(scalars_all=[entry]),
        _result(scalar_one=target),
    ]

    captured = []
    monkeypatch.setattr(
        "app.services.catalog_base.upsert_membership",
        lambda session, **kw: captured.append(kw),
    )

    assert caldwell.match_caldwell_targets(session) == 1
    assert captured[0]["catalog_name"] == "caldwell"
    assert captured[0]["catalog_number"] == "C14"
    assert captured[0]["metadata"] == {"caldwell_number": 14, "ngc_ic": "NGC 869"}


def test_match_caldwell_skips_entries_without_ngc(monkeypatch):
    entry = MagicMock()
    entry.catalog_id = "C99"
    entry.ngc_ic_id = None

    session = MagicMock()
    session.execute.side_effect = [_result(scalars_all=[entry])]
    monkeypatch.setattr(
        "app.services.catalog_base.upsert_membership",
        lambda *a, **k: pytest.fail("should not match entry without ngc_ic_id"),
    )

    assert caldwell.match_caldwell_targets(session) == 0
