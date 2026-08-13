"""Build V0.9 causal dynamic consistency and candidate-value evidence."""

from __future__ import annotations

import json
import hashlib
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
    BUSINESS_NOT_ESTABLISHED, DYNAMIC_MODE, CausalMultiSourceStore, DynamicMissionCase,
    DynamicMissionEngine, DynamicMissionGeometry, DynamicPolicy, assess_mission_saved,
    assess_value_status, build_mission_value_blocker_report, summarize_dynamic_results,
)
from core.mission.state import MissionState
from core.resonance import load_engineering_estimate


REGION = StudyRegion(121.5, 124.5, 38.5, 40.5, (11, 12, 1, 2, 3))
V07 = ROOT / "data/results/v0.7_causal_mission_replay.json"
RESULT = ROOT / "data/results/v0.9_dynamic_mission_evidence.json"
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
    DynamicMissionGeometry("SHORT_ROUTE", (39.2, 122.2), (39.205, 122.195),
                           "SIMULATED SHORT_ROUTE - NOT ACTUAL INSPECTION GEOMETRY"),
    DynamicMissionGeometry("MEDIUM_ROUTE", (39.2, 122.2), (39.17, 122.23),
                           "SIMULATED MEDIUM_ROUTE - NOT ACTUAL INSPECTION GEOMETRY"),
    DynamicMissionGeometry("STRESS_TEST_ROUTE", (39.2, 122.2), (39.0, 122.0),
                           "STRESS-TEST SIMULATED ROUTE - NOT ACTUAL INSPECTION GEOMETRY"),
)
POPULATION_RULE = (
    "All 120 predeclared V0.7 winter timestamps crossed with three predeclared simulated "
    "geometries; policy outcomes never used. 360 historical replay scenarios, not real missions."
)
DECISION_RELEVANT_RULE = (
    "Before any policy replay: initial residual-high OR direct-route current-snapshot high-risk; "
    "fixed direct route, fixed nominal vessel state, real public environment only."
)


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    raise TypeError(type(value).__name__)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compact(result):
    return {
        "outcome_status": result.outcome_status,
        "technical_completed": result.technical_completed,
        "duration_reference_compatible_completion": result.duration_reference_compatible_completion,
        "duration_reference_status": result.duration_reference_status,
        "energy_feasibility_status": result.energy_feasibility_status,
        "predeparture_delay": result.predeparture_delay,
        "unplanned_return": result.unplanned_return,
        "maneuver_count": result.maneuver_count,
        "reroute_count": result.reroute_used_count,
        "safe_hold_count": result.hold_used_count,
        "high_risk_exposure_time_s": result.exposure.high_risk_exposure_time_s,
        "maximum_continuous_high_risk_time_s": result.exposure.maximum_continuous_high_risk_time_s,
        "risk_burden_level_seconds": result.exposure.risk_burden_level_seconds,
        "signed_mission_time_delta_s": result.signed_mission_time_delta_s,
        "positive_time_penalty_s": result.positive_time_penalty_s,
        "time_saving_s": result.time_saving_s,
        "extra_distance_m": result.extra_distance_m,
        "maneuver_distance_m": result.maneuver_distance_m,
        "affected_by_decision": result.affected_by_decision,
    }


def evaluate_cohort(cases, records, parameters):
    policies = tuple(DynamicPolicy)
    by_policy = {policy: [] for policy in policies}
    stores = {policy: CausalMultiSourceStore(records) for policy in policies}
    engines = {policy: DynamicMissionEngine(stores[policy], parameters) for policy in policies}
    for index, case in enumerate(cases, 1):
        for policy in policies:
            by_policy[policy].append(engines[policy].run(case, policy))
        if index % 60 == 0:
            print(f"replayed {index}/{len(cases)} scenarios", flush=True)
    summaries = {policy: summarize_dynamic_results(by_policy[policy]) for policy in policies}
    baseline = by_policy[DynamicPolicy.BASELINE_CONSERVATIVE]
    hanhai = by_policy[DynamicPolicy.HANHAI_MISSION_CONTINUITY]
    leakage = sum(store.future_action_access_count for store in stores.values())
    saved = tuple(assess_mission_saved(base, candidate, future_action_leakage_count=leakage)
                  for base, candidate in zip(baseline, hanhai, strict=True))
    value = assess_value_status(
        baseline=summaries[DynamicPolicy.BASELINE_CONSERVATIVE],
        hanhai=summaries[DynamicPolicy.HANHAI_MISSION_CONTINUITY], saved=saved,
        future_action_leakage_count=leakage,
    )
    blocker = build_mission_value_blocker_report(baseline, hanhai, saved)
    return {
        "N": len(cases),
        "policy_summaries": {policy.value: asdict(summary) for policy, summary in summaries.items()},
        "mission_saved_count": sum(item.saved for item in saved),
        "blocker_report": asdict(blocker),
        "replay_integrity_gate": value.replay_integrity_gate,
        "business_value_status": value.business_value_status,
        "scenario_results": [
            {"scenario_id": case.case_id,
             "policies": {policy.value: _compact(by_policy[policy][index]) for policy in policies}}
            for index, case in enumerate(cases)
        ],
    }


