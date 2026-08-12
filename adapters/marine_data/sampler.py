"""Tolerance-controlled multi-source nearest-neighbour sampler."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import asin, cos, radians, sin, sqrt
from typing import Iterable

from core.marine import FieldProvenance, MarineEnvironment, MarineQualityFlag


MARINE_FIELDS = (
    "Hs", "Tp", "wave_direction", "wind_speed", "wind_direction",
    "surface_current_speed", "surface_current_direction", "water_depth",
)
STATIC_FIELDS = frozenset({"water_depth"})


@dataclass(frozen=True, slots=True)
class SamplingTolerance:
    max_time_offset_seconds: float = 10_800.0
    max_spatial_distance_m: float = 30_000.0

    def __post_init__(self) -> None:
        if self.max_time_offset_seconds < 0 or self.max_spatial_distance_m < 0:
            raise ValueError("sampling tolerances cannot be negative")


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_m = 6_371_008.8
    phi1, phi2 = radians(lat1), radians(lat2)
    d_phi = radians(lat2 - lat1)
    d_lambda = radians(lon2 - lon1)
    value = sin(d_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(d_lambda / 2) ** 2
    return 2 * radius_m * asin(sqrt(value))


class MarineEnvironmentSampler:
    """Sample each environmental field independently with explicit rejection metadata."""

    def __init__(self, records: Iterable[MarineEnvironment], tolerance: SamplingTolerance | None = None) -> None:
        self.records = tuple(records)
        self.tolerance = tolerance or SamplingTolerance()

    def sample(self, timestamp: datetime, latitude: float, longitude: float) -> MarineEnvironment:
        values: dict[str, float | None] = {}
        provenance: dict[str, FieldProvenance] = {}
        accepted_quality: list[MarineQualityFlag] = []
        for field_name in MARINE_FIELDS:
            candidates = [record for record in self.records if getattr(record, field_name) is not None]
            if not candidates:
                values[field_name] = None
                provenance[field_name] = FieldProvenance(None, "nearest", None, None, False)
                continue
            scored = []
            for record in candidates:
                time_offset = 0.0 if field_name in STATIC_FIELDS else abs((record.timestamp - timestamp).total_seconds())
                distance = haversine_distance_m(latitude, longitude, record.latitude, record.longitude)
                within = (
                    distance <= self.tolerance.max_spatial_distance_m
                    and (field_name in STATIC_FIELDS or time_offset <= self.tolerance.max_time_offset_seconds)
                )
                time_scale = max(self.tolerance.max_time_offset_seconds, 1.0)
                distance_scale = max(self.tolerance.max_spatial_distance_m, 1.0)
                normalized_score = distance / distance_scale + (
                    0.0 if field_name in STATIC_FIELDS else time_offset / time_scale
                )
                scored.append((not within, normalized_score, time_offset, distance, record))
            rejected, _, time_offset, distance, selected = min(scored, key=lambda item: (item[0], item[1]))
            within = (
                distance <= self.tolerance.max_spatial_distance_m
                and (field_name in STATIC_FIELDS or time_offset <= self.tolerance.max_time_offset_seconds)
            )
            if rejected:
                within = False
            values[field_name] = getattr(selected, field_name) if within else None
            provenance[field_name] = FieldProvenance(
                selected.source, "nearest", time_offset if field_name not in STATIC_FIELDS else None,
                distance, within,
            )
            if within:
                accepted_quality.append(selected.quality_flag)

        if accepted_quality and all(flag == MarineQualityFlag.PUBLIC_PRODUCT_FILE for flag in accepted_quality):
            quality = MarineQualityFlag.PUBLIC_PRODUCT_FILE
        elif accepted_quality and all(flag == MarineQualityFlag.VERIFIED_SOURCE for flag in accepted_quality):
            quality = MarineQualityFlag.VERIFIED_SOURCE
        elif accepted_quality:
            quality = MarineQualityFlag.PROVISIONAL
        else:
            quality = MarineQualityFlag.MISSING
        return MarineEnvironment(
            timestamp=timestamp, latitude=latitude, longitude=longitude,
            source="MULTI_SOURCE_NEAREST_SAMPLER", quality_flag=quality,
            provenance_by_field=provenance, **values,
        )
