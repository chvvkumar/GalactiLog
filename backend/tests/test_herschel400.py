"""Tests for the Herschel 400 catalog service public functions."""
from unittest.mock import MagicMock

import pytest

import app.services.herschel400 as herschel400


def _result(scalar_one=None, scalars_all=None):
    wrapper = MagicMock()
    wrapper.scalar_one_or_none.return_value = scalar_one
    scalars_obj = MagicMock()
    scalars_obj.all.return_value = scalars_all or []
    scalars_obj.first.return_value = None
    wrapper.scalars.return_value = scalars_obj
    return wrapper


def test_load_herschel400_csv_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(herschel400, "CSV_PATH", tmp_path / "missing.csv")
    session = MagicMock()
    assert herschel400.load_herschel400_csv(session) == 0
    session.execute.assert_not_called()


def test_load_herschel400_csv_parses_magnitude(monkeypatch, tmp_path):
    csv_file = tmp_path / "h400.csv"
    csv_file.write_text(
        "ngc_id,object_type,constellation,magnitude\n"
        "NGC0040,PN,Cep,11.4\n"
        "NGC0129,OCl,Cas,\n"
        ",,,9.0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(herschel400, "CSV_PATH", csv_file)

    captured_values = []

    def fake_pg_insert(model):
        stmt = MagicMock()

        def values(**kw):
            captured_values.append(kw)
            return MagicMock()

        stmt.values.side_effect = values
        return stmt

    monkeypatch.setattr("app.services.catalog_base.pg_insert", fake_pg_insert)
    session = MagicMock()

    assert herschel400.load_herschel400_csv(session) == 2  # blank ngc_id skipped
    assert captured_values[0]["magnitude"] == 11.4
    assert captured_values[1]["magnitude"] is None  # blank -> None


def test_match_herschel400_matches_with_metadata(monkeypatch):
    entry = MagicMock()
    entry.ngc_id = "NGC 40"
    entry.object_type = "PN"
    entry.constellation = "Cep"
    entry.magnitude = 11.4

    target = MagicMock()
    target.id = 3

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

    assert herschel400.match_herschel400_targets(session) == 1
    assert captured[0]["catalog_name"] == "herschel400"
    assert captured[0]["catalog_number"] == "H400"
    assert captured[0]["metadata"] == {
        "constellation": "Cep",
        "type": "PN",
        "magnitude": 11.4,
    }
