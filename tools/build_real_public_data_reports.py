"""Build credential-free reports from locally downloaded real public data."""

from __future__ import annotations

import json
import sys
from hashlib import sha256
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.marine_data import copernicus_current, copernicus_wave, era5, gebco
from adapters.marine_data.netcdf import StudyRegion
from adapters.marine_data.sampler import MarineEnvironmentSampler, SamplingTolerance
from adapters.marine_data.validation import summarize, validate_public_netcdf
from core.navigation import relative_wave_angle
from core.resonance import assess_resonance, load_engineering_estimate


RAW = ROOT / "data" / "raw"
MANIFESTS = ROOT / "data" / "manifests"
REGION = StudyRegion(121.5, 124.5, 38.5, 40.5, (11, 12, 1, 2, 3))
SMOKE_START = datetime(2026, 2, 20, tzinfo=timezone.utc)
SMOKE_END = datetime(2026, 2, 20, 23, 59, 59, tzinfo=timezone.utc)
BBOX = (121.5, 124.5, 38.5, 40.5)


def environment_dict(record):
    values = {
        name: getattr(record, name)
        for name in (
            "Hs", "Tp", "wave_direction", "wind_speed", "wind_direction",
            "surface_current_speed", "surface_current_direction", "water_depth",
        )
    }
    return {
        "timestamp": record.timestamp.isoformat(),
        "latitude": record.latitude,
        "longitude": record.longitude,
        **values,
        "provenance_by_field": {
            field: {
                **asdict(provenance),
                "decision": "ACCEPTED" if provenance.within_tolerance else "REJECTED",
            }
            for field, provenance in record.provenance_by_field.items()
        },
    }


def resonance_examples(wave_records):
    parameters, thresholds = load_engineering_estimate()
    best = {"NORMAL": None, "WARNING": None, "HIGH_RISK": None}
    speeds = tuple(value / 10 for value in range(0, 41))
    relative_angles = (0.0, 45.0, 90.0, 135.0, 180.0)
    targets = {"NORMAL": 0.30, "WARNING": 0.15, "HIGH_RISK": 0.05}
    sensitive_environment_keys = set()
    closest = None
    period_results = {}
    sensitive_periods = set()
    for record in wave_records:
        period_key = round(record.Tp, 8)
        if period_key in period_results:
            if period_key in sensitive_periods:
                sensitive_environment_keys.add((record.timestamp.isoformat(), record.latitude, record.longitude))
            continue
        period_best = {"NORMAL": None, "WARNING": None, "HIGH_RISK": None}
        record_sensitive = False
        for sog in speeds:
            for target_angle in relative_angles:
                hdg = (record.wave_direction + target_angle) % 360.0
                angle = relative_wave_angle(record.wave_direction, hdg)
                result = assess_resonance(
                    record.Tp, sog, angle, parameters=parameters, thresholds=thresholds,
                )
                status = result.resonance_status.value
                score = abs(result.resonance_margin_ratio - targets[status])
                if closest is None or result.resonance_margin_ratio < closest[0]:
                    closest = (result.resonance_margin_ratio, record, sog, hdg, angle, result)
                if period_best[status] is None or score < period_best[status][0]:
                    period_best[status] = (score, record, sog, hdg, angle, result)
                if status in {"WARNING", "HIGH_RISK"}:
                    record_sensitive = True
        period_results[period_key] = period_best
        if record_sensitive:
            sensitive_periods.add(period_key)
        for status, candidate in period_best.items():
            if candidate is not None and (best[status] is None or candidate[0] < best[status][0]):
                best[status] = candidate
        if record_sensitive:
            sensitive_environment_keys.add((record.timestamp.isoformat(), record.latitude, record.longitude))
    examples = []
    for status in targets:
        _, record, sog, hdg, angle, result = best[status]
        examples.append({
            "environment_source": "REAL PUBLIC ENVIRONMENT DATA",
            "vessel_state_source": "SIMULATED VESSEL STATE",
            "selection_method": "fixed SOG 0.0-4.0 m/s grid and relative angles 0/45/90/135/180; real Hs/Tp/direction unchanged",
            "timestamp": record.timestamp.isoformat(),
            "latitude": record.latitude,
            "longitude": record.longitude,
            "Hs": record.Hs,
            "Tp": record.Tp,
            "wave_direction": record.wave_direction,
            "SOG_m_s": sog,
            "HDG_deg": hdg,
            "relative_wave_angle_deg": angle,
            "encounter_frequency_rad_s": result.encounter_frequency_rad_s,
            "resonance_margin_ratio": result.resonance_margin_ratio,
            "resonance_status": result.resonance_status.value,
            "parameter_source": result.parameter_source.value,
            "parameter_status": result.parameter_status,
        })
    _, record, sog, hdg, angle, result = closest
    closest_condition = {
        "label": "基于工程估计横摇参数筛选的潜在共振敏感工况",
        "environment_source": "REAL PUBLIC ENVIRONMENT DATA",
        "vessel_state_source": "SIMULATED VESSEL STATE",
        "timestamp": record.timestamp.isoformat(), "latitude": record.latitude,
        "longitude": record.longitude, "Hs": record.Hs, "Tp": record.Tp,
        "wave_direction": record.wave_direction, "SOG_m_s": sog, "HDG_deg": hdg,
        "relative_wave_angle_deg": angle,
        "encounter_frequency_rad_s": result.encounter_frequency_rad_s,
        "resonance_margin_ratio": result.resonance_margin_ratio,
        "resonance_status": result.resonance_status.value,
        "parameter_source": result.parameter_source.value,
        "parameter_status": result.parameter_status,
    }
    return examples, len(sensitive_environment_keys), closest_condition


