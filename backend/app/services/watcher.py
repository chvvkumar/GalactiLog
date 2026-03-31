import logging
from pathlib import Path

from watchdog.events import FileSystemEventHandler

from app.services.scanner import SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)


class ImageEventHandler(FileSystemEventHandler):
    """Watches for new FITS files and triggers a callback."""

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix in SUPPORTED_EXTENSIONS:
            logger.info("New image file detected: %s", path.name)
            self.callback(str(path))


def start_watcher(watch_path: str, callback) -> "Observer":
    """Start a filesystem watcher on the given path.
    Call this from a dedicated thread in the worker container.
    """
    from watchdog.observers import Observer

    handler = ImageEventHandler(callback=callback)
    observer = Observer()
    observer.schedule(handler, watch_path, recursive=True)
    observer.start()
    logger.info("Watching %s for new image files", watch_path)
    return observer
