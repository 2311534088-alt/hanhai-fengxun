"""Build V0.4 roll-response scenarios from validated public winter products."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.marine_data import copernicus_current, copernicus_wave, era5, gebco
from adapters.marine_data.netcdf import StudyRegion
from adapters.marine_data.sampler import MarineEnvironmentSampler, SamplingTolerance
from core.navigation import relative_wave_angle
from core.resonance import load_engineering_estimate, search_resonance_avoidance
from core.roll_response import scan_roll_response_uncertainty


RAW = ROOT / "data" / "raw"
SCENARIOS = ROOT / "data" / "scenarios" / "v0.4"
RESULT = ROOT / "data" / "results" / "v0.4_roll_response_demo.json"
MANIFEST = ROOT / "data" / "manifests" / "winter_environment_20251101_20260331.json"
REGION = StudyRegion(121.5, 124.5, 38.5, 40.5, (11, 12, 1, 2, 3))
ENVIRONMENT_LABEL = "REAL PUBLIC ENVIRONMENT DATA - NOT IN-SITU ZHUANGHE OBSERVATION"
VESSEL_LABEL = "SIMULATED VESSEL STATE"
PARAMETER_LABEL = "ENGINEERING_ESTIMATE / NOT_EXPERIMENTALLY_CALIBRATED"
REDUCTION_LABEL = "MODEL-ESTIMATED REDUCTION / NOT EXPERIMENTALLY MEASURED"


SEEDS = (
    {
        "scenario_id": "FREQUENCY_CLOSE_LOW_EXCITATION",
        "timestamp": "2025-11-01T00:00:00+00:00", "latitude": 39.599998474121094,
        "longitude": 123.4000015258789, "SOG": 2.1, "HDG": 234.93,
        "selection": "Retained V0.3 Hs=0.14 m case and reclassified with wave-excitation-aware model.",
    },
    {
        "scenario_id": "MODERATE_ROLL_RESPONSE_RISK",
        "timestamp": "2026-03-12T12:00:00+00:00", "latitude": 39.2,
        "longitude": 122.8, "SOG": 0.9, "HDG": 305.48,
        "selection": "Real WAVERYS point screened on declared simulated SOG/relative-angle grid.",
    },
    {
        "scenario_id": "HIGH_ROLL_RESPONSE_RISK",
        "timestamp": "2026-02-05T00:00:00+00:00", "latitude": 39.2,
        "longitude": 122.2, "SOG": 1.8, "HDG": 214.66,
        "selection": "Highest nominal response among frequency-close real WAVERYS points on the declared grid.",
    },
)


def _environment(environment) -> dict:
    return {
        "timestamp": environment.timestamp.isoformat(), "latitude": environment.latitude,
        "longitude": environment.longitude, "Hs": environment.Hs, "Tp": environment.Tp,
        "wave_direction": environment.wave_direction, "wind_speed": environment.wind_speed,
        "wind_direction": environment.wind_direction,
        "surface_current_speed": environment.surface_current_speed,
        "surface_current_direction": environment.surface_current_direction,
        "water_depth": environment.water_depth,
        "provenance_by_field": {
            name: {**asdict(item), "decision": "ACCEPTED" if item.within_tolerance else "REJECTED"}
            for name, item in environment.provenance_by_field.items()
        },
    }


def _candidate(candidate) -> dict | None:
    if candidate is None:
        return None
    return {
        "SOG": candidate.SOG_m_s, "HDG": candidate.HDG_deg,
        "relative_wave_angle": candidate.relative_wave_angle_deg,
        "encounter_frequency_rad_s": candidate.encounter_frequency_rad_s,
        "frequency_ratio": candidate.frequency_ratio,
        "resonance_margin_ratio": candidate.resonance_margin_ratio,
        "resonance_proximity_status": candidate.resonance_proximity_status.value,
        "wave_slope_proxy": candidate.wave_slope_proxy,
        "beam_excitation_factor": candidate.beam_excitation_factor,
        "dynamic_amplification_factor": candidate.dynamic_amplification_factor,
        "estimated_roll_response_deg": candidate.estimated_roll_response_deg,
        "roll_response_risk": candidate.roll_response_risk.value,
        "parameter_source": candidate.parameter_source,
        "parameter_status": candidate.parameter_status,
        "response_model_status": candidate.response_model_status,
        "response_validation_status": candidate.response_validation_status,
        "roll_response_classification": candidate.roll_response_classification,
        "roll_response_proxy": candidate.estimated_roll_response_deg,
        "roll_response_degree_equivalent": candidate.estimated_roll_response_deg,
        "actual_roll_response_deg": None,
        "roll_transfer_gain": None,
        "roll_transfer_gain_status": "REQUIRES REAL ROLL DATA OR HYDRODYNAMIC CALIBRATION",
        "angle_prediction_status": "NOT A CALIBRATED ROLL ANGLE PREDICTION",
        "legacy_estimated_roll_response_deg_status": "DEPRECATED COMPATIBILITY FIELD",
    }


def main() -> None:
    winter = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = [
        *era5.read_local_netcdf(RAW / "era5" / "era5_winter_20251101_20260331.nc", REGION,
                                "reanalysis-era5-single-levels"),
        *copernicus_wave.read_local_netcdf(
            RAW / "waverys" / "waverys_winter_20251101_20260331.nc", REGION,
            "cmems_mod_glo_wav_my_0.2deg_PT3H-i"),
        *copernicus_current.read_local_netcdf(
            RAW / "glorys" / "glorys_surface_winter_20251101_20260331.nc", REGION,
            "cmems_mod_glo_phy_my_0.083deg_P1D-m"),
        *gebco.read_local_netcdf(
            RAW / "gebco" / "GEBCO_2026_121.5_124.5E_38.5_40.5N.nc",
            datetime(2025, 11, 1, tzinfo=timezone.utc), REGION, "GEBCO_2026"),
    ]
    sampler = MarineEnvironmentSampler(records, SamplingTolerance(86_400, 30_000))
    parameters, resonance_thresholds = load_engineering_estimate()
    SCENARIOS.mkdir(parents=True, exist_ok=True)
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    scenarios = []
    for seed in SEEDS:
        environment = _environment(sampler.sample(
            datetime.fromisoformat(seed["timestamp"]), seed["latitude"], seed["longitude"],
        ))
        if any(environment[name] is None for name in (
            "Hs", "Tp", "wave_direction", "wind_speed", "wind_direction",
            "surface_current_speed", "surface_current_direction", "water_depth",
        )):
            raise RuntimeError(f"{seed['scenario_id']} contains rejected or missing environment fields")
        search = search_resonance_avoidance(
            Hs_m=environment["Hs"], Tp_s=environment["Tp"],
            wave_direction_deg=environment["wave_direction"],
            current_speed_m_s=seed["SOG"], current_heading_deg=seed["HDG"],
            parameters=parameters, thresholds=resonance_thresholds,
        )
        before, after = _candidate(search.current), _candidate(search.recommended)
        before_uncertainty = asdict(scan_roll_response_uncertainty(
            Hs_m=environment["Hs"], Tp_s=environment["Tp"],
            vessel_speed_m_s=search.current.SOG_m_s,
            relative_wave_angle_deg=search.current.relative_wave_angle_deg,
            parameters=parameters,
        ))
        after_uncertainty = asdict(scan_roll_response_uncertainty(
            Hs_m=environment["Hs"], Tp_s=environment["Tp"],
            vessel_speed_m_s=search.recommended.SOG_m_s,
            relative_wave_angle_deg=search.recommended.relative_wave_angle_deg,
            parameters=parameters,
        ))
        reduction = max(0.0, (
            1.0 - after["estimated_roll_response_deg"] / before["estimated_roll_response_deg"]
        ) * 100.0) if before["estimated_roll_response_deg"] > 0 else 0.0
        scenario = {
            "schema_version": 1, "scenario_id": seed["scenario_id"],
            "environment_source": ENVIRONMENT_LABEL, "vessel_state_source": VESSEL_LABEL,
            "parameter_source": parameters.parameter_source.value,
            "parameter_status": parameters.parameter_status,
            "parameter_classification": PARAMETER_LABEL,
            "response_model_status": "LOW_FIDELITY_ENGINEERING_ESTIMATE",
        "response_validation_status": "NOT VALIDATED AGAINST REAL ROLL DATA",
        "parameter_grid_method": "DETERMINISTIC SENSITIVITY GRID",
        "parameter_grid_statistical_status": "NOT A STATISTICAL CONFIDENCE INTERVAL",
        "threshold_status": "PRELIMINARY / NEEDS CALIBRATION",
            "selection_method": seed["selection"],
            "source_manifest": "data/manifests/winter_environment_20251101_20260331.json",
            "source_file_sha256": {
                name: winter["files"][name]["sha256"] for name in ("ERA5", "WAVERYS", "GLORYS", "GEBCO")
            },
            "environment": environment,
            "simulated_vessel_state": {
                "SOG": seed["SOG"], "HDG": seed["HDG"],
                "roll": None, "pitch": None, "roll_rate": None, "label": VESSEL_LABEL,
            },
            "before": before, "after": after,
            "before_uncertainty": before_uncertainty, "after_uncertainty": after_uncertainty,
            "recommended_mode": search.recommended_mode.value if search.recommended_mode else None,
            "decision_status": search.decision_status.value,
            "decision_reason": search.decision_reason,
            "estimated_roll_reduction_percent": reduction,
            "reduction_label": REDUCTION_LABEL,
            "control_status": "DECISION ADVICE ONLY - REAL VESSEL CONTROL DISABLED",
            "algorithm_status": "DETERMINISTIC ENGINEERING SEARCH - NOT SAC / NOT REINFORCEMENT LEARNING",
        }
        filename = seed["scenario_id"].lower() + ".json"
        (SCENARIOS / filename).write_text(json.dumps(scenario, indent=2) + "\n", encoding="utf-8")
        scenarios.append(scenario)
    high = next(item for item in scenarios if item["scenario_id"] == "HIGH_ROLL_RESPONSE_RISK")
    result = {
        "schema_version": 1, "demo_name": "V0.4 WAVE-EXCITATION-AWARE ROLL RESPONSE",
        "environment_source": ENVIRONMENT_LABEL, "vessel_state_source": VESSEL_LABEL,
        "parameter_classification": PARAMETER_LABEL,
        "response_model_status": "LOW_FIDELITY_ENGINEERING_ESTIMATE",
        "response_validation_status": "NOT VALIDATED AGAINST REAL ROLL DATA",
        "parameter_grid_method": "DETERMINISTIC SENSITIVITY GRID",
        "parameter_grid_statistical_status": "NOT A STATISTICAL CONFIDENCE INTERVAL",
        "threshold_status": "PRELIMINARY / NEEDS CALIBRATION",
        "formula_note": "Standard SDOF DAF uses sqrt((1-r^2)^2 + (2*zeta*r)^2); response proxy is excitation multiplied by DAF.",
        "winter_screening_grid": {
            "real_fields_unchanged": ["Hs", "Tp", "wave_direction"],
            "simulated_speed_range_m_s": [0.5, 3.0],
            "simulated_speed_step_m_s": 0.1,
            "simulated_relative_wave_angles_deg": [90, 105, 120, 135, 150, 165, 180],
            "scope": "frequency-close candidates with resonance_margin_ratio < 0.10",
        },
        "scenarios": scenarios, "representative_high_risk_evidence": high,
        "reduction_label": REDUCTION_LABEL,
        "algorithm_status": "NOT SAC / NOT REINFORCEMENT LEARNING",
        "control_status": "REAL VESSEL CONTROL DISABLED",
    }
    RESULT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(high, indent=2))


if __name__ == "__main__":
    main()
