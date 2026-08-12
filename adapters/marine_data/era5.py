"""ERA5 10 m wind NetCDF/CSV adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.marine import MarineEnvironment, MarineQualityFlag
from adapters.marine_data.csv_reader import MarineCSVReader, ProviderCSVSchema
from adapters.marine_data.netcdf import (
    ZHUANGHE_STUDY_REGION, StudyRegion, as_datetime, coordinate_name,
    direction_of_travel, finite_or_none, open_netcdf, require_units,
    validate_time_and_region, variable_name, vector_speed,
)


def csv_reader(quality_flag: MarineQualityFlag = MarineQualityFlag.PROVISIONAL) -> MarineCSVReader:
    return MarineCSVReader(ProviderCSVSchema("ERA5", {
        "timestamp": "timestamp", "latitude": "latitude", "longitude": "longitude",
        "wind_speed": "wind_speed", "wind_direction": "wind_direction",
    }, quality_flag))


def records_from_dataset(
    dataset: Any,
    source_id: str,
    region: StudyRegion = ZHUANGHE_STUDY_REGION,
    quality_flag: MarineQualityFlag = MarineQualityFlag.PUBLIC_PRODUCT_FILE,
) -> list[MarineEnvironment]:
    u_name = variable_name(dataset, ("u10", "10u"))
    v_name = variable_name(dataset, ("v10", "10v"))
    require_units(dataset[u_name], {"m s-1", "m/s", "m s^-1"}, u_name)
    require_units(dataset[v_name], {"m s-1", "m/s", "m s^-1"}, v_name)
    time_name = coordinate_name(dataset, ("valid_time", "time"))
    lat_name = coordinate_name(dataset, ("latitude", "lat"))
    lon_name = coordinate_name(dataset, ("longitude", "lon"))
    frame = dataset[[u_name, v_name]].to_dataframe().reset_index()
    records: list[MarineEnvironment] = []
    for row in frame.to_dict("records"):
        u = finite_or_none(row[u_name])
        v = finite_or_none(row[v_name])
        if u is None or v is None:
            continue
        timestamp = as_datetime(row[time_name])
        latitude, longitude = float(row[lat_name]), float(row[lon_name])
        longitude = ((longitude + 180.0) % 360.0) - 180.0
        if not validate_time_and_region(timestamp, latitude, longitude, region):
            continue
        records.append(MarineEnvironment(
            timestamp=timestamp, latitude=latitude, longitude=longitude,
            wind_speed=vector_speed(u, v), wind_direction=direction_of_travel(u, v),
            source=f"ERA5:{source_id}", quality_flag=quality_flag,
        ))
    return records


def read_local_netcdf(
    path: str | Path,
    region: StudyRegion = ZHUANGHE_STUDY_REGION,
    source_id: str | None = None,
) -> list[MarineEnvironment]:
    dataset = open_netcdf(path)
    try:
        return records_from_dataset(dataset, source_id or Path(path).name, region)
    finally:
        dataset.close()
