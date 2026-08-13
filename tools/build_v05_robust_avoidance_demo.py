"""Build V0.5 robust-avoidance evidence for the retained public-environment case."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.resonance import load_engineering_estimate, search_robust_roll_avoidance


SOURCE = ROOT / "data" / "scenarios" / "v0.4" / "high_roll_response_risk.json"
RESULT = ROOT / "data" / "results" / "v0.5_robust_avoidance_demo.json"
ENVIRONMENT_LABEL = "REAL PUBLIC ENVIRONMENT DATA - NOT IN-SITU ZHUANGHE OBSERVATION"
VESSEL_LABEL = "SIMULATED VESSEL STATE"


def _grid(grid) -> dict:
    data = asdict(grid)
    for key in ("nominal_roll_risk", "grid_q90_roll_risk", "worst_case_roll_risk", "robust_decision_status"):
        data[key] = getattr(grid, key).value
    return data


def _candidate(candidate) -> dict:
    return {
        "SOG": candidate.SOG_m_s, "HDG": candidate.HDG_deg,
        "relative_wave_angle": candidate.relative_wave_angle_deg,
        "speed_change_percent": candidate.speed_change_percent,
        "heading_change_deg": candidate.heading_change_deg,
        "response_grid": _grid(candidate.response_grid),
        "speed_search_boundary_hit": candidate.speed_search_boundary_hit,
        "heading_search_boundary_hit": candidate.heading_search_boundary_hit,
        "boundary_status": candidate.boundary_status,
        "decision_confidence_warning": candidate.decision_confidence_warning,
        "conflict_status": candidate.conflict_status,
    }


def _recommendation(recommendation) -> dict:
    return {
        "label": recommendation.label,
        "candidate": _candidate(recommendation.candidate),
        "robust_status": recommendation.robust_status.value,
        "operator_advice": recommendation.operator_advice,
        "evaluated_candidate_count": recommendation.evaluated_candidate_count,
        "search_bound_status": recommendation.search_bound_status,
        "operational_range_status": recommendation.operational_range_status,
    }


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    environment = source["environment"]
    state = source["simulated_vessel_state"]
    parameters, _ = load_engineering_estimate()
    search = search_robust_roll_avoidance(
        Hs_m=environment["Hs"], Tp_s=environment["Tp"],
        wave_direction_deg=environment["wave_direction"],
        current_speed_m_s=state["SOG"], current_heading_deg=state["HDG"],
        parameters=parameters,
    )
    constrained = _recommendation(search.constrained_recommendation)
    unrestricted = _recommendation(search.unrestricted_simulation_best)
    result = {
        "schema_version": 1,
        "demo_name": "V0.5 PARAMETER-UNCERTAINTY-AWARE ROBUST ROLL AVOIDANCE",
        "environment_source": ENVIRONMENT_LABEL,
        "vessel_state_source": VESSEL_LABEL,
        "parameter_source": search.parameter_source,
        "parameter_status": search.parameter_status,
        "response_model_status": "LOW_FIDELITY_ENGINEERING_ESTIMATE",
        "response_validation_status": "NOT VALIDATED AGAINST REAL ROLL DATA",
        "parameter_grid_method": search.parameter_grid_method,
        "parameter_grid_statistical_status": search.parameter_grid_statistical_status,
        "source_scenario": "data/scenarios/v0.4/high_roll_response_risk.json",
        "environment": environment,
        "simulated_vessel_state": state,
        "maximum_operational_speed_m_s": None,
        "maximum_operational_speed_status": "REQUIRES MANUFACTURER DATA OR REAL SPEED TEST",
        "before": _candidate(search.current),
        "unrestricted_simulation_best": unrestricted,
        "constrained_recommendation": constrained,
        "preliminary_maneuver_constraint": asdict(search.maneuver_constraint),
        "residual_high_risk": (
            constrained["robust_status"] == "RESIDUAL_HIGH_RISK_UNDER_PARAMETER_UNCERTAINTY"
        ),
        "model_result_expression_limit": (
            "USE MODEL-ESTIMATED RELATIVE REDUCTION; DO NOT DESCRIBE AS MEASURED ROLL REDUCTION"
        ),
        "algorithm_status": "NOT SAC / NOT REINFORCEMENT LEARNING",
        "control_status": "REAL VESSEL CONTROL DISABLED",
    }
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "before": result["before"],
        "unrestricted_simulation_best": unrestricted,
        "constrained_recommendation": constrained,
    }, indent=2))


if __name__ == "__main__":
    main()
