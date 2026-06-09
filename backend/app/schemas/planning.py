from __future__ import annotations

from pydantic import BaseModel


class NightEphemerisResponse(BaseModel):
    date: str
    astro_dusk: str | None = None
    astro_dawn: str | None = None
    moon_phase: str | None = None
    moon_illumination: float | None = None
    moon_rise: str | None = None
    moon_set: str | None = None
    source_available: bool
