"""Shared NetCDF ingestion utilities for verified public-data files."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from math import atan2, degrees, hypot, isfinite
from pathlib import Path
from typing import Any, Iterable


class MarineDataDependencyError(RuntimeError):
    pass


class MarineDataSchemaError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StudyRegion:
    longitude_min: float = 121.5
    longitude_max: float = 124.5
    latitude_min: float = 38.5
    latitude_max: float = 40.5
    winter_months: tuple[int, ...] = (11, 12, 1, 2, 3)

    def contains(self, latitude: float, longitude: float) -> bool:
        return (
            self.latitude_min <= latitude <= self.latitude_max
            and self.longitude_min <= longitude <= self.longitude_max
        )


ZHUANGHE_STUDY_REGION = StudyRegion()


def require_xarray() -> Any:
    try:
        import xarray as xr
    except ImportError as exc:
        raise MarineDataDependencyError(
            "NetCDF ingestion requires the optional 'marine' dependencies: pip install .[marine]"
        ) from exc
    return xr


def open_netcdf(path: str | Path) -> Any:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    xr = require_xarray()
    return xr.open_dataset(source)


def source_sha256(path: str | Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def coordinate_name(dataset: Any, candidates: Iterable[str]) -> str:
    for name in candidates:
        if name in dataset.coords or name in dataset.dims:
            return name
    raise MarineDataSchemaError(f"missing coordinate; expected one of {tuple(candidates)}")


def variable_name(dataset: Any, candidates: Iterable[str]) -> str:
    for name in candidates:
        if name in dataset.data_vars:
            return name
    raise MarineDataSchemaError(f"missing variable; expected one of {tuple(candidates)}")


def subset_dataset(
    dataset: Any,
    region: StudyRegion,
    *,
    time_candidates: Iterable[str] = ("valid_time", "time"),
    latitude_candidates: Iterable[str] = ("latitude", "lat"),
    longitude_candidates: Iterable[str] = ("longitude", "lon"),
    winter_only: bool = True,
) -> Any:
    """Subset coordinates before tabular expansion.

    Boolean coordinate indexing handles ascending/descending latitude and both
    -180..180 and 0..360 longitude conventions without touching data values.
    """
    lat_name = coordinate_name(dataset, latitude_candidates)
    lon_name = coordinate_name(dataset, longitude_candidates)
    longitude = dataset[lon_name]
    uses_360 = bool(float(longitude.max()) > 180.0)
    lon_min = region.longitude_min % 360.0 if uses_360 else region.longitude_min
    lon_max = region.longitude_max % 360.0 if uses_360 else region.longitude_max
    lat_mask = (dataset[lat_name] >= region.latitude_min) & (dataset[lat_name] <= region.latitude_max)
    if lon_min <= lon_max:
        lon_mask = (longitude >= lon_min) & (longitude <= lon_max)
    else:
        lon_mask = (longitude >= lon_min) | (longitude <= lon_max)
    subset = dataset.sel({lat_name: dataset[lat_name][lat_mask], lon_name: longitude[lon_mask]})
    if winter_only:
        time_name = coordinate_name(subset, time_candidates)
        time_mask = subset[time_name].dt.month.isin(region.winter_months)
        subset = subset.sel({time_name: subset[time_name][time_mask]})
    return subset


def select_surface_depth(dataset: Any, candidates: Iterable[str] = ("depth", "deptht")) -> Any:
    for name in candidates:
        if name in dataset.coords or name in dataset.dims:
            surface_index = int(abs(dataset[name]).values.argmin())
            return dataset.isel({name: surface_index})
    return dataset


def require_units(variable: Any, accepted: set[str], field_name: str) -> None:
    raw = str(variable.attrs.get("units", "")).strip().lower().replace(" ", "")
    normalized = raw.replace("**", "^")
    accepted_normalized = {item.lower().replace(" ", "").replace("**", "^") for item in accepted}
    if normalized not in accepted_normalized:
        raise MarineDataSchemaError(
            f"{field_name} has unsupported or missing units {variable.attrs.get('units')!r}; "
            f"accepted: {sorted(accepted)}"
        )


def direction_of_travel(eastward: float, northward: float) -> float | None:
    if not isfinite(eastward) or not isfinite(northward):
        return None
    if eastward == 0 and northward == 0:
        return None
    return (degrees(atan2(eastward, northward)) + 360.0) % 360.0


def from_direction_to_travel(direction_from: float) -> float:
    if not isfinite(direction_from):
        raise MarineDataSchemaError("direction must be finite")
    return (direction_from + 180.0) % 360.0


def as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        import numpy as np
        if isinstance(value, np.datetime64):
            text = np.datetime_as_string(value, unit="us")
            return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
    except ImportError:
        pass
    if hasattr(value, "isoformat"):
        parsed = datetime.fromisoformat(value.isoformat())
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def validate_time_and_region(timestamp: datetime, latitude: float, longitude: float, region: StudyRegion) -> bool:
    return region.contains(latitude, longitude) and timestamp.month in region.winter_months


def vector_speed(eastward: float, northward: float) -> float:
    return hypot(eastward, northward)
