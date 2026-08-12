"""Copernicus WAVERYS total-wave NetCDF/CSV adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.marine import MarineEnvironment, MarineQualityFlag
from adapters.marine_data.csv_reader import MarineCSVReader, ProviderCSVSchema
from adapters.marine_data.netcdf import (
    ZHUANGHE_STUDY_REGION, StudyRegion, as_datetime, coordinate_name,
    finite_or_none, from_direction_to_travel, open_netcdf, require_units,
    validate_time_and_region, variable_name,
)


def csv_reader(quality_flag: MarineQualityFlag = MarineQualityFlag.PROVISIONAL) -> MarineCSVReader:
    return MarineCSVReader(ProviderCSVSchema("Copernicus WAVERYS", {
        "timestamp": "timestamp", "latitude": "latitude", "longitude": "longitude",
        "Hs": "Hs", "Tp": "Tp", "wave_direction": "wave_direction",
    }, quality_flag))


def records_from_dataset(
    dataset: Any,
    source_id: str,
    region: StudyRegion = ZHUANGHE_STUDY_REGION,
    quality_flag: MarineQualityFlag = MarineQualityFlag.PUBLIC_PRODUCT_FILE,
) -> list[MarineEnvironment]:
    hs_name = variable_name(dataset, ("VHM0", "vhm0"))
    tp_name = variable_name(dataset, ("VTPK", "vtpk"))
    direction_name = variable_name(dataset, ("VMDR", "vmdr"))
    require_units(dataset[hs_name], {"m", "meter", "metre"}, hs_name)
    require_units(dataset[tp_name], {"s", "second", "seconds"}, tp_name)
    require_units(dataset[direction_name], {"degree", "degrees", "degrees_true"}, direction_name)
    time_name = coordinate_name(dataset, ("time",))
    lat_name = coordinate_name(dataset, ("latitude", "lat"))
    lon_name = coordinate_name(dataset, ("longitude", "lon"))
    frame = dataset[[hs_name, tp_name, direction_name]].to_dataframe().reset_index()
    records: list[MarineEnvironment] = []
    for row in frame.to_dict("records"):
        hs, tp, direction_from = (
            finite_or_none(row[hs_name]), finite_or_none(row[tp_name]), finite_or_none(row[direction_name])
        )
        if hs is None and tp is None and direction_from is None:
            continue
        timestamp = as_datetime(row[time_name])
        latitude, longitude = float(row[lat_name]), float(row[lon_name])
        longitude = ((longitude + 180.0) % 360.0) - 180.0
        if not validate_time_and_region(timestamp, latitude, longitude, region):
            continue
        records.append(MarineEnvironment(
            timestamp=timestamp, latitude=latitude, longitude=longitude,
            Hs=hs, Tp=tp,
            wave_direction=from_direction_to_travel(direction_from) if direction_from is not None else None,
            source=f"Copernicus WAVERYS:{source_id}", quality_flag=quality_flag,
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