def file_provenance(path: Path) -> dict:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"filename": path.name, "filesize_bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def representative_windows(wind_records, wave_records, current_records, resonance):
    candidates = []
    for label, records, field in (
        ("maximum_Hs", wave_records, "Hs"),
        ("maximum_Tp", wave_records, "Tp"),
        ("maximum_wind_speed", wind_records, "wind_speed"),
        ("maximum_surface_current_speed", current_records, "surface_current_speed"),
    ):
        for record in sorted(records, key=lambda item: getattr(item, field), reverse=True)[:4]:
            candidates.append({
                "reason": label,
                "timestamp": record.timestamp.isoformat(),
                "latitude": record.latitude,
                "longitude": record.longitude,
                "Hs": record.Hs,
                "Tp": record.Tp,
                "wind_speed": record.wind_speed,
                "surface_current_speed": record.surface_current_speed,
            })
    candidates.extend({
        "reason": f"potential_resonance_{item['resonance_status']}",
        "timestamp": item["timestamp"], "latitude": item["latitude"], "longitude": item["longitude"],
        "Hs": item["Hs"], "Tp": item["Tp"], "wind_speed": None, "surface_current_speed": None,
    } for item in resonance)
    unique = []
    seen = set()
    for candidate in candidates:
        key = (candidate["timestamp"], candidate["latitude"], candidate["longitude"], candidate["reason"])
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique[:10]


