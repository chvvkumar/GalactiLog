"""Unit tests for app.services.catalog_membership - upsert and aggregation."""
import pytest
from unittest.mock import MagicMock, call, patch

from app.services.catalog_membership import (
    upsert_membership,
    load_all_catalogs,
    match_all_memberships,
    load_catalog_memberships,
)


# ---------------------------------------------------------------------------
# upsert_membership
# ---------------------------------------------------------------------------

class TestUpsertMembership:
    def test_executes_insert_on_session(self):
        session = MagicMock()
        upsert_membership(session, "target-uuid", "Caldwell", "C 14")
        session.execute.assert_called_once()

    def test_executes_with_metadata(self):
        session = MagicMock()
        upsert_membership(
            session, "target-uuid", "Arp", "Arp 273", metadata={"description": "pair"}
        )
        session.execute.assert_called_once()

    def test_executes_with_none_metadata(self):
        session = MagicMock()
        upsert_membership(session, "target-uuid", "Herschel 400", "H400-42", metadata=None)
        session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# load_all_catalogs
# ---------------------------------------------------------------------------

class TestLoadAllCatalogs:
    def test_calls_all_loaders_and_returns_summary(self):
        # load_all_catalogs uses lazy imports inside the function body, so patch
        # the actual sub-service modules rather than attributes of catalog_membership.
        session = MagicMock()
        caldwell_mock = MagicMock()
        caldwell_mock.load_caldwell_csv = MagicMock(return_value=109)
        herschel_mock = MagicMock()
        herschel_mock.load_herschel400_csv = MagicMock(return_value=400)
        arp_mock = MagicMock()
        arp_mock.load_arp_csv = MagicMock(return_value=338)
        abell_mock = MagicMock()
        abell_mock.load_abell_csv = MagicMock(return_value=86)

        import sys
        with patch.dict(sys.modules, {
            "app.services.caldwell": caldwell_mock,
            "app.services.herschel400": herschel_mock,
            "app.services.arp": arp_mock,
            "app.services.abell": abell_mock,
        }):
            summary = load_all_catalogs(session)

        assert "Caldwell" in summary
        assert "109" in summary
        assert "Herschel 400" in summary
        assert "400" in summary
        assert "Arp" in summary
        assert "Abell" in summary

    def test_returns_string(self):
        import sys
        caldwell_mock = MagicMock()
        caldwell_mock.load_caldwell_csv = MagicMock(return_value=0)
        herschel_mock = MagicMock()
        herschel_mock.load_herschel400_csv = MagicMock(return_value=0)
        arp_mock = MagicMock()
        arp_mock.load_arp_csv = MagicMock(return_value=0)
        abell_mock = MagicMock()
        abell_mock.load_abell_csv = MagicMock(return_value=0)

        session = MagicMock()
        with patch.dict(sys.modules, {
            "app.services.caldwell": caldwell_mock,
            "app.services.herschel400": herschel_mock,
            "app.services.arp": arp_mock,
            "app.services.abell": abell_mock,
        }):
            summary = load_all_catalogs(session)

        assert isinstance(summary, str)


# ---------------------------------------------------------------------------
# match_all_memberships
# ---------------------------------------------------------------------------

class TestMatchAllMemberships:
    def test_calls_all_matchers_and_returns_summary(self):
        import sys
        caldwell_mock = MagicMock()
        caldwell_mock.match_caldwell_targets = MagicMock(return_value=10)
        herschel_mock = MagicMock()
        herschel_mock.match_herschel400_targets = MagicMock(return_value=50)
        arp_mock = MagicMock()
        arp_mock.match_arp_targets = MagicMock(return_value=30)
        abell_mock = MagicMock()
        abell_mock.match_abell_targets = MagicMock(return_value=20)

        session = MagicMock()
        with patch.dict(sys.modules, {
            "app.services.caldwell": caldwell_mock,
            "app.services.herschel400": herschel_mock,
            "app.services.arp": arp_mock,
            "app.services.abell": abell_mock,
        }):
            summary = match_all_memberships(session)

        assert "Caldwell" in summary
        assert "10" in summary
        assert "Herschel 400" in summary
        assert "50" in summary

    def test_returns_string(self):
        import sys
        caldwell_mock = MagicMock()
        caldwell_mock.match_caldwell_targets = MagicMock(return_value=0)
        herschel_mock = MagicMock()
        herschel_mock.match_herschel400_targets = MagicMock(return_value=0)
        arp_mock = MagicMock()
        arp_mock.match_arp_targets = MagicMock(return_value=0)
        abell_mock = MagicMock()
        abell_mock.match_abell_targets = MagicMock(return_value=0)

        session = MagicMock()
        with patch.dict(sys.modules, {
            "app.services.caldwell": caldwell_mock,
            "app.services.herschel400": herschel_mock,
            "app.services.arp": arp_mock,
            "app.services.abell": abell_mock,
        }):
            summary = match_all_memberships(session)

        assert isinstance(summary, str)


# ---------------------------------------------------------------------------
# load_catalog_memberships
# ---------------------------------------------------------------------------

class TestLoadCatalogMemberships:
    def test_combines_load_and_match_summaries(self):
        session = MagicMock()
        import sys
        caldwell_mock = MagicMock()
        caldwell_mock.load_caldwell_csv = MagicMock(return_value=0)
        caldwell_mock.match_caldwell_targets = MagicMock(return_value=0)
        herschel_mock = MagicMock()
        herschel_mock.load_herschel400_csv = MagicMock(return_value=0)
        herschel_mock.match_herschel400_targets = MagicMock(return_value=0)
        arp_mock = MagicMock()
        arp_mock.load_arp_csv = MagicMock(return_value=0)
        arp_mock.match_arp_targets = MagicMock(return_value=0)
        abell_mock = MagicMock()
        abell_mock.load_abell_csv = MagicMock(return_value=0)
        abell_mock.match_abell_targets = MagicMock(return_value=0)

        with patch.dict(sys.modules, {
            "app.services.caldwell": caldwell_mock,
            "app.services.herschel400": herschel_mock,
            "app.services.arp": arp_mock,
            "app.services.abell": abell_mock,
        }):
            result = load_catalog_memberships(session)

        assert isinstance(result, str)
        assert "\n" in result  # load + match summaries joined by newline
