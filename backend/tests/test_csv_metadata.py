import os
import tempfile
from pathlib import Path

import pytest

from app.services import csv_metadata
from app.services.csv_metadata import (
    get_csv_metrics,
    parse_image_metadata_csv,
    parse_weather_csv,
)


@pytest.fixture(autouse=True)
def clear_caches():
    """Clear mtime cache between tests so temp dirs don't collide."""
    csv_metadata._cache.clear()
    yield
    csv_metadata._cache.clear()


def _write_csv(directory: Path, filename: str, header: str, rows: list[str]):
    filepath = directory / filename
    with open(filepath, "w", newline="") as f:
        f.write(header + "\n")
        for row in rows:
            f.write(row + "\n")


class TestParseImageMetadataCsvGoodData:
    def test_returns_dict_keyed_by_filename(self, tmp_path):
        header = "FilePath,HFR,HFRStDev,FWHM,Eccentricity,DetectedStars,GuidingRMSArcSec,GuidingRMSRAArcSec,GuidingRMSDECArcSec,ADUStDev,ADUMean,ADUMedian,ADUMin,ADUMax,FocuserPosition,FocuserTemp,RotatorPosition,PierSide,Airmass,ExposureStartUTC"
        row = r"D:\Astro\Light\2024-01-15\NGC1234_Ha_300s_001.fits,2.35,0.42,3.1,0.55,312,0.78,0.52,0.58,150.3,1024.5,1020.0,100,4095,25000,-5.2,182.3,West,1.23,2024-01-15T22:30:00"
        _write_csv(tmp_path, "ImageMetaData.csv", header, [row])

        result = parse_image_metadata_csv(tmp_path)

        assert "NGC1234_Ha_300s_001.fits" in result
        entry = result["NGC1234_Ha_300s_001.fits"]
        assert entry["median_hfr"] == 2.35
        assert entry["hfr_stdev"] == 0.42
        assert entry["fwhm"] == 3.1
        assert entry["eccentricity"] == 0.55
        assert entry["detected_stars"] == 312
        assert entry["guiding_rms_arcsec"] == 0.78
        assert entry["guiding_rms_ra_arcsec"] == 0.52
        assert entry["guiding_rms_dec_arcsec"] == 0.58
        assert entry["adu_stdev"] == 150.3
        assert entry["adu_mean"] == 1024.5
        assert entry["adu_median"] == 1020.0
        assert entry["adu_min"] == 100
        assert entry["adu_max"] == 4095
        assert entry["focuser_position"] == 25000
        assert entry["focuser_temp"] == -5.2
        assert entry["rotator_position"] == 182.3
        assert entry["pier_side"] == "West"
        assert entry["airmass"] == 1.23

    def test_multiple_rows(self, tmp_path):
        header = "FilePath,HFR,HFRStDev,FWHM,Eccentricity,DetectedStars,GuidingRMSArcSec,GuidingRMSRAArcSec,GuidingRMSDECArcSec,ADUStDev,ADUMean,ADUMedian,ADUMin,ADUMax,FocuserPosition,FocuserTemp,RotatorPosition,PierSide,Airmass,ExposureStartUTC"
        row1 = r"D:\Astro\Light\img_001.fits,2.0,0.4,3.0,0.5,300,0.7,0.5,0.5,150.0,1000.0,1000.0,100,4000,25000,-5.0,180.0,West,1.2,2024-01-15T22:30:00"
        row2 = r"D:\Astro\Light\img_002.fits,2.5,0.5,3.5,0.6,350,0.8,0.6,0.6,160.0,1100.0,1050.0,110,4100,25100,-4.5,181.0,East,1.3,2024-01-15T22:35:00"
        _write_csv(tmp_path, "ImageMetaData.csv", header, [row1, row2])

        result = parse_image_metadata_csv(tmp_path)

        assert len(result) == 2
        assert "img_001.fits" in result
        assert "img_002.fits" in result


class TestParseImageMetadataCsvNaN:
    def test_nan_values_become_none(self, tmp_path):
        header = "FilePath,HFR,HFRStDev,FWHM,Eccentricity,DetectedStars,GuidingRMSArcSec,GuidingRMSRAArcSec,GuidingRMSDECArcSec,ADUStDev,ADUMean,ADUMedian,ADUMin,ADUMax,FocuserPosition,FocuserTemp,RotatorPosition,PierSide,Airmass,ExposureStartUTC"
        row = r"D:\Astro\Light\img_001.fits,NaN,NaN,3.1,0.55,312,NaN,NaN,NaN,150.3,1024.5,1020.0,100,4095,25000,-5.2,182.3,West,1.23,2024-01-15T22:30:00"
        _write_csv(tmp_path, "ImageMetaData.csv", header, [row])

        result = parse_image_metadata_csv(tmp_path)
        entry = result["img_001.fits"]

        assert entry["median_hfr"] is None
        assert entry["hfr_stdev"] is None
        assert entry["guiding_rms_arcsec"] is None
        assert entry["fwhm"] == 3.1


