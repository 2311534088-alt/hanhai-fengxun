"""Build V0.7 causal mission-replay development evidence from real public waves."""

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
from core.mission import (
    CausalEnvironmentStore, EnvironmentUse, MissionCase, ReplayPolicy, evaluate_business_value_gate,
    mission_saved, replay_complete_mission, summarize_complete_replay,
)
from core.mission.causal_replay import (
    CAUSAL_MODE, MODEL_BASED_REPLAY, NOT_OPERATIONAL_PERFORMANCE, ORACLE_MODE,
    REAL_ENVIRONMENT, SIMULATED_VESSEL, STRESS_TEST_ROUTE, _distance,
)
from core.resonance import load_engineering_estimate


RAW_WAVE = ROOT / "data/raw/waverys/waverys_winter_20251101_20260331.nc"
RESULT = ROOT / "data/generated/v0.7_causal_mission_replay.json"
REGION = StudyRegion(121.5, 124.5, 38.5, 40.5, (11, 12, 1, 2, 3))
DATASET_ID = "cmems_mod_glo_wav_my_0.2deg_PT3H-i"
SELECTION_RULE = (
    "At fixed simulated departure point (39.2N, 122.2E), group all 3-hour WAVERYS "
    "timestamps by month; sort each month by deterministic wave-excitation stratum "
    "score Hs/Tp^2; select 8 evenly spaced cases from each lower/middle/upper tercile "
    "(24 per month x 5 months = 120). No outcome or policy result is used in selection."
)


def _evenly(values, count):
    if len(values) < count:
        raise ValueError("not enough records for deterministic stratum")
    return [values[round(i * (len(values) - 1) / (count - 1))] for i in range(count)]


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    raise TypeError(f"cannot serialize {type(value).__name__}")


def select_cases(records):
    point_records = {}
    for item in records:
        current = point_records.get(item.timestamp)
        distance = (item.latitude - 39.2) ** 2 + (item.longitude - 122.2) ** 2
        if current is None or distance < (current.latitude - 39.2) ** 2 + (current.longitude - 122.2) ** 2:
            point_records[item.timestamp] = item
    cases = []
    for month in ((2025, 11), (2025, 12), (2026, 1), (2026, 2), (2026, 3)):
        values = [item for item in point_records.values() if (item.timestamp.year, item.timestamp.month) == month]
        values.sort(key=lambda item: ((item.Hs or 0.0) / max((item.Tp or 1.0) ** 2, 1e-9), item.timestamp))
        cut1, cut2 = len(values) // 3, 2 * len(values) // 3
        for label, stratum in (("LOW", values[:cut1]), ("MIDDLE", values[cut1:cut2]), ("HIGH", values[cut2:])):
            for index, item in enumerate(_evenly(stratum, 8), 1):
                cases.append(MissionCase(
                    case_id=f"{month[0]}-{month[1]:02d}-{label}-{index:02d}",
                    departure_time=item.timestamp,
                    start=(39.2, 122.2), task_point=(39.185, 122.185),
                    inspection_service_time_s=1800.0,
                    route_source_status="SIMULATED REPRESENTATIVE TASK ROUTE - NOT ACTUAL WIND-FARM ROUTE",
                    selection_rule=SELECTION_RULE,
                ))
    if len(cases) != 120:
        raise AssertionError(f"expected 120 deterministic cases, got {len(cases)}")
    return tuple(cases)


