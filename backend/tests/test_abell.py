"""Tests for the Abell catalog service public functions."""
from unittest.mock import MagicMock

import pytest

import app.services.abell as abell


def _result(scalars_all=None):
    wrapper = MagicMock()
    scalars_obj = MagicMock()
    scalars_obj.all.return_value = scalars_all or []
    wrapper.scalars.return_value = scalars_obj
    return wrapper


def _make_entry(abell_id, ra=None, dec=None, richness=None, distance=None, bm=None):
    e = MagicMock()
    e.abell_id = abell_id
    e.ra = ra
    e.dec = dec
    e.richness_class = richness
    e.distance_class = distance
    e.bm_type = bm
    return e


def _make_target(tid, catalog_id=None, aliases=None, ra=None, dec=None, object_type=None):
    t = MagicMock()
    t.id = tid
    t.catalog_id = catalog_id
    t.aliases = aliases
    t.ra = ra
    t.dec = dec
    t.object_type = object_type
    return t


def test_load_abell_csv_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(abell, "CSV_PATH", tmp_path / "missing.csv")
    session = MagicMock()
    assert abell.load_abell_csv(session) == 0
    session.execute.assert_not_called()


def test_load_abell_csv_parses_numeric_fields(monkeypatch, tmp_path):
    csv_file = tmp_path / "abell.csv"
    csv_file.write_text(
        "abell_id,ra,dec,richness_class,distance_class,bm_type,redshift\n"
        "Abell 1656,194.95,27.98,2,4,II,0.0231\n"
        "Abell 2,bad,,,,,\n"
        ",1.0,2.0,1,1,I,0.1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(abell, "CSV_PATH", csv_file)

    captured = []

    def fake_pg_insert(model):
        stmt = MagicMock()

        def values(**kw):
            captured.append(kw)
            return MagicMock()

        stmt.values.side_effect = values
        return stmt

    monkeypatch.setattr("app.services.catalog_base.pg_insert", fake_pg_insert)
    session = MagicMock()

    assert abell.load_abell_csv(session) == 2  # blank abell_id skipped
    assert captured[0]["ra"] == 194.95
    assert captured[0]["richness_class"] == 2
    # second row: bad ra -> None, blank numerics -> None
    assert captured[1]["ra"] is None
    assert captured[1]["richness_class"] is None


def test_match_stage1_catalog_id(monkeypatch):
    entry = _make_entry("Abell 1656", richness=2, distance=4, bm="II")
    target = _make_target(1, catalog_id="Abell 1656")

    session = MagicMock()
    session.execute.side_effect = [
        _result(scalars_all=[entry]),   # AbellEntry query
        _result(scalars_all=[target]),  # Target query
    ]

    captured = []
    monkeypatch.setattr(
        "app.services.abell.upsert_membership",
        lambda session, **kw: captured.append(kw),
    )

    assert abell.match_abell_targets(session) == 1
    assert captured[0]["catalog_name"] == "abell"
    assert captured[0]["catalog_number"] == "Abell 1656"
    assert captured[0]["metadata"]["abell_number"] == 1656
    assert captured[0]["metadata"]["richness"] == 2


def test_match_stage1_aco_prefix(monkeypatch):
    entry = _make_entry("Abell 2151")
    target = _make_target(1, catalog_id="ACO 2151")

    session = MagicMock()
    session.execute.side_effect = [
        _result(scalars_all=[entry]),
        _result(scalars_all=[target]),
    ]

    captured = []
    monkeypatch.setattr(
        "app.services.abell.upsert_membership",
        lambda session, **kw: captured.append(kw),
    )

    assert abell.match_abell_targets(session) == 1
    assert captured[0]["catalog_number"] == "Abell 2151"


def test_match_stage2_alias(monkeypatch):
    entry = _make_entry("Abell 426")
    target = _make_target(1, catalog_id="NGC 1275", aliases=["Perseus", "Abell 426"])

    session = MagicMock()
    session.execute.side_effect = [
        _result(scalars_all=[entry]),
        _result(scalars_all=[target]),
    ]

    captured = []
    monkeypatch.setattr(
        "app.services.abell.upsert_membership",
        lambda session, **kw: captured.append(kw),
    )

    assert abell.match_abell_targets(session) == 1
    assert captured[0]["catalog_number"] == "Abell 426"


def test_match_stage3_coordinate_proximity(monkeypatch):
    entry = _make_entry("Abell 1656", ra=194.95, dec=27.98)
    # Cluster-type target with no name match but close coordinates.
    target = _make_target(
        1, catalog_id="UnknownCluster", ra=194.96, dec=27.97, object_type="ClG"
    )

    session = MagicMock()
    session.execute.side_effect = [
        _result(scalars_all=[entry]),
        _result(scalars_all=[target]),
    ]

    captured = []
    monkeypatch.setattr(
        "app.services.abell.upsert_membership",
        lambda session, **kw: captured.append(kw),
    )

    assert abell.match_abell_targets(session) == 1
    assert captured[0]["catalog_number"] == "Abell 1656"


def test_match_stage3_skips_non_cluster(monkeypatch):
    entry = _make_entry("Abell 1656", ra=194.95, dec=27.98)
    target = _make_target(
        1, catalog_id="SomeGalaxy", ra=194.95, dec=27.98, object_type="G"
    )

    session = MagicMock()
    session.execute.side_effect = [
        _result(scalars_all=[entry]),
        _result(scalars_all=[target]),
    ]

    monkeypatch.setattr(
        "app.services.abell.upsert_membership",
        lambda *a, **k: pytest.fail("non-cluster target should not coordinate-match"),
    )

    assert abell.match_abell_targets(session) == 0


def test_match_no_double_count_across_stages(monkeypatch):
    # A target matched in stage 1 must not also match in stage 3.
    entry = _make_entry("Abell 1656", ra=194.95, dec=27.98)
    target = _make_target(
        1, catalog_id="Abell 1656", ra=194.95, dec=27.98, object_type="ClG"
    )

    session = MagicMock()
    session.execute.side_effect = [
        _result(scalars_all=[entry]),
        _result(scalars_all=[target]),
    ]

    captured = []
    monkeypatch.setattr(
        "app.services.abell.upsert_membership",
        lambda session, **kw: captured.append(kw),
    )

    assert abell.match_abell_targets(session) == 1
    assert len(captured) == 1
