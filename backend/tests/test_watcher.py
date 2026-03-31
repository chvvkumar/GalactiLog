import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.watcher import ImageEventHandler


def test_handler_detects_fits_file(tmp_path: Path):
    mock_callback = MagicMock()
    handler = ImageEventHandler(callback=mock_callback)

    # Simulate a file creation event
    event = MagicMock()
    event.is_directory = False
    event.src_path = str(tmp_path / "Light_001.fits")

    handler.on_created(event)
    mock_callback.assert_called_once_with(str(tmp_path / "Light_001.fits"))


def test_handler_ignores_non_fits(tmp_path: Path):
    mock_callback = MagicMock()
    handler = ImageEventHandler(callback=mock_callback)

    event = MagicMock()
    event.is_directory = False
    event.src_path = str(tmp_path / "notes.txt")

    handler.on_created(event)
    mock_callback.assert_not_called()
