import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.simbad import (
    resolve_target_name,
    normalize_object_name,
    _catalog_priority,
    extract_catalog_id,
    curate_aliases,
    extract_common_name,
    build_primary_name,
    _fetch_tap_aliases,
)


def test_normalize_object_name():
    assert normalize_object_name("m 31") == "M 31"
    assert normalize_object_name("  ngc  224 ") == "NGC 224"
    assert normalize_object_name("IC1396") == "IC1396"
    assert normalize_object_name("Andromeda Galaxy") == "ANDROMEDA GALAXY"


class TestResolveTargetName:
    """Tests for SIMBAD resolution with mocked external API."""

    @pytest.mark.asyncio
    async def test_resolve_known_messier_object(self):
        mock_result = {
            "primary_name": "M 31 - Andromeda Galaxy",
            "catalog_id": "M 31",
            "common_name": "Andromeda Galaxy",
            "aliases": ["M 31", "NGC 224", "Andromeda Galaxy"],
            "ra": 10.6847,
            "dec": 41.2687,
            "object_type": "Galaxy",
        }
        with patch("app.services.simbad._query_simbad", new_callable=AsyncMock, return_value=mock_result):
            result = await resolve_target_name("m 31")

        assert result is not None
        assert result["primary_name"] == "M 31 - Andromeda Galaxy"
        assert result["catalog_id"] == "M 31"
        assert result["common_name"] == "Andromeda Galaxy"
        assert "NGC 224" in result["aliases"]
        assert result["ra"] == pytest.approx(10.6847, abs=0.01)

    @pytest.mark.asyncio
    async def test_resolve_unknown_object_returns_none(self):
        with patch("app.services.simbad._query_simbad", new_callable=AsyncMock, return_value=None):
            result = await resolve_target_name("XYZNOTREAL123")
        assert result is None


# ---------------------------------------------------------------------------
# normalize_object_name (upper=False mode)
# ---------------------------------------------------------------------------

class TestNormalizeObjectName:
    def test_uppercase_by_default(self):
        assert normalize_object_name("m 31") == "M 31"
        assert normalize_object_name("  ngc  224 ") == "NGC 224"

    def test_case_preserving_mode(self):
        assert normalize_object_name("North  America Nebula", upper=False) == "North America Nebula"
        assert normalize_object_name("  vdB  142 ", upper=False) == "vdB 142"

    def test_collapses_multiple_spaces(self):
        assert normalize_object_name("M  31", upper=False) == "M 31"

    def test_strips_leading_trailing(self):
        assert normalize_object_name("  NGC 7000  ", upper=False) == "NGC 7000"


# ---------------------------------------------------------------------------
# _catalog_priority
# ---------------------------------------------------------------------------

class TestCatalogPriority:
    def test_messier(self):
        p = _catalog_priority("M 31")
        assert p is not None and p == 0

    def test_ngc(self):
        p = _catalog_priority("NGC 7000")
        assert p is not None and p == 1

    def test_ic(self):
        assert _catalog_priority("IC 1805") is not None

    def test_ic_with_letter(self):
        assert _catalog_priority("IC 1396A") is not None

    def test_sharpless(self):
        assert _catalog_priority("SH 2-155") is not None

    def test_arp(self):
        assert _catalog_priority("Arp 273") is not None

    def test_barnard(self):
        assert _catalog_priority("B 33") is not None

    def test_vdb(self):
        assert _catalog_priority("vdB 142") is not None

    def test_collinder(self):
        assert _catalog_priority("Cr 399") is not None
        assert _catalog_priority("Collinder 399") is not None

    def test_caldwell(self):
        assert _catalog_priority("Caldwell 4") is not None
        assert _catalog_priority("C 4") is not None

    def test_coordinate_based_returns_none(self):
        assert _catalog_priority("2MASS J12345678+1234567") is None

    def test_random_string_returns_none(self):
        assert _catalog_priority("some random thing") is None

    def test_messier_beats_ngc(self):
        pm = _catalog_priority("M 31")
        pn = _catalog_priority("NGC 224")
        assert pm < pn

    def test_ngc_beats_ic(self):
        pn = _catalog_priority("NGC 7000")
        pi = _catalog_priority("IC 1805")
        assert pn < pi

    def test_abell_pn(self):
        assert _catalog_priority("PN A66 39") is not None
        assert _catalog_priority("Abell 39") is not None

    def test_hcg(self):
        assert _catalog_priority("HCG 92") is not None

    def test_lbn(self):
        assert _catalog_priority("LBN 468") is not None

    def test_ldn(self):
        assert _catalog_priority("LDN 1622") is not None

    def test_melotte(self):
        assert _catalog_priority("Mel 15") is not None
        assert _catalog_priority("Melotte 15") is not None

    def test_snr(self):
        assert _catalog_priority("SNR G180.0-01.7") is not None

    def test_berkeley(self):
        assert _catalog_priority("Cl Berkeley 59") is not None

    def test_king(self):
        assert _catalog_priority("Cl King 14") is not None

    def test_gum(self):
        assert _catalog_priority("Gum 12") is not None


