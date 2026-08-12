"""Copernicus GLORYS local-file adapter skeleton."""

from core.marine import MarineQualityFlag
from adapters.marine_data.csv_reader import MarineCSVReader, ProviderCSVSchema


def csv_reader(quality_flag: MarineQualityFlag = MarineQualityFlag.PROVISIONAL) -> MarineCSVReader:
    return MarineCSVReader(ProviderCSVSchema("Copernicus GLORYS", {
        "timestamp": "timestamp", "latitude": "latitude", "longitude": "longitude",
        "surface_current_speed": "surface_current_speed",
        "surface_current_direction": "surface_current_direction",
    }, quality_flag))


def read_local_netcdf(_path: str) -> None:
    raise NotImplementedError("TODO: add optional NetCDF reader after product variables are confirmed")

