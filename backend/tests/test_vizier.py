from unittest.mock import MagicMock, patch
import pytest
from app.services.vizier import (
    determine_vizier_catalog,
    build_adql_query,
    _adql_quote,
    _adql_int,
    enrich_target_from_vizier,
)
from app.services import catalog_cache as cc


class TestAdqlEscaping:
    def test_adql_quote_doubles_single_quote(self):
        assert _adql_quote("a'b") == "a''b"

    def test_adql_quote_injection(self):
        assert _adql_quote("x'; DROP TABLE y--") == "x''; DROP TABLE y--"

    def test_adql_int_valid(self):
        assert _adql_int("129") == 129
        assert _adql_int(" 33 ") == 33

    def test_adql_int_rejects_non_numeric(self):
        assert _adql_int("129; DROP") is None
        assert _adql_int("") is None

    def test_cluster_name_injection_does_not_match(self):
        """fullmatch prevents an injected cluster name from over-matching B/ocl."""
        # "Collinder 399'; DROP ..." no longer matches the cluster pattern,
        # so no query is built at all.
        assert determine_vizier_catalog("Collinder 399'; DROP TABLE x--") is None
        assert build_adql_query("Collinder 399'; DROP TABLE x--") is None

    def test_cluster_name_quote_escaped(self):
        """A legitimately matching cluster value still has quotes doubled.

        Ced uses a permissive `(.+)$` capture, so a quote in the value is kept
        and must be escaped rather than allowed to break out of the literal.
        """
        q = build_adql_query("Ced 51'--")
        assert q is not None
        assert "''" in q
        assert "='51'--'" not in q

    def test_cederblad_quote_escaped(self):
        q = build_adql_query("Ced 51'--")
        assert q is not None
        assert "''" in q

    def test_numeric_catalog_rejects_injection(self):
        """A Sharpless id whose number part is not an int yields no query."""
        # Forge a value where _extract_number returns non-numeric text.
        assert build_adql_query("SH 2-1 OR 1=1") is None


class TestDetermineVizierCatalog:
    def test_sharpless(self):
        result = determine_vizier_catalog("SH 2-129")
        assert result is not None
        catalog_id, table, num_col = result
        assert catalog_id == "VII/20"
        assert table == '"VII/20/catalog"'
        assert num_col == "Sh2"

    def test_sharpless_variant(self):
        result = determine_vizier_catalog("Sh2-129")
        assert result is not None
        assert result[0] == "VII/20"

    def test_barnard(self):
        result = determine_vizier_catalog("B 33")
        assert result is not None
        assert result[0] == "VII/220A"
        assert result[2] == "Barn"

    def test_lbn(self):
        result = determine_vizier_catalog("LBN 437")
        assert result is not None
        assert result[0] == "VII/9"

    def test_ldn(self):
        result = determine_vizier_catalog("LDN 1622")
        assert result is not None
        assert result[0] == "VII/7A"

    def test_vdb(self):
        result = determine_vizier_catalog("vdB 152")
        assert result is not None
        assert result[0] == "VII/21"

    def test_rcw(self):
        result = determine_vizier_catalog("RCW 49")
        assert result is not None
        assert result[0] == "VII/216"

    def test_collinder(self):
        result = determine_vizier_catalog("Collinder 399")
        assert result is not None
        assert result[0] == "B/ocl"

    def test_melotte(self):
        result = determine_vizier_catalog("Melotte 111")
        assert result is not None
        assert result[0] == "B/ocl"

    def test_trumpler(self):
        result = determine_vizier_catalog("Trumpler 37")
        assert result is not None
        assert result[0] == "B/ocl"

    def test_cederblad(self):
        result = determine_vizier_catalog("Ced 214")
        assert result is not None
        assert result[0] == "VII/231"

    def test_abell_pn(self):
        result = determine_vizier_catalog("Abell 39")
        assert result is not None
        assert result[0] == "V/84"

    def test_pn_a66(self):
        result = determine_vizier_catalog("PN A66 39")
        assert result is not None
        assert result[0] == "V/84"

    def test_ngc_returns_none(self):
        assert determine_vizier_catalog("NGC 7000") is None

    def test_messier_returns_none(self):
        assert determine_vizier_catalog("M 31") is None

    def test_ic_returns_none(self):
        assert determine_vizier_catalog("IC 1396") is None

    def test_none_input(self):
        assert determine_vizier_catalog(None) is None

    def test_empty_input(self):
        assert determine_vizier_catalog("") is None


