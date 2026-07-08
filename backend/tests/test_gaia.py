"""Unit tests for app.services.gaia - cluster detection, math, and HTTP mocking."""
import pytest
from unittest.mock import MagicMock, patch

from app.services.gaia import (
    _is_cluster_type,
    _compute_cone_radius,
    _median,
    query_cluster_distance,
    enrich_target_from_gaia,
)


# ---------------------------------------------------------------------------
# _is_cluster_type
# ---------------------------------------------------------------------------

class TestIsClusterType:
    def test_open_cluster_code(self):
        assert _is_cluster_type("OpC") is True

    def test_globular_cluster_code(self):
        assert _is_cluster_type("GlC") is True

    def test_multi_token_string_with_cluster(self):
        assert _is_cluster_type("G,OpC") is True

    def test_single_token_star_cluster_code(self):
        # "Star Cluster" is split by spaces into ["Star", "Cluster"], neither of
        # which is in _CLUSTER_CODES - only single-word codes like OpC/GlC match.
        assert _is_cluster_type("OpC") is True

    def test_galaxy_type_not_cluster(self):
        assert _is_cluster_type("G") is False

    def test_none_returns_false(self):
        assert _is_cluster_type(None) is False

    def test_empty_string_returns_false(self):
        assert _is_cluster_type("") is False

    def test_mixed_tokens_one_cluster(self):
        assert _is_cluster_type("HII|OpC") is True

    def test_open_cluster_multi_word_matches(self):
        # Bug fix: "Open Cluster" is a multi-word code and must now match.
        assert _is_cluster_type("Open Cluster") is True

    def test_globular_cluster_multi_word_matches(self):
        assert _is_cluster_type("Globular Cluster") is True

    def test_star_cluster_multi_word_matches(self):
        assert _is_cluster_type("Star Cluster") is True

    def test_mixed_tokens_star_cluster_code_with_ocl(self):
        # OCl is a single-word cluster code and does match
        assert _is_cluster_type("OCl") is True

    def test_galaxy_not_cluster(self):
        assert _is_cluster_type("Galaxy") is False

    def test_hii_not_cluster(self):
        assert _is_cluster_type("HII") is False


# ---------------------------------------------------------------------------
# _compute_cone_radius
# ---------------------------------------------------------------------------

class TestComputeConeRadius:
    def test_uses_size_major_scaled(self):
        target = MagicMock()
        target.size_major = 60.0  # arcmin
        # radius = 60/60*0.5 = 0.5 deg
        assert _compute_cone_radius(target) == pytest.approx(0.5)

    def test_enforces_minimum_radius(self):
        target = MagicMock()
        target.size_major = 1.0  # very small -> radius would be <0.1
        # radius = 1/60*0.5 ~ 0.0083, clamped to 0.1
        assert _compute_cone_radius(target) == pytest.approx(0.1)

    def test_defaults_when_size_major_is_none(self):
        target = MagicMock()
        target.size_major = None
        assert _compute_cone_radius(target) == pytest.approx(0.15)


# ---------------------------------------------------------------------------
# _median
# ---------------------------------------------------------------------------

class TestMedian:
    def test_odd_count(self):
        assert _median([1.0, 3.0, 2.0]) == pytest.approx(2.0)

    def test_even_count(self):
        assert _median([1.0, 2.0, 3.0, 4.0]) == pytest.approx(2.5)

    def test_single_element(self):
        assert _median([7.0]) == pytest.approx(7.0)

    def test_already_sorted(self):
        assert _median([1.0, 2.0, 5.0]) == pytest.approx(2.0)

    def test_unsorted_input(self):
        assert _median([5.0, 1.0, 3.0]) == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# query_cluster_distance (HTTP mocked)
# ---------------------------------------------------------------------------

class TestQueryClusterDistance:
    def _make_mock_response(self, text, status=200):
        resp = MagicMock()
        resp.text = text
        resp.raise_for_status = MagicMock()
        return resp

    def _make_mock_client(self, resp):
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.post = MagicMock(return_value=resp)
        return client

    def test_returns_distance_and_count_with_valid_data(self):
        # 5 parallax values around 2 mas => ~500 pc
        csv_text = "parallax\n2.0\n2.1\n1.9\n2.05\n1.95\n"
        resp = self._make_mock_response(csv_text)
        client = self._make_mock_client(resp)

        with patch("app.services.gaia.httpx.Client", return_value=client):
            result = query_cluster_distance(83.82, -5.39, 0.15)

        assert result is not None
        distance_pc, count = result
        assert count == 5
        # median parallax ~ 2.0 => 500 pc
        assert distance_pc == pytest.approx(500.0, rel=0.05)

    def test_returns_none_when_fewer_than_5_stars(self):
        csv_text = "parallax\n2.0\n2.1\n1.9\n"
        resp = self._make_mock_response(csv_text)
        client = self._make_mock_client(resp)

        with patch("app.services.gaia.httpx.Client", return_value=client):
            result = query_cluster_distance(83.82, -5.39, 0.15)

        assert result is None

    def test_returns_none_when_header_only(self):
        csv_text = "parallax\n"
        resp = self._make_mock_response(csv_text)
        client = self._make_mock_client(resp)

        with patch("app.services.gaia.httpx.Client", return_value=client):
            result = query_cluster_distance(83.82, -5.39, 0.15)

        assert result is None

    def test_raises_on_http_error(self):
        import httpx
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.post = MagicMock(side_effect=httpx.HTTPError("timeout"))

        with patch("app.services.gaia.httpx.Client", return_value=client):
            with pytest.raises(httpx.HTTPError):
                query_cluster_distance(83.82, -5.39, 0.15)

    def test_rejects_implausible_distance(self):
        # parallax of 0.000001 -> distance > 100000 pc -> rejected
        csv_text = "parallax\n" + "\n".join(["0.000001"] * 10) + "\n"
        resp = self._make_mock_response(csv_text)
        client = self._make_mock_client(resp)

        with patch("app.services.gaia.httpx.Client", return_value=client):
            result = query_cluster_distance(83.82, -5.39, 0.15)

        assert result is None


