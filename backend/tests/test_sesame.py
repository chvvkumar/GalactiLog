"""Unit tests for app.services.sesame - XML parsing, cache helpers, and resolution."""
import pytest
import xml.etree.ElementTree as ET
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.sesame import (
    _query_sesame_raw,
    get_cached_sesame,
    save_sesame_cache,
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
    async def test_returns_none_on_http_error(self):
        import httpx
        client = _make_async_client("", raise_error=httpx.HTTPError("timeout"))
        with patch("app.services.sesame.httpx.AsyncClient", return_value=client):
            result = await _query_sesame_raw("M 42")

        assert result is None

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
# get_cached_sesame
# ---------------------------------------------------------------------------

class TestGetCachedSesame:
    def test_returns_none_when_not_in_cache(self):
        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = None

        result = get_cached_sesame("M 42", session)
        assert result is None

    def test_returns_negative_marker_when_main_id_is_none(self):
        row = MagicMock()
        row.main_id = None
        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = row

        result = get_cached_sesame("NOTFOUND", session)
        assert result == {"_negative": True}

    def test_returns_dict_on_hit(self):
        row = MagicMock()
        row.main_id = "M 42"
        row.raw_aliases = ["NGC 1976"]
        row.ra = 83.82
        row.dec = -5.39
        row.object_type = "HII"
        row.resolver = "S=Simbad"
        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = row

        result = get_cached_sesame("M 42", session)
        assert result is not None
        assert result["main_id"] == "M 42"
        assert result["ra"] == pytest.approx(83.82)
        assert result["resolver"] == "S=Simbad"


# ---------------------------------------------------------------------------
# save_sesame_cache (smoke test - verifies session.execute is called)
# ---------------------------------------------------------------------------

class TestSaveSesameCacheSmoke:
    def test_positive_result_executes_upsert(self):
        session = MagicMock()
        data = {
            "main_id": "M 42",
            "raw_aliases": ["NGC 1976"],
            "ra": 83.82,
            "dec": -5.39,
            "object_type": "HII",
            "resolver": "S=Simbad",
        }
        save_sesame_cache("M 42", data, session)
        session.execute.assert_called_once()

    def test_negative_result_executes_upsert(self):
        session = MagicMock()
        save_sesame_cache("NOTFOUND", None, session)
        session.execute.assert_called_once()
