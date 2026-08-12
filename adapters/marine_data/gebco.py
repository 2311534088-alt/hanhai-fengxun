"""GEBCO local-file adapter skeleton for non-negative depth magnitude."""

from core.marine import MarineQualityFlag
from adapters.marine_data.csv_reader import MarineCSVReader, ProviderCSVSchema


def csv_reader(quality_flag: MarineQualityFlag = MarineQualityFlag.PROVISIONAL) -> MarineCSVReader:
    return MarineCSVReader(ProviderCSVSchema("GEBCO", {
        "timestamp": "timestamp", "latitude": "latitude", "longitude": "longitude",
        "water_depth": "water_depth",
    }, quality_flag))


def read_local_netcdf(_path: str) -> None:
    raise NotImplementedError("TODO: add optional NetCDF reader after elevation-to-depth convention is confirmed")