# ---------------------------------------------------------------------------
# enrich_target_from_gaia
# ---------------------------------------------------------------------------

class TestEnrichTargetFromGaia:
    def test_skips_non_cluster_type(self):
        session = MagicMock()
        target = MagicMock()
        target.object_type = "G"  # galaxy, not cluster

        result = enrich_target_from_gaia(session, target)
        assert result is False

    def test_skips_when_coordinates_missing(self):
        session = MagicMock()
        target = MagicMock()
        target.object_type = "OpC"
        target.ra = None
        target.dec = None

        result = enrich_target_from_gaia(session, target)
        assert result is False

    def test_uses_cached_distance(self):
        session = MagicMock()
        target = MagicMock()
        target.object_type = "OpC"
        target.ra = 83.82
        target.dec = -5.39
        target.distance_pc = None

        mock_cache = MagicMock()
        mock_cache.distance_pc = 450.0

        with patch("app.services.gaia.get_cached_gaia", return_value=mock_cache):
            result = enrich_target_from_gaia(session, target)

        assert result is True
        assert target.distance_pc == pytest.approx(450.0)

    def test_skips_when_cached_but_distance_already_set(self):
        session = MagicMock()
        target = MagicMock()
        target.object_type = "OpC"
        target.ra = 83.82
        target.dec = -5.39
        target.distance_pc = 500.0  # already set

        mock_cache = MagicMock()
        mock_cache.distance_pc = 450.0

        with patch("app.services.gaia.get_cached_gaia", return_value=mock_cache):
            result = enrich_target_from_gaia(session, target)

        assert result is False

    def test_queries_gaia_when_no_cache(self):
        session = MagicMock()
        target = MagicMock()
        target.object_type = "OpC"
        target.ra = 83.82
        target.dec = -5.39
        target.size_major = None
        target.distance_pc = None
        target.id = "test-uuid"

        payload = {"distance_pc": 450.0, "parallax_count": 20}
        with patch("app.services.gaia.get_cached_gaia", return_value=None), \
             patch("app.services.gaia.cc.get_or_fetch", return_value=payload) as mock_get_or_fetch:
            result = enrich_target_from_gaia(session, target)

        assert result is True
        assert target.distance_pc == pytest.approx(450.0)
        # Verify get_or_fetch was called with correct args
        mock_get_or_fetch.assert_called_once()
        call_args = mock_get_or_fetch.call_args
        assert call_args[0][1] == "gaia"  # source
        assert call_args[0][2] == "test-uuid"  # key
        session.commit.assert_called_once()

    def test_returns_false_when_gaia_query_empty(self):
        session = MagicMock()
        target = MagicMock()
        target.object_type = "OpC"
        target.ra = 83.82
        target.dec = -5.39
        target.size_major = None
        target.distance_pc = None
        target.id = "test-uuid"

        with patch("app.services.gaia.get_cached_gaia", return_value=None), \
             patch("app.services.gaia.cc.get_or_fetch", return_value=None) as mock_get_or_fetch:
            result = enrich_target_from_gaia(session, target)

        assert result is False
        mock_get_or_fetch.assert_called_once()
        session.commit.assert_called_once()

    def test_negative_cache_suppresses_refetch(self):
        """Verify that a negatively cached row (distance_pc is None) prevents refetch.

        This is the "negative cache still suppresses refetch" verification bar.
        A target with a negative cache entry should return False without making
        an HTTP call to query_cluster_distance.
        """
        session = MagicMock()
        target = MagicMock()
        target.object_type = "OpC"
        target.ra = 83.82
        target.dec = -5.39
        target.distance_pc = None

        # Return a cached object with distance_pc=None (negative cache)
        from app.services.gaia import _CachedPayload
        mock_cache = _CachedPayload(distance_pc=None)

        with patch("app.services.gaia.get_cached_gaia", return_value=mock_cache), \
             patch("app.services.gaia.query_cluster_distance") as mock_query:
            result = enrich_target_from_gaia(session, target)

        # Should return False (no update, no distance data)
        assert result is False
        # Should NOT call query_cluster_distance (negative cache suppresses refetch)
        mock_query.assert_not_called()
        # Should NOT commit (didn't cache anything new)
        session.commit.assert_not_called()
