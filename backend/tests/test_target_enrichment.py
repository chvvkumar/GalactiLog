"""Tests for AUD-006 per-target follow-up enrichment.

Covers the per-target catalog membership matchers (inverses of the bulk
matchers), the enrich_new_target coordinator, and end-to-end parity between a
freshly enriched target and a migration-time target against the test DB.
"""
import os
import uuid
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault(
    "GALACTILOG_DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/test_catalog",
)


def _scalars_result(items):
    wrapper = MagicMock()
    scalars_obj = MagicMock()
    scalars_obj.all.return_value = items
    wrapper.scalars.return_value = scalars_obj
    return wrapper


def _target(catalog_id=None, aliases=None, ra=None, dec=None, object_type=None):
    t = MagicMock()
    t.id = uuid.uuid4()
    t.catalog_id = catalog_id
    t.aliases = aliases or []
    t.ra = ra
    t.dec = dec
    t.object_type = object_type
    return t


# ---------------------------------------------------------------------------
# Per-target NGC-catalog matchers (Caldwell / Herschel 400)
# ---------------------------------------------------------------------------

class TestPerTargetNgcMatchers:
    def test_caldwell_matches_by_catalog_id(self, monkeypatch):
        import app.services.caldwell as caldwell

        entry = MagicMock()
        entry.catalog_id = "C14"
        entry.ngc_ic_id = "NGC 869"

        session = MagicMock()
        session.execute.return_value = _scalars_result([entry])

        captured = []
        monkeypatch.setattr(
            "app.services.catalog_base.upsert_membership",
            lambda session, **kw: captured.append(kw),
        )

        target = _target(catalog_id="NGC 869")
        assert caldwell.match_caldwell_for_target(session, target) == 1
        assert captured[0]["catalog_name"] == "caldwell"
        assert captured[0]["catalog_number"] == "C14"
        assert captured[0]["metadata"] == {"caldwell_number": 14, "ngc_ic": "NGC 869"}

    def test_caldwell_matches_by_alias(self, monkeypatch):
        import app.services.caldwell as caldwell

        entry = MagicMock()
        entry.catalog_id = "C14"
        entry.ngc_ic_id = "NGC0869"  # zero-padded, must normalize to "NGC 869"

        session = MagicMock()
        session.execute.return_value = _scalars_result([entry])
        captured = []
        monkeypatch.setattr(
            "app.services.catalog_base.upsert_membership",
            lambda session, **kw: captured.append(kw),
        )

        target = _target(catalog_id="Double Cluster", aliases=["NGC 869"])
        assert caldwell.match_caldwell_for_target(session, target) == 1

    def test_caldwell_no_match(self, monkeypatch):
        import app.services.caldwell as caldwell

        entry = MagicMock()
        entry.catalog_id = "C14"
        entry.ngc_ic_id = "NGC 869"

        session = MagicMock()
        session.execute.return_value = _scalars_result([entry])
        monkeypatch.setattr(
            "app.services.catalog_base.upsert_membership",
            lambda *a, **k: pytest.fail("should not upsert for a non-member target"),
        )

        target = _target(catalog_id="NGC 7000")
        assert caldwell.match_caldwell_for_target(session, target) == 0

    def test_target_with_no_identifiers_returns_zero(self):
        import app.services.caldwell as caldwell

        session = MagicMock()
        target = _target(catalog_id=None, aliases=[])
        assert caldwell.match_caldwell_for_target(session, target) == 0
        session.execute.assert_not_called()  # short-circuits before scanning

    def test_herschel_matches_by_catalog_id(self, monkeypatch):
        import app.services.herschel400 as herschel400

        entry = MagicMock()
        entry.ngc_id = "NGC 40"
        entry.constellation = "Cep"
        entry.object_type = "PN"
        entry.magnitude = 12.4

        session = MagicMock()
        session.execute.return_value = _scalars_result([entry])
        captured = []
        monkeypatch.setattr(
            "app.services.catalog_base.upsert_membership",
            lambda session, **kw: captured.append(kw),
        )

        target = _target(catalog_id="NGC 40")
        assert herschel400.match_herschel400_for_target(session, target) == 1
        assert captured[0]["catalog_number"] == "H400"


# ---------------------------------------------------------------------------
# Per-target Arp matcher
# ---------------------------------------------------------------------------

