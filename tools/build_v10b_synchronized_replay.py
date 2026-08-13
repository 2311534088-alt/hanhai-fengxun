"""Build the compact V1.0-B synchronized historical mission replay asset.

The selection rule is environment-only. It never reads mission-policy outputs,
completion, mission_saved, or business metrics.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.marine_data.netcdf import StudyRegion
from adapters.marine_data.netcdf import source_sha256
from adapters.marine_data import copernicus_current, copernicus_wave, era5, gebco
import xarray as xr
from adapters.marine_data.sampler import MarineEnvironmentSampler, SamplingTolerance
from adapters.marine_data.sampler import haversine_distance_m
from adapters.replay.csv_replay import CSVReplay


REGION = StudyRegion(121.5, 124.5, 38.5, 40.5, (11, 12, 1, 2, 3))
RAW = ROOT / "data/raw"
PATHS = {
    "ERA5": RAW / "era5/era5_winter_20251101_20260331.nc",
    "Copernicus WAVERYS": RAW / "waverys/waverys_winter_20251101_20260331.nc",
    "Copernicus GLORYS": RAW / "glorys/glorys_surface_winter_20251101_20260331.nc",
    "GEBCO": RAW / "gebco/GEBCO_2026_121.5_124.5E_38.5_40.5N.nc",
}
PRODUCT_IDS = {
    "ERA5": "reanalysis-era5-single-levels",
    "Copernicus WAVERYS": "cmems_mod_glo_wav_my_0.2deg_PT3H-i",
    "Copernicus GLORYS": "cmems_mod_glo_phy_my_0.083deg_P1D-m",
    "GEBCO": "GEBCO_2026",
}
MANIFEST = ROOT / "data/manifests/winter_environment_20251101_20260331.json"
VESSEL_TIMELINE = ROOT / "data/samples/sample_mission_001.csv"
OUTPUT = ROOT / "data/replay/v1.0b_synchronized_historical_mission.json"
REFERENCE_POINT = (39.6, 122.5)
STEP = timedelta(hours=3)
WINDOW_STEPS = 11
SELECTION_RULE = (
    "At the fixed declared reference point 39.6N, 122.5E, evaluate every complete "
    "11-step/30-hour window on the native 3-hour WAVERYS clock. Select the earliest "
    "window maximizing normalized Hs range plus normalized wind-speed range, using "
    "winter-wide ranges as denominators. This environment-only rule does not read "
    "policy recommendations, mission_saved, completion, or business outcomes."
)


def provenance_dict(value) -> dict:
    return {
        "source": value.source,
        "sampling_method": value.sampling_method,
        "time_offset_seconds": value.time_offset_seconds,
        "spatial_distance_m": value.spatial_distance_m,
        "accepted": value.within_tolerance,
    }


def main() -> None:
    missing = [str(path) for path in PATHS.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Validated raw public files are required: {missing}")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest_keys = {
        "ERA5": "ERA5", "Copernicus WAVERYS": "WAVERYS",
        "Copernicus GLORYS": "GLORYS", "GEBCO": "GEBCO",
    }
    for name, path in PATHS.items():
        actual = source_sha256(path)
        expected = manifest["files"][manifest_keys[name]]["sha256"]
        if actual != expected:
            raise ValueError(f"validated source hash mismatch for {name}")
    # The netCDF4 C backend cannot reliably open Windows paths containing
    # non-ASCII characters. h5netcdf can, while the existing adapter-level
    # records_from_dataset functions retain all schema/unit transformations.
    opened = {name: xr.open_dataset(path, engine="h5netcdf") for name, path in PATHS.items()}
    try:
        wind = era5.records_from_dataset(opened["ERA5"], PRODUCT_IDS["ERA5"], REGION)
        wave = copernicus_wave.records_from_dataset(
            opened["Copernicus WAVERYS"], PRODUCT_IDS["Copernicus WAVERYS"], REGION,
        )
        current = copernicus_current.records_from_dataset(
            opened["Copernicus GLORYS"], PRODUCT_IDS["Copernicus GLORYS"], REGION,
        )
        reference_time = min(record.timestamp for record in (*wind, *wave, *current))
        depth = gebco.records_from_dataset(
            opened["GEBCO"], PRODUCT_IDS["GEBCO"], reference_time, REGION,
        )
        records = sorted(
            [*wind, *wave, *current, *depth],
            key=lambda item: (item.timestamp, item.latitude, item.longitude, item.source),
        )
    finally:
        for dataset in opened.values():
            dataset.close()
    nearest_wave = {}
    nearest_wind = {}
    for record in records:
        target = nearest_wave if record.Hs is not None else nearest_wind if record.wind_speed is not None else None
        if target is None:
            continue
        distance = haversine_distance_m(*REFERENCE_POINT, record.latitude, record.longitude)
        previous = target.get(record.timestamp)
        if previous is None or distance < previous[0]:
            target[record.timestamp] = (distance, record)
    wave_times = sorted(nearest_wave)
    starts = [
        timestamp for timestamp in wave_times
        if all(timestamp + STEP * index in wave_times for index in range(WINDOW_STEPS))
    ]
    hs_values = [item[1].Hs for item in nearest_wave.values()]
    wind_values = [item[1].wind_speed for item in nearest_wind.values()]
    hs_span = max(hs_values) - min(hs_values)
    wind_span = max(wind_values) - min(wind_values)

    def score(start: datetime) -> tuple[float, float]:
        timestamps = [start + STEP * index for index in range(WINDOW_STEPS)]
        hs = [nearest_wave[timestamp][1].Hs for timestamp in timestamps]
        wind = [nearest_wind[timestamp][1].wind_speed for timestamp in timestamps]
        if any(value is None for value in (*hs, *wind)):
            return (-1.0, -start.timestamp())
        variation = (max(hs) - min(hs)) / hs_span + (max(wind) - min(wind)) / wind_span
        return (variation, -start.timestamp())

    start = max(starts, key=score)
    vessel = tuple(CSVReplay(VESSEL_TIMELINE))
    if len(vessel) != WINDOW_STEPS:
        raise ValueError("simulated vessel timeline must contain exactly 11 states")
    end = start + STEP * (WINDOW_STEPS - 1)
    local_records = [
        record for record in records
        if (
            record.water_depth is not None
            or start - STEP <= record.timestamp <= end + STEP
        )
        and 39.3 <= record.latitude <= 39.9
        and 122.1 <= record.longitude <= 122.9
    ]
    sampler = MarineEnvironmentSampler(local_records, SamplingTolerance(10_800, 30_000))
    replay = []
    for index, state in enumerate(vessel):
        timestamp = start + STEP * index
        environment = sampler.sample(timestamp, state.latitude, state.longitude)
        replay.append({
            "timestamp": timestamp.isoformat(),
            "latitude": state.latitude,
            "longitude": state.longitude,
            "mission_state": state.mission_state.value,
            "environment": {
                "Hs": environment.Hs, "Tp": environment.Tp,
                "wave_direction": environment.wave_direction,
                "wind_speed": environment.wind_speed,
                "wind_direction": environment.wind_direction,
                "surface_current_speed": environment.surface_current_speed,
                "surface_current_direction": environment.surface_current_direction,
                "water_depth": environment.water_depth,
                "quality_flag": environment.quality_flag.value,
                "provenance_by_field": {
                    name: provenance_dict(value)
                    for name, value in environment.provenance_by_field.items()
                },
            },
            "simulated_vessel_state": {
                "SOG": state.SOG, "COG": state.COG, "HDG": state.HDG,
                "roll": state.roll, "pitch": state.pitch,
                "roll_rate": state.roll_rate, "battery": state.battery,
                "source": "SIMULATED VESSEL STATE",
            },
        })
    hs = [item["environment"]["Hs"] for item in replay]
    wind = [item["environment"]["wind_speed"] for item in replay]
    payload = {
        "schema_version": 1,
        "replay_mode": "SYNCHRONIZED_HISTORICAL_MISSION_REPLAY",
        "environment_source": "REAL PUBLIC HISTORICAL ENVIRONMENT",
        "environment_observation_status": "NOT IN-SITU OBSERVATION",
        "forecast_status": "NOT REAL-TIME FORECAST",
        "vessel_state_source": "SIMULATED VESSEL STATE",
        "selection_rule": SELECTION_RULE,
        "selection_independence": "POLICY AND OUTCOME INDEPENDENT",
        "reference_point": {"latitude": REFERENCE_POINT[0], "longitude": REFERENCE_POINT[1]},
        "time_range": [replay[0]["timestamp"], replay[-1]["timestamp"]],
        "step_seconds": int(STEP.total_seconds()),
        "environment_change": {
            "Hs_min_m": min(hs), "Hs_max_m": max(hs),
            "wind_speed_min_m_s": min(wind), "wind_speed_max_m_s": max(wind),
        },
        "source_manifest": "data/manifests/winter_environment_20251101_20260331.json",
        "input_sha256": {
            name: manifest["files"][key]["sha256"]
            for name, key in (
                ("ERA5", "ERA5"), ("WAVERYS", "WAVERYS"),
                ("GLORYS", "GLORYS"), ("GEBCO", "GEBCO"),
            )
        },
        "sampling": {
            "method": "MarineEnvironmentSampler nearest field assembly; NOT final multi-source fusion",
            "max_time_offset_seconds": 10_800,
            "max_spatial_distance_m": 30_000,
        },
        "records": replay,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(OUTPUT), "time_range": payload["time_range"],
        "environment_change": payload["environment_change"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
