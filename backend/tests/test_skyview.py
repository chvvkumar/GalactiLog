"""Unit tests for app.services.skyview - FOV computation and HTTP mocking."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.skyview import (
    _compute_fov,
    fetch_reference_thumbnail,
)


# ---------------------------------------------------------------------------
# _compute_fov
# ---------------------------------------------------------------------------

class TestComputeFov:
    def test_default_when_size_major_is_none(self):
        target = MagicMock()
        target.size_major = None
        assert _compute_fov(target) == pytest.approx(0.5)

    def test_calculated_fov(self):
        target = MagicMock()
        target.size_major = 60.0  # arcmin
        # fov = 60 * 1.5 / 60 = 1.5 deg
        assert _compute_fov(target) == pytest.approx(1.5)

    def test_minimum_clamped(self):
        target = MagicMock()
        target.size_major = 1.0  # very small -> would be 0.025, clamped to 0.1
        assert _compute_fov(target) == pytest.approx(0.1)

    def test_maximum_clamped(self):
        target = MagicMock()
        target.size_major = 600.0  # 600 arcmin -> 15 deg, clamped to 5.0
        assert _compute_fov(target) == pytest.approx(5.0)

    def test_boundary_at_minimum(self):
        # size_major = 4 arcmin -> fov = 4*1.5/60 = 0.1 exact
        target = MagicMock()
        target.size_major = 4.0
        assert _compute_fov(target) == pytest.approx(0.1)

    def test_boundary_at_maximum(self):
        # size_major = 200 arcmin -> fov = 200*1.5/60 = 5.0 exact
        target = MagicMock()
        target.size_major = 200.0
        assert _compute_fov(target) == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# fetch_reference_thumbnail (HTTP mocked)
# ---------------------------------------------------------------------------

class TestFetchReferenceThumbnail:
    def _make_target(self, ra=83.82, dec=-5.39, size_major=None, tid="target-1"):
        target = MagicMock()
        target.id = tid
        target.ra = ra
        target.dec = dec
        target.size_major = size_major
        return target

    def _make_client(self, content=b"JPEG_BYTES", raise_exc=None):
        resp = MagicMock()
        resp.content = content
        resp.raise_for_status = MagicMock()

        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        if raise_exc:
            client.get = MagicMock(side_effect=raise_exc)
        else:
            client.get = MagicMock(return_value=resp)
        return client

    def test_returns_filename_on_success(self, tmp_path):
        target = self._make_target()
        client = self._make_client()
        with patch("app.services.skyview.httpx.Client", return_value=client):
            result = fetch_reference_thumbnail(target, tmp_path)

        assert result == "target-1.jpg"
        assert (tmp_path / "target-1.jpg").exists()

    def test_file_written_with_response_bytes(self, tmp_path):
        target = self._make_target()
        client = self._make_client(content=b"FAKE_JPEG_DATA")
        with patch("app.services.skyview.httpx.Client", return_value=client):
            fetch_reference_thumbnail(target, tmp_path)

        assert (tmp_path / "target-1.jpg").read_bytes() == b"FAKE_JPEG_DATA"

    def test_returns_none_when_ra_missing(self, tmp_path):
        target = self._make_target(ra=None)
        result = fetch_reference_thumbnail(target, tmp_path)
        assert result is None

    def test_returns_none_when_dec_missing(self, tmp_path):
        target = self._make_target(dec=None)
        result = fetch_reference_thumbnail(target, tmp_path)
        assert result is None

    def test_returns_none_on_http_error(self, tmp_path):
        import httpx
        target = self._make_target()
        client = self._make_client(raise_exc=httpx.HTTPError("timeout"))
        with patch("app.services.skyview.httpx.Client", return_value=client):
            result = fetch_reference_thumbnail(target, tmp_path)

        assert result is None

    def test_creates_output_dir(self, tmp_path):
        target = self._make_target()
        nested_dir = tmp_path / "a" / "b"
        client = self._make_client()
        with patch("app.services.skyview.httpx.Client", return_value=client):
            result = fetch_reference_thumbnail(target, nested_dir)

        assert result == "target-1.jpg"
        assert nested_dir.exists()

    def test_passes_correct_survey_params(self, tmp_path):
        target = self._make_target(ra=10.68, dec=41.27, size_major=30.0)
        client = self._make_client()
        with patch("app.services.skyview.httpx.Client", return_value=client):
            fetch_reference_thumbnail(target, tmp_path)

        call_kwargs = client.__enter__().get.call_args
        params = call_kwargs[1]["params"] if "params" in call_kwargs[1] else call_kwargs[0][1]
        assert params["Survey"] == "DSS2 Red"
        assert params["Pixels"] == "512"
        assert params["Return"] == "JPEG"
