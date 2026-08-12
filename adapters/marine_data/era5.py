"""ERA5 local-file adapter skeleton for wind variables."""

from core.marine import MarineQualityFlag
from adapters.marine_data.csv_reader import MarineCSVReader, ProviderCSVSchema


def csv_reader(quality_flag: MarineQualityFlag = MarineQualityFlag.PROVISIONAL) -> MarineCSVReader:
    return MarineCSVReader(ProviderCSVSchema("ERA5", {
        "timestamp": "timestamp", "latitude": "latitude", "longitude": "longitude",
        "wind_speed": "wind_speed", "wind_direction": "wind_direction",
    }, quality_flag))


def read_local_netcdf(_path: str) -> None:
    raise NotImplementedError("TODO: add optional NetCDF reader after variable mapping is confirmed")

