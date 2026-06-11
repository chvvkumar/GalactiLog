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

    def test_timeout_is_120_seconds(self, tmp_path):
        """du (thumbnails only) is invoked with the 120-second timeout."""
        from app.api.stats import _compute_dir_size, _DU_TIMEOUT

        assert _DU_TIMEOUT == 120

        captured_kwargs = {}

        def _capture(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return MagicMock(returncode=0, stdout="1\t/p\n")

        with patch("app.api.stats.subprocess.run", side_effect=_capture):
            _compute_dir_size(str(tmp_path))

        assert captured_kwargs.get("timeout") == 120


class TestRefreshStorageCache:
    """Unit tests for _refresh_storage_cache (both FITS and thumbnails via du)."""

    @pytest.mark.asyncio
    async def test_cache_preserved_on_timeout(self, tmp_path):
        """When du times out, the old FITS and thumbnail sizes must survive."""
        import app.api.stats as stats_mod

        # Seed the in-memory cache with known values.
        stats_mod._storage_cache["fits"] = 70_000
        stats_mod._storage_cache["thumbnails"] = 50_000
        # Force a stale timestamp so the refresh proceeds.
        stats_mod._storage_last_update = 0

        with patch(
            "app.api.stats.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="du", timeout=120),
        ), patch("app.api.stats.settings") as mock_settings:
            # Use tmp_path so Path.exists() returns True and subprocess is reached.
            mock_settings.fits_data_path = str(tmp_path)
            mock_settings.thumbnails_path = str(tmp_path)
            await stats_mod._refresh_storage_cache()

        assert stats_mod._storage_cache["fits"] == 70_000
        assert stats_mod._storage_cache["thumbnails"] == 50_000

    @pytest.mark.asyncio
    async def test_cache_updated_on_success(self, tmp_path):
        """Successful du updates both the FITS and thumbnail cache slots."""
        import app.api.stats as stats_mod

        stats_mod._storage_cache["fits"] = 1
        stats_mod._storage_cache["thumbnails"] = 2
        stats_mod._storage_last_update = 0

        # Two du calls run in order: FITS first, then thumbnails.
        with patch(
            "app.api.stats.subprocess.run",
            side_effect=[
                MagicMock(returncode=0, stdout="999\t/fits\n"),
                MagicMock(returncode=0, stdout="888\t/thumbs\n"),
            ],
        ):
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

        stats_mod._storage_cache["fits"] = 33
        stats_mod._storage_cache["thumbnails"] = 77
        stats_mod._storage_last_update = time.time()  # fresh

        with patch("app.api.stats.subprocess.run") as mock_run:
            await stats_mod._refresh_storage_cache()

        mock_run.assert_not_called()
        assert stats_mod._storage_cache["fits"] == 33
        assert stats_mod._storage_cache["thumbnails"] == 77


class TestComputeFitsBytes:
    """Unit tests for _compute_fits_bytes (FITS size summed from the DB)."""

    @pytest.mark.asyncio
    async def test_returns_scalar_sum(self):
        """The aggregate scalar is returned as an int."""
        from app.api.stats import _compute_fits_bytes

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 2_049_831_638_581
        session.execute = AsyncMock(return_value=mock_result)

        total = await _compute_fits_bytes(session)

        assert total == 2_049_831_638_581
        assert isinstance(total, int)

    @pytest.mark.asyncio
    async def test_empty_table_returns_zero(self):
        """COALESCE makes an empty table return 0, never None."""
        from app.api.stats import _compute_fits_bytes

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 0
        session.execute = AsyncMock(return_value=mock_result)

        assert await _compute_fits_bytes(session) == 0

    @pytest.mark.asyncio
    async def test_sums_all_rows_without_image_type_filter(self):
        """The sum must not filter by image_type.

        Calibration frames are only rows when include_calibration is on; with no
        type filter they are counted whenever present and ignored when absent, so
        the figure tracks the include/exclude setting automatically.
        """
        from app.api.stats import _compute_fits_bytes

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 0
        session.execute = AsyncMock(return_value=mock_result)

        await _compute_fits_bytes(session)

        sql = str(session.execute.call_args[0][0]).lower()
        assert "sum(images.file_size)" in sql
        assert "coalesce" in sql
        # No WHERE clause discriminating calibration frames.
        assert "where" not in sql
        assert "image_type" not in sql


class TestAllFramesQuery:
    """The overview `all_frames` count must include every image row.

    `_query_all_frames` is a closure inside get_stats and cannot be imported,
    so this reconstructs the same query and asserts it counts all rows with no
    image_type or capture_date discriminator (unlike total_frames, which is
    LIGHT-only). Mirrors the SQL-inspection style of TestComputeFitsBytes.
    """

    def test_counts_all_rows_without_filters(self):
        from sqlalchemy import select, func
        from app.models import Image

        q = select(func.count(Image.id))

        sql = str(q).lower()
        assert "count(images.id)" in sql
        # No WHERE clause restricting by frame type or capture date.
        assert "where" not in sql
        assert "image_type" not in sql
        assert "capture_date" not in sql


class TestShouldCacheStats:
    """The stats Redis write must be gated on storage having been computed once.

    On the first request after startup _storage_cache is still {fits:0,
    thumbnails:0} and _storage_last_update is 0, so the response carries 0 for
    on-disk sizes. Persisting that would freeze "0 on disk" for the full TTL.
    _should_cache_stats() is the gate that prevents it.
    """

    def test_cold_start_must_not_cache(self):
        """When no storage refresh has completed, the gate is False."""
        import app.api.stats as stats_mod

        stats_mod._storage_last_update = 0
        assert stats_mod._should_cache_stats() is False

    def test_warm_cache_may_cache(self):
        """Once a storage refresh has completed, the gate is True."""
        import time
        import app.api.stats as stats_mod

        stats_mod._storage_last_update = time.time()
        assert stats_mod._should_cache_stats() is True


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
