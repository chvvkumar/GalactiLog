import pytest
import numpy as np
import fitsio
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

from app.services.scanner import extract_metadata
from app.services.thumbnail import generate_thumbnail


@pytest.fixture
def sample_fits(tmp_path: Path) -> Path:
    data = np.random.default_rng(42).normal(1000, 50, (128, 128)).astype(np.float32)
    header = fitsio.FITSHDR()
    for k, v in {
        "OBJECT": "NGC 7000", "EXPTIME": 600.0, "FILTER": "OIII",
        "CCD-TEMP": -15.0, "GAIN": 100, "DATE-OBS": "2024-06-15T01:30:00",
    }.items():
        header.add_record({"name": k, "value": v})
    path = tmp_path / "Light_NGC7000_001.fits"
    fitsio.write(str(path), data, header=header, clobber=True)
    return path


def test_full_ingest_pipeline(sample_fits: Path, tmp_path: Path):
    """Integration test: extract metadata + generate thumbnail for a single file."""
    meta = extract_metadata(sample_fits)
    assert meta["object_name"] == "NGC 7000"
    assert meta["filter_used"] == "OIII"

    thumb_path = tmp_path / "thumbnails" / "thumb.jpg"
    result = generate_thumbnail(sample_fits, thumb_path, max_width=200)
    assert result.exists()