def main() -> None:
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    parameters, _ = load_engineering_estimate()
    waves = copernicus_wave.read_local_netcdf(RAW_WAVE, REGION, DATASET_ID)
    store = CausalEnvironmentStore(waves)
    cases = select_cases(waves)
    policies = (
        ReplayPolicy.BASELINE_CONSERVATIVE,
        ReplayPolicy.LOCAL_ADJUST_ONLY,
        ReplayPolicy.HANHAI_MISSION_CONTINUITY,
    )
    by_policy = {policy: [] for policy in policies}
    for case in cases:
        for policy in policies:
            by_policy[policy].append(replay_complete_mission(
                case=case, policy=policy, store=store, parameters=parameters,
                sampling_interval_s=1800.0,
            ))
    nominal_times = {
        case.case_id: 2.0 * _distance(case.start, case.task_point) / case.SOG_m_s
        + case.inspection_service_time_s
        for case in cases
    }
    summaries = {
        policy.value: summarize_complete_replay(tuple(by_policy[policy]), nominal_times)
        for policy in policies
    }
    baseline = {item.case_id: item for item in by_policy[ReplayPolicy.BASELINE_CONSERVATIVE]}
    hanhai = {item.case_id: item for item in by_policy[ReplayPolicy.HANHAI_MISSION_CONTINUITY]}
    saved_ids = [case_id for case_id in baseline if mission_saved(baseline[case_id], hanhai[case_id])]
    all_results = tuple(item for values in by_policy.values() for item in values)
    gate = evaluate_business_value_gate(
        results=all_results, future_action_leakage_count=store.future_action_access_count,
        saved_pairs=tuple((baseline[key], hanhai[key]) for key in baseline),
    )

    current_case = MissionCase(
        "2026-02-05-STRESS-TEST", datetime.fromisoformat("2026-02-05T00:00:00+00:00"),
        (39.2, 122.2), (39.0, 122.0), inspection_service_time_s=1800.0,
        route_source_status=STRESS_TEST_ROUTE,
        selection_rule="RE-EVALUATION OF DECLARED V0.6 DEVELOPMENT SCENARIO",
    )
    current_store = CausalEnvironmentStore(waves)
    current_result = replay_complete_mission(
        case=current_case, policy=ReplayPolicy.HANHAI_MISSION_CONTINUITY,
        store=current_store, parameters=parameters, sampling_interval_s=1800.0,
    )
    current_environment = current_store.nearest(
        timestamp=current_case.departure_time, latitude=39.2, longitude=122.2,
        decision_timestamp=current_case.departure_time,
        purpose=EnvironmentUse.ACTION_SELECTION,
    )
    result = {
        "schema_version": 1,
        "demo_name": "V0.7 CAUSAL COMPLETE MISSION REPLAY",
        "environment_source": REAL_ENVIRONMENT,
        "environment_product": "Copernicus Marine WAVERYS GLOBAL_MULTIYEAR_WAV_001_032",
        "environment_dataset_id": DATASET_ID,
        "vessel_state_source": SIMULATED_VESSEL,
        "parameter_source": parameters.parameter_source.value,
        "parameter_status": parameters.parameter_status,
        "replay_mode": CAUSAL_MODE,
        "oracle_experiment": {
            "status": ORACLE_MODE,
            "used_for_business_metrics": False,
        },
        "selection": {
            "selection_rule": SELECTION_RULE,
            "total_cases_N": len(cases),
            "months": ["2025-11", "2025-12", "2026-01", "2026-02", "2026-03"],
            "cases_per_month": 24,
            "strata": ["LOW", "MIDDLE", "HIGH"],
            "case_ids": [item.case_id for item in cases],
        },
        "policy_summaries": {key: asdict(value) for key, value in summaries.items()},
        "case_outcomes": [
            {
                "case_id": case.case_id,
                "departure_time": case.departure_time,
                "selection_rule": case.selection_rule,
                "policies": {
                    policy.value: {
                        "outcome_status": next(item for item in by_policy[policy] if item.case_id == case.case_id).outcome_status,
                        "mission_completed": next(item for item in by_policy[policy] if item.case_id == case.case_id).mission_completed,
                        "mission_elapsed_time_s": next(item for item in by_policy[policy] if item.case_id == case.case_id).timeline.mission_elapsed_time_s,
                        "unplanned_return": next(item for item in by_policy[policy] if item.case_id == case.case_id).outcome_status.value == "RETURNED_UNPLANNED",
                        "hold_used": next(item for item in by_policy[policy] if item.case_id == case.case_id).hold_used,
                        "reroute_used": next(item for item in by_policy[policy] if item.case_id == case.case_id).reroute_used,
                        "high_risk_exposure_time_s": next(item for item in by_policy[policy] if item.case_id == case.case_id).exposure.high_risk_exposure_time_s,
                        "risk_exposure_ratio": next(item for item in by_policy[policy] if item.case_id == case.case_id).exposure.risk_exposure_ratio,
                        "mission_time_feasibility_status": next(item for item in by_policy[policy] if item.case_id == case.case_id).endurance.mission_time_feasibility_status,
                    }
                    for policy in policies
                },
            }
            for case in cases
        ],
        "mission_saved": {
            "count": len(saved_ids), "denominator_N": len(cases),
            "case_ids": saved_ids,
            "definition": (
                "Same case baseline interrupted/unplanned return AND Hanhai fully completed "
                "AND high-risk exposure acceptable AND within published minimum work-time reference"
            ),
        },
        "scenario_2026_02_05": {
            "initial_environment": {
                "timestamp": current_environment.timestamp,
                "latitude": current_environment.latitude,
                "longitude": current_environment.longitude,
                "Hs": current_environment.Hs,
                "Tp": current_environment.Tp,
                "wave_direction": current_environment.wave_direction,
            },
            "route_status": STRESS_TEST_ROUTE,
            "result": current_result.to_dict(),
            "causal_access_audit": {
                "future_action_access_count": current_store.future_action_access_count,
                "hold_does_not_assume_future_improvement": True,
            },
        },
        "business_value_gate": asdict(gate),
        "replay_integrity_gate": "PASS" if gate.business_value_evidence == "DEVELOPMENT_PASS" else "FAIL",
        "business_value_status": "NOT_ESTABLISHED",
        "legacy_business_value_evidence_status": "DEPRECATED - USE REPLAY_INTEGRITY_GATE AND BUSINESS_VALUE_STATUS",
        "result_status": MODEL_BASED_REPLAY,
        "performance_status": NOT_OPERATIONAL_PERFORMANCE,
        "algorithm_status": "NOT SAC / NOT REINFORCEMENT LEARNING",
        "control_status": "REAL VESSEL CONTROL DISABLED",
        "final_gui_status": "NOT STARTED",
    }
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": str(RESULT),
        "case_count": len(cases),
        "policy_summaries": result["policy_summaries"],
        "mission_saved_count": len(saved_ids),
        "scenario_2026_02_05": result["scenario_2026_02_05"],
        "business_value_gate": result["business_value_gate"],
    }, ensure_ascii=False, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