class TestPerTargetArpMatcher:
    def test_matches_multi_id_entry(self, monkeypatch):
        import app.services.arp as arp

        entry = MagicMock()
        entry.arp_id = "Arp 77"
        entry.ngc_ic_ids = "NGC 1097, NGC 1097A"
        entry.peculiarity_class = "Spiral"

        session = MagicMock()
        session.execute.return_value = _scalars_result([entry])
        captured = []
        monkeypatch.setattr(
            "app.services.arp.upsert_membership",
            lambda session, **kw: captured.append(kw),
        )

        target = _target(catalog_id="NGC 1097")
        assert arp.match_arp_for_target(session, target) == 1
        assert captured[0]["catalog_number"] == "Arp 77"
        assert captured[0]["metadata"]["arp_number"] == 77

    def test_no_match_when_ids_absent(self, monkeypatch):
        import app.services.arp as arp

        entry = MagicMock()
        entry.arp_id = "Arp 1"
        entry.ngc_ic_ids = "NGC 2857"
        entry.peculiarity_class = "x"

        session = MagicMock()
        session.execute.return_value = _scalars_result([entry])
        monkeypatch.setattr(
            "app.services.arp.upsert_membership",
            lambda *a, **k: pytest.fail("should not upsert"),
        )
        target = _target(catalog_id="NGC 9999")
        assert arp.match_arp_for_target(session, target) == 0


# ---------------------------------------------------------------------------
# Per-target Abell matcher
# ---------------------------------------------------------------------------

class TestPerTargetAbellMatcher:
    def test_matches_by_catalog_id(self, monkeypatch):
        import app.services.abell as abell

        entry = MagicMock()
        entry.abell_id = "Abell 2151"
        entry.richness_class = 2
        entry.distance_class = 5
        entry.bm_type = "III"
        entry.ra = 241.3
        entry.dec = 17.7

        session = MagicMock()
        session.execute.return_value = _scalars_result([entry])
        captured = []
        monkeypatch.setattr(
            "app.services.abell.upsert_membership",
            lambda session, **kw: captured.append(kw),
        )

        target = _target(catalog_id="Abell 2151")
        assert abell.match_abell_for_target(session, target) == 1
        assert captured[0]["catalog_number"] == "Abell 2151"

    def test_matches_by_alias_aco(self, monkeypatch):
        import app.services.abell as abell

        entry = MagicMock()
        entry.abell_id = "Abell 1656"
        entry.richness_class = 2
        entry.distance_class = 1
        entry.bm_type = "II"
        entry.ra = 194.9
        entry.dec = 27.9

        session = MagicMock()
        session.execute.return_value = _scalars_result([entry])
        monkeypatch.setattr(
            "app.services.abell.upsert_membership", lambda *a, **k: None,
        )
        target = _target(catalog_id="Coma Cluster", aliases=["ACO 1656"])
        assert abell.match_abell_for_target(session, target) == 1

    def test_no_match_returns_zero(self, monkeypatch):
        import app.services.abell as abell

        entry = MagicMock()
        entry.abell_id = "Abell 1656"
        entry.ra = 194.9
        entry.dec = 27.9
        session = MagicMock()
        session.execute.return_value = _scalars_result([entry])
        monkeypatch.setattr(
            "app.services.abell.upsert_membership",
            lambda *a, **k: pytest.fail("should not upsert"),
        )
        target = _target(catalog_id="NGC 7000", object_type="Neb")
        assert abell.match_abell_for_target(session, target) == 0


# ---------------------------------------------------------------------------
# enrich_new_target coordinator (mocked sub-services)
# ---------------------------------------------------------------------------

