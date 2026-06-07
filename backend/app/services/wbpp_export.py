"""WBPP session export service.

Translates container-internal FITS paths to user-machine paths, computes
per-session folder level candidates, detects contamination, disambiguates
colliding staging names, and generates copy scripts.
"""
import posixpath
import re
from collections import Counter
from dataclasses import dataclass, field


def detect_os(library_root: str) -> str:
    """Return 'windows' if root has a drive letter or backslash, else 'posix'."""
    if re.match(r"^[A-Za-z]:\\", library_root) or "\\" in library_root:
        return "windows"
    return "posix"


def translate_path(container_path: str, fits_root: str, library_root: str, target_os: str) -> str:
    """Strip fits_root from container_path, prepend library_root, adjust separators.

    Raises ValueError if container_path is not under fits_root.
    """
    fits_root = fits_root.rstrip("/")
    if not container_path.startswith(fits_root + "/") and container_path != fits_root:
        raise ValueError(f"Path {container_path!r} does not start with fits_root {fits_root!r}")
    relative = container_path[len(fits_root):].lstrip("/")
    if target_os == "windows":
        return library_root.rstrip("\\").rstrip("/") + "\\" + relative.replace("/", "\\")
    return library_root.rstrip("/") + "/" + relative
