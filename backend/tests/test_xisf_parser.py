"""Tests for XISF header parsing and metadata extraction."""
import struct
import pytest
from pathlib import Path
from app.services.xisf_parser import extract_xisf_metadata


def _make_xisf_bytes(xml_header: str) -> bytes:
    """Build a minimal monolithic XISF file from an XML header string."""
    header_bytes = xml_header.encode("utf-8")
    signature = b"XISF0100"
    header_len = struct.pack("<I", len(header_bytes))
    reserved = b"\x00\x00\x00\x00"
    return signature + header_len + reserved + header_bytes


HEADER_WITH_FITS_KEYWORDS = """\
<?xml version="1.0" encoding="UTF-8"?>
<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">
  <Image geometry="1024:768:1" sampleFormat="UInt16" imageType="Light"
         location="attachment:4096:1572864">
    <FITSKeyword name="OBJECT" value="'NGC 7000'" comment="Target name"/>
    <FITSKeyword name="EXPTIME" value="300.0" comment="Exposure time"/>
    <FITSKeyword name="FILTER" value="'Ha'" comment="Filter used"/>
    <FITSKeyword name="CCD-TEMP" value="-10.0" comment="Sensor temp"/>
    <FITSKeyword name="GAIN" value="100" comment="Camera gain"/>
    <FITSKeyword name="IMAGETYP" value="'Light'" comment="Frame type"/>
    <FITSKeyword name="TELESCOP" value="'Esprit 100'" comment="Telescope"/>
    <FITSKeyword name="INSTRUME" value="'ASI2600MM'" comment="Camera"/>
    <FITSKeyword name="DATE-OBS" value="'2025-12-15T22:30:00'" comment="Obs date"/>
  </Image>
</xisf>"""

HEADER_WITH_XISF_PROPERTIES = """\
<?xml version="1.0" encoding="UTF-8"?>
<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">
  <Image geometry="1024:768:1" sampleFormat="Float32" imageType="Light"
         location="attachment:4096:3145728" bounds="0:1">
    <Property id="Observation:Object:Name" type="String" value="M 42"/>
    <Property id="Instrument:ExposureTime" type="Float32" value="120.0"/>
    <Property id="Instrument:Filter:Name" type="String" value="OIII"/>
    <Property id="Instrument:Sensor:Temperature" type="Float32" value="-15.0"/>
    <Property id="Instrument:Camera:Gain" type="Float32" value="200"/>
    <Property id="Instrument:Telescope:Name" type="String" value="RC8"/>
    <Property id="Instrument:Camera:Name" type="String" value="QHY600M"/>
    <Property id="Observation:Time:Start" type="TimePoint" value="2025-11-20T21:00:00Z"/>
  </Image>
</xisf>"""

HEADER_MIXED = """\
<?xml version="1.0" encoding="UTF-8"?>
<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">
  <Image geometry="2048:1536:1" sampleFormat="UInt16" imageType="Dark"
         location="attachment:4096:6291456">
    <FITSKeyword name="OBJECT" value="'Dark Frame'" comment=""/>
    <FITSKeyword name="EXPTIME" value="300.0" comment=""/>
    <FITSKeyword name="IMAGETYP" value="'Dark'" comment=""/>
    <Property id="Instrument:Camera:Name" type="String" value="ASI294MC"/>
  </Image>
</xisf>"""


class TestExtractXisfMetadata:
    """Test metadata extraction from XISF headers."""

    def test_fits_keywords_path(self, tmp_path):
        """XISF files with FITSKeyword elements (N.I.N.A. output)."""
        xisf_file = tmp_path / "nina_output.xisf"
        xisf_file.write_bytes(_make_xisf_bytes(HEADER_WITH_FITS_KEYWORDS))

        meta = extract_xisf_metadata(xisf_file)

        assert meta["object_name"] == "NGC 7000"
        assert meta["exposure_time"] == 300.0
        assert meta["filter_used"] == "Ha"
        assert meta["sensor_temp"] == -10.0
        assert meta["camera_gain"] == 100
        assert meta["image_type"] == "Light"
        assert meta["telescope"] == "Esprit 100"
        assert meta["camera"] == "ASI2600MM"
        assert meta["capture_date"].isoformat() == "2025-12-15T22:30:00"
        assert meta["file_name"] == "nina_output.xisf"
        assert "OBJECT" in meta["raw_headers"]

    def test_xisf_properties_path(self, tmp_path):
        """XISF files with native properties (PixInsight output)."""
        xisf_file = tmp_path / "pi_output.xisf"
        xisf_file.write_bytes(_make_xisf_bytes(HEADER_WITH_XISF_PROPERTIES))

        meta = extract_xisf_metadata(xisf_file)

        assert meta["object_name"] == "M 42"
        assert meta["exposure_time"] == 120.0
        assert meta["filter_used"] == "OIII"
        assert meta["sensor_temp"] == -15.0
        assert meta["camera_gain"] == 200
        assert meta["telescope"] == "RC8"
        assert meta["camera"] == "QHY600M"
        assert meta["capture_date"].isoformat() == "2025-11-20T21:00:00+00:00"

    def test_mixed_keywords_and_properties(self, tmp_path):
        """FITSKeywords take priority, properties fill gaps."""
        xisf_file = tmp_path / "mixed.xisf"
        xisf_file.write_bytes(_make_xisf_bytes(HEADER_MIXED))

        meta = extract_xisf_metadata(xisf_file)

        # FITSKeyword takes priority
        assert meta["object_name"] == "Dark Frame"
        assert meta["exposure_time"] == 300.0
        assert meta["image_type"] == "Dark"
        # Property fills gap (no INSTRUME FITSKeyword)
        assert meta["camera"] == "ASI294MC"

    def test_raw_headers_include_all(self, tmp_path):
        """raw_headers should contain all FITSKeywords and XISF properties."""
        xisf_file = tmp_path / "test.xisf"
        xisf_file.write_bytes(_make_xisf_bytes(HEADER_MIXED))

        meta = extract_xisf_metadata(xisf_file)

        assert "OBJECT" in meta["raw_headers"]
        assert "EXPTIME" in meta["raw_headers"]
        assert "Instrument:Camera:Name" in meta["raw_headers"]

    def test_invalid_signature_raises(self, tmp_path):
        """Non-XISF files should raise ValueError."""
        bad_file = tmp_path / "bad.xisf"
        bad_file.write_bytes(b"NOT_XISF" + b"\x00" * 100)

        with pytest.raises(ValueError, match="Not a valid XISF file"):
            extract_xisf_metadata(bad_file)

    def test_hfr_from_filename(self, tmp_path):
        """HFR should be extracted from N.I.N.A. filename patterns."""
        xisf_file = tmp_path / "Light_NGC7000_Ha_300s_1.56HFR_001.xisf"
        xisf_file.write_bytes(_make_xisf_bytes(HEADER_WITH_XISF_PROPERTIES))

        meta = extract_xisf_metadata(xisf_file)

        assert meta["median_hfr"] == 1.56


