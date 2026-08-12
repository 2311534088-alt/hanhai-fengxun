"""Unified telemetry model shared by core modules and adapters."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime
from math import isfinite
from typing import Any

from core.mission.state import MissionState


OPTIONAL_NUMERIC_FIELDS = (
    "Hs", "Tp", "wave_direction", "wind_speed", "wind_direction",
    "SOG", "COG", "HDG", "roll", "pitch", "battery",
)


@dataclass(frozen=True, slots=True)
class TelemetryRecord:
    timestamp: datetime
    latitude: float
    longitude: float
    Hs: float | None
    Tp: float | None
    wave_direction: float | None
    wind_speed: float | None
    wind_direction: float | None
    SOG: float | None
    COG: float | None
    HDG: float | None
    roll: float | None
    pitch: float | None
    battery: float | None
    mission_state: MissionState
    data_label: str

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp, datetime):
            raise ValueError("timestamp must be a datetime")
        self._bounded("latitude", self.latitude, -90.0, 90.0)
        self._bounded("longitude", self.longitude, -180.0, 180.0)
        if not isinstance(self.mission_state, MissionState):
            raise ValueError("mission_state must be a MissionState")
        for name in OPTIONAL_NUMERIC_FIELDS:
            value = getattr(self, name)
            if value is not None and (not isinstance(value, (int, float)) or not isfinite(value)):
                raise ValueError(f"{name} must be a finite number or null")
        for name in ("Hs", "Tp", "wind_speed", "SOG"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative")
        for name in ("wave_direction", "wind_direction", "COG", "HDG"):
            value = getattr(self, name)
            if value is not None and not 0 <= value <= 360:
                raise ValueError(f"{name} must be in [0, 360]")
        if self.roll is not None:
            self._bounded("roll", self.roll, -180.0, 180.0)
        if self.pitch is not None:
            self._bounded("pitch", self.pitch, -90.0, 90.0)
        if self.battery is not None:
            self._bounded("battery", self.battery, 0.0, 100.0)
        if not self.data_label.strip():
            raise ValueError("data_label cannot be empty")

    @staticmethod
    def _bounded(name: str, value: float, low: float, high: float) -> None:
        if not isinstance(value, (int, float)) or not isfinite(value) or not low <= value <= high:
            raise ValueError(f"{name} must be in [{low}, {high}]")

    @classmethod
    def from_mapping(cls, row: dict[str, Any]) -> "TelemetryRecord":
        required = {field.name for field in fields(cls)}
        missing = sorted(name for name in required if name not in row)
        if missing:
            raise ValueError(f"missing fields: {', '.join(missing)}")

        def optional_float(name: str) -> float | None:
            raw = row.get(name)
            return None if raw is None or str(raw).strip() == "" else float(raw)

        try:
            timestamp = datetime.fromisoformat(str(row["timestamp"]).replace("Z", "+00:00"))
            state = MissionState(str(row["mission_state"]).strip())
            return cls(
                timestamp=timestamp,
                latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),
                mission_state=state,
                data_label=str(row["data_label"]),
                **{name: optional_float(name) for name in OPTIONAL_NUMERIC_FIELDS},
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid telemetry row: {exc}") from exc
