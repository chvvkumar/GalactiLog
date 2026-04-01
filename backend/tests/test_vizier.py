import pytest
from app.services.vizier import determine_vizier_catalog, build_adql_query


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
