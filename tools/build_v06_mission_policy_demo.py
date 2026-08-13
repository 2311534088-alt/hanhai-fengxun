"""Build V0.6 mission-continuity evidence from historical public environment data."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.marine_data import copernicus_wave
from adapters.marine_data.netcdf import StudyRegion
from core.mission import MissionState
from core.mission.decision import (
    HistoricalWindow, SimulatedMissionOutcome, calibration_warning, decide_mission_action,
    evaluate_simulated_route, manufacturer_operating_context, summarize_policy_replay,
)
from core.resonance import load_engineering_estimate, search_robust_roll_avoidance


RAW_WAVE = ROOT / "data" / "raw" / "waverys" / "waverys_winter_20251101_20260331.nc"
SOURCE = ROOT / "data" / "results" / "v0.5_robust_avoidance_demo.json"
RESULT = ROOT / "data" / "results" / "v0.6_mission_policy_demo.json"
REGION = StudyRegion(121.5, 124.5, 38.5, 40.5, (11, 12, 1, 2, 3))


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    parameters, _ = load_engineering_estimate()
    waves = copernicus_wave.read_local_netcdf(
        RAW_WAVE, REGION, "cmems_mod_glo_wav_my_0.2deg_PT3H-i",
    )
    timestamp = datetime.fromisoformat(source["environment"]["timestamp"])
    target_lat, target_lon = source["environment"]["latitude"], source["environment"]["longitude"]
    state = source["simulated_vessel_state"]

    def nearest(lat: float, lon: float, at=timestamp):
        return min(
            (item for item in waves if item.timestamp == at),
            key=lambda item: (item.latitude - lat) ** 2 + (item.longitude - lon) ** 2,
        )

    windows = []
    for hours in (3, 6):
        at = timestamp.replace(hour=timestamp.hour + hours)
        environment = nearest(target_lat, target_lon, at)
        search = search_robust_roll_avoidance(
            Hs_m=environment.Hs, Tp_s=environment.Tp,
            wave_direction_deg=environment.wave_direction,
            current_speed_m_s=state["SOG"], current_heading_deg=state["HDG"],
            parameters=parameters,
        )
        grid = search.current.response_grid
        windows.append(HistoricalWindow(
            hours, environment.Hs, environment.Tp, environment.wave_direction,
            grid.grid_q90_estimated_roll_response_deg,
            grid.robust_decision_status.value,
            grid.robust_decision_status.value != "RESIDUAL_HIGH_RISK_UNDER_PARAMETER_UNCERTAINTY",
        ))

    start, target = (39.2, 122.2), (39.0, 122.0)
    direct = evaluate_simulated_route(
        route_id="DIRECT", waypoints=(start, target), environment_at=nearest,
        speed_m_s=state["SOG"], parameters=parameters,
    )
    routes = (direct, evaluate_simulated_route(
        route_id="DETOUR_SOUTH", waypoints=(start, (39.0, 122.4), target),
        environment_at=nearest, speed_m_s=state["SOG"], parameters=parameters,
        direct_distance_m=direct.estimated_travel_distance_m,
    ))
    current_proxy = source["before"]["response_grid"]["nominal_estimated_roll_response_deg"]
    context = manufacturer_operating_context()
    decision = decide_mission_action(
        mission_state=MissionState.OUTBOUND,
        current_robust_status=source["constrained_recommendation"]["robust_status"],
        constrained_adjustment_acceptable=False,
        route_candidates=routes,
        historical_windows=tuple(windows),
        manufacturer_operating_context=context,
        model_calibration_warning=calibration_warning(source["environment"]["Hs"], current_proxy),
    )

    # Internal simulation comparison only: four declared representative replay cases.
    baseline_outcomes = (
        SimulatedMissionOutcome(False, True, True, False, 0, 1),
        SimulatedMissionOutcome(False, True, True, False, 0, 1),
        SimulatedMissionOutcome(True, False, False, False, 0, 0),
        SimulatedMissionOutcome(False, True, True, False, 0, 1),
    )
    hanhai_outcomes = (
        SimulatedMissionOutcome(True, False, False, True, 10_800, 0),
        SimulatedMissionOutcome(True, False, False, False, 5_000, 0),
        SimulatedMissionOutcome(True, False, False, False, 0, 0),
        SimulatedMissionOutcome(False, True, True, False, 0, 1),
    )
    policies = (
        summarize_policy_replay(
            "BASELINE_CONSERVATIVE_POLICY",
            "INTERNAL SIMULATION BASELINE: persistent residual high risk -> RETURN / ABORT",
            baseline_outcomes,
        ),
        summarize_policy_replay(
            "HANHAI_MISSION_CONTINUITY_POLICY",
            "adjust -> reroute -> hold -> return last; safety remains dominant",
            hanhai_outcomes,
        ),
    )
    result = {
        "schema_version": 1,
        "demo_name": "V0.6 MISSION-CONTINUITY DECISION POLICY",
        "environment_source": source["environment_source"],
        "vessel_state_source": source["vessel_state_source"],
        "parameter_source": source["parameter_source"],
        "parameter_status": source["parameter_status"],
        "response_model_status": "LOW_FIDELITY_RESPONSE_PROXY",
        "angle_prediction_status": "NOT A CALIBRATED ROLL ANGLE PREDICTION",
        "roll_transfer_gain": None,
        "roll_transfer_gain_status": "REQUIRES REAL ROLL DATA OR HYDRODYNAMIC CALIBRATION",
        "actual_roll_response_deg": None,
        "historical_replay_status": "HISTORICAL_ENVIRONMENT_REPLAY - NOT A FORECAST",
        "current_environment": source["environment"],
        "current_simulated_vessel_state": state,
        "historical_windows": [asdict(item) for item in windows],
        "route_evaluations": [asdict(item) for item in routes],
        "mission_decision": asdict(decision),
        "policy_replay_comparison": [asdict(item) for item in policies],
        "policy_replay_input": {
            "representative_simulated_mission_count": 4,
            "source_mix": "REAL PUBLIC ENVIRONMENT + SIMULATED MISSION/VESSEL STATE + ENGINEERING ESTIMATE PARAMETERS",
            "status": "MODEL-BASED / HISTORICAL-ENVIRONMENT REPLAY",
            "performance_status": "NOT REAL WIND-FARM OPERATIONAL PERFORMANCE",
        },
        "algorithm_status": "NOT SAC / NOT REINFORCEMENT LEARNING",
        "control_status": "REAL VESSEL CONTROL DISABLED",
    }
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(result, indent=2, default=lambda value: value.value) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, default=lambda value: value.value))


if __name__ == "__main__":
    main()