# ---------------------------------------------------------------------------
# extract_catalog_id
# ---------------------------------------------------------------------------

class TestExtractCatalogId:
    def test_messier_wins_over_ngc(self):
        aliases = ["NGC 224", "M 31", "NAME Andromeda Galaxy"]
        assert extract_catalog_id(aliases, "M  31") == "M 31"

    def test_ngc_wins_over_ic(self):
        aliases = ["IC 434", "NGC 2024"]
        assert extract_catalog_id(aliases, "NGC  2024") == "NGC 2024"

    def test_sharpless_extraction(self):
        aliases = ["SH 2-155", "NAME Cave Nebula"]
        assert extract_catalog_id(aliases, "SH  2-155") == "SH 2-155"

    def test_arp(self):
        aliases = ["Arp 273", "NGC 2623"]
        # NGC has higher priority than Arp, so NGC wins
        assert extract_catalog_id(aliases, "NGC 2623") == "NGC 2623"

    def test_barnard(self):
        aliases = ["B 33"]
        assert extract_catalog_id(aliases, "B  33") == "B 33"

    def test_vdb(self):
        aliases = ["vdB 142"]
        assert extract_catalog_id(aliases, "vdB 142") == "vdB 142"

    def test_collinder(self):
        aliases = ["Cr 399"]
        assert extract_catalog_id(aliases, "Cr 399") == "Cr 399"

    def test_caldwell(self):
        aliases = ["Caldwell 4", "NGC 7023"]
        # NGC has higher priority than Caldwell
        assert extract_catalog_id(aliases, "NGC 7023") == "NGC 7023"

    def test_fallback_to_normalized_main_id(self):
        aliases = ["NAME Something Weird"]
        assert extract_catalog_id(aliases, "V*  RR Lyr") == "V* RR Lyr"

    def test_whitespace_normalization(self):
        aliases = ["M  31", "NGC  224"]
        assert extract_catalog_id(aliases, "M   31") == "M 31"

    def test_checks_simbad_main_id(self):
        # simbad_main_id is a catalog match but not in aliases
        aliases = ["NAME Andromeda Galaxy"]
        assert extract_catalog_id(aliases, "M  31") == "M 31"

    def test_empty_aliases(self):
        assert extract_catalog_id([], "NGC  7000") == "NGC 7000"


# ---------------------------------------------------------------------------
# curate_aliases
# ---------------------------------------------------------------------------

