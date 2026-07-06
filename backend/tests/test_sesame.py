"""Unit tests for app.services.sesame - XML parsing, cache helpers, and resolution."""
import pytest
import xml.etree.ElementTree as ET
from unittest.mock import AsyncMock, MagicMock, patch, Mock

from app.services.sesame import (
    _query_sesame_raw,
    get_cached_sesame,
    save_sesame_cache,
    resolve_sesame_cached,
)


# ---------------------------------------------------------------------------
# _query_sesame_raw (async, HTTP mocked)
# ---------------------------------------------------------------------------

_SESAME_XML_HIT = """\
<?xml version="1.0" encoding="UTF-8"?>
<Sesame>
  <Target>
    <Resolver name="S=Simbad">
      <jradeg>83.82208</jradeg>
      <jdedeg>-5.39111</jdedeg>
      <oname>M 42</oname>
      <otype>HII</otype>
      <alias>NGC 1976</alias>
      <alias>Orion Nebula</alias>
    </Resolver>
  </Target>
</Sesame>
"""

_SESAME_XML_MISS = """\
<?xml version="1.0" encoding="UTF-8"?>
<Sesame>
  <Target/>
</Sesame>
"""


def _make_async_client(text, raise_error=None):
    resp = MagicMock()
    resp.text = text
    resp.raise_for_status = MagicMock()

    client = AsyncMock()
    if raise_error:
        client.get = AsyncMock(side_effect=raise_error)
    else:
        client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


class TestQuerySesameRaw:
    @pytest.mark.asyncio
    async def test_parses_successful_response(self):
        client = _make_async_client(_SESAME_XML_HIT)
        with patch("app.services.sesame.httpx.AsyncClient", return_value=client):
            result = await _query_sesame_raw("M 42")

        assert result is not None
        assert result["main_id"] == "M 42"
        assert result["ra"] == pytest.approx(83.82208)
        assert result["dec"] == pytest.approx(-5.39111)
        assert result["object_type"] == "HII"
        assert "NGC 1976" in result["raw_aliases"]
        assert "Orion Nebula" in result["raw_aliases"]

    @pytest.mark.asyncio
    async def test_returns_none_when_no_resolver_matches(self):
        client = _make_async_client(_SESAME_XML_MISS)
        with patch("app.services.sesame.httpx.AsyncClient", return_value=client):
            result = await _query_sesame_raw("XYZNOTREAL")

        assert result is None

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self):
        import httpx
        client = _make_async_client("", raise_error=httpx.HTTPError("timeout"))
        with patch("app.services.sesame.httpx.AsyncClient", return_value=client):
            with pytest.raises(httpx.HTTPError):
                await _query_sesame_raw("M 42")

    @pytest.mark.asyncio
    async def test_returns_none_on_parse_error(self):
        client = _make_async_client("THIS IS NOT XML")
        with patch("app.services.sesame.httpx.AsyncClient", return_value=client):
            result = await _query_sesame_raw("M 42")

        assert result is None

    @pytest.mark.asyncio
    async def test_skips_resolver_with_no_coordinates(self):
        # Resolver element with no jradeg/jdedeg should be skipped
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<Sesame>
  <Target>
    <Resolver name="S=Simbad">
      <oname>M 42</oname>
    </Resolver>
  </Target>
</Sesame>
"""
        client = _make_async_client(xml)
        with patch("app.services.sesame.httpx.AsyncClient", return_value=client):
            result = await _query_sesame_raw("M 42")

        assert result is None

    @pytest.mark.asyncio
    async def test_uses_object_name_as_fallback_for_oname(self):
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<Sesame>
  <Target>
    <Resolver name="N=NED">
      <jradeg>10.0</jradeg>
      <jdedeg>20.0</jdedeg>
    </Resolver>
  </Target>
</Sesame>
"""
        client = _make_async_client(xml)
        with patch("app.services.sesame.httpx.AsyncClient", return_value=client):
            result = await _query_sesame_raw("some object")

        assert result is not None
        assert result["main_id"] == "some object"


# ---------------------------------------------------------------------------
# get_cached_sesame and save_sesame_cache (database tests)
# ---------------------------------------------------------------------------