HEADER_EXPOSURE_KEYWORD = """\
<?xml version="1.0" encoding="UTF-8"?>
<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">
  <Image geometry="1024:768:1" sampleFormat="UInt16" imageType="Light"
         location="attachment:4096:1572864">
    <FITSKeyword name="OBJECT" value="'M 31'" comment=""/>
    <FITSKeyword name="EXPOSURE" value="240.0" comment="Exposure (legacy keyword)"/>
    <FITSKeyword name="IMAGETYP" value="'Light'" comment=""/>
  </Image>
</xisf>"""

HEADER_FWHM_NO_HFR = """\
<?xml version="1.0" encoding="UTF-8"?>
<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">
  <Image geometry="1024:768:1" sampleFormat="UInt16" imageType="Light"
         location="attachment:4096:1572864">
    <FITSKeyword name="OBJECT" value="'M 31'" comment=""/>
    <FITSKeyword name="EXPTIME" value="300.0" comment=""/>
    <FITSKeyword name="MEANFWHM" value="3.2" comment="Mean FWHM"/>
    <FITSKeyword name="ELLIPTICITY" value="0.19" comment="Ellipticity"/>
    <FITSKeyword name="IMAGETYP" value="'Light'" comment=""/>
  </Image>
</xisf>"""

HEADER_BAD_DATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">
  <Image geometry="1024:768:1" sampleFormat="UInt16" imageType="Light"
         location="attachment:4096:1572864">
    <FITSKeyword name="OBJECT" value="'M 31'" comment=""/>
    <FITSKeyword name="EXPTIME" value="300.0" comment=""/>
    <FITSKeyword name="DATE-OBS" value="'15/06/2025 not-iso'" comment=""/>
    <FITSKeyword name="IMAGETYP" value="'Light'" comment=""/>
  </Image>
</xisf>"""


class TestXisfMetricSeparation:
    """AUD-001 / AUD-007 / AUD-020 fixes on the XISF path."""

    def test_exposure_keyword_fallback(self, tmp_path):
        """XISF carrying EXPOSURE (not EXPTIME) yields a non-null exposure_time."""
        xisf_file = tmp_path / "legacy_exposure.xisf"
        xisf_file.write_bytes(_make_xisf_bytes(HEADER_EXPOSURE_KEYWORD))

        meta = extract_xisf_metadata(xisf_file)

        assert meta["exposure_time"] == 240.0

    def test_fwhm_only_populates_median_fwhm_not_hfr(self, tmp_path):
        """A FWHM-only XISF gets median_hfr = None and median_fwhm populated."""
        xisf_file = tmp_path / "fwhm_only.xisf"
        xisf_file.write_bytes(_make_xisf_bytes(HEADER_FWHM_NO_HFR))

        meta = extract_xisf_metadata(xisf_file)

        assert meta["median_hfr"] is None
        assert meta["median_fwhm"] == 3.2

    def test_ellipticity_converted_to_eccentricity(self, tmp_path):
        """ELLIPTICITY is converted, not stored raw."""
        import math
        xisf_file = tmp_path / "ellip.xisf"
        xisf_file.write_bytes(_make_xisf_bytes(HEADER_FWHM_NO_HFR))

        meta = extract_xisf_metadata(xisf_file)

        expected = math.sqrt(1.0 - (1.0 - 0.19) ** 2)
        assert meta["eccentricity"] == pytest.approx(expected)
        assert meta["eccentricity"] != 0.19

    def test_unparseable_date_obs_logs_warning(self, tmp_path, caplog):
        """A malformed DATE-OBS logs a warning and leaves capture_date None."""
        xisf_file = tmp_path / "bad_date.xisf"
        xisf_file.write_bytes(_make_xisf_bytes(HEADER_BAD_DATE))

        with caplog.at_level("WARNING"):
            meta = extract_xisf_metadata(xisf_file)

        assert meta["capture_date"] is None
        assert any(
            "DATE-OBS" in rec.message and "bad_date.xisf" in rec.message
            for rec in caplog.records
        )


from app.services.scanner import SUPPORTED_EXTENSIONS


def test_xisf_in_supported_extensions():
    assert ".xisf" in SUPPORTED_EXTENSIONS
    assert ".XISF" in SUPPORTED_EXTENSIONS