class TestEnrichNewTargetCoordinator:
    def test_constellation_fallback_only_when_missing(self):
        from app.services.target_enrichment import enrich_new_target

        session = MagicMock()
        target = _target(ra=10.0, dec=41.0, object_type="Neb")
        target.constellation = None

        with patch("app.services.constellation.coords_to_constellation", return_value="And") as m_const, \
             patch("app.services.catalog_membership.match_target_memberships", return_value=0), \
             patch("app.services.gaia.enrich_target_from_gaia", return_value=False), \
             patch("app.services.hyperleda.enrich_target_from_hyperleda", return_value=False):
            res = enrich_new_target(session, target)

        m_const.assert_called_once_with(10.0, 41.0)
        assert target.constellation == "And"
        assert res["constellation"] is True

    def test_constellation_not_overwritten(self):
        from app.services.target_enrichment import enrich_new_target

        session = MagicMock()
        target = _target(ra=10.0, dec=41.0, object_type="Neb")
        target.constellation = "Cyg"

        with patch("app.services.constellation.coords_to_constellation") as m_const, \
             patch("app.services.catalog_membership.match_target_memberships", return_value=0), \
             patch("app.services.gaia.enrich_target_from_gaia", return_value=False), \
             patch("app.services.hyperleda.enrich_target_from_hyperleda", return_value=False):
            res = enrich_new_target(session, target)

        m_const.assert_not_called()
        assert target.constellation == "Cyg"
        assert res["constellation"] is False

    def test_flags_network_query_for_cluster_cache_miss(self):
        from app.services.target_enrichment import enrich_new_target

        session = MagicMock()
        target = _target(ra=100.0, dec=-10.0, object_type="OpC")
        target.constellation = "Ori"

        with patch("app.services.catalog_membership.match_target_memberships", return_value=0), \
             patch("app.services.gaia._is_cluster_type", return_value=True), \
             patch("app.services.gaia.get_cached_gaia", return_value=None), \
             patch("app.services.gaia.enrich_target_from_gaia", return_value=True), \
             patch("app.services.hyperleda._is_galaxy_type", return_value=False), \
             patch("app.services.hyperleda.enrich_target_from_hyperleda", return_value=False):
            res = enrich_new_target(session, target)

        assert res["queried_network"] is True
        assert res["gaia"] is True

    def test_soft_time_limit_propagates(self):
        from celery.exceptions import SoftTimeLimitExceeded
        from app.services.target_enrichment import enrich_new_target

        session = MagicMock()
        target = _target(catalog_id="NGC 4236", object_type="G")
        target.constellation = "Dra"

        with patch("app.services.catalog_membership.match_target_memberships", return_value=0), \
             patch("app.services.gaia.enrich_target_from_gaia", return_value=False), \
             patch("app.services.hyperleda._is_galaxy_type", return_value=True), \
             patch("app.services.hyperleda.get_cached_hyperleda", return_value=None), \
             patch("app.services.hyperleda.enrich_target_from_hyperleda",
                   side_effect=SoftTimeLimitExceeded()):
            with pytest.raises(SoftTimeLimitExceeded):
                enrich_new_target(session, target)

    def test_gaia_failure_is_caught_and_logged_not_raised(self):
        """A Gaia enrichment failure (e.g. a NonTransientError from the shared
        cache wrapper) must not abort the rest of enrich_new_target -- mirrors
        the existing HyperLEDA except-and-continue behavior."""
        from app.services.target_enrichment import enrich_new_target

        session = MagicMock()
        target = _target(ra=100.0, dec=-10.0, object_type="OpC")
        target.constellation = "Ori"

        with patch("app.services.catalog_membership.match_target_memberships", return_value=0), \
             patch("app.services.gaia._is_cluster_type", return_value=True), \
             patch("app.services.gaia.get_cached_gaia", return_value=None), \
             patch("app.services.gaia.enrich_target_from_gaia",
                   side_effect=RuntimeError("boom")), \
             patch("app.services.hyperleda._is_galaxy_type", return_value=False), \
             patch("app.services.hyperleda.enrich_target_from_hyperleda", return_value=False):
            res = enrich_new_target(session, target)

        assert res["gaia"] is False
        # HyperLEDA step still ran despite the Gaia failure.
        assert res["hyperleda"] is False

    def test_gaia_soft_time_limit_propagates(self):
        from celery.exceptions import SoftTimeLimitExceeded
        from app.services.target_enrichment import enrich_new_target

        session = MagicMock()
        target = _target(ra=100.0, dec=-10.0, object_type="OpC")
        target.constellation = "Ori"

        with patch("app.services.catalog_membership.match_target_memberships", return_value=0), \
             patch("app.services.gaia._is_cluster_type", return_value=True), \
             patch("app.services.gaia.get_cached_gaia", return_value=None), \
             patch("app.services.gaia.enrich_target_from_gaia",
                   side_effect=SoftTimeLimitExceeded()):
            with pytest.raises(SoftTimeLimitExceeded):
                enrich_new_target(session, target)


# ---------------------------------------------------------------------------
# _create_target dispatches the async follow-up on a genuine new insert
# ---------------------------------------------------------------------------

class TestCreateTargetDispatch:
    def test_dispatches_enrichment_on_new_insert(self):
        from app.services import target_resolver

        mock_session = MagicMock()
        # No existing target on the identity re-check -> genuine insert path.
        simbad_result = {
            "primary_name": "NGC 7000 - North America Nebula",
            "catalog_id": "NGC 7000",
            "aliases": ["NGC 7000"],
        }

        with patch("app.services.target_resolver.enrich_target_from_openngc"), \
             patch("app.services.target_resolver.enrich_target_from_vizier"), \
             patch("app.services.target_resolver.enrich_target_from_sac"), \
             patch("app.services.target_resolver.match_target_by_identity", return_value=None), \
             patch("app.services.target_resolver._dispatch_enrich_new_target") as m_dispatch:
            result = target_resolver._create_target(simbad_result, "NGC 7000", mock_session)

        assert result is not None
        m_dispatch.assert_called_once_with(result)

    def test_no_dispatch_when_existing_target_found(self):
        from app.services import target_resolver

        mock_session = MagicMock()
        existing = MagicMock()
        existing.id = "existing-id"
        simbad_result = {
            "primary_name": "NGC 7000",
            "catalog_id": "NGC 7000",
            "aliases": ["NGC 7000"],
        }

        with patch("app.services.target_resolver.enrich_target_from_openngc"), \
             patch("app.services.target_resolver.match_target_by_identity", return_value=existing), \
             patch("app.services.target_resolver._dispatch_enrich_new_target") as m_dispatch:
            result = target_resolver._create_target(simbad_result, "NGC 7000", mock_session)

        assert result == "existing-id"
        m_dispatch.assert_not_called()


