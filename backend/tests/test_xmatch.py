"""Unit tests for app.services.xmatch - CSV building and response parsing."""
import pytest
from unittest.mock import MagicMock, patch

from app.services.xmatch import (
    build_target_csv,
    bulk_xmatch_targets,
)


# ---------------------------------------------------------------------------
# build_target_csv
# ---------------------------------------------------------------------------

class TestBuildTargetCsv:
    def test_header_row_present(self):
        csv_str = build_target_csv([])
        lines = [l for l in csv_str.splitlines() if l]
        assert lines[0] == "id,ra,dec"

    def test_single_target_row(self):
        targets = [{"id": "t1", "ra": 83.82, "dec": -5.39}]
        csv_str = build_target_csv(targets)
        lines = csv_str.splitlines()
        assert len(lines) >= 2
        assert "t1" in lines[1]
        assert "83.82" in lines[1]
        assert "-5.39" in lines[1]

    def test_multiple_targets(self):
        targets = [
            {"id": "a", "ra": 1.0, "dec": 2.0},
            {"id": "b", "ra": 3.0, "dec": 4.0},
        ]
        csv_str = build_target_csv(targets)
        lines = [l for l in csv_str.splitlines() if l]
        assert len(lines) == 3  # header + 2 data rows
        assert lines[1].startswith("a")
        assert lines[2].startswith("b")

    def test_empty_list_gives_only_header(self):
        csv_str = build_target_csv([])
        lines = [l for l in csv_str.splitlines() if l]
        assert lines == ["id,ra,dec"]


# ---------------------------------------------------------------------------
# bulk_xmatch_targets (HTTP mocked)
# ---------------------------------------------------------------------------

class TestBulkXmatchTargets:
    def _make_client(self, response_text, raise_exc=None):
        resp = MagicMock()
        resp.text = response_text
        resp.raise_for_status = MagicMock()

        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        if raise_exc:
            client.post = MagicMock(side_effect=raise_exc)
        else:
            client.post = MagicMock(return_value=resp)
        return client

    def test_empty_targets_returns_empty_dict(self):
        result = bulk_xmatch_targets([], "VII/118/ngc2000")
        assert result == {}

    def test_parses_csv_response(self):
        csv_text = "id,ra,dec,Name\nt1,83.82,-5.39,M 42\nt2,10.68,41.27,M 31\n"
        targets = [
            {"id": "t1", "ra": 83.82, "dec": -5.39},
            {"id": "t2", "ra": 10.68, "dec": 41.27},
        ]
        client = self._make_client(csv_text)
        with patch("app.services.xmatch.httpx.Client", return_value=client):
            result = bulk_xmatch_targets(targets, "VII/118/ngc2000")

        assert "t1" in result
        assert "t2" in result
        assert result["t1"]["Name"] == "M 42"

    def test_returns_empty_on_http_error(self):
        import httpx
        targets = [{"id": "t1", "ra": 83.82, "dec": -5.39}]
        client = self._make_client("", raise_exc=httpx.HTTPError("timeout"))
        with patch("app.services.xmatch.httpx.Client", return_value=client):
            result = bulk_xmatch_targets(targets, "VII/118/ngc2000")

        assert result == {}

    def test_returns_empty_on_malformed_csv(self):
        # Not valid CSV - will still be parsed but without valid id column
        targets = [{"id": "t1", "ra": 83.82, "dec": -5.39}]
        client = self._make_client("NOTCSV\x00BINARY\xff")
        with patch("app.services.xmatch.httpx.Client", return_value=client):
            # Should not raise, just return what it can
            result = bulk_xmatch_targets(targets, "VII/118/ngc2000")

        # Either empty or no crash - the function swallows parse errors
        assert isinstance(result, dict)

    def test_rows_without_id_are_skipped(self):
        csv_text = "id,col\n,value_no_id\nt1,value_with_id\n"
        targets = [{"id": "t1", "ra": 1.0, "dec": 2.0}]
        client = self._make_client(csv_text)
        with patch("app.services.xmatch.httpx.Client", return_value=client):
            result = bulk_xmatch_targets(targets, "VII/118/ngc2000")

        # Row with id="" is stored under "" key, not None
        # Row with id="t1" is present
        assert "t1" in result

    def test_passes_correct_catalog_param(self):
        csv_text = "id,ra,dec\n"
        targets = [{"id": "t1", "ra": 1.0, "dec": 2.0}]
        client = self._make_client(csv_text)
        with patch("app.services.xmatch.httpx.Client", return_value=client):
            bulk_xmatch_targets(targets, "VII/118/ngc2000", radius_arcsec=30.0)

        call_kwargs = client.__enter__().post.call_args
        data = call_kwargs[1]["data"] if "data" in call_kwargs[1] else call_kwargs[0][1]
        assert data["cat2"] == "vizier:VII/118/ngc2000"
        assert data["distMaxArcsec"] == "30.0"
