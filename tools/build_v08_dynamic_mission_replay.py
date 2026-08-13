"""Build V0.8 dynamic causal mission replay development evidence."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.marine_data.netcdf import StudyRegion
from adapters.marine_data.pipeline import ingest_local_public_files
from core.mission.dynamic_replay import (
    BUSINESS_NOT_ESTABLISHED, DECISION_INTERVAL_S, DYNAMIC_MODE, MODEL_BASED_REPLAY,
    NOT_OPERATIONAL_PERFORMANCE, CausalMultiSourceStore, DynamicMissionCase,
    DynamicMissionEngine, DynamicMissionGeometry, DynamicPolicy, assess_mission_saved,
    assess_value_status, summarize_dynamic_results,
)
from core.mission.state import MissionState
from core.resonance import load_engineering_estimate


REGION = StudyRegion(121.5, 124.5, 38.5, 40.5, (11, 12, 1, 2, 3))
V07 = ROOT / "data/results/v0.7_causal_mission_replay.json"
RESULT = ROOT / "data/results/v0.8_dynamic_mission_replay.json"
PATHS = {
    "ERA5": ROOT / "data/raw/era5/era5_winter_20251101_20260331.nc",
    "Copernicus WAVERYS": ROOT / "data/raw/waverys/waverys_winter_20251101_20260331.nc",
    "Copernicus GLORYS": ROOT / "data/raw/glorys/glorys_surface_winter_20251101_20260331.nc",
    "GEBCO": ROOT / "data/raw/gebco/GEBCO_2026_121.5_124.5E_38.5_40.5N.nc",
}
PRODUCT_IDS = {
    "ERA5": "reanalysis-era5-single-levels",
    "Copernicus WAVERYS": "cmems_mod_glo_wav_my_0.2deg_PT3H-i",
    "Copernicus GLORYS": "cmems_mod_glo_phy_my_0.083deg_P1D-m",
    "GEBCO": "GEBCO_2026",
}
GEOMETRIES = (
    DynamicMissionGeometry(
        "SHORT_ROUTE", (39.2, 122.2), (39.205, 122.195),
        "SIMULATED SHORT_ROUTE - NOT ZHUANGHE ACTUAL WIND-TURBINE SPACING",
    ),
    DynamicMissionGeometry(
        "MEDIUM_ROUTE", (39.2, 122.2), (39.17, 122.23),
        "SIMULATED MEDIUM_ROUTE - NOT ZHUANGHE ACTUAL WIND-TURBINE SPACING",
    ),
    DynamicMissionGeometry(
        "STRESS_TEST_ROUTE", (39.2, 122.2), (39.0, 122.0),
        "STRESS-TEST SIMULATED ROUTE - NOT ZHUANGHE ACTUAL INSPECTION DISTANCE",
    ),
)
SELECTION_RULE = (
    "Use all 120 timestamps predeclared by V0.7 deterministic monthly lower/middle/upper "
    "wave-excitation selection, crossed with three geometry definitions declared before "
    "V0.8 replay: SHORT_ROUTE, MEDIUM_ROUTE, STRESS_TEST_ROUTE. 360 historical replay "
    "scenarios; not 360 real missions; policy outcomes are never used for selection."
)


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    raise TypeError(type(value).__name__)


def main() -> None:
    v07 = json.loads(V07.read_text(encoding="utf-8"))
    timestamps = tuple(datetime.fromisoformat(item["departure_time"]) for item in v07["case_outcomes"])
    if len(timestamps) != 120 or len(set(timestamps)) != 120:
        raise ValueError("V0.8 requires the 120 unique predeclared V0.7 timestamps")
    records = ingest_local_public_files(
        era5_path=PATHS["ERA5"], waverys_path=PATHS["Copernicus WAVERYS"],
        glorys_path=PATHS["Copernicus GLORYS"], gebco_path=PATHS["GEBCO"],
        product_ids=PRODUCT_IDS, region=REGION,
    )
    parameters, _ = load_engineering_estimate()
    store = CausalMultiSourceStore(records)
    engine = DynamicMissionEngine(store, parameters)
    cases = tuple(
        DynamicMissionCase(
            f"{timestamp:%Y%m%dT%H%M}-{geometry.geometry_id}", timestamp, geometry,
            selection_rule=SELECTION_RULE,
        )
        for timestamp in timestamps for geometry in GEOMETRIES
    )
    policies = tuple(DynamicPolicy)
    by_policy = {policy: [] for policy in policies}
    for index, case in enumerate(cases, 1):
        for policy in policies:
            by_policy[policy].append(engine.run(case, policy))
        if index % 60 == 0:
            print(f"replayed {index}/{len(cases)} scenarios", flush=True)
    summaries = {policy: summarize_dynamic_results(by_policy[policy]) for policy in policies}
    baseline = {item.case_id: item for item in by_policy[DynamicPolicy.BASELINE_CONSERVATIVE]}
    hanhai = {item.case_id: item for item in by_policy[DynamicPolicy.HANHAI_MISSION_CONTINUITY]}
    saved = tuple(
        assess_mission_saved(baseline[key], hanhai[key],
                             future_action_leakage_count=store.future_action_access_count)
        for key in baseline
    )
    value = assess_value_status(
        baseline=summaries[DynamicPolicy.BASELINE_CONSERVATIVE],
        hanhai=summaries[DynamicPolicy.HANHAI_MISSION_CONTINUITY], saved=saved,
        future_action_leakage_count=store.future_action_access_count,
    )

    stress_case = DynamicMissionCase(
        "20260205T0000-STRESS-TEST-DYNAMIC", datetime.fromisoformat("2026-02-05T00:00:00+00:00"),
        GEOMETRIES[-1], selection_rule="DECLARED V0.7 STRESS SCENARIO DYNAMIC RE-EVALUATION",
        initial_phase=MissionState.OUTBOUND,
    )
    stress_store = CausalMultiSourceStore(records)
    stress = DynamicMissionEngine(stress_store, parameters).run(
        stress_case, DynamicPolicy.HANHAI_MISSION_CONTINUITY,
    )
    compact_scenarios = [
        {
            "scenario_id": case.case_id,
            "departure_time": case.departure_time,
            "geometry_id": case.geometry.geometry_id,
            "geometry_source_status": case.geometry.source_status,
            "policies": {
                policy.value: {
                    "outcome_status": by_policy[policy][index].outcome_status,
                    "technical_completed": by_policy[policy][index].technical_completed,
                    "evidence_qualified_completion": by_policy[policy][index].evidence_qualified_completion,
                    "completion_evidence_status": by_policy[policy][index].completion_evidence_status,
                    "mission_elapsed_time_s": by_policy[policy][index].mission_elapsed_time_s,
                    "time_penalty_s": by_policy[policy][index].time_penalty_s,
                    "unplanned_return": by_policy[policy][index].unplanned_return,
                    "predeparture_delay": by_policy[policy][index].predeparture_delay,
                    "hold_count": by_policy[policy][index].hold_used_count,
                    "reroute_count": by_policy[policy][index].reroute_used_count,
                    "high_risk_exposure_time_s": by_policy[policy][index].exposure.high_risk_exposure_time_s,
                    "maximum_continuous_high_risk_time_s": by_policy[policy][index].exposure.maximum_continuous_high_risk_time_s,
                    "risk_burden_level_seconds": by_policy[policy][index].exposure.risk_burden_level_seconds,
                }
                for policy in policies
            },
        }
        for index, case in enumerate(cases)
    ]
    result = {
        "schema_version": 1,
        "demo_name": "V0.8 DYNAMIC CAUSAL MISSION REPLAY",
        "replay_mode": DYNAMIC_MODE,
        "decision_interval_s": DECISION_INTERVAL_S,
        "decision_interval_status": "PRELIMINARY MISSION POLICY PARAMETER",
        "selection": {
            "selection_rule": SELECTION_RULE, "historical_timestamp_count": 120,
            "geometry_count": len(GEOMETRIES), "total_scenario_N": len(cases),
            "scenario_wording": "HISTORICAL REPLAY SCENARIOS - NOT INDEPENDENT REAL MISSIONS",
            "geometries": [asdict(value) for value in GEOMETRIES],
        },
        "data_sources": {
            "environment": "REAL PUBLIC ENVIRONMENT DATA - NOT IN-SITU ZHUANGHE OBSERVATION",
            "products": PRODUCT_IDS,
            "sampling": "MarineEnvironmentSampler nearest field assembly with tolerance; NOT final fusion",
            "vessel_state": "SIMULATED VESSEL STATE",
            "parameters": "ENGINEERING_ESTIMATE / NOT_EXPERIMENTALLY_CALIBRATED",
            "risk_baseline": "PRELIMINARY / NEEDS CALIBRATION",
        },
        "policy_summaries": {policy.value: asdict(summary) for policy, summary in summaries.items()},
        "mission_saved": {
            "count": sum(item.saved for item in saved), "denominator_N": len(cases),
            "assessments": [asdict(item) for item in saved],
        },
        "scenario_results": compact_scenarios,
        "scenario_2026_02_05": {
            "result": stress.to_dict(),
            "future_action_access_count": stress_store.future_action_access_count,
        },
        "value_assessment": asdict(value),
        "replay_integrity_gate": value.replay_integrity_gate,
        "business_value_status": value.business_value_status,
        "result_status": MODEL_BASED_REPLAY,
        "performance_status": NOT_OPERATIONAL_PERFORMANCE,
        "algorithm_status": "NOT SAC / NOT REINFORCEMENT LEARNING",
        "control_status": "REAL VESSEL CONTROL DISABLED",
        "final_gui_status": "NOT STARTED",
    }
    if result["business_value_status"] not in {BUSINESS_NOT_ESTABLISHED, "CANDIDATE", "DEVELOPMENT_EVIDENCE"}:
        raise AssertionError("invalid business value status")
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": str(RESULT), "scenario_N": len(cases),
        "summaries": result["policy_summaries"],
        "mission_saved_count": result["mission_saved"]["count"],
        "stress_actions": [item.action.value for item in stress.actions],
        "stress_result": {
            "technical_completed": stress.technical_completed,
            "evidence_qualified_completion": stress.evidence_qualified_completion,
            "completion_evidence_status": stress.completion_evidence_status.value,
            "mission_elapsed_time_s": stress.mission_elapsed_time_s,
            "high_risk_exposure_time_s": stress.exposure.high_risk_exposure_time_s,
            "maximum_continuous_high_risk_time_s": stress.exposure.maximum_continuous_high_risk_time_s,
        },
        "value_assessment": result["value_assessment"],
    }, ensure_ascii=False, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