class TestParseImageMetadataCsvHfrZero:
    def test_hfr_zero_becomes_none(self, tmp_path):
        header = "FilePath,HFR,HFRStDev,FWHM,Eccentricity,DetectedStars,GuidingRMSArcSec,GuidingRMSRAArcSec,GuidingRMSDECArcSec,ADUStDev,ADUMean,ADUMedian,ADUMin,ADUMax,FocuserPosition,FocuserTemp,RotatorPosition,PierSide,Airmass,ExposureStartUTC"
        row = r"D:\Astro\Light\img_001.fits,0.0,0.42,3.1,0.55,312,0.78,0.52,0.58,150.3,1024.5,1020.0,100,4095,25000,-5.2,182.3,West,1.23,2024-01-15T22:30:00"
        _write_csv(tmp_path, "ImageMetaData.csv", header, [row])

        result = parse_image_metadata_csv(tmp_path)
        entry = result["img_001.fits"]

        assert entry["median_hfr"] is None
        assert entry["hfr_stdev"] == 0.42


class TestParseImageMetadataCsvMissing:
    def test_missing_csv_returns_empty_dict(self, tmp_path):
        result = parse_image_metadata_csv(tmp_path)
        assert result == {}


class TestParseWeatherCsv:
    def test_returns_dict_keyed_by_exposure_start(self, tmp_path):
        header = "ExposureStartUTC,Temperature,DewPoint,Humidity,Pressure,WindSpeed,WindDirection,WindGust,CloudCover,SkyQuality"
        row = "2024-01-15T22:30:00,5.2,1.3,72.0,1013.25,3.5,180.0,5.2,25.0,20.5"
        _write_csv(tmp_path, "WeatherData.csv", header, [row])

        result = parse_weather_csv(tmp_path)

        assert "2024-01-15T22:30:00" in result
        entry = result["2024-01-15T22:30:00"]
        assert entry["ambient_temp"] == 5.2
        assert entry["dew_point"] == 1.3
        assert entry["humidity"] == 72.0
        assert entry["pressure"] == 1013.25
        assert entry["wind_speed"] == 3.5
        assert entry["wind_direction"] == 180.0
        assert entry["wind_gust"] == 5.2
        assert entry["cloud_cover"] == 25.0
        assert entry["sky_quality"] == 20.5

    def test_nan_values_become_none(self, tmp_path):
        header = "ExposureStartUTC,Temperature,DewPoint,Humidity,Pressure,WindSpeed,WindDirection,WindGust,CloudCover,SkyQuality"
        row = "2024-01-15T22:30:00,5.2,NaN,72.0,NaN,3.5,180.0,NaN,NaN,20.5"
        _write_csv(tmp_path, "WeatherData.csv", header, [row])

        result = parse_weather_csv(tmp_path)
        entry = result["2024-01-15T22:30:00"]

        assert entry["ambient_temp"] == 5.2
        assert entry["dew_point"] is None
        assert entry["pressure"] is None
        assert entry["wind_gust"] is None
        assert entry["cloud_cover"] is None

    def test_missing_csv_returns_empty_dict(self, tmp_path):
        result = parse_weather_csv(tmp_path)
        assert result == {}