class TestBuildAdqlQuery:
    def test_sharpless(self):
        query = build_adql_query("SH 2-129")
        assert query is not None
        assert '"VII/20/catalog"' in query
        assert "Sh2=129" in query
        assert "Diam" in query

    def test_barnard(self):
        query = build_adql_query("B 33")
        assert query is not None
        assert '"VII/220A/barnard"' in query
        assert "TRIM(Barn)='33'" in query

    def test_lbn(self):
        query = build_adql_query("LBN 437")
        assert query is not None
        assert '"VII/9/catalog"' in query

    def test_open_cluster(self):
        query = build_adql_query("Collinder 399")
        assert query is not None
        assert '"B/ocl/clusters"' in query
        assert "Collinder 399" in query

    def test_ngc_returns_none(self):
        assert build_adql_query("NGC 7000") is None


class TestEnrichTargetFromVizierCache:
    """Test enrich_target_from_vizier behavior with the generic catalog cache wrapper."""

    def test_negative_cache_suppresses_refetch(self):
        """Test that a negative cache hit suppresses HTTP calls without fetching."""
        catalog_id = "SH 2-999"
        mock_session = MagicMock()

        # Create a mock target
        target = MagicMock()
        target.user_defined = False
        target.catalog_id = catalog_id
        target.size_major = None
        target.size_minor = None
        target.constellation = None

        # Mock get_cached_vizier to return cc.NEGATIVE
        with patch("app.services.vizier.get_cached_vizier") as mock_get_cached:
            mock_get_cached.return_value = cc.NEGATIVE

            # Mock query_vizier to track if it's called
            with patch("app.services.vizier.query_vizier") as mock_query:
                result = enrich_target_from_vizier(mock_session, target)

        # Should return False (no update) and not call query_vizier
        assert result is False
        mock_query.assert_not_called()

    def test_positive_cache_applies_enrichment(self):
        """Test that a positive cache hit applies enrichment to target."""
        catalog_id = "SH 2-129"
        payload = {
            "size_major": 45.0,
            "size_minor": 30.0,
            "constellation": "CYG",
            "vizier_catalog": "VII/20",
        }

        mock_session = MagicMock()

        # Create a mock target
        target = MagicMock()
        target.user_defined = False
        target.catalog_id = catalog_id
        target.size_major = None
        target.size_minor = None
        target.constellation = None

        # Mock get_cached_vizier to return the positive cache
        with patch("app.services.vizier.get_cached_vizier") as mock_get_cached:
            mock_get_cached.return_value = payload

            # Mock query_vizier to verify it's not called
            with patch("app.services.vizier.query_vizier") as mock_query:
                result = enrich_target_from_vizier(mock_session, target)

        # Should apply enrichment without calling query_vizier
        assert result is True
        assert target.size_major == 45.0
        assert target.size_minor == 30.0
        assert target.constellation == "CYG"
        mock_query.assert_not_called()

    def test_user_defined_targets_skipped(self):
        """Test that user-defined targets are never enriched."""
        mock_session = MagicMock()
        target = MagicMock()
        target.user_defined = True
        target.catalog_id = "SH 2-129"

        with patch("app.services.vizier.query_vizier") as mock_query:
            result = enrich_target_from_vizier(mock_session, target)

        assert result is False
        mock_query.assert_not_called()

    def test_cache_miss_triggers_query(self):
        """Test that a cache miss triggers a VizieR query and caches the result."""
        catalog_id = "SH 2-129"
        fetched_data = {"size_major": 45.0, "size_minor": 30.0}

        mock_session = MagicMock()

        # Create a mock target
        target = MagicMock()
        target.user_defined = False
        target.catalog_id = catalog_id
        target.size_major = None
        target.size_minor = None
        target.constellation = None

        # Mock get_cached_vizier to return None (cache miss)
        with patch("app.services.vizier.get_cached_vizier") as mock_get_cached:
            mock_get_cached.return_value = None

            # Mock query_vizier to return data
            with patch("app.services.vizier.query_vizier") as mock_query:
                mock_query.return_value = fetched_data

                # Mock save_vizier_cache to verify it's called
                with patch("app.services.vizier.save_vizier_cache") as mock_save:
                    result = enrich_target_from_vizier(mock_session, target)

        # Should have called query_vizier
        mock_query.assert_called_once_with(catalog_id)

        # Should have saved to cache
        mock_save.assert_called_once()

        # Should have applied enrichment
        assert result is True
        assert target.size_major == 45.0
        assert target.size_minor == 30.0