def main():
    source = json.loads(V07.read_text(encoding="utf-8"))
    timestamps = tuple(datetime.fromisoformat(item["departure_time"]) for item in source["case_outcomes"])
    if len(timestamps) != 120 or len(set(timestamps)) != 120:
        raise ValueError("V0.9 requires 120 unique predeclared V0.7 timestamps")
    records = ingest_local_public_files(
        era5_path=PATHS["ERA5"], waverys_path=PATHS["Copernicus WAVERYS"],
        glorys_path=PATHS["Copernicus GLORYS"], gebco_path=PATHS["GEBCO"],
        product_ids=PRODUCT_IDS, region=REGION,
    )
    parameters, _ = load_engineering_estimate()
    population = tuple(
        DynamicMissionCase(f"{at:%Y%m%dT%H%M}-{geometry.geometry_id}", at, geometry,
                           selection_rule=POPULATION_RULE)
        for at in timestamps for geometry in GEOMETRIES
    )
    selection_engine = DynamicMissionEngine(CausalMultiSourceStore(records), parameters)
    selections = tuple(selection_engine.select_decision_relevant(case) for case in population)
    relevant_ids = {item.scenario_id for item in selections if item.selected}
    relevant = tuple(case for case in population if case.case_id in relevant_ids)
    population_result = evaluate_cohort(population, records, parameters)
    relevant_result = evaluate_cohort(relevant, records, parameters)

    stress_case = DynamicMissionCase(
        "20260205T0000-STRESS-TEST-V09", datetime.fromisoformat("2026-02-05T00:00:00+00:00"),
        GEOMETRIES[-1], initial_phase=MissionState.OUTBOUND,
        initial_position=((GEOMETRIES[-1].start[0] + GEOMETRIES[-1].task_point[0]) / 2,
                          (GEOMETRIES[-1].start[1] + GEOMETRIES[-1].task_point[1]) / 2),
        selection_rule="PREDECLARED V0.7 STRESS SCENARIO - V0.9 DYNAMIC RE-EVALUATION",
    )
    stress_store = CausalMultiSourceStore(records)
    stress = DynamicMissionEngine(stress_store, parameters).run(
        stress_case, DynamicPolicy.HANHAI_MISSION_CONTINUITY,
    )
    result = {
        "schema_version": 1, "demo_name": "V0.9 DYNAMIC CONSISTENCY EVIDENCE",
        "replay_mode": DYNAMIC_MODE,
        "data_sources": {
            "environment": "REAL PUBLIC ENVIRONMENT DATA - NOT IN-SITU ZHUANGHE OBSERVATION",
            "vessel_state": "SIMULATED VESSEL STATE",
            "parameters": "ENGINEERING_ESTIMATE / NOT_EXPERIMENTALLY_CALIBRATED",
            "energy": "NOT VERIFIED ENERGY FEASIBILITY",
            "products": PRODUCT_IDS,
            "input_provenance": {
                source: {
                    "product_id": PRODUCT_IDS[source], "filename": path.name,
                    "filesize_bytes": path.stat().st_size, "sha256": _sha256(path),
                }
                for source, path in PATHS.items()
            },
        },
        "cohorts": {
            "WINTER_POPULATION_COHORT": {"selection_rule": POPULATION_RULE, **population_result},
            "DECISION_RELEVANT_COHORT": {
                "selection_rule": DECISION_RELEVANT_RULE,
                "selection_assessments": [asdict(item) for item in selections], **relevant_result,
            },
        },
        "scenario_2026_02_05": {
            "result": stress.to_dict(), "action_chain": [item.action for item in stress.actions],
            "decision_reasons": [item.reason for item in stress.actions],
            "return_risk_decisions": [item.action for item in stress.actions
                                      if item.mission_state is MissionState.RETURNING],
            "future_action_access_count": stress_store.future_action_access_count,
        },
        "replay_integrity_gate": population_result["replay_integrity_gate"],
        "business_value_status": population_result["business_value_status"],
        "result_status": "MODEL-BASED HISTORICAL REPLAY - NOT OPERATIONAL PERFORMANCE",
        "algorithm_status": "NOT SAC / NOT REINFORCEMENT LEARNING",
        "control_status": "REAL VESSEL CONTROL DISABLED",
        "final_gui_status": "NOT STARTED",
    }
    if result["business_value_status"] not in {BUSINESS_NOT_ESTABLISHED, "DEVELOPMENT_EVIDENCE"}:
        raise AssertionError("invalid business value status")
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default) + "\n",
                      encoding="utf-8")
    print(json.dumps({
        "result": str(RESULT), "population_N": len(population), "decision_relevant_N": len(relevant),
        "population_saved": population_result["mission_saved_count"],
        "relevant_saved": relevant_result["mission_saved_count"],
        "stress_actions": result["scenario_2026_02_05"]["action_chain"],
        "integrity": result["replay_integrity_gate"], "business": result["business_value_status"],
    }, ensure_ascii=False, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
