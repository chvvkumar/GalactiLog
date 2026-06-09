"""Unit tests for app.services.hyperleda - galaxy detection, name normalization, HTML parsing."""
import sys
from unittest.mock import MagicMock

# hyperleda.py imports HyperLEDACache at module level; stub it out so the
# import succeeds even when the model file doesn't exist on this branch.
if "app.models.hyperleda_cache" not in sys.modules:
    sys.modules["app.models.hyperleda_cache"] = MagicMock()

import pytest
from unittest.mock import patch

from app.services.hyperleda import (
    _is_galaxy_type,
    _hyperleda_name,
    _extract_param_value,
    query_hyperleda,
    enrich_target_from_hyperleda,
)


# ---------------------------------------------------------------------------
# _is_galaxy_type
# ---------------------------------------------------------------------------

class TestIsGalaxyType:
    def test_galaxy_token(self):
        assert _is_galaxy_type("G") is True

    def test_agn_token(self):
        assert _is_galaxy_type("AGN") is True

    def test_seyfert1_token(self):
        assert _is_galaxy_type("Sy1") is True

    def test_seyfert2_token(self):
        assert _is_galaxy_type("Sy2") is True

    def test_comma_separated_tokens(self):
        assert _is_galaxy_type("HII,G") is True

    def test_pipe_separated_tokens(self):
        assert _is_galaxy_type("OpC|G") is True

    def test_non_galaxy_type(self):
        assert _is_galaxy_type("OpC") is False

    def test_none_returns_false(self):
        assert _is_galaxy_type(None) is False

    def test_empty_string_returns_false(self):
        assert _is_galaxy_type("") is False

    def test_galaxy_group(self):
        assert _is_galaxy_type("GGroup") is True


# ---------------------------------------------------------------------------
# _hyperleda_name
# ---------------------------------------------------------------------------

class TestHyperledaName:
    def test_lowercases_ngc(self):
        assert _hyperleda_name("NGC 224") == "ngc224"

    def test_removes_spaces(self):
        assert _hyperleda_name("M 31") == "m31"

    def test_already_lower_no_spaces(self):
        assert _hyperleda_name("ic1011") == "ic1011"


# ---------------------------------------------------------------------------
# _extract_param_value
# ---------------------------------------------------------------------------

class TestExtractParamValue:
    _html_template = (
        '<td><a href="leda/param/t.html">t</a></td>'
        '<td>  4.0 &#177; 0.2</td>'
        '<td><a href="leda/param/incl.html">incl</a></td>'
        '<td>  67.3 &#177; 1.0</td>'
    )

    def test_extracts_t_type(self):
        val = _extract_param_value(self._html_template, "t")
        assert val == pytest.approx(4.0)

    def test_extracts_inclination(self):
        val = _extract_param_value(self._html_template, "incl")
        assert val == pytest.approx(67.3)

    def test_returns_none_for_missing_param(self):
        val = _extract_param_value(self._html_template, "dist")
        assert val is None

    def test_handles_negative_value(self):
        html = '<td><a href="x">t</a></td><td>-2.5</td>'
        val = _extract_param_value(html, "t")
        assert val == pytest.approx(-2.5)

    def test_returns_none_for_empty_cell(self):
        html = '<td><a href="x">t</a></td><td></td>'
        val = _extract_param_value(html, "t")
        assert val is None

    def test_returns_none_on_non_numeric(self):
        html = '<td><a href="x">t</a></td><td>  N/A  </td>'
        val = _extract_param_value(html, "t")
        assert val is None


# ---------------------------------------------------------------------------
# query_hyperleda (HTTP mocked)
# ---------------------------------------------------------------------------