# ---------------------------------------------------------------------------
# End-to-end parity against the test DB
# ---------------------------------------------------------------------------

def _sync_session_factory():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    url = os.environ["GALACTILOG_DATABASE_URL"].replace("+asyncpg", "+psycopg2")
    engine = create_engine(url, pool_pre_ping=True)
    try:
        conn = engine.connect()
        conn.close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"test DB not reachable: {exc}")
    return sessionmaker(bind=engine), engine


class TestEnrichNewTargetParity:
    """A freshly ingested target gets the same enrichment as a migration-time one."""

    def test_new_target_converges_with_bulk_matcher(self):
        from sqlalchemy import text
        from app.models import Target
        from app.models.catalog_membership import TargetCatalogMembership
        from app.services.catalog_membership import (
            load_all_catalogs, match_all_memberships, match_target_memberships,
        )
        from app.services.target_enrichment import enrich_new_target

        Session, engine = _sync_session_factory()
        session = Session()

        # NGC 4236 is Caldwell C3, a galaxy in Draco.
        new_id = uuid.uuid4()
        mig_id = uuid.uuid4()
        try:
            for tbl in (
                "images", "target_catalog_memberships", "mosaic_panels",
                "mosaics", "targets", "hyperleda_cache", "gaia_cache",
            ):
                session.execute(text(f"DELETE FROM {tbl}"))
            session.commit()

            load_all_catalogs(session)
            session.commit()

            def _make(tid, primary_name):
                return Target(
                    id=tid,
                    primary_name=primary_name,
                    catalog_id="NGC 4236",
                    object_type="G",
                    ra=184.176,
                    dec=69.463,
                )

            # Migration-time target: enriched via the bulk matcher + HyperLEDA.
            # `primary_name` is unique per row and irrelevant to matching (which
            # keys off catalog_id/ra/dec/object_type), so the two rows use
            # distinct display names while sharing the same catalog identity.
            session.add(_make(mig_id, "NGC 4236"))
            session.commit()
            with patch(
                "app.services.hyperleda.query_hyperleda",
                return_value={"t_type": 8.0, "inclination": 71.0},
            ):
                match_all_memberships(session)
                from app.services.hyperleda import enrich_target_from_hyperleda
                enrich_target_from_hyperleda(session, session.get(Target, mig_id))
            session.commit()

            # Freshly-ingested target: enriched via the new per-target path.
            session.add(_make(new_id, "NGC 4236 (new)"))
            session.commit()
            with patch(
                "app.services.hyperleda.query_hyperleda",
                return_value={"t_type": 8.0, "inclination": 71.0},
            ):
                res = enrich_new_target(session, session.get(Target, new_id))
            session.commit()

            new_t = session.get(Target, new_id)
            mig_t = session.get(Target, mig_id)

            # Constellation fallback fired for the new target.
            assert new_t.constellation == "Dra"
            # HyperLEDA morphology matches the migration-time target.
            assert new_t.hubble_t_type == pytest.approx(mig_t.hubble_t_type)
            assert new_t.inclination == pytest.approx(mig_t.inclination)
            assert res["hyperleda"] is True
            assert res["memberships"] >= 1

            def _memberships(tid):
                rows = session.execute(
                    text(
                        "SELECT catalog_name, catalog_number FROM "
                        "target_catalog_memberships WHERE target_id = :tid"
                    ),
                    {"tid": tid},
                ).all()
                return {(r[0], r[1]) for r in rows}

            new_members = _memberships(new_id)
            mig_members = _memberships(mig_id)
            assert new_members == mig_members
            assert ("caldwell", "C3") in new_members
        finally:
            session.rollback()
            for tbl in ("target_catalog_memberships", "targets"):
                session.execute(text(f"DELETE FROM {tbl} WHERE 1=1"))
            session.commit()
            session.close()
            engine.dispose()
