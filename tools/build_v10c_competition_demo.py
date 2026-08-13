"""Build the deterministic V1.0-C competition demo from frozen V0.9 core output.

The builder never edits conclusions by hand.  It uses validated public historical
environment products, a fixed simulated near-farm geometry, and the frozen
DynamicMissionEngine.  Selection does not read completion, mission_saved, or any
business-value outcome.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from math import atan2, cos, degrees, radians, sin, sqrt
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.marine_data.netcdf import StudyRegion
from adapters.marine_data import copernicus_current, copernicus_wave, era5, gebco
import xarray as xr
from core.mission.dynamic_replay import (
    CausalMultiSourceStore, DynamicAction, DynamicMissionCase, DynamicMissionEngine,
    DynamicMissionGeometry, DynamicPolicy, ExecutedSegment,
)
from core.mission.state import MissionState
from core.resonance import load_engineering_estimate
from core.roll_response import RobustDecisionStatus


REGION = StudyRegion(121.5, 124.5, 38.5, 40.5, (11, 12, 1, 2, 3))
RAW_PATHS = {
    "ERA5": ROOT / "data/raw/era5/era5_winter_20251101_20260331.nc",
    "WAVERYS": ROOT / "data/raw/waverys/waverys_winter_20251101_20260331.nc",
    "GLORYS": ROOT / "data/raw/glorys/glorys_surface_winter_20251101_20260331.nc",
    "GEBCO": ROOT / "data/raw/gebco/GEBCO_2026_121.5_124.5E_38.5_40.5N.nc",
}
PRODUCT_IDS = {
    "ERA5": "reanalysis-era5-single-levels",
    "WAVERYS": "cmems_mod_glo_wav_my_0.2deg_PT3H-i",
    "GLORYS": "cmems_mod_glo_phy_my_0.083deg_P1D-m",
    "GEBCO": "GEBCO_2026",
}
CONTEXT = ROOT / "data/context/zhuanghe_public_operational_context.json"
MANIFEST = ROOT / "data/manifests/winter_environment_20251101_20260331.json"
OUTPUT = ROOT / "data/replay/v1.0c_competition_demo.json"
STORYBOARD = ROOT / "data/replay/v1.0c_video_storyboard.json"
FROZEN_COMMIT = "772ec55982eac96eec26b85d5d9a335f4d1127c2"
CORE_SOURCE = "core.mission.dynamic_replay.DynamicMissionEngine"
ENVIRONMENT_SOURCE = "REAL PUBLIC HISTORICAL ENVIRONMENT - NOT IN-SITU OBSERVATION"
VESSEL_SOURCE = "SIMULATED VESSEL STATE"
GEOMETRY_SOURCE = "SIMULATED NEAR-FARM MISSION GEOMETRY"
TARGET_RADIUS_M = 75.0
TARGET_RADIUS_STATUS = "SIMULATED MISSION PARAMETER"
DISPLAY_STATUS = "DISPLAY TIME COMPRESSED - UNDERLYING HISTORICAL TIMESTAMPS UNCHANGED"
SELECTION_RULE = (
    "At the declared Zhuanghe III public-reference center, use the fixed simulated near-farm "
    "geometry, fixed 0.5 m/s initial speed, and every native three-hour WAVERYS epoch. Select "
    "the earliest epoch whose current causal snapshot is acceptable and whose next native "
    "environment epoch is unsafe under the frozen V0.9 definition, while the frozen dynamic "
    "engine finds an executable constrained local action whose recomputed state improves "
    "robust status or GRID_Q90 without leaving single-vessel risk HIGH. This pre-outcome "
    "technical screen never reads mission_saved, completion, policy comparison, business "
    "outcome, or any future environment in action selection."
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(type(value).__name__)


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    radius = 6_371_008.8
    lat1, lat2 = radians(a[0]), radians(b[0])
    dlat, dlon = lat2 - lat1, radians(b[1] - a[1])
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * radius * atan2(sqrt(h), sqrt(max(0.0, 1 - h)))


def _bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lat2 = radians(a[0]), radians(b[0])
    dlon = radians(b[1] - a[1])
    y = sin(dlon) * cos(lat2)
    x = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(dlon)
    return (degrees(atan2(y, x)) + 360.0) % 360.0


def _interpolate(a: tuple[float, float], b: tuple[float, float], fraction: float) -> tuple[float, float]:
    return a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction


def _status_rank(status: str) -> int:
    return {
        RobustDecisionStatus.UNAVAILABLE.value: 3,
        RobustDecisionStatus.RESIDUAL_HIGH_RISK.value: 2,
        RobustDecisionStatus.ROBUST_MODERATE.value: 1,
        RobustDecisionStatus.ROBUST_NORMAL.value: 0,
    }.get(status, 3)


def _state_dict(state) -> dict:
    provenance = state.environment_provenance_by_field
    field_times = {}
    for name, item in provenance.items():
        offset = item.get("time_offset_seconds")
        field_times[name] = (
            (state.timestamp - timedelta(seconds=offset)).isoformat()
            if offset is not None else "STATIC"
        )
    return {
        "timestamp": state.timestamp.isoformat(),
        "environment_data_time": field_times.get("Hs", state.timestamp.isoformat()),
        "environment_data_time_by_field": field_times,
        "decision_epoch": state.timestamp.isoformat(),
        "latitude": state.latitude,
        "longitude": state.longitude,
        "mission_state": state.mission_state.value,
        "SOG": state.SOG_m_s,
        "HDG": state.HDG_deg,
        "Hs": state.Hs_m,
        "Tp": state.Tp_s,
        "wave_direction": state.wave_direction_deg,
        "wind_speed": state.wind_speed_m_s,
        "wind_direction": state.wind_direction_deg,
        "surface_current_speed": state.surface_current_speed_m_s,
        "surface_current_direction": state.surface_current_direction_deg,
        "water_depth": state.water_depth_m,
        "single_vessel_risk_score": state.single_vessel_risk_score,
        "single_vessel_risk_level": state.single_vessel_risk_level,
        "risk_components": state.risk_components,
        "GRID_Q90": state.roll_response_grid_q90_proxy,
        "robust_status": state.robust_status,
        "unsafe": (
            state.robust_status == RobustDecisionStatus.RESIDUAL_HIGH_RISK.value
            or state.single_vessel_risk_level == "HIGH"
        ),
        "provenance_by_field": provenance,
        "environment_source": state.environment_source,
        "vessel_state_source": state.vessel_state_source,
    }


def _event(event_type: str, state, decision=None, segment=None, **extra) -> dict:
    payload = {
        "event_type": event_type,
        **_state_dict(state),
        "decision_action": decision.action.value if decision else "NONE",
        "decision_reason": decision.reason if decision else "NO DECISION AT THIS EVENT",
        "recommended_SOG": decision.recommended_SOG_m_s if decision else None,
        "recommended_HDG": decision.recommended_HDG_deg if decision else None,
        "executed_SOG": segment.executed_SOG_m_s if segment else None,
        "executed_HDG": segment.executed_HDG_deg if segment else None,
        "source_labels": {
            "environment": ENVIRONMENT_SOURCE,
            "vessel": VESSEL_SOURCE,
            "mission_geometry": GEOMETRY_SOURCE,
            "parameters": "ENGINEERING_ESTIMATE / NOT_EXPERIMENTALLY_CALIBRATED",
            "action": "SIMULATED ACTION EXECUTED" if segment else "DECISION ADVICE ONLY",
            "control": "REAL VESSEL CONTROL DISABLED",
        },
    }
    payload.update(extra)
    return payload


def _first_action_after(actions, timestamp):
    return next((item for item in actions if item.timestamp > timestamp), None)


def _segment_at(segments: tuple[ExecutedSegment, ...], timestamp: datetime, segment_type=None):
    return next((item for item in segments if item.start_time == timestamp and (
        segment_type is None or item.segment_type == segment_type
    )), None)


def _model_improved(before, after) -> bool:
    if after.single_vessel_risk_level == "HIGH":
        return False
    robust_improved = _status_rank(after.robust_status) < _status_rank(before.robust_status)
    q90_improved = (
        before.roll_response_grid_q90_proxy is not None
        and after.roll_response_grid_q90_proxy is not None
        and after.roll_response_grid_q90_proxy < before.roll_response_grid_q90_proxy - 1e-9
    )
    risk_improved = after.single_vessel_risk_score < before.single_vessel_risk_score - 1e-9
    return robust_improved or q90_improved or risk_improved


def _build_events(engine: DynamicMissionEngine, result, target: tuple[float, float]) -> tuple[list[dict], dict]:
    actions, segments = result.actions, result.executed_segments
    if not actions:
        raise ValueError("dynamic result has no actions")
    events: list[dict] = []
    first = actions[0]
    events.append(_event("MISSION_START", first.state, first))
    normal = next((item for item in actions if not item.state.single_vessel_risk_level == "HIGH"
                   and item.state.robust_status != RobustDecisionStatus.RESIDUAL_HIGH_RISK.value), first)
    events.append(_event("NORMAL_NAVIGATION", normal.state, normal))
    unsafe = next((item for item in actions if (
        item.state.single_vessel_risk_level == "HIGH"
        or item.state.robust_status == RobustDecisionStatus.RESIDUAL_HIGH_RISK.value
    )), None)
    advisory = next((item for item in actions if item.action in (
        DynamicAction.ADJUST_SPEED_HEADING, DynamicAction.ADJUST_RETURN_SPEED_HEADING,
    )), None)
    if unsafe is None or advisory is None:
        raise ValueError("selected demo did not produce the required risk/advisory chain")
    previous = max((item for item in actions if item.timestamp < unsafe.timestamp), key=lambda x: x.timestamp)
    events.append(_event("RISK_RISING", previous.state, previous,
                         next_unsafe_decision_epoch=unsafe.timestamp.isoformat()))
    events.append(_event("RISK_DETECTED", unsafe.state, unsafe))
    events.append(_event("ADVISORY_ISSUED", advisory.state, advisory,
                         decision_source=CORE_SOURCE))
    maneuver = _segment_at(segments, advisory.timestamp, "MANEUVER_SEGMENT")
    if maneuver is None:
        raise ValueError("advisory did not produce an executed maneuver segment")
    if maneuver.executed_SOG_m_s != advisory.recommended_SOG_m_s:
        raise ValueError("recommended/executed SOG mismatch")
    if maneuver.executed_HDG_deg != advisory.recommended_HDG_deg:
        raise ValueError("recommended/executed HDG mismatch")
    events.append(_event("SIMULATED_ACTION_ACCEPTED", advisory.state, advisory))
    after_state = engine._state(
        maneuver.end_time, maneuver.end, advisory.mission_state,
        maneuver.executed_SOG_m_s, maneuver.executed_HDG_deg,
    )
    events.append(_event(
        "SIMULATED_ACTION_EXECUTED", after_state, advisory, maneuver,
        executed_segment={**asdict(maneuver), "distance_m": maneuver.distance_m},
    ))
    events.append(_event(
        "RISK_REASSESSED", after_state, advisory, maneuver,
        before=_state_dict(advisory.state), after=_state_dict(after_state),
    ))
    improved = _model_improved(advisory.state, after_state)
    if improved:
        events.append(_event(
            "RISK_IMPROVED", after_state, advisory, maneuver,
            before=_state_dict(advisory.state), after=_state_dict(after_state),
            improvement_status="MODEL-BASED REASSESSMENT - NOT EXPERIMENTALLY MEASURED",
        ))
    target_segment = next((segment for segment in segments if (
        _distance(segment.start, target) > TARGET_RADIUS_M
        and _distance(segment.end, target) <= TARGET_RADIUS_M
    )), None)
    if target_segment is None:
        raise ValueError("executed track never entered target radius")
    target_action = next((item for item in actions if item.timestamp >= target_segment.end_time), actions[-1])
    target_state = engine._state(
        target_segment.end_time, target_segment.end, MissionState.ON_STATION,
        0.0, target_segment.executed_HDG_deg,
    )
    arrival_fields = {
        "arrival_distance_m": _distance(target_segment.end, target),
        "target_radius_m": TARGET_RADIUS_M,
        "target_radius_status": TARGET_RADIUS_STATUS,
        "trigger": "EXECUTED_TRACK_DISTANCE_TO_TARGET",
    }
    events.append(_event("TARGET_APPROACH", target_state, target_action, target_segment,
                         **arrival_fields))
    events.append(_event("TARGET_REACHED", target_state, target_action, target_segment,
                         **arrival_fields))
    events.append(_event("INSPECTION_AREA_ENTERED", target_state, target_action,
                         inspection_area_source="SIMULATED INSPECTION AREA", **arrival_fields))
    events.append(_event("INSPECTION_PAYLOAD_READY", target_state, target_action,
                         payload_status="UAV / VISION PAYLOAD READY (SIMULATED)"))
    inspection = next((segment for segment in segments if segment.segment_type == "SIMULATED_INSPECTION_SERVICE"), None)
    if inspection:
        events.append(_event("INSPECTION_PAYLOAD_ACTIVE", target_state, target_action, inspection,
                             payload_status="SIMULATED PAYLOAD ACTIVE - NO DEFECT DETECTION CLAIM"))
    returning = next((item for item in actions if item.mission_state is MissionState.RETURNING), None)
    if returning:
        return_segment = next((item for item in segments if item.start_time >= returning.timestamp), None)
        events.append(_event("RETURN_START", returning.state, returning, return_segment))
    events.sort(key=lambda item: (item["timestamp"], [
        "MISSION_START", "NORMAL_NAVIGATION", "RISK_RISING", "RISK_DETECTED",
        "ADVISORY_ISSUED", "SIMULATED_ACTION_ACCEPTED", "SIMULATED_ACTION_EXECUTED",
        "RISK_REASSESSED", "RISK_IMPROVED", "TARGET_APPROACH", "TARGET_REACHED",
        "INSPECTION_AREA_ENTERED", "INSPECTION_PAYLOAD_READY", "INSPECTION_PAYLOAD_ACTIVE",
        "RETURN_START",
    ].index(item["event_type"])))
    return events, {
        "before": _state_dict(advisory.state),
        "after": _state_dict(after_state),
        "model_improved": improved,
        "executed_maneuver": {**asdict(maneuver), "distance_m": maneuver.distance_m},
        "target_reached": True,
        "target_arrival_distance_m": _distance(target_segment.end, target),
    }


def _storyboard(events: list[dict]) -> dict:
    pairs = (
        ("mission_start", "MISSION_START", "RISK_RISING", 2.0, "mission map", "normal navigation"),
        ("risk_detected", "RISK_RISING", "ADVISORY_ISSUED", 3.0, "risk and WHY panel", "risk detected"),
        ("maneuver", "ADVISORY_ISSUED", "SIMULATED_ACTION_EXECUTED", 3.0, "map and WHAT TO DO", "simulated maneuver"),
        ("reassessment", "SIMULATED_ACTION_EXECUTED", "RISK_IMPROVED", 3.0, "WHAT CHANGES", "model reassessment"),
        ("arrival", "RISK_IMPROVED", "INSPECTION_PAYLOAD_READY", 4.0, "target turbine", "inspection area reached"),
    )
    available = {item["event_type"] for item in events}
    scenes = []
    for scene_id, start, end, duration, focus, caption in pairs:
        if start in available and end in available:
            event = next(item for item in events if item["event_type"] == start)
            scenes.append({
                "scene_id": scene_id, "start_event": start, "end_event": end,
                "duration_hint_s": duration, "camera_focus": focus,
                "primary_ui_state": start, "vessel_state": {
                    "SOG": event["SOG"], "HDG": event["HDG"],
                    "latitude": event["latitude"], "longitude": event["longitude"],
                },
                "environment_state": {
                    "timestamp": event["environment_data_time"], "Hs": event["Hs"],
                    "Tp": event["Tp"], "wind_speed": event["wind_speed"],
                },
                "caption_hint": caption,
            })
    return {
        "schema_version": 1, "source": "data/replay/v1.0c_competition_demo.json",
        "status": "STRUCTURED STORYBOARD ONLY - NO VIDEO GENERATED", "scenes": scenes,
    }


def main() -> None:
    missing = [str(path) for path in (*RAW_PATHS.values(), CONTEXT, MANIFEST) if not path.exists()]
    if missing:
        raise FileNotFoundError(f"required validated inputs missing: {missing}")
    context = json.loads(CONTEXT.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    reference = context["public_reference_center"]
    reference_point = (reference["latitude"], reference["longitude"])
    opened = {name: xr.open_dataset(path, engine="h5netcdf") for name, path in RAW_PATHS.items()}
    try:
        wind = era5.records_from_dataset(opened["ERA5"], PRODUCT_IDS["ERA5"], REGION)
        wave = copernicus_wave.records_from_dataset(opened["WAVERYS"], PRODUCT_IDS["WAVERYS"], REGION)
        current = copernicus_current.records_from_dataset(opened["GLORYS"], PRODUCT_IDS["GLORYS"], REGION)
        reference_time = min(item.timestamp for item in (*wind, *wave, *current))
        depth = gebco.records_from_dataset(opened["GEBCO"], PRODUCT_IDS["GEBCO"], reference_time, REGION)
        records = sorted(
            [*wind, *wave, *current, *depth],
            key=lambda item: (item.timestamp, item.latitude, item.longitude, item.source),
        )
    finally:
        for dataset in opened.values():
            dataset.close()
    parameters, _ = load_engineering_estimate()
    start = (39.474, 123.305)
    target = (39.532, 123.378)
    geometry = DynamicMissionGeometry(
        "V10C-NEAR-FARM-DEMO", start, target,
        "SIMULATED NEAR-FARM DEPLOYMENT MISSION - NOT OFFICIAL TURBINE COORDINATES",
    )
    nominal_speed = 0.5
    heading = _bearing(start, target)
    wave_times = sorted({item.timestamp for item in records if item.Hs is not None})
    selected = None
    screening_engine = DynamicMissionEngine(CausalMultiSourceStore(records), parameters)
    for at in wave_times[:-1]:
        next_epoch = at + timedelta(hours=3)
        if next_epoch not in wave_times:
            continue
        initial = screening_engine._state(at, start, MissionState.OUTBOUND, nominal_speed, heading)
        distance = nominal_speed * 3 * 3600
        fraction = min(0.85, distance / _distance(start, target))
        later_position = _interpolate(start, target, fraction)
        later = screening_engine._state(next_epoch, later_position, MissionState.OUTBOUND, nominal_speed, heading)
        if screening_engine._unsafe(initial) or not screening_engine._unsafe(later):
            continue
        decision = screening_engine._decision(
            later, DynamicPolicy.HANHAI_MISSION_CONTINUITY, destination=target,
        )
        if decision.action is not DynamicAction.ADJUST_SPEED_HEADING:
            continue
        recomputed = screening_engine._state(
            next_epoch, later_position, MissionState.OUTBOUND,
            decision.recommended_SOG_m_s, decision.recommended_HDG_deg,
        )
        if _model_improved(later, recomputed):
            selected = (at, initial, later, decision, recomputed)
            break
    if selected is None:
        raise RuntimeError("no policy-outcome-independent technical demo window satisfied the declared rule")
    selected_at, screen_initial, screen_before, screen_decision, screen_after = selected
    case = DynamicMissionCase(
        "V10C-COMPETITION-DEMO", selected_at, geometry, SOG_m_s=nominal_speed,
        inspection_service_time_s=1800.0, selection_rule=SELECTION_RULE,
        initial_phase=MissionState.OUTBOUND,
    )
    store = CausalMultiSourceStore(records)
    engine = DynamicMissionEngine(store, parameters)
    result = engine.run(case, DynamicPolicy.HANHAI_MISSION_CONTINUITY)
    events, evidence = _build_events(engine, result, target)
    if store.future_action_access_count:
        raise AssertionError("future environment access detected during action selection")
    event_types = [item["event_type"] for item in events]
    if "RISK_IMPROVED" not in event_types:
        raise RuntimeError("actual executed demo did not produce model-based risk improvement")
    segments = [{**asdict(item), "distance_m": item.distance_m} for item in result.executed_segments]
    input_hashes = {
        name: {
            "product_id": PRODUCT_IDS[name], "filename": path.name,
            "filesize_bytes": path.stat().st_size, "sha256": _sha256(path),
        } for name, path in RAW_PATHS.items()
    }
    geobco_value = next(
        (event["water_depth"] for event in events if event["water_depth"] is not None), None
    )
    payload = {
        "schema_version": 1,
        "demo_name": "V1.0-C COMPETITION CLOSED-LOOP PRODUCT DEMO",
        "generation_timestamp": datetime.now(timezone.utc).isoformat(),
        "replay_mode": "DYNAMIC CAUSAL HISTORICAL REPLAY WITH SIMULATED ACTION EXECUTION",
        "display_status": DISPLAY_STATUS,
        "source_manifest": str(MANIFEST.relative_to(ROOT)).replace("\\", "/"),
        "input_provenance": input_hashes,
        "environment_source": ENVIRONMENT_SOURCE,
        "environment_forecast_status": "NOT REAL-TIME FORECAST",
        "mission_geometry_source": GEOMETRY_SOURCE,
        "vessel_state_source": VESSEL_SOURCE,
        "parameter_source": "ENGINEERING_ESTIMATE",
        "parameter_status": "NOT_EXPERIMENTALLY_CALIBRATED",
        "core_source": CORE_SOURCE,
        "core_version": {"freeze": "V0.9", "frozen_commit": FROZEN_COMMIT},
        "selection_rule": SELECTION_RULE,
        "selection_independence": "DETERMINISTIC / POLICY-OUTCOME-INDEPENDENT",
        "selection_forbidden_inputs": ["mission_saved", "completion", "business_outcome", "policy_comparison"],
        "historical_environment_window": [
            min(item["timestamp"] for item in events), max(item["timestamp"] for item in events),
        ],
        "environment_reference_point": {
            "latitude": reference_point[0], "longitude": reference_point[1],
            "status": reference["status"],
        },
        "mission": {
            "mission_type": "OFFSHORE WIND TURBINE INSPECTION NAVIGATION ASSURANCE",
            "mission_type_zh": "海上风机巡检航行保障任务",
            "target": "WT-DEMO-07",
            "deployment_mode": "SIMULATED NEAR-FARM DEPLOYMENT",
            "hanhai_role": "NAVIGATION / MISSION ASSURANCE",
            "inspection_payload": "UAV / VISION PAYLOAD - SIMULATED",
            "start": start, "target_position": target,
            "target_radius_m": TARGET_RADIUS_M,
            "target_radius_status": TARGET_RADIUS_STATUS,
            "route_length_m": _distance(start, target),
            "port_to_farm_route_used": False,
        },
        "public_operational_context": context,
        "public_bathymetry_comparison": {
            "public_operational_water_depth_range_m_approx": context["public_operational_water_depth_range_m_approx"],
            "GEBCO_sample_m": geobco_value,
            "status": "PUBLIC PRODUCT / SAMPLING DIFFERENCE" if geobco_value is not None and not 15 <= geobco_value <= 20 else "CONSISTENT WITH APPROXIMATE PUBLIC RANGE",
            "navigation_status": "GEBCO PUBLIC BATHYMETRY REFERENCE - NOT FOR NAVIGATIONAL SAFETY",
        },
        "selection_screen": {
            "initial": _state_dict(screen_initial), "before": _state_dict(screen_before),
            "advisory": {
                "action": screen_decision.action.value,
                "recommended_SOG": screen_decision.recommended_SOG_m_s,
                "recommended_HDG": screen_decision.recommended_HDG_deg,
            },
            "recomputed_candidate": _state_dict(screen_after),
        },
        "dynamic_result_summary": {
            "policy": result.policy_name,
            "final_mission_state": result.final_mission_state.value,
            "technical_completed": result.technical_completed,
            "evidence_qualified_completion": result.evidence_qualified_completion,
            "energy_feasibility_status": result.energy_feasibility_status,
            "future_action_access_count": store.future_action_access_count,
            "business_value_status": "NOT_ESTABLISHED",
            "mission_saved_claim": False,
        },
        "before_after_evidence": evidence,
        "executed_segments": segments,
        "risk_assessments": [
            {"timestamp": item.timestamp, "latitude": item.latitude, "longitude": item.longitude,
             "risk_score": item.risk_score, "single_vessel_risk_level": item.single_vessel_risk_level,
             "robust_status": item.robust_status, "GRID_Q90": item.roll_response_proxy,
             "actual_SOG": item.actual_SOG_m_s, "actual_HDG": item.actual_HDG_deg,
             "segment_id": item.segment_id}
            for item in result.risk_samples
        ],
        "event_markers": events,
        "truth_labels": [
            ENVIRONMENT_SOURCE, "PUBLIC OPERATIONAL CONTEXT", "PUBLIC GEOSPATIAL REFERENCE",
            "SIMULATED TURBINE LAYOUT - NOT OFFICIAL TURBINE COORDINATES",
            GEOMETRY_SOURCE, VESSEL_SOURCE,
            "ENGINEERING_ESTIMATE / NOT_EXPERIMENTALLY_CALIBRATED",
            "NOT VERIFIED ENERGY FEASIBILITY", "DECISION ADVICE ONLY",
            "SIMULATED ACTION EXECUTED", "REAL VESSEL CONTROL DISABLED",
            "SEA ICE / ICE RISK: UNAVAILABLE / FUTURE EXTENSION",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")
    STORYBOARD.write_text(json.dumps(_storyboard(events), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(OUTPUT), "selected_at": selected_at,
        "event_markers": event_types, "before_after": evidence,
        "final_state": result.final_mission_state, "technical_completed": result.technical_completed,
    }, ensure_ascii=False, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
