"""Build V0.3 Commit 3 scenarios and task-level decision evidence."""

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
from core.marine import MarineEnvironment
from core.mission import MissionState
from core.models import TelemetryRecord
from core.resonance import load_engineering_estimate, search_resonance_avoidance
from core.risk import BaselineRiskEvaluator, VesselParameters


RAW = ROOT / "data" / "raw"
SCENARIOS = ROOT / "data" / "scenarios"
RESULTS = ROOT / "data" / "results"
WINTER_MANIFEST = ROOT / "data" / "manifests" / "winter_environment_20251101_20260331.json"
REGION = StudyRegion(121.5, 124.5, 38.5, 40.5, (11, 12, 1, 2, 3))
ENVIRONMENT_LABEL = "REAL PUBLIC ENVIRONMENT DATA - NOT IN-SITU ZHUANGHE OBSERVATION"
VESSEL_LABEL = "SIMULATED VESSEL STATE"
RESPONSE_LABEL = "UNAVAILABLE - NO REAL OR SIMULATED ATTITUDE RESPONSE USED"


def _environment_dict(environment: MarineEnvironment) -> dict:
    return {
        "timestamp": environment.timestamp.isoformat(),
        "latitude": environment.latitude,
        "longitude": environment.longitude,
        "Hs": environment.Hs,
        "Tp": environment.Tp,
        "wave_direction": environment.wave_direction,
        "wind_speed": environment.wind_speed,
        "wind_direction": environment.wind_direction,
        "surface_current_speed": environment.surface_current_speed,
        "surface_current_direction": environment.surface_current_direction,
        "water_depth": environment.water_depth,
        "provenance_by_field": {
            field: {
                **asdict(provenance),
                "decision": "ACCEPTED" if provenance.within_tolerance else "REJECTED",
            }
            for field, provenance in environment.provenance_by_field.items()
        },
    }


def _telemetry(environment: dict, speed: float, heading: float) -> TelemetryRecord:
    return TelemetryRecord(
        timestamp=datetime.fromisoformat(environment["timestamp"]),
        latitude=environment["latitude"], longitude=environment["longitude"],
        Hs=environment["Hs"], Tp=environment["Tp"], wave_direction=environment["wave_direction"],
        wind_speed=environment["wind_speed"], wind_direction=environment["wind_direction"],
        surface_current_speed=environment["surface_current_speed"],
        surface_current_direction=environment["surface_current_direction"],
        SOG=speed, COG=heading, HDG=heading,
        roll=None, pitch=None, roll_rate=None, battery=None,
        mission_state=MissionState.OUTBOUND,
        data_label=f"{ENVIRONMENT_LABEL} + {VESSEL_LABEL}",
    )


def _risk(environment: dict, speed: float, heading: float, evaluator, vessel) -> dict:
    result = evaluator.evaluate(_telemetry(environment, speed, heading), vessel)
    return {
        "risk_score": result.risk_score,
        "risk_level": result.risk_level.value,
        "risk_components": result.risk_components,
        "primary_risk": result.primary_risk,
        "data_quality": result.data_quality,
        "attitude_response_source": RESPONSE_LABEL,
    }


def _candidate_dict(candidate, environment: dict, evaluator, vessel) -> dict | None:
    if candidate is None:
        return None
    return {
        "SOG": candidate.SOG_m_s,
        "HDG": candidate.HDG_deg,
        "relative_wave_angle": candidate.relative_wave_angle_deg,
        "encounter_frequency": candidate.encounter_frequency_rad_s,
        "resonance_margin_ratio": candidate.resonance_margin_ratio,
        "resonance_status": candidate.resonance_status.value,
        "parameter_source": candidate.parameter_source,
        "parameter_status": candidate.parameter_status,
        "speed_change_percent": candidate.speed_change_percent,
        "heading_change_deg": candidate.heading_change_deg,
        **_risk(environment, candidate.SOG_m_s, candidate.HDG_deg, evaluator, vessel),
    }