class TestQueryHyperleda:
    def _make_client(self, html_text, status=200):
        resp = MagicMock()
        resp.text = html_text
        resp.raise_for_status = MagicMock()
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get = MagicMock(return_value=resp)
        return client

    def test_returns_dict_on_valid_html(self):
        html = (
            '<td><a href="x">t</a></td><td>3.0</td>'
            '<td><a href="x">incl</a></td><td>55.0</td>'
        )
        client = self._make_client(html)
        with patch("app.services.hyperleda.httpx.Client", return_value=client):
            result = query_hyperleda("NGC 224")

        assert result is not None
        assert result["t_type"] == pytest.approx(3.0)
        assert result["inclination"] == pytest.approx(55.0)

    def test_returns_none_when_no_record(self):
        client = self._make_client("returns no record in the database")
        with patch("app.services.hyperleda.httpx.Client", return_value=client):
            result = query_hyperleda("NGC 9999")

        assert result is None

    def test_returns_none_when_both_params_absent(self):
        client = self._make_client("<html>no matching params here</html>")
        with patch("app.services.hyperleda.httpx.Client", return_value=client):
            result = query_hyperleda("NGC 9999")

        assert result is None

    def test_returns_none_on_http_error(self):
        import httpx
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get = MagicMock(side_effect=httpx.HTTPError("connection refused"))
        with patch("app.services.hyperleda.httpx.Client", return_value=client):
            result = query_hyperleda("NGC 224")

        assert result is None

    def test_partial_result_returned(self):
        # Only inclination available, t_type absent
        html = '<td><a href="x">incl</a></td><td>72.0</td>'
        client = self._make_client(html)
        with patch("app.services.hyperleda.httpx.Client", return_value=client):
            result = query_hyperleda("NGC 224")

        assert result is not None
        assert result["inclination"] == pytest.approx(72.0)
        assert result["t_type"] is None


# ---------------------------------------------------------------------------
# enrich_target_from_hyperleda
# ---------------------------------------------------------------------------

class TestEnrichTargetFromHyperleda:
    def test_skips_non_galaxy_type(self):
        session = MagicMock()
        target = MagicMock()
        target.object_type = "OpC"

        result = enrich_target_from_hyperleda(session, target)
        assert result is False

    def test_skips_when_no_catalog_id(self):
        session = MagicMock()
        target = MagicMock()
        target.object_type = "G"
        target.catalog_id = None

        result = enrich_target_from_hyperleda(session, target)
        assert result is False

    def test_uses_cached_data(self):
        session = MagicMock()
        target = MagicMock()
        target.object_type = "G"
        target.catalog_id = "NGC 224"
        target.hubble_t_type = None
        target.inclination = None

        mock_cache = MagicMock()
        mock_cache.t_type = 3.0
        mock_cache.inclination = 55.0

        with patch("app.services.hyperleda.get_cached_hyperleda", return_value=mock_cache):
            result = enrich_target_from_hyperleda(session, target)

        assert result is True
        assert target.hubble_t_type == pytest.approx(3.0)
        assert target.inclination == pytest.approx(55.0)

    def test_does_not_overwrite_existing_t_type(self):
        session = MagicMock()
        target = MagicMock()
        target.object_type = "G"
        target.catalog_id = "NGC 224"
        target.hubble_t_type = 5.0  # already set
        target.inclination = None

        mock_cache = MagicMock()
        mock_cache.t_type = 3.0
        mock_cache.inclination = 55.0

        with patch("app.services.hyperleda.get_cached_hyperleda", return_value=mock_cache):
            result = enrich_target_from_hyperleda(session, target)

        # Only inclination updated
        assert result is True
        assert target.hubble_t_type == 5.0  # unchanged

    def test_negative_cache_returns_false(self):
        session = MagicMock()
        target = MagicMock()
        target.object_type = "G"
        target.catalog_id = "NGC 224"

        mock_cache = MagicMock()
        mock_cache.t_type = None
        mock_cache.inclination = None

        with patch("app.services.hyperleda.get_cached_hyperleda", return_value=mock_cache):
            result = enrich_target_from_hyperleda(session, target)

        assert result is False

    def test_queries_hyperleda_when_no_cache(self):
        session = MagicMock()
        target = MagicMock()
        target.object_type = "G"
        target.catalog_id = "NGC 224"
        target.hubble_t_type = None
        target.inclination = None

        data = {"t_type": 3.0, "inclination": 55.0}

        with patch("app.services.hyperleda.get_cached_hyperleda", return_value=None), \
             patch("app.services.hyperleda.query_hyperleda", return_value=data), \
             patch("app.services.hyperleda.save_hyperleda_cache") as mock_save:
            result = enrich_target_from_hyperleda(session, target)

        assert result is True
        mock_save.assert_called_once()
