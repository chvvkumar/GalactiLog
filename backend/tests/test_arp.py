"""Tests for the Arp catalog service public functions."""
from unittest.mock import MagicMock

import pytest

import app.services.arp as arp


def _result(scalar_one=None, scalars_all=None, scalars_first=None):
    wrapper = MagicMock()
    wrapper.scalar_one_or_none.return_value = scalar_one
    scalars_obj = MagicMock()
    scalars_obj.all.return_value = scalars_all or []
    scalars_obj.first.return_value = scalars_first
    wrapper.scalars.return_value = scalars_obj
    return wrapper


def test_load_arp_csv_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(arp, "CSV_PATH", tmp_path / "missing.csv")
    session = MagicMock()
    assert arp.load_arp_csv(session) == 0
    session.execute.assert_not_called()


def test_load_arp_csv_parses_rows(monkeypatch, tmp_path):
    csv_file = tmp_path / "arp.csv"
    csv_file.write_text(
        "arp_id,ngc_ic_ids,peculiarity_class,peculiarity_description\n"
        "Arp 1,NGC2857,Spiral,desc\n"
        ",NGC0001,,skip\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(arp, "CSV_PATH", csv_file)
    monkeypatch.setattr(
        "app.services.catalog_base.pg_insert", lambda model: MagicMock()
    )
    session = MagicMock()
    assert arp.load_arp_csv(session) == 1
    session.flush.assert_called_once()


def test_match_arp_multiple_targets_per_entry(monkeypatch):
    # One Arp entry with two NGC ids -> two matches.
    entry = MagicMock()
    entry.arp_id = "Arp 77"
    entry.ngc_ic_ids = "NGC1097, NGC1097A"
    entry.peculiarity_class = "Spiral with companion"

    t1 = MagicMock()
    t1.id = 1
    t2 = MagicMock()
    t2.id = 2

    session = MagicMock()
    session.execute.side_effect = [
        _result(scalars_all=[entry]),
        _result(scalar_one=t1),  # first ngc id
        _result(scalar_one=t2),  # second ngc id
    ]

    captured = []
    monkeypatch.setattr(
        "app.services.arp.upsert_membership",
        lambda session, **kw: captured.append(kw),
    )

    assert arp.match_arp_targets(session) == 2
    assert all(c["catalog_name"] == "arp" for c in captured)
    assert all(c["catalog_number"] == "Arp 77" for c in captured)
    assert captured[0]["metadata"] == {
        "peculiarity_class": "Spiral with companion",
        "arp_number": 77,
    }


def test_match_arp_skips_entries_without_ngc(monkeypatch):
    entry = MagicMock()
    entry.arp_id = "Arp 1"
    entry.ngc_ic_ids = None

    session = MagicMock()
    session.execute.side_effect = [_result(scalars_all=[entry])]
    monkeypatch.setattr(
        "app.services.arp.upsert_membership",
        lambda *a, **k: pytest.fail("should not match entry without ngc_ic_ids"),
    )

    assert arp.match_arp_targets(session) == 0


def test_match_arp_no_arp_number_omits_metadata_key(monkeypatch):
    entry = MagicMock()
    entry.arp_id = "ArpWeird"  # no parseable number
    entry.ngc_ic_ids = "NGC1097"
    entry.peculiarity_class = "X"

    target = MagicMock()
    target.id = 1
    session = MagicMock()
    session.execute.side_effect = [
        _result(scalars_all=[entry]),
        _result(scalar_one=target),
    ]

    captured = []
    monkeypatch.setattr(
        "app.services.arp.upsert_membership",
        lambda session, **kw: captured.append(kw),
    )

    assert arp.match_arp_targets(session) == 1
    assert "arp_number" not in captured[0]["metadata"]
