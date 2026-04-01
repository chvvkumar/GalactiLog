import pytest
from app.services.openngc import parse_ra_hms, parse_dec_dms, normalize_ngc_name


def test_parse_ra_hms_valid():
    # 20:59:17.14 -> (20 + 59/60 + 17.14/3600) * 15 = 314.8214... degrees
    result = parse_ra_hms("20:59:17.14")
    assert abs(result - 314.8214) < 0.001


def test_parse_ra_hms_zero():
    result = parse_ra_hms("00:00:00.00")
    assert result == 0.0


def test_parse_ra_hms_empty():
    assert parse_ra_hms("") is None
    assert parse_ra_hms(None) is None


def test_parse_dec_dms_positive():
    # +44:31:43.6 -> 44 + 31/60 + 43.6/3600 = 44.5288...
    result = parse_dec_dms("+44:31:43.6")
    assert abs(result - 44.5288) < 0.001


def test_parse_dec_dms_negative():
    # -56:59:11.4 -> -(56 + 59/60 + 11.4/3600) = -56.9865
    result = parse_dec_dms("-56:59:11.4")
    assert abs(result - (-56.9865)) < 0.001


def test_parse_dec_dms_empty():
    assert parse_dec_dms("") is None
    assert parse_dec_dms(None) is None


def test_normalize_ngc_name():
    assert normalize_ngc_name("NGC0031") == "NGC 31"
    assert normalize_ngc_name("IC0002") == "IC 2"
    assert normalize_ngc_name("NGC7000") == "NGC 7000"
    assert normalize_ngc_name("IC1396") == "IC 1396"
