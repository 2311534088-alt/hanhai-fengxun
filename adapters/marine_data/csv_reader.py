"""Local CSV to MarineEnvironment conversion; no network access."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.marine import MarineEnvironment, MarineQualityFlag


@dataclass(frozen=True, slots=True)
class ProviderCSVSchema:
    source: str
    field_map: dict[str, str]
    quality_flag: MarineQualityFlag = MarineQualityFlag.PROVISIONAL


class MarineCSVReader:
    def __init__(self, schema: ProviderCSVSchema) -> None:
        self.schema = schema

    def read(self, path: str | Path) -> list[MarineEnvironment]:
        with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
            return [self._convert(row) for row in csv.DictReader(stream)]

    def _convert(self, row: dict[str, str]) -> MarineEnvironment:
        def text(name: str) -> str:
            column = self.schema.field_map[name]
            return row[column].strip()

        def optional_float(name: str) -> float | None:
            column = self.schema.field_map.get(name)
            if column is None or not row.get(column, "").strip():
                return None
            return float(row[column])

        return MarineEnvironment(
            timestamp=datetime.fromisoformat(text("timestamp").replace("Z", "+00:00")),
            latitude=float(text("latitude")),
            longitude=float(text("longitude")),
            Hs=optional_float("Hs"), Tp=optional_float("Tp"),
            wave_direction=optional_float("wave_direction"),
            wind_speed=optional_float("wind_speed"),
            wind_direction=optional_float("wind_direction"),
            surface_current_speed=optional_float("surface_current_speed"),
            surface_current_direction=optional_float("surface_current_direction"),
            water_depth=optional_float("water_depth"),
            source=self.schema.source,
            quality_flag=self.schema.quality_flag,
        )

