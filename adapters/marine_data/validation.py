"""Validation helpers for downloaded public marine-product NetCDF files."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from adapters.marine_data.netcdf import source_sha256


def _coordinate(dataset: Any, candidates: Iterable[str]) -> str:
    for name in candidates:
        if name in dataset.coords:
            return name
    raise ValueError(f"missing coordinate; expected one of {tuple(candidates)}")


def _iso(value: Any) -> str:
    import pandas as pd

    converted = pd.Timestamp(value).to_pydatetime()
    if converted.tzinfo is None:
        converted = converted.replace(tzinfo=timezone.utc)
    return converted.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_public_netcdf(
    path: str | Path,
    *,
    product_id: str,
    dataset_id: str,
    variable_units: dict[str, set[str]],
    requested_bbox: tuple[float, float, float, float],
    requested_time_range: tuple[datetime, datetime] | None,
    direction_convention: str,
    dataset_version: str | None = None,
    surface_depth_required: bool = False,
) -> dict[str, Any]:
    """Open and validate a public product file without reading any credentials."""

    import numpy as np
    import xarray as xr

    source = Path(path)
    errors: list[str] = []
    with xr.open_dataset(source) as dataset:
        lat_name = _coordinate(dataset, ("latitude", "lat"))
        lon_name = _coordinate(dataset, ("longitude", "lon"))
        lat_values = np.asarray(dataset[lat_name].values, dtype=float)
        lon_values = np.asarray(dataset[lon_name].values, dtype=float)
        longitude_convention = "0_to_360" if np.nanmax(lon_values) > 180 else "-180_to_180"
        latitude_order = "ascending" if lat_values[-1] >= lat_values[0] else "descending"
        extent = {
            "minimum_longitude": float(np.nanmin(lon_values)),
            "maximum_longitude": float(np.nanmax(lon_values)),
            "minimum_latitude": float(np.nanmin(lat_values)),
            "maximum_latitude": float(np.nanmax(lat_values)),
        }
        lon_min, lon_max, lat_min, lat_max = requested_bbox
        normalized_lon = ((lon_values + 180.0) % 360.0) - 180.0
        if not (
            np.nanmin(normalized_lon) >= lon_min - 1e-6
            and np.nanmax(normalized_lon) <= lon_max + 1e-6
            and np.nanmin(lat_values) >= lat_min - 1e-6
            and np.nanmax(lat_values) <= lat_max + 1e-6
        ):
            errors.append("coordinates extend outside requested project clipping box")

        variables: dict[str, Any] = {}
        for name, allowed_units in variable_units.items():
            if name not in dataset:
                errors.append(f"missing variable: {name}")
                continue
            array = dataset[name]
            units = str(array.attrs.get("units", ""))
            if units not in allowed_units:
                errors.append(f"unexpected units for {name}: {units!r}")
            count = int(array.size)
            valid_count = int(array.count().values)
            variables[name] = {
                "units": units,
                "standard_name": array.attrs.get("standard_name"),
                "count": count,
                "valid_count": valid_count,
                "missing_percentage": (count - valid_count) / count * 100.0 if count else None,
                "minimum": float(array.min(skipna=True).values) if valid_count else None,
                "maximum": float(array.max(skipna=True).values) if valid_count else None,
            }

        actual_time = None
        if requested_time_range is not None:
            time_name = _coordinate(dataset, ("valid_time", "time"))
            time_values = dataset[time_name].values
            actual_start = _iso(np.asarray(time_values).min())
            actual_end = _iso(np.asarray(time_values).max())
            actual_time = {"start": actual_start, "end": actual_end}
            requested_start, requested_end = requested_time_range
            actual_start_dt = datetime.fromisoformat(actual_start.replace("Z", "+00:00"))
            actual_end_dt = datetime.fromisoformat(actual_end.replace("Z", "+00:00"))
            if actual_start_dt < requested_start or actual_end_dt > requested_end:
                errors.append("time coordinates extend outside requested range")

        surface_depth = None
        if surface_depth_required:
            depth_name = _coordinate(dataset, ("depth", "deptht", "lev"))
            depth_values = np.asarray(dataset[depth_name].values, dtype=float)
            surface_depth = float(depth_values[np.argmin(np.abs(depth_values))])
            if depth_values.size != 1:
                errors.append("file contains more than one depth layer")

    return {
        "status": "PASSED" if not errors else "FAILED",
        "data_classification": "REAL PUBLIC ENVIRONMENT DATA",
        "observation_status": "PUBLIC REANALYSIS / MODEL DATA - NOT IN-SITU ZHUANGHE OBSERVATION",
        "product_id": product_id,
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "dataset_id_evidence": "BOUND_TO_SUCCESSFUL DOWNLOAD REQUEST; DATASET ID IS NOT EMBEDDED IN NETCDF",
        "variables": variables,
        "direction_convention": direction_convention,
        "requested_bounding_box": {
            "longitude": [requested_bbox[0], requested_bbox[1]],
            "latitude": [requested_bbox[2], requested_bbox[3]],
            "warning": "PROJECT CLIPPING BOX - NOT ZHUANGHE ADMINISTRATIVE BOUNDARY",
        },
        "actual_coordinate_extent": extent,
        "longitude_convention": longitude_convention,
        "latitude_order": latitude_order,
        "actual_time_range": actual_time,
        "surface_depth_m": surface_depth,
        "filename": source.name,
        "filesize_bytes": source.stat().st_size,
        "sha256": source_sha256(source),
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "errors": errors,
    }


def summarize(values: Iterable[float], percentiles: Iterable[int]) -> dict[str, float | int | None]:
    import numpy as np

    array = np.asarray(tuple(values), dtype=float)
    array = array[np.isfinite(array)]
    result: dict[str, float | int | None] = {"sample_count": int(array.size)}
    if not array.size:
        result.update({"minimum": None, "median": None, "maximum": None})
        result.update({f"p{value}": None for value in percentiles})
        return result
    result.update({
        "minimum": float(np.min(array)),
        "median": float(np.median(array)),
        "maximum": float(np.max(array)),
    })
    result.update({f"p{value}": float(np.percentile(array, value)) for value in percentiles})
    return result