class TestGetCsvMetrics:
    def test_joins_image_and_weather(self, tmp_path):
        img_header = "FilePath,HFR,HFRStDev,FWHM,Eccentricity,DetectedStars,GuidingRMSArcSec,GuidingRMSRAArcSec,GuidingRMSDECArcSec,ADUStDev,ADUMean,ADUMedian,ADUMin,ADUMax,FocuserPosition,FocuserTemp,RotatorPosition,PierSide,Airmass,ExposureStartUTC"
        img_row = r"D:\Astro\Light\img_001.fits,2.35,0.42,3.1,0.55,312,0.78,0.52,0.58,150.3,1024.5,1020.0,100,4095,25000,-5.2,182.3,West,1.23,2024-01-15T22:30:00"
        _write_csv(tmp_path, "ImageMetaData.csv", img_header, [img_row])

        wx_header = "ExposureStartUTC,Temperature,DewPoint,Humidity,Pressure,WindSpeed,WindDirection,WindGust,CloudCover,SkyQuality"
        wx_row = "2024-01-15T22:30:00,5.2,1.3,72.0,1013.25,3.5,180.0,5.2,25.0,20.5"
        _write_csv(tmp_path, "WeatherData.csv", wx_header, [wx_row])

        fits_path = tmp_path / "img_001.fits"
        result = get_csv_metrics(fits_path)

        assert result["median_hfr"] == 2.35
        assert result["detected_stars"] == 312
        assert result["pier_side"] == "West"
        assert result["ambient_temp"] == 5.2
        assert result["humidity"] == 72.0
        assert result["sky_quality"] == 20.5

    def test_image_only_when_no_weather(self, tmp_path):
        img_header = "FilePath,HFR,HFRStDev,FWHM,Eccentricity,DetectedStars,GuidingRMSArcSec,GuidingRMSRAArcSec,GuidingRMSDECArcSec,ADUStDev,ADUMean,ADUMedian,ADUMin,ADUMax,FocuserPosition,FocuserTemp,RotatorPosition,PierSide,Airmass,ExposureStartUTC"
        img_row = r"D:\Astro\Light\img_001.fits,2.35,0.42,3.1,0.55,312,0.78,0.52,0.58,150.3,1024.5,1020.0,100,4095,25000,-5.2,182.3,West,1.23,2024-01-15T22:30:00"
        _write_csv(tmp_path, "ImageMetaData.csv", img_header, [img_row])

        fits_path = tmp_path / "img_001.fits"
        result = get_csv_metrics(fits_path)

        assert result["median_hfr"] == 2.35
        assert "ambient_temp" not in result

    def test_no_csv_returns_empty_dict(self, tmp_path):
        fits_path = tmp_path / "img_001.fits"
        result = get_csv_metrics(fits_path)
        assert result == {}

    def test_no_matching_file_returns_empty_dict(self, tmp_path):
        img_header = "FilePath,HFR,HFRStDev,FWHM,Eccentricity,DetectedStars,GuidingRMSArcSec,GuidingRMSRAArcSec,GuidingRMSDECArcSec,ADUStDev,ADUMean,ADUMedian,ADUMin,ADUMax,FocuserPosition,FocuserTemp,RotatorPosition,PierSide,Airmass,ExposureStartUTC"
        img_row = r"D:\Astro\Light\img_001.fits,2.35,0.42,3.1,0.55,312,0.78,0.52,0.58,150.3,1024.5,1020.0,100,4095,25000,-5.2,182.3,West,1.23,2024-01-15T22:30:00"
        _write_csv(tmp_path, "ImageMetaData.csv", img_header, [img_row])

        fits_path = tmp_path / "no_such_file.fits"
        result = get_csv_metrics(fits_path)
        assert result == {}


class TestFilenameExtraction:
    def test_windows_backslash_path(self, tmp_path):
        header = "FilePath,HFR,HFRStDev,FWHM,Eccentricity,DetectedStars,GuidingRMSArcSec,GuidingRMSRAArcSec,GuidingRMSDECArcSec,ADUStDev,ADUMean,ADUMedian,ADUMin,ADUMax,FocuserPosition,FocuserTemp,RotatorPosition,PierSide,Airmass,ExposureStartUTC"
        row = r"D:\Deep Sky\Sessions\2024-01-15\Light\NGC 1234_Ha_300s_001.fits,2.35,0.42,3.1,0.55,312,0.78,0.52,0.58,150.3,1024.5,1020.0,100,4095,25000,-5.2,182.3,West,1.23,2024-01-15T22:30:00"
        _write_csv(tmp_path, "ImageMetaData.csv", header, [row])

        result = parse_image_metadata_csv(tmp_path)
        assert "NGC 1234_Ha_300s_001.fits" in result

    def test_forward_slash_path(self, tmp_path):
        header = "FilePath,HFR,HFRStDev,FWHM,Eccentricity,DetectedStars,GuidingRMSArcSec,GuidingRMSRAArcSec,GuidingRMSDECArcSec,ADUStDev,ADUMean,ADUMedian,ADUMin,ADUMax,FocuserPosition,FocuserTemp,RotatorPosition,PierSide,Airmass,ExposureStartUTC"
        row = "D:/Astro/Light/img_001.fits,2.35,0.42,3.1,0.55,312,0.78,0.52,0.58,150.3,1024.5,1020.0,100,4095,25000,-5.2,182.3,West,1.23,2024-01-15T22:30:00"
        _write_csv(tmp_path, "ImageMetaData.csv", header, [row])

        result = parse_image_metadata_csv(tmp_path)
        assert "img_001.fits" in result
