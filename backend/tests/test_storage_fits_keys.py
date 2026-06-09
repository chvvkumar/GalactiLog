"""Tests for storage-size fallback (PERF-7) and fits-keys caching (PERF-8)."""
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# PERF-7: _compute_dir_size + _refresh_storage_cache
# ---------------------------------------------------------------------------

class TestComputeDirSize:
    """Unit tests for _compute_dir_size."""

    def test_returns_size_on_success(self, tmp_path):
        """Normal du run returns parsed byte count."""
        from app.api.stats import _compute_dir_size

        with patch("app.api.stats.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="12345\t/some/path\n")
            result = _compute_dir_size(str(tmp_path), fallback=999)

        assert result == 12345

    def test_returns_fallback_on_timeout(self, tmp_path):
        """TimeoutExpired causes fallback value to be returned, not 0."""
        from app.api.stats import _compute_dir_size

        with patch("app.api.stats.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="du", timeout=12)):
            result = _compute_dir_size(str(tmp_path), fallback=42000)

        assert result == 42000

    def test_returns_fallback_on_nonzero_returncode(self, tmp_path):
        """Non-zero returncode falls through to return fallback."""
        from app.api.stats import _compute_dir_size

        with patch("app.api.stats.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            result = _compute_dir_size(str(tmp_path), fallback=7777)

        assert result == 7777

    def test_returns_fallback_on_generic_exception(self, tmp_path):
        """Any unexpected exception returns the fallback."""
        from app.api.stats import _compute_dir_size

        with patch("app.api.stats.subprocess.run", side_effect=OSError("permission denied")):
            result = _compute_dir_size(str(tmp_path), fallback=555)

        assert result == 555

    def test_returns_zero_for_nonexistent_path(self):
        """Non-existent path returns 0 (no subprocess call, no fallback needed)."""
        from app.api.stats import _compute_dir_size

        with patch("app.api.stats.subprocess.run") as mock_run:
            result = _compute_dir_size("/definitely/does/not/exist/xyz", fallback=99)

        mock_run.assert_not_called()
        assert result == 0

    def test_timeout_is_12_seconds(self, tmp_path):
        """du is invoked with the 12-second timeout, not the old 120."""
        from app.api.stats import _compute_dir_size, _DU_TIMEOUT

        assert _DU_TIMEOUT == 12

        captured_kwargs = {}

        def _capture(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return MagicMock(returncode=0, stdout="1\t/p\n")

        with patch("app.api.stats.subprocess.run", side_effect=_capture):
            _compute_dir_size(str(tmp_path))

        assert captured_kwargs.get("timeout") == 12


class TestRefreshStorageCache:
    """Unit tests for _refresh_storage_cache."""

    @pytest.mark.asyncio
    async def test_cache_preserved_on_timeout(self, tmp_path):
        """When du times out, the old cached value must survive in _storage_cache."""
        import app.api.stats as stats_mod

        # Seed the in-memory cache with known values.
        stats_mod._storage_cache["fits"] = 100_000
        stats_mod._storage_cache["thumbnails"] = 50_000
        # Force a stale timestamp so the refresh proceeds.
        stats_mod._storage_last_update = 0

        with patch(
            "app.api.stats.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="du", timeout=12),
        ), patch("app.api.stats.settings") as mock_settings:
            # Use tmp_path so Path.exists() returns True and subprocess is reached.
            mock_settings.fits_data_path = str(tmp_path)
            mock_settings.thumbnails_path = str(tmp_path)
            await stats_mod._refresh_storage_cache()

        assert stats_mod._storage_cache["fits"] == 100_000
        assert stats_mod._storage_cache["thumbnails"] == 50_000

    @pytest.mark.asyncio
    async def test_cache_updated_on_success(self, tmp_path):
        """Successful du updates both cache slots."""
        import app.api.stats as stats_mod

        stats_mod._storage_cache["fits"] = 1
        stats_mod._storage_cache["thumbnails"] = 2
        stats_mod._storage_last_update = 0

        call_seq = iter([
            MagicMock(returncode=0, stdout="999\t/fits\n"),
            MagicMock(returncode=0, stdout="888\t/thumbs\n"),
        ])

        with patch("app.api.stats.subprocess.run", side_effect=lambda *a, **kw: next(call_seq)):
            with patch("app.api.stats.settings") as mock_settings:
                mock_settings.fits_data_path = str(tmp_path)
                mock_settings.thumbnails_path = str(tmp_path)
                await stats_mod._refresh_storage_cache()

        assert stats_mod._storage_cache["fits"] == 999
        assert stats_mod._storage_cache["thumbnails"] == 888

    @pytest.mark.asyncio
    async def test_no_refresh_within_ttl(self):
        """If the cache is still fresh, _refresh_storage_cache is a no-op."""
        import time
        import app.api.stats as stats_mod

        stats_mod._storage_cache["fits"] = 77
        stats_mod._storage_last_update = time.time()  # fresh

        with patch("app.api.stats.subprocess.run") as mock_run:
            await stats_mod._refresh_storage_cache()

        mock_run.assert_not_called()
        assert stats_mod._storage_cache["fits"] == 77


# ---------------------------------------------------------------------------
# PERF-8: get_distinct_fits_keys
# ---------------------------------------------------------------------------

class TestGetDistinctFitsKeys:
    """Unit tests for get_distinct_fits_keys."""

    @pytest.mark.asyncio
    async def test_returns_sorted_list(self):
        """Query result rows are returned as a flat sorted list of strings."""
        from app.services.fits_headers import get_distinct_fits_keys

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [("BITPIX",), ("DATE-OBS",), ("EXPTIME",)]
        session.execute = AsyncMock(return_value=mock_result)

        keys = await get_distinct_fits_keys(session)

        assert keys == ["BITPIX", "DATE-OBS", "EXPTIME"]

    @pytest.mark.asyncio
    async def test_empty_table_returns_empty_list(self):
        """No rows in images table yields an empty list without error."""
        from app.services.fits_headers import get_distinct_fits_keys

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        session.execute = AsyncMock(return_value=mock_result)

        keys = await get_distinct_fits_keys(session)

        assert keys == []

    @pytest.mark.asyncio
    async def test_uses_correct_sql(self):
        """The query text contains the expected DISTINCT + jsonb_object_keys pattern."""
        from app.services.fits_headers import get_distinct_fits_keys
        from sqlalchemy import text

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        session.execute = AsyncMock(return_value=mock_result)

        await get_distinct_fits_keys(session)

        call_args = session.execute.call_args
        sql_obj = call_args[0][0]
        # Verify it uses raw SQL text (not ORM) with the expected pattern.
        assert hasattr(sql_obj, "text") or "jsonb_object_keys" in str(sql_obj)
        query_str = str(sql_obj)
        assert "DISTINCT" in query_str
        assert "jsonb_object_keys" in query_str
        assert "ORDER BY" in query_str
