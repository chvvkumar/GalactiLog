"""Unit tests for app.services.constellation - coordinate-to-constellation mapping."""
import pytest
from unittest.mock import patch, MagicMock

from app.services.constellation import coords_to_constellation


# ---------------------------------------------------------------------------
# coords_to_constellation
# ---------------------------------------------------------------------------

class TestCoordsToConstellation:
    def test_returns_none_when_ra_is_none(self):
        assert coords_to_constellation(None, 0.0) is None

    def test_returns_none_when_dec_is_none(self):
        assert coords_to_constellation(0.0, None) is None

    def test_returns_none_when_both_none(self):
        assert coords_to_constellation(None, None) is None

    def test_returns_string_for_known_coords(self):
        # Orion Nebula (M 42): RA ~83.82, Dec ~-5.39 -> should be Ori
        result = coords_to_constellation(83.82, -5.39)
        assert result is not None
        assert isinstance(result, str)
        assert len(result) <= 3

    def test_orion_nebula_in_orion(self):
        result = coords_to_constellation(83.82, -5.39)
        assert result == "Ori"

    def test_andromeda_galaxy_in_andromeda(self):
        # M 31: RA ~10.68, Dec ~41.27
        result = coords_to_constellation(10.68, 41.27)
        assert result == "And"

    def test_north_celestial_pole_in_ursa_minor(self):
        # Very close to Dec +89.9 -> Ursa Minor
        result = coords_to_constellation(0.0, 89.9)
        assert result == "UMi"

    def test_returns_none_on_astropy_exception(self):
        # SkyCoord is imported locally inside the function, so patch via
        # astropy.coordinates rather than a module-level attribute.
        mock_coord_module = MagicMock()
        mock_coord_module.SkyCoord = MagicMock(side_effect=Exception("astropy failure"))
        import sys
        with patch.dict(sys.modules, {"astropy.coordinates": mock_coord_module}):
            result = coords_to_constellation(83.82, -5.39)
        assert result is None

    def test_returns_none_on_import_error(self):
        import sys
        # Remove astropy.coordinates from sys.modules so the import inside
        # coords_to_constellation raises ImportError.
        saved = sys.modules.pop("astropy.coordinates", None)
        saved_top = sys.modules.pop("astropy", None)
        try:
            import unittest.mock as _mock
            with _mock.patch.dict(sys.modules, {"astropy.coordinates": None, "astropy": None}):
                result = coords_to_constellation(83.82, -5.39)
        finally:
            if saved is not None:
                sys.modules["astropy.coordinates"] = saved
            if saved_top is not None:
                sys.modules["astropy"] = saved_top

        assert result is None

    def test_south_celestial_pole_area(self):
        # Dec near -90 -> Octans
        result = coords_to_constellation(0.0, -89.9)
        assert result == "Oct"
