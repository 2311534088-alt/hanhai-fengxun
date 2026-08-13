"""GEBCO elevation NetCDF/CSV adapter with explicit depth conversion."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from core.marine import MarineEnvironment, MarineQualityFlag
from adapters.marine_data.csv_reader import MarineCSVReader, ProviderCSVSchema
from adapters.marine_data.netcdf import (
    ZHUANGHE_STUDY_REGION, StudyRegion, coordinate_name, finite_or_none,
    open_netcdf, require_units, subset_dataset, variable_name,
)


def csv_reader(quality_flag: MarineQualityFlag = MarineQualityFlag.PROVISIONAL) -> MarineCSVReader:
    return MarineCSVReader(ProviderCSVSchema("GEBCO", {
        "timestamp": "timestamp", "latitude": "latitude", "longitude": "longitude",
        "water_depth": "water_depth",
    }, quality_flag))


def records_from_dataset(
    dataset: Any,
    source_id: str,
    reference_time: datetime,
    region: StudyRegion = ZHUANGHE_STUDY_REGION,
    quality_flag: MarineQualityFlag = MarineQualityFlag.PUBLIC_PRODUCT_FILE,
) -> list[MarineEnvironment]:
    elevation_name = variable_name(dataset, ("elevation",))
    require_units(dataset[elevation_name], {"m", "meter", "metre"}, elevation_name)
    lat_name = coordinate_name(dataset, ("lat", "latitude"))
    lon_name = coordinate_name(dataset, ("lon", "longitude"))
    dataset = subset_dataset(
        dataset[[elevation_name]], region, latitude_candidates=(lat_name,),
        longitude_candidates=(lon_name,), winter_only=False,
    )
    frame = dataset[[elevation_name]].to_dataframe().reset_index()
    records: list[MarineEnvironment] = []
    for row in frame.to_dict("records"):
        elevation = finite_or_none(row[elevation_name])
        latitude, longitude = float(row[lat_name]), float(row[lon_name])
        longitude = ((longitude + 180.0) % 360.0) - 180.0
        if elevation is None or elevation >= 0 or not region.contains(latitude, longitude):
            continue
        records.append(MarineEnvironment(
            timestamp=reference_time, latitude=latitude, longitude=longitude,
            water_depth=-elevation,
            source=f"GEBCO:{source_id}", quality_flag=quality_flag,
        ))
    return records


def read_local_netcdf(
    path: str | Path,
    reference_time: datetime,
    region: StudyRegion = ZHUANGHE_STUDY_REGION,
    source_id: str | None = None,
) -> list[MarineEnvironment]:
    dataset = open_netcdf(path)
    try:
        return records_from_dataset(dataset, source_id or Path(path).name, reference_time, region)
    finally:
        dataset.close()
