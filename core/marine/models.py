"""Provider-independent marine environment domain model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite


class MarineQualityFlag(str, Enum):
    VERIFIED_SOURCE = "VERIFIED_SOURCE"
    PUBLIC_PRODUCT_FILE = "PUBLIC_PRODUCT_FILE"
    PROVISIONAL = "PROVISIONAL"
    MISSING = "MISSING"
    SIMULATED = "SIMULATED / DEMO ONLY"


@dataclass(frozen=True, slots=True)
class MarineEnvironment:
    timestamp: datetime
    latitude: float
    longitude: float
    Hs: float | None = None
    Tp: float | None = None
    wave_direction: float | None = None
    wind_speed: float | None = None
    wind_direction: float | None = None
    surface_current_speed: float | None = None
    surface_current_direction: float | None = None
    water_depth: float | None = None
    source: str = ""
    quality_flag: MarineQualityFlag = MarineQualityFlag.MISSING

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp, datetime):
            raise ValueError("timestamp must be a datetime")
        self._bounded("latitude", self.latitude, -90, 90)
        self._bounded("longitude", self.longitude, -180, 180)
        for name in ("Hs", "Tp", "wind_speed", "surface_current_speed", "water_depth"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, (int, float)) or not isfinite(value) or value < 0):
                raise ValueError(f"{name} must be a finite non-negative number or null")
        for name in ("wave_direction", "wind_direction", "surface_current_direction"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, (int, float)) or not 0 <= value < 360):
                raise ValueError(f"{name} must be in [0, 360) or null")
        if not self.source.strip():
            raise ValueError("source is required")
        if not isinstance(self.quality_flag, MarineQualityFlag):
            raise ValueError("quality_flag must be a MarineQualityFlag")

    @staticmethod
    def _bounded(name: str, value: float, low: float, high: float) -> None:
        if not isinstance(value, (int, float)) or not isfinite(value) or not low <= value <= high:
            raise ValueError(f"{name} must be in [{low}, {high}]")
