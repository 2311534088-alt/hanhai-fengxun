"""Read-only V1.0 product presentation models; no actuator path exists."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from apps.desktop.frozen_core_facade import FrozenCoreFacade
from core.mission import MissionState
from core.models import TelemetryRecord


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPLAY = ROOT / "data/replay/v1.0b_synchronized_historical_mission.json"
DEFAULT_COMPETITION_DEMO = ROOT / "data/replay/v1.0c_competition_demo.json"
REAL_ENVIRONMENT = "REAL PUBLIC HISTORICAL ENVIRONMENT"
PUBLIC_GEOSPATIAL = "PUBLIC GEOSPATIAL REFERENCE: NOT YET LOADED IN MAP"
SIMULATED_GEOMETRY = "SIMULATED MISSION GEOMETRY: ACTIVE"
SIMULATED_TURBINES = "SIMULATED TURBINE LAYOUT"
SIMULATED_VESSEL = "SIMULATED VESSEL STATE"
ENGINEERING_ESTIMATE = "ENGINEERING_ESTIMATE / NOT_EXPERIMENTALLY_CALIBRATED"
UNAVAILABLE = "UNAVAILABLE / REQUIRES VALIDATION"
HISTORICAL_REPLAY = "HISTORICAL ENVIRONMENT MISSION REPLAY · NOT REAL-TIME FORECAST · NOT IN-SITU OBSERVATION"
CONTROL_DISABLED = "DECISION ADVICE ONLY · OPERATOR RETAINS AUTHORITY · REAL VESSEL CONTROL DISABLED"
DYNAMIC_CORE_SOURCE = "core.mission.dynamic_replay.DynamicMissionEngine"
SIMULATED_ACTION = "SIMULATED ACTION EXECUTED"
PUBLIC_CONTEXT = "PUBLIC OPERATIONAL CONTEXT"


@dataclass(frozen=True, slots=True)
class ProductSnapshot:
    index: int
    total: int
    timestamp: str
    latitude: float
    longitude: float
    mission_state: str
    Hs: float | None
    Tp: float | None
    wave_direction: float | None
    wind_speed: float | None
    wind_direction: float | None
    current_speed: float | None
    current_direction: float | None
    water_depth: float | None
    SOG: float | None
    HDG: float | None
    battery: float | None
    risk_score: float
    risk_level: str
    primary_risk: str
    risk_components: dict[str, float]
    encounter_frequency: float | None
    resonance_margin_ratio: float | None
    resonance_status: str
    current_grid_q90: float | None
    current_robust_status: str
    recommended_SOG: float | None
    recommended_HDG: float | None
    recommended_grid_q90: float | None
    recommended_robust_status: str
    speed_change_percent: float | None
    heading_change_deg: float | None
    boundary_hit: bool | None
    unrestricted_SOG: float | None
    unrestricted_HDG: float | None
    unrestricted_grid_q90: float | None
    parameter_source: str
    parameter_status: str
    operator_advice: str
    decision_action: str
    decision_reason: str
    decision_source: str
    robust_advice_source: str
    environment_source: str
    vessel_state_source: str
    provenance_by_field: dict[str, Any]


class ProductReplay:
    """Read-only synchronized historical replay; no actuator path exists."""

    def __init__(self, replay_path: Path = DEFAULT_REPLAY) -> None:
        payload = json.loads(Path(replay_path).read_text(encoding="utf-8-sig"))
        if payload.get("replay_mode") != "SYNCHRONIZED_HISTORICAL_MISSION_REPLAY":
            raise ValueError("V1.0-B requires synchronized historical replay evidence")
        if payload.get("environment_source") != REAL_ENVIRONMENT:
            raise ValueError("environment source label is invalid")
        self.metadata = payload
        self.facade = FrozenCoreFacade()
        self.records = tuple(self._record(item) for item in payload["records"])
        if not self.records:
            raise ValueError("product replay requires at least one record")
        self.provenance = tuple(item["environment"]["provenance_by_field"] for item in payload["records"])
        self.index = 0
        self.snapshots = tuple(self._snapshot(index) for index in range(len(self.records)))

    @staticmethod
    def _record(item: dict[str, Any]) -> TelemetryRecord:
        environment = item["environment"]
        vessel = item["simulated_vessel_state"]
        return TelemetryRecord(
            timestamp=datetime.fromisoformat(item["timestamp"]),
            latitude=float(item["latitude"]), longitude=float(item["longitude"]),
            Hs=environment.get("Hs"), Tp=environment.get("Tp"),
            wave_direction=environment.get("wave_direction"),
            wind_speed=environment.get("wind_speed"), wind_direction=environment.get("wind_direction"),
            surface_current_speed=environment.get("surface_current_speed"),
            surface_current_direction=environment.get("surface_current_direction"),
            SOG=vessel.get("SOG"), COG=vessel.get("COG"), HDG=vessel.get("HDG"),
            roll=vessel.get("roll"), pitch=vessel.get("pitch"), roll_rate=vessel.get("roll_rate"),
            battery=vessel.get("battery"), mission_state=MissionState(item["mission_state"]),
            data_label=f"{REAL_ENVIRONMENT} + {SIMULATED_VESSEL}",
        )

    def _snapshot(self, index: int) -> ProductSnapshot:
        record = self.records[index]
        result = self.facade.assess(record)
        robust = result.robust
        current = robust.current if robust else None
        constrained = robust.constrained_recommendation if robust else None
        recommended = constrained.candidate if constrained else None
        unrestricted = robust.unrestricted_simulation_best.candidate if robust else None
        return ProductSnapshot(
            index=index, total=len(self.records), timestamp=record.timestamp.isoformat(),
            latitude=record.latitude, longitude=record.longitude,
            mission_state=record.mission_state.value,
            Hs=record.Hs, Tp=record.Tp, wave_direction=record.wave_direction,
            wind_speed=record.wind_speed, wind_direction=record.wind_direction,
            current_speed=record.surface_current_speed,
            current_direction=record.surface_current_direction,
            water_depth=self.metadata["records"][index]["environment"].get("water_depth"),
            SOG=record.SOG, HDG=record.HDG, battery=record.battery,
            risk_score=result.risk.risk_score, risk_level=result.risk.risk_level.value,
            primary_risk=result.risk.primary_risk, risk_components=result.risk.risk_components,
            encounter_frequency=result.resonance.encounter_frequency_rad_s,
            resonance_margin_ratio=result.resonance.resonance_margin_ratio,
            resonance_status=result.resonance.resonance_status.value,
            current_grid_q90=current.response_grid.grid_q90_estimated_roll_response_deg if current else None,
            current_robust_status=current.response_grid.robust_decision_status.value if current else "UNAVAILABLE",
            recommended_SOG=recommended.SOG_m_s if recommended else None,
            recommended_HDG=recommended.HDG_deg if recommended else None,
            recommended_grid_q90=recommended.response_grid.grid_q90_estimated_roll_response_deg if recommended else None,
            recommended_robust_status=constrained.robust_status.value if constrained else "UNAVAILABLE",
            speed_change_percent=recommended.speed_change_percent if recommended else None,
            heading_change_deg=recommended.heading_change_deg if recommended else None,
            boundary_hit=(recommended.speed_search_boundary_hit or recommended.heading_search_boundary_hit) if recommended else None,
            unrestricted_SOG=unrestricted.SOG_m_s if unrestricted else None,
            unrestricted_HDG=unrestricted.HDG_deg if unrestricted else None,
            unrestricted_grid_q90=unrestricted.response_grid.grid_q90_estimated_roll_response_deg if unrestricted else None,
            parameter_source=robust.parameter_source if robust else self.facade.parameters.parameter_source.value,
            parameter_status=robust.parameter_status if robust else self.facade.parameters.parameter_status,
            operator_advice=constrained.operator_advice if constrained else "OPERATOR REVIEW REQUIRED - ROBUST SEARCH UNAVAILABLE",
            decision_action=result.mission_advisory,
            decision_reason=result.mission_reason,
            decision_source=result.decision_source,
            robust_advice_source=result.robust_advice_source,
            environment_source=REAL_ENVIRONMENT,
            vessel_state_source=SIMULATED_VESSEL,
            provenance_by_field=self.provenance[index],
        )

    def seek(self, index: int) -> ProductSnapshot:
        self.index = max(0, min(index, len(self.records) - 1))
        return self.snapshot()

    def next(self) -> ProductSnapshot:
        return self.seek(self.index + 1)

    def previous(self) -> ProductSnapshot:
        return self.seek(self.index - 1)

    def snapshot(self) -> ProductSnapshot:
        return self.snapshots[self.index]

    @property
    def track(self) -> tuple[tuple[float, float], ...]:
        return tuple((record.latitude, record.longitude) for record in self.records)

    @property
    def timeline(self) -> tuple[str, ...]:
        return tuple(record.mission_state.value for record in self.records)

    @property
    def action_timeline(self) -> tuple[str, ...]:
        return tuple(snapshot.decision_action for snapshot in self.snapshots)


class CompetitionDemoReplay:
    """V1.0-C event replay generated by the frozen DynamicMissionEngine."""

    def __init__(self, replay_path: Path = DEFAULT_COMPETITION_DEMO) -> None:
        payload = json.loads(Path(replay_path).read_text(encoding="utf-8-sig"))
        if payload.get("core_source") != DYNAMIC_CORE_SOURCE:
            raise ValueError("V1.0-C requires frozen DynamicMissionEngine evidence")
        self.metadata = payload
        self.events = tuple(payload["event_markers"])
        if not self.events:
            raise ValueError("competition demo requires event markers")
        self.index = 0
        self.facade = FrozenCoreFacade()
        self.snapshots = tuple(self._snapshot(i) for i in range(len(self.events)))

    def _snapshot(self, index: int) -> ProductSnapshot:
        event = self.events[index]
        before_after = self.metadata["before_after_evidence"]
        after = before_after["after"]
        recommended_q90 = after["GRID_Q90"] if event.get("recommended_SOG") is not None else None
        recommended_robust = after["robust_status"] if recommended_q90 is not None else "UNAVAILABLE"
        components = event.get("risk_components") or {}
        primary = max(components, key=components.get) if components else "UNAVAILABLE"
        provenance = event.get("provenance_by_field") or {}
        warning = any(not item.get("within_tolerance", item.get("accepted", False)) for item in provenance.values())
        decision_action = event.get("decision_action", "NONE")
        if event["event_type"] == "RISK_IMPROVED":
            decision_action = "CONTINUE · RISK IMPROVED"
        elif event["event_type"] in {"TARGET_REACHED", "INSPECTION_AREA_ENTERED"}:
            decision_action = event["event_type"].replace("_", " ")
        elif event["event_type"].startswith("INSPECTION_PAYLOAD"):
            decision_action = event["event_type"].replace("_", " ") + " (SIMULATED)"
        return ProductSnapshot(
            index=index, total=len(self.events), timestamp=event["timestamp"],
            latitude=event["latitude"], longitude=event["longitude"],
            mission_state=event["mission_state"], Hs=event.get("Hs"), Tp=event.get("Tp"),
            wave_direction=event.get("wave_direction"), wind_speed=event.get("wind_speed"),
            wind_direction=event.get("wind_direction"),
            current_speed=event.get("surface_current_speed"),
            current_direction=event.get("surface_current_direction"),
            water_depth=event.get("water_depth"), SOG=event.get("SOG"), HDG=event.get("HDG"),
            battery=None, risk_score=event["single_vessel_risk_score"],
            risk_level=event["single_vessel_risk_level"], primary_risk=primary,
            risk_components=components, encounter_frequency=None, resonance_margin_ratio=None,
            resonance_status="ENGINEERING DETAILS", current_grid_q90=event.get("GRID_Q90"),
            current_robust_status=event.get("robust_status", "UNAVAILABLE"),
            recommended_SOG=event.get("recommended_SOG"),
            recommended_HDG=event.get("recommended_HDG"),
            recommended_grid_q90=recommended_q90,
            recommended_robust_status=recommended_robust,
            speed_change_percent=(
                (event["recommended_SOG"] - event["SOG"]) / event["SOG"] * 100.0
                if event.get("recommended_SOG") is not None and event.get("SOG") else None
            ),
            heading_change_deg=(
                abs((event["recommended_HDG"] - event["HDG"] + 180.0) % 360.0 - 180.0)
                if event.get("recommended_HDG") is not None else None
            ),
            boundary_hit=None, unrestricted_SOG=None, unrestricted_HDG=None,
            unrestricted_grid_q90=None, parameter_source="ENGINEERING_ESTIMATE",
            parameter_status="NOT_EXPERIMENTALLY_CALIBRATED",
            operator_advice=("DATA QUALITY / PROVENANCE WARNING" if warning else "DECISION ADVICE ONLY"),
            decision_action=decision_action,
            decision_reason=event.get("decision_reason", "Derived from executed dynamic replay event."),
            decision_source=DYNAMIC_CORE_SOURCE, robust_advice_source=DYNAMIC_CORE_SOURCE,
            environment_source=event["source_labels"]["environment"],
            vessel_state_source=event["source_labels"]["vessel"],
            provenance_by_field=provenance,
        )

    def seek(self, index: int) -> ProductSnapshot:
        self.index = max(0, min(index, len(self.snapshots) - 1))
        return self.snapshot()

    def next(self) -> ProductSnapshot:
        return self.seek(self.index + 1)

    def previous(self) -> ProductSnapshot:
        return self.seek(self.index - 1)

    def snapshot(self) -> ProductSnapshot:
        return self.snapshots[self.index]

    @property
    def current_event(self) -> dict[str, Any]:
        return self.events[self.index]

    @property
    def track(self) -> tuple[tuple[float, float], ...]:
        return tuple((item["latitude"], item["longitude"]) for item in self.events)

    @property
    def executed_track(self) -> tuple[tuple[float, float], ...]:
        segments = self.metadata["executed_segments"]
        return tuple([tuple(segments[0]["start"]), *(tuple(item["end"]) for item in segments)])

    @property
    def completed_executed_track(self) -> tuple[tuple[float, float], ...]:
        at = datetime.fromisoformat(self.current_event["timestamp"])
        segments = [item for item in self.metadata["executed_segments"]
                    if datetime.fromisoformat(item["end_time"]) <= at]
        if not segments:
            return (tuple(self.metadata["executed_segments"][0]["start"]),)
        return tuple([tuple(segments[0]["start"]), *(tuple(item["end"]) for item in segments)])

    @property
    def timeline(self) -> tuple[str, ...]:
        return tuple(item["mission_state"] for item in self.events)

    @property
    def action_timeline(self) -> tuple[str, ...]:
        return tuple(item["event_type"] for item in self.events)
