from pathlib import Path

import pytest

from app.services.filename_parser import extract_target_from_filename


@pytest.mark.parametrize(
    "filename, expected",
    [
        # N.I.N.A. basic
        ("M31_Light_Ha_300s_Bin1_0001.fits", "M31"),
        # N.I.N.A. full
        ("NGC7000_Light_OIII_120s_Gain100_-10C_Bin1_0042.fits", "NGC7000"),
        # N.I.N.A. with camera
        ("IC1396_Light_SII_300s_ASI2600MM_Bin1_0003.fits", "IC1396"),
        # ASIAIR
        ("Light_M42_240.0s_Bin1_ISO1600_20230212-195555_0001.FIT", "M42"),
        # ASIAIR dark (no target)
        ("Dark_60s_Bin1_20250723-130732_0018.fit", None),
        # SGPro
        ("M42_Light_1x1_600sec_frame1.fit", "M42"),
        # SGPro with filter
        ("ngc7662_30s_-20C_CLS_f202.fit", "ngc7662"),
        # Ekos
        ("M_106_Light_30_secs_2023-03-20T21-04-17_Ha_001.fits", "M 106"),
        # MaxIm DL
        ("M27-001R.fit", "M27"),
        # PixInsight master (no target)
        (
            "MasterDark_Stack20_180.0s_Bin1_2600MC_gain100_20250305_-10.0C.fit",
            None,
        ),
        # No target
        ("image_001.fits", None),
        # UUID filename
        ("a1b2c3d4-e5f6-7890-abcd-ef1234567890.fits", None),
        # Multi-word target
        ("North_America_Nebula_Light_Ha_300s_0001.fits", "North America Nebula"),
        # Catalog with hyphen
        ("Sh2-132_Light_OIII_300s_0001.fits", "Sh2-132"),
        # Pelican (L in name)
        ("Pelican_Light_300s_0001.fits", "Pelican"),
        # L filter stripped
        ("M51_L_300s_0001.fits", "M51"),
        # XISF extension
        ("IC434_Light_Ha_120s_0001.xisf", "IC434"),
        # Dual band filter
        ("NGC6992_Light_L-eXtreme_300s_Gain100_0001.fits", "NGC6992"),
        # Temperature T prefix
        ("M31_20201015_180s_G139_T-25_12.fit", "M31"),
        # Panel stripped
        ("NGC7000_Panel1_Light_Ha_300s_0001.fits", "NGC7000"),
        # Pier side
        ("M33_Light_Ha_300s_PierEast_0001.fits", "M33"),
        # HFR
        ("M81_Light_Lum_300s_1.56HFR_0001.fits", "M81"),
        # QHY camera
        ("M101_Light_Ha_300s_QHY268M_Bin1_0001.fits", "M101"),
        # ISO
        ("M45_Light_ISO3200_120s_0001.fits", "M45"),
        # Readout mode
        ("M33_Light_Ha_HighGain_300s_0001.fits", "M33"),
    ],
)
def test_extract_target(filename: str, expected: str | None):
    result = extract_target_from_filename(Path(filename))
    assert result == expected


class TestPathBasedExtraction:
    """Test extraction from directory components."""

    def test_nina_target_prefix(self):
        """N.I.N.A. default folder structure with Target_ prefix."""
        p = Path("/app/data/fits/2026/Date_2026-02-09/LIGHT/ZWO ASI2600MM Pro/Target_NGC 2264/Angle_93.74/Ha_ZWO ASI2600MM Pro_SQA55_93.74deg_600.00s_110G_50Of_1.60HFR_0002.fits")
        assert extract_target_from_filename(p) == "NGC 2264"

    def test_target_prefix_messier(self):
        p = Path("/data/Target_M31/Light/Ha_300s_0001.fits")
        assert extract_target_from_filename(p) == "M31"

    def test_target_prefix_multiword(self):
        p = Path("/data/Target_North America Nebula/Light/Ha_300s_0001.fits")
        assert extract_target_from_filename(p) == "North America Nebula"

    def test_object_prefix(self):
        """Object_ prefix also works."""
        p = Path("/data/Object_IC 1396/Light/Ha_300s_0001.fits")
        assert extract_target_from_filename(p) == "IC 1396"

    def test_prefixed_dir_takes_precedence_over_filename(self):
        """Prefixed dir should win over filename-based extraction."""
        p = Path("/data/Target_NGC 7000/M31_Light_Ha_300s_0001.fits")
        assert extract_target_from_filename(p) == "NGC 7000"

    def test_plain_target_dir(self):
        """Plain directory name used as target (no prefix)."""
        p = Path("/data/M42/Light/Ha_300s_0001.fits")
        assert extract_target_from_filename(p) == "M42"

    def test_plain_target_dir_multiword(self):
        """Multi-word target as plain directory."""
        p = Path("/data/Horsehead Nebula/Light/Ha_300s_0001.fits")
        assert extract_target_from_filename(p) == "Horsehead Nebula"

    def test_deepest_non_noise_dir_wins(self):
        """Deepest non-noise directory is the most specific target."""
        p = Path("/data/2026/NGC7000/LIGHT/Ha_300s_0001.fits")
        assert extract_target_from_filename(p) == "NGC7000"

    def test_noise_dirs_skipped(self):
        """Frame types, dates, cameras are not mistaken for targets."""
        p = Path("/app/data/fits/2026/Date_2026-02-09/LIGHT/ZWO ASI2600MM Pro/M33/Ha_300s_0001.fits")
        assert extract_target_from_filename(p) == "M33"

    def test_no_target_anywhere_falls_back_to_filename(self):
        """If all dirs are noise, fall back to filename parsing."""
        p = Path("/data/2026/LIGHT/M42_Light_Ha_300s_0001.fits")
        assert extract_target_from_filename(p) == "M42"

    def test_no_target_at_all(self):
        """No target in path or filename."""
        p = Path("/data/LIGHT/Ha_300s_0001.fits")
        assert extract_target_from_filename(p) is None

    def test_nina_compact_tokens_no_target(self):
        """N.I.N.A. filename with compact tokens but no target dir."""
        p = Path("/data/Ha_ZWO ASI2600MM Pro_SQA55_93.74deg_600.00s_110G_50Of_1.60HFR_0002.fits")
        assert extract_target_from_filename(p) is None

    def test_target_at_any_level(self):
        """Target can be at any level in the path hierarchy."""
        p = Path("/volumes/astro/IC 434/2026/01/LIGHT/Ha_300s_0001.fits")
        assert extract_target_from_filename(p) == "IC 434"