def main() -> None:
    MANIFESTS.mkdir(parents=True, exist_ok=True)
    wave_smoke_path = RAW / "waverys" / "waverys_smoke_20260220.nc"
    era5_smoke_path = RAW / "era5" / "era5_smoke_20260220.nc"
    current_smoke_path = RAW / "glorys" / "glorys_surface_smoke_20260220.nc"
    depth_path = RAW / "gebco" / "GEBCO_2026_121.5_124.5E_38.5_40.5N.nc"
    wave_winter_path = RAW / "waverys" / "waverys_winter_20251101_20260331.nc"
    current_winter_path = RAW / "glorys" / "glorys_surface_winter_20251101_20260331.nc"
    era5_winter_path = RAW / "era5" / "era5_winter_20251101_20260331.nc"

    validations = {
        "ERA5": validate_public_netcdf(
            era5_smoke_path, product_id="reanalysis-era5-single-levels",
            dataset_id="reanalysis-era5-single-levels",
            variable_units={"u10": {"m s-1", "m s**-1"}, "v10": {"m s-1", "m s**-1"}},
            requested_bbox=BBOX, requested_time_range=(SMOKE_START, SMOKE_END),
            direction_convention="u10 eastward and v10 northward; project stores wind blowing-toward vector direction",
        ),
        "WAVERYS": validate_public_netcdf(
            wave_smoke_path, product_id="GLOBAL_MULTIYEAR_WAV_001_032",
            dataset_id="cmems_mod_glo_wav_my_0.2deg_PT3H-i", dataset_version="202411",
            variable_units={"VHM0": {"m"}, "VTPK": {"s"}, "VMDR": {"degree"}},
            requested_bbox=BBOX, requested_time_range=(SMOKE_START, SMOKE_END),
            direction_convention="VMDR is wave-from direction; project stores travel direction as (VMDR + 180) mod 360",
        ),
        "GLORYS": validate_public_netcdf(
            current_smoke_path, product_id="GLOBAL_MULTIYEAR_PHY_001_030",
            dataset_id="cmems_mod_glo_phy_my_0.083deg_P1D-m", dataset_version="202311",
            variable_units={"uo": {"m s-1"}, "vo": {"m s-1"}},
            requested_bbox=BBOX, requested_time_range=(SMOKE_START, SMOKE_END),
            direction_convention="uo eastward and vo northward; project stores vector travel direction",
            surface_depth_required=True,
        ),
        "GEBCO": validate_public_netcdf(
            depth_path, product_id="GEBCO_2026", dataset_id="GEBCO_2026 Grid ice surface elevation",
            variable_units={"elevation": {"m"}}, requested_bbox=BBOX, requested_time_range=None,
            direction_convention="negative elevation below mean sea level is converted to positive water_depth; land excluded",
        ),
    }

    wave_smoke = copernicus_wave.read_local_netcdf(
        wave_smoke_path, REGION, "cmems_mod_glo_wav_my_0.2deg_PT3H-i",
    )
    current_smoke = copernicus_current.read_local_netcdf(
        current_smoke_path, REGION, "cmems_mod_glo_phy_my_0.083deg_P1D-m",
    )
    depth = gebco.read_local_netcdf(depth_path, SMOKE_START, REGION, "GEBCO_2026")
    wind_smoke = era5.read_local_netcdf(
        era5_smoke_path, REGION, "reanalysis-era5-single-levels",
    )
    sampler = MarineEnvironmentSampler(
        [*wind_smoke, *wave_smoke, *current_smoke, *depth], SamplingTolerance(86_400, 30_000),
    )
    points = (
        (datetime(2026, 2, 20, 0, tzinfo=timezone.utc), 39.4, 122.0),
        (datetime(2026, 2, 20, 12, tzinfo=timezone.utc), 39.6, 122.5),
        (datetime(2026, 2, 20, 21, tzinfo=timezone.utc), 40.0, 122.2),
    )
    sampled = [environment_dict(sampler.sample(*point)) for point in points]
    smoke_resonance, _, smoke_closest = resonance_examples(wave_smoke)
    manifest = {
        "schema_version": 1,
        "artifact_type": "REAL PUBLIC ENVIRONMENT DATA VALIDATION WITH SEPARATE SIMULATED VESSEL STATE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "clipping_box_warning": "PROJECT CLIPPING BOX - NOT ZHUANGHE ADMINISTRATIVE BOUNDARY",
        "validations": validations,
        "adapter_record_counts": {
            "ERA5": len(wind_smoke), "WAVERYS": len(wave_smoke),
            "GLORYS": len(current_smoke), "GEBCO_ocean_cells": len(depth),
        },
        "smoke_test_all_sources_passed": all(item["status"] == "PASSED" for item in validations.values()),
        "nearest_neighbour_sampling_note": "Tolerance-controlled field assembly; NOT final multi-source fusion",
        "marine_environment_samples": sampled,
        "resonance_examples": smoke_resonance,
        "closest_potential_resonance_sensitive_condition": smoke_closest,
    }
    (MANIFESTS / "smoke_test_20260220.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )

    wave_winter = copernicus_wave.read_local_netcdf(
        wave_winter_path, REGION, "cmems_mod_glo_wav_my_0.2deg_PT3H-i",
    )
    current_winter = copernicus_current.read_local_netcdf(
        current_winter_path, REGION, "cmems_mod_glo_phy_my_0.083deg_P1D-m",
    )
    wind_winter = era5.read_local_netcdf(
        era5_winter_path, REGION, "reanalysis-era5-single-levels",
    )
    winter_resonance, sensitive_count, closest_sensitive = resonance_examples(wave_winter)
    max_hs = max(wave_winter, key=lambda item: item.Hs)
    max_wind = max(wind_winter, key=lambda item: item.wind_speed)
    winter_files = {
        "ERA5": validate_public_netcdf(
            era5_winter_path, product_id="reanalysis-era5-single-levels",
            dataset_id="reanalysis-era5-single-levels",
            variable_units={"u10": {"m s-1", "m s**-1"}, "v10": {"m s-1", "m s**-1"}},
            requested_bbox=BBOX,
            requested_time_range=(datetime(2025, 11, 1, tzinfo=timezone.utc), datetime(2026, 3, 31, 23, 59, 59, tzinfo=timezone.utc)),
            direction_convention="u10 eastward and v10 northward; project stores wind blowing-toward vector direction",
        ),
        "WAVERYS": validate_public_netcdf(
            wave_winter_path, product_id="GLOBAL_MULTIYEAR_WAV_001_032",
            dataset_id="cmems_mod_glo_wav_my_0.2deg_PT3H-i", dataset_version="202411",
            variable_units={"VHM0": {"m"}, "VTPK": {"s"}, "VMDR": {"degree"}},
            requested_bbox=BBOX,
            requested_time_range=(datetime(2025, 11, 1, tzinfo=timezone.utc), datetime(2026, 3, 31, 23, 59, 59, tzinfo=timezone.utc)),
            direction_convention="VMDR is wave-from direction; project stores travel direction as (VMDR + 180) mod 360",
        ),
        "GLORYS": validate_public_netcdf(
            current_winter_path, product_id="GLOBAL_MULTIYEAR_PHY_001_030",
            dataset_id="cmems_mod_glo_phy_my_0.083deg_P1D-m", dataset_version="202311",
            variable_units={"uo": {"m s-1"}, "vo": {"m s-1"}}, requested_bbox=BBOX,
            requested_time_range=(datetime(2025, 11, 1, tzinfo=timezone.utc), datetime(2026, 3, 31, 23, 59, 59, tzinfo=timezone.utc)),
            direction_convention="uo eastward and vo northward; project stores vector travel direction", surface_depth_required=True,
        ),
        "GEBCO": validations["GEBCO"],
    }
    winter_report = {
        "schema_version": 1,
        "data_classification": "REAL PUBLIC ENVIRONMENT DATA - NOT IN-SITU ZHUANGHE OBSERVATION",
        "time_range": ["2025-11-01T00:00:00Z", "2026-03-31T23:59:59Z"],
        "completeness": "COMPLETE FOR REQUESTED ERA5/WAVERYS/GLORYS/GEBCO INPUTS",
        "all_files_passed": all(item["status"] == "PASSED" for item in winter_files.values()),
        "files": winter_files,
        "era5_monthly_source_files": [
            file_provenance(RAW / "era5" / f"era5_{value}.nc")
            for value in ("202511", "202512", "202601", "202602", "202603")
        ],
        "adapter_record_counts": {
            "ERA5": len(wind_winter), "WAVERYS": len(wave_winter),
            "GLORYS": len(current_winter), "GEBCO_ocean_cells": len(depth),
        },
        "statistics": {
            "Hs_m": summarize((item.Hs for item in wave_winter), (90, 95)),
            "Tp_s": summarize((item.Tp for item in wave_winter), (90,)),
            "wind_speed_m_s": summarize((item.wind_speed for item in wind_winter), (90, 95)),
            "surface_current_speed_m_s": summarize(
                (item.surface_current_speed for item in current_winter), (95,),
            ),
        },
        "maximum_Hs": {
            "timestamp": max_hs.timestamp.isoformat(), "latitude": max_hs.latitude,
            "longitude": max_hs.longitude, "Hs_m": max_hs.Hs,
        },
        "maximum_wind_speed": {
            "timestamp": max_wind.timestamp.isoformat(), "latitude": max_wind.latitude,
            "longitude": max_wind.longitude, "wind_speed_m_s": max_wind.wind_speed,
        },
        "potential_resonance_sensitive_condition": {
            "label": "基于工程估计横摇参数筛选的潜在共振敏感工况",
            "unique_environment_point_count": sensitive_count,
            "closest_condition": closest_sensitive,
            "screening_examples": winter_resonance,
        },
        "representative_windows": representative_windows(
            wind_winter, wave_winter, current_winter, winter_resonance,
        ),
    }
    (MANIFESTS / "winter_environment_20251101_20260331.json").write_text(
        json.dumps(winter_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )


if __name__ == "__main__":
    main()
