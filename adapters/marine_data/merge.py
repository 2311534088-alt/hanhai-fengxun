"""Merge colocated provider records without inventing missing values."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import fields

from core.marine import MarineEnvironment, MarineQualityFlag


VARIABLES = (
    "Hs", "Tp", "wave_direction", "wind_speed", "wind_direction",
    "surface_current_speed", "surface_current_direction", "water_depth",
)


def merge_environments(records: Iterable[MarineEnvironment]) -> MarineEnvironment:
    items = list(records)
    if not items:
        raise ValueError("at least one environment record is required")
    first = items[0]
    for item in items[1:]:
        if (item.timestamp, item.latitude, item.longitude) != (first.timestamp, first.latitude, first.longitude):
            raise ValueError("records must share timestamp and coordinates")
    merged: dict[str, float | None] = {}
    for name in VARIABLES:
        values = [getattr(item, name) for item in items if getattr(item, name) is not None]
        if len(set(values)) > 1:
            raise ValueError(f"conflicting values for {name}")
        merged[name] = values[0] if values else None
    quality = MarineQualityFlag.VERIFIED_SOURCE if all(
        item.quality_flag == MarineQualityFlag.VERIFIED_SOURCE for item in items
    ) else MarineQualityFlag.PROVISIONAL
    return MarineEnvironment(
        timestamp=first.timestamp, latitude=first.latitude, longitude=first.longitude,
        source=" + ".join(item.source for item in items), quality_flag=quality, **merged,
    )

