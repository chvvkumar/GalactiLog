import pytest
from app.services.stellarium_names import parse_names_dat, get_stellarium_names


class TestParseNamesDat:
    def test_parses_ngc_entry(self):
        lines = ['NGC  40              _("Bow-Tie Nebula") # ESKY, B500']
        result = parse_names_dat(lines)
        assert result["bow-tie nebula"] == "NGC 40"

    def test_parses_messier_entry(self):
        lines = ['M    8               _("Lagoon Nebula") # WK, DSW']
        result = parse_names_dat(lines)
        assert result["lagoon nebula"] == "M 8"

    def test_parses_sharpless_entry(self):
        lines = ['SH2  129             _("Flying Bat Nebula") # APOD']
        result = parse_names_dat(lines)
        assert result["flying bat nebula"] == "Sh2-129"

    def test_parses_barnard_entry(self):
        lines = ['B    33              _("Horsehead Nebula") # WK']
        result = parse_names_dat(lines)
        assert result["horsehead nebula"] == "Barnard 33"

    def test_parses_collinder_entry(self):
        lines = ['CR   69              _("Orion Cluster")']
        result = parse_names_dat(lines)
        assert result["orion cluster"] == "Collinder 69"

    def test_parses_ic_entry(self):
        lines = ['IC   405             _("Flaming Star Nebula") # WK']
        result = parse_names_dat(lines)
        assert result["flaming star nebula"] == "IC 405"

    def test_parses_lbn_entry(self):
        lines = ['LBN  437             _("Gecko Nebula") # WK']
        result = parse_names_dat(lines)
        assert result["gecko nebula"] == "LBN 437"

    def test_parses_ldn_entry(self):
        lines = ['LDN  1622            _("Boogie Man Nebula")']
        result = parse_names_dat(lines)
        assert result["boogie man nebula"] == "LDN 1622"

    def test_parses_rcw_entry(self):
        lines = ['RCW  114             _("Dragon\'s Heart Nebula") # APOD']
        result = parse_names_dat(lines)
        assert result["dragon's heart nebula"] == "RCW 114"

    def test_parses_vdb_entry(self):
        lines = ['VDB  142             _("Elephant\'s Trunk") # MISC']
        result = parse_names_dat(lines)
        assert result["elephant's trunk"] == "vdB 142"

    def test_parses_pgc_entry(self):
        lines = ['PGC  50779           _("Circinus Galaxy") # NED']
        result = parse_names_dat(lines)
        assert result["circinus galaxy"] == "PGC 50779"

    def test_parses_arp_entry(self):
        lines = ['ARP  244             _("Antennae Galaxies") # NED']
        result = parse_names_dat(lines)
        assert result["antennae galaxies"] == "Arp 244"

    def test_skips_comment_lines(self):
        lines = [
            "# This is a comment",
            'NGC  40              _("Bow-Tie Nebula")',
        ]
        result = parse_names_dat(lines)
        assert len(result) == 1
        assert "bow-tie nebula" in result

    def test_skips_blank_lines(self):
        lines = [
            "",
            'NGC  40              _("Bow-Tie Nebula")',
            "   ",
        ]
        result = parse_names_dat(lines)
        assert len(result) == 1

    def test_multiple_names_same_object(self):
        lines = [
            'NGC  40              _("Bow-Tie Nebula")',
            'NGC  40              _("Scarab Nebula")',
        ]
        result = parse_names_dat(lines)
        assert result["bow-tie nebula"] == "NGC 40"
        assert result["scarab nebula"] == "NGC 40"

    def test_duplicate_name_different_objects_keeps_first(self):
        lines = [
            'SH2  155             _("Cave Nebula")',
            'LBN  531             _("Cave Nebula")',
        ]
        result = parse_names_dat(lines)
        assert result["cave nebula"] == "Sh2-155"

    def test_unknown_prefix_uses_fallback(self):
        lines = ['XCAT 99              _("Test Object")']
        result = parse_names_dat(lines)
        assert result["test object"] == "XCAT 99"

    def test_question_mark_galaxy_is_m51(self):
        lines = ['NGC  5194            _("Question Mark Galaxy")']
        result = parse_names_dat(lines)
        assert result["question mark galaxy"] == "NGC 5194"


class TestGetStellariumNames:
    def test_returns_dict(self):
        names = get_stellarium_names()
        assert isinstance(names, dict)
        assert len(names) > 100

    def test_contains_well_known_objects(self):
        names = get_stellarium_names()
        assert "horsehead nebula" in names
        assert "andromeda galaxy" in names
        assert "pleiades" in names

    def test_singleton_returns_same_object(self):
        a = get_stellarium_names()
        b = get_stellarium_names()
        assert a is b
