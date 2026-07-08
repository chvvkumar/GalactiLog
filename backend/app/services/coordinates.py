from __future__ import annotations


def _parse_coord(value) -> float | None:
    """Parse a coordinate value that may be numeric or sexagesimal.

    Handles:
    - Numeric (float/int): returned directly
    - RA sexagesimal 'HH MM SS.s': converted to degrees (* 15)
    - DEC sexagesimal '[+-]DD MM SS.s': converted to degrees
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    try:
        return float(s)
    except ValueError:
        pass
    # Sexagesimal parsing
    parts = s.lstrip("+-").split()
    if len(parts) != 3:
        return None
    try:
        d, m, sec = float(parts[0]), float(parts[1]), float(parts[2])
        deg = d + m / 60 + sec / 3600
        if s.startswith("-"):
            deg = -deg
        return deg
    except (ValueError, IndexError):
        return None


def _parse_ra(value) -> float | None:
    """Parse RA - if sexagesimal (HH MM SS), multiply by 15 for degrees."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    try:
        return float(s)
    except ValueError:
        pass
    parts = s.split()
    if len(parts) != 3:
        return None
    try:
        h, m, sec = float(parts[0]), float(parts[1]), float(parts[2])
        return (h + m / 60 + sec / 3600) * 15
    except (ValueError, IndexError):
        return None