class TestGetCachedSesameAndSave:
    @pytest.fixture(autouse=True)
    def setup(self):
        """Clear catalog_cache before each test."""
        from app.database import sync_engine
        from app.models.catalog_cache import CatalogCache
        from sqlalchemy.orm import Session

        with Session(sync_engine) as session:
            session.query(CatalogCache).filter(CatalogCache.source == "sesame").delete()
            session.commit()
        yield
        with Session(sync_engine) as session:
            session.query(CatalogCache).filter(CatalogCache.source == "sesame").delete()
            session.commit()

    def test_returns_none_when_not_in_cache(self):
        from app.database import sync_engine
        from sqlalchemy.orm import Session

        with Session(sync_engine) as session:
            result = get_cached_sesame("NOTCACHED", session)
            assert result is None

    def test_returns_negative_marker_on_negative_cache_hit(self):
        from app.database import sync_engine
        from sqlalchemy.orm import Session

        with Session(sync_engine) as session:
            save_sesame_cache("NOTFOUND", None, session)
            session.commit()

        with Session(sync_engine) as session:
            result = get_cached_sesame("NOTFOUND", session)
            assert result == {"_negative": True}

    def test_returns_dict_on_positive_cache_hit(self):
        from app.database import sync_engine
        from sqlalchemy.orm import Session

        data = {
            "main_id": "M 42",
            "raw_aliases": ["NGC 1976"],
            "ra": 83.82,
            "dec": -5.39,
            "object_type": "HII",
            "resolver": "S=Simbad",
        }
        with Session(sync_engine) as session:
            save_sesame_cache("M 42", data, session)
            session.commit()

        with Session(sync_engine) as session:
            result = get_cached_sesame("M 42", session)
            assert result is not None
            assert result["main_id"] == "M 42"
            assert result["ra"] == pytest.approx(83.82)
            assert result["object_type"] == "HII"
            assert result["resolver"] == "S=Simbad"
            assert "NGC 1976" in result["raw_aliases"]

    def test_save_positive_and_retrieve(self):
        from app.database import sync_engine
        from sqlalchemy.orm import Session

        data = {
            "main_id": "NGC 1976",
            "raw_aliases": ["Orion Nebula"],
            "ra": 83.82,
            "dec": -5.39,
            "object_type": "EmissionNebula",
            "resolver": "N=NED",
        }
        with Session(sync_engine) as session:
            save_sesame_cache("NGC 1976", data, session)
            session.commit()

        with Session(sync_engine) as session:
            cached = get_cached_sesame("NGC 1976", session)
            assert cached["main_id"] == "NGC 1976"
            assert cached["resolver"] == "N=NED"

    def test_save_negative_and_retrieve(self):
        from app.database import sync_engine
        from sqlalchemy.orm import Session

        with Session(sync_engine) as session:
            save_sesame_cache("XYZNOTREAL", None, session)
            session.commit()

        with Session(sync_engine) as session:
            cached = get_cached_sesame("XYZNOTREAL", session)
            assert cached == {"_negative": True}


# ---------------------------------------------------------------------------
# resolve_sesame_cached with negative cache suppression
# ---------------------------------------------------------------------------

class TestResolveSesameNegativeCache:
    @pytest.fixture(autouse=True)
    def setup(self):
        """Clear catalog_cache before each test."""
        from app.database import sync_engine
        from app.models.catalog_cache import CatalogCache
        from sqlalchemy.orm import Session

        with Session(sync_engine) as session:
            session.query(CatalogCache).filter(CatalogCache.source == "sesame").delete()
            session.commit()
        yield
        with Session(sync_engine) as session:
            session.query(CatalogCache).filter(CatalogCache.source == "sesame").delete()
            session.commit()

    def test_negative_cache_suppresses_refetch(self):
        """Negative-cached result returns None without calling _query_sesame_raw."""
        from app.database import sync_engine
        from sqlalchemy.orm import Session
        from app.services.simbad import normalize_object_name

        object_name = "NOTFOUND"
        normalized = normalize_object_name(object_name)

        # Pre-populate negative cache
        with Session(sync_engine) as session:
            save_sesame_cache(normalized, None, session)
            session.commit()

        # Mock _query_sesame_raw to assert it's not called
        with Session(sync_engine) as session:
            with patch("app.services.sesame._query_sesame_raw") as mock_query:
                result = resolve_sesame_cached(object_name, session)

            assert result is None
            mock_query.assert_not_called()