class TestCurateAliases:
    def test_keeps_catalog_ids(self):
        raw = ["M 31", "NGC 224", "IC 123"]
        result = curate_aliases(raw)
        assert "M 31" in result
        assert "NGC 224" in result

    def test_keeps_name_entries_title_cased(self):
        raw = ["NAME ANDROMEDA GALAXY"]
        result = curate_aliases(raw)
        assert "Andromeda Galaxy" in result

    def test_keeps_fits_names(self):
        raw = ["M 31"]
        result = curate_aliases(raw, fits_names=["Andromeda"])
        assert "Andromeda" in result

    def test_drops_coordinate_based_ids(self):
        raw = ["M 31", "2MASS J00424433+4116074", "[BFS98] 0040+4059"]
        result = curate_aliases(raw)
        assert "M 31" in result
        assert "2MASS J00424433+4116074" not in result

    def test_deduplicates(self):
        raw = ["M 31", "M  31"]
        result = curate_aliases(raw)
        # Only one M 31 entry
        m31_count = sum(1 for a in result if a.upper().replace(" ", "") == "M31")
        assert m31_count == 1

    def test_normalizes_whitespace(self):
        raw = ["NGC  7000"]
        result = curate_aliases(raw)
        assert "NGC 7000" in result

    def test_name_prefix_stripped_in_output(self):
        raw = ["NAME north america nebula"]
        result = curate_aliases(raw)
        assert "North America Nebula" in result
        # No "NAME " prefix in output
        assert not any(a.startswith("NAME ") for a in result)

    def test_drops_bracket_prefixed_ids(self):
        raw = ["[BFS98] 0040+4059", "M 31"]
        result = curate_aliases(raw)
        assert not any(a.startswith("[") for a in result)


# ---------------------------------------------------------------------------
# extract_common_name
# ---------------------------------------------------------------------------

class TestExtractCommonName:
    def test_simbad_name_alias_priority(self):
        raw = ["M 31", "NGC 224", "NAME Andromeda Galaxy"]
        result = extract_common_name(raw)
        assert result == "Andromeda Galaxy"

    def test_fits_name_fallback(self):
        raw = ["M 31", "NGC 224"]
        result = extract_common_name(raw, fits_names=["Andromeda Galaxy"])
        assert result == "Andromeda Galaxy"

    def test_fits_name_catalog_id_not_used(self):
        # If FITS name is itself a catalog ID, don't use it as common name
        raw = ["NGC 7000"]
        result = extract_common_name(raw, fits_names=["NGC 7000"])
        assert result is None

    def test_none_when_no_common_name(self):
        raw = ["NGC 7000", "IC 5070"]
        result = extract_common_name(raw)
        assert result is None

    def test_title_cases_name(self):
        raw = ["NAME NORTH AMERICA NEBULA"]
        result = extract_common_name(raw)
        assert result == "North America Nebula"

    def test_catalog_ids_not_used_as_common_names(self):
        raw = ["M 31"]
        result = extract_common_name(raw)
        assert result is None


# ---------------------------------------------------------------------------
# build_primary_name
# ---------------------------------------------------------------------------

class TestBuildPrimaryName:
    def test_both_catalog_and_common(self):
        assert build_primary_name("NGC 7000", "North America Nebula") == "NGC 7000 - North America Nebula"

    def test_catalog_only(self):
        assert build_primary_name("NGC 7000", None) == "NGC 7000"

    def test_common_only(self):
        assert build_primary_name(None, "North America Nebula") == "North America Nebula"

    def test_neither(self):
        assert build_primary_name(None, None) == "Unknown"


# ---------------------------------------------------------------------------
# _fetch_tap_aliases
# ---------------------------------------------------------------------------

class TestFetchTapAliases:
    @pytest.mark.asyncio
    async def test_parses_tsv_response(self):
        """TAP returns TSV with header row; function should skip header and return alias rows."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "id\nM 31\nNGC 224\nNAME Andromeda Galaxy\n"
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.simbad.httpx.AsyncClient", return_value=mock_client):
            result = await _fetch_tap_aliases("M  31")

        assert result == ["M 31", "NGC 224", "NAME Andromeda Galaxy"]

    @pytest.mark.asyncio
    async def test_returns_empty_on_no_results(self):
        """When TAP returns only a header, result should be empty."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "id\n"
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.simbad.httpx.AsyncClient", return_value=mock_client):
            result = await _fetch_tap_aliases("NONEXISTENT")

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_http_error(self):
        """On HTTP error, should log warning and return empty list."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.HTTPError("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.simbad.httpx.AsyncClient", return_value=mock_client):
            result = await _fetch_tap_aliases("M 31")

        assert result == []