def _plan_dict(plan, environment: dict, evaluator, vessel) -> dict:
    return {
        "mode": plan.mode.value,
        "decision_status": plan.decision_status.value,
        "recommended": _candidate_dict(plan.recommended, environment, evaluator, vessel),
        "speed_loss_percent": plan.speed_loss_percent,
        "estimated_travel_time_change_percent": plan.estimated_travel_time_change_percent,
        "energy_cost": plan.energy_cost,
        "energy_model_status": plan.energy_model_status,
        "control_output_status": plan.control_output_status,
        "decision_reason": plan.decision_reason,
    }


def main() -> None:
    winter = json.loads(WINTER_MANIFEST.read_text(encoding="utf-8"))
    selected = {
        item["resonance_status"]: item
        for item in winter["potential_resonance_sensitive_condition"]["screening_examples"]
    }
    wave_path = RAW / "waverys" / "waverys_winter_20251101_20260331.nc"
    current_path = RAW / "glorys" / "glorys_surface_winter_20251101_20260331.nc"
    wind_path = RAW / "era5" / "era5_winter_20251101_20260331.nc"
    depth_path = RAW / "gebco" / "GEBCO_2026_121.5_124.5E_38.5_40.5N.nc"
    reference_time = datetime(2025, 11, 1, tzinfo=timezone.utc)
    records = [
        *era5.read_local_netcdf(wind_path, REGION, "reanalysis-era5-single-levels"),
        *copernicus_wave.read_local_netcdf(wave_path, REGION, "cmems_mod_glo_wav_my_0.2deg_PT3H-i"),
        *copernicus_current.read_local_netcdf(current_path, REGION, "cmems_mod_glo_phy_my_0.083deg_P1D-m"),
        *gebco.read_local_netcdf(depth_path, reference_time, REGION, "GEBCO_2026"),
    ]
    sampler = MarineEnvironmentSampler(records, SamplingTolerance(86_400, 30_000))
    parameters, thresholds = load_engineering_estimate()
    evaluator = BaselineRiskEvaluator()
    vessel = VesselParameters(
        model="ZLUSV-200", length_overall_m=2.02, beam_m=0.88, draft_m=0.25,
        hull_mass_approx_kg=50.0, full_load_displacement_min_kg=100.0,
    )
    SCENARIOS.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    results = []
    filenames = {
        "NORMAL": "normal_mission.json",
        "WARNING": "warning_mission.json",
        "HIGH_RISK": "high_risk_mission.json",
    }
    for expected_status in ("NORMAL", "WARNING", "HIGH_RISK"):
        seed = selected[expected_status]
        target_time = datetime.fromisoformat(seed["timestamp"])
        sampled = sampler.sample(target_time, seed["latitude"], seed["longitude"])
        environment = _environment_dict(sampled)
        if any(environment[field] is None for field in (
            "Hs", "Tp", "wave_direction", "wind_speed", "wind_direction",
            "surface_current_speed", "surface_current_direction", "water_depth",
        )):
            raise RuntimeError(f"scenario {expected_status} has rejected or missing environment fields")
        search = search_resonance_avoidance(
            Tp_s=environment["Tp"], wave_direction_deg=environment["wave_direction"],
            current_speed_m_s=seed["SOG_m_s"], current_heading_deg=seed["HDG_deg"],
            parameters=parameters, thresholds=thresholds,
        )
        if search.current.resonance_status.value != expected_status:
            raise RuntimeError(f"scenario status drift: expected {expected_status}, got {search.current.resonance_status.value}")
        before = _candidate_dict(search.current, environment, evaluator, vessel)
        plans = {
            "speed_only": _plan_dict(search.speed_only, environment, evaluator, vessel),
            "heading_only": _plan_dict(search.heading_only, environment, evaluator, vessel),
            "joint_speed_heading": _plan_dict(search.joint, environment, evaluator, vessel),
        }
        after = _candidate_dict(search.recommended, environment, evaluator, vessel)
        if after is not None:
            after["recommended_SOG"] = after["SOG"]
            after["recommended_HDG"] = after["HDG"]
        selected_plan = next(
            (value for value in plans.values() if value["mode"] == (search.recommended_mode.value if search.recommended_mode else None)),
            None,
        )
        scenario = {
            "schema_version": 1,
            "scenario_id": expected_status,
            "environment_source": ENVIRONMENT_LABEL,
            "vessel_state_source": VESSEL_LABEL,
            "attitude_response_source": RESPONSE_LABEL,
            "parameter_source": parameters.parameter_source.value,
            "parameter_status": parameters.parameter_status,
            "threshold_status": thresholds.status,
            "source_manifest": "data/manifests/winter_environment_20251101_20260331.json",
            "source_file_sha256": {
                name: winter["files"][name]["sha256"] for name in ("ERA5", "WAVERYS", "GLORYS", "GEBCO")
            },
            "environment": environment,
            "simulated_vessel_state": {
                "SOG": seed["SOG_m_s"], "HDG": seed["HDG_deg"],
                "roll": None, "pitch": None, "roll_rate": None,
                "label": VESSEL_LABEL,
            },
            "before": before,
            "plans": plans,
            "after": after,
            "selected_mode": search.recommended_mode.value if search.recommended_mode else None,
            "decision_status": search.decision_status.value,
            "decision_reason": search.decision_reason,
            "speed_loss_percent": selected_plan["speed_loss_percent"] if selected_plan else None,
            "estimated_travel_time_change_percent": (
                selected_plan["estimated_travel_time_change_percent"] if selected_plan else None
            ),
            "energy_cost": None,
            "energy_model_status": "REQUIRES REAL SPEED-POWER DATA",
            "control_output_status": "DECISION ADVICE ONLY - NO REAL ACTUATOR COMMAND",
        }
        (SCENARIOS / filenames[expected_status]).write_text(
            json.dumps(scenario, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        results.append(scenario)

    high = next(item for item in results if item["scenario_id"] == "HIGH_RISK")
    mission_result = {
        "schema_version": 1,
        "demo_name": "V0.3 REAL WINTER ENVIRONMENT MISSION RESONANCE AVOIDANCE",
        "environment_source": ENVIRONMENT_LABEL,
        "vessel_state_source": VESSEL_LABEL,
        "parameter_source": parameters.parameter_source.value,
        "parameter_status": parameters.parameter_status,
        "algorithm_status": "DETERMINISTIC ENGINEERING SEARCH - NOT SAC / NOT REINFORCEMENT LEARNING",
        "control_status": "DECISION ADVICE ONLY - REAL VESSEL CONTROL DISABLED",
        "mission_flow": [
            "NORMAL_NAVIGATION", "ENTER_REAL_WINTER_ENVIRONMENT", "EVALUATE_SINGLE_VESSEL_RISK",
            "CALCULATE_ENCOUNTER_FREQUENCY", "DETECT_HIGH_RISK_RESONANCE_PROXIMITY",
            "SEARCH_SPEED_AND_HEADING_CANDIDATES", "SELECT_RECOMMENDATION",
            "VERIFY_RESONANCE_MARGIN_IMPROVEMENT", "CONTINUE_SIMULATED_INSPECTION_MISSION",
        ],
        "scenarios": results,
        "high_risk_evidence": {
            "before": high["before"], "after": high["after"],
            "decision_reason": high["decision_reason"],
            "speed_loss_percent": high["speed_loss_percent"],
        },
        "no_safe_candidate_policy": {
            "status": "NO_SAFE_CANDIDATE_WITHIN_SEARCH_LIMITS",
            "operator_advice": "PAUSE / RETURN ASSESSMENT",
            "standard_scenarios_triggered": False,
            "note": "The explicit no-safe path is covered by a restrictive-boundary regression test.",
        },
        "energy_cost": None,
        "energy_model_status": "REQUIRES REAL SPEED-POWER DATA",
    }
    (RESULTS / "v0.3_mission_demo.json").write_text(
        json.dumps(mission_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(mission_result["high_risk_evidence"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
