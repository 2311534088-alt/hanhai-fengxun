"""Synchronized V1.0-B presentation model backed only by FrozenCoreFacade."""

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
REAL_ENVIRONMENT = "REAL PUBLIC HISTORICAL ENVIRONMENT"
PUBLIC_GEOSPATIAL = "PUBLIC GEOSPATIAL REFERENCE: NOT YET LOADED IN MAP"
SIMULATED_GEOMETRY = "SIMULATED MISSION GEOMETRY: ACTIVE"
SIMULATED_TURBINES = "SIMULATED TURBINE LAYOUT"
SIMULATED_VESSEL = "SIMULATED VESSEL STATE"
ENGINEERING_ESTIMATE = "ENGINEERING_ESTIMATE / NOT_EXPERIMENTALLY_CALIBRATED"
UNAVAILABLE = "UNAVAILABLE / REQUIRES VALIDATION"
HISTORICAL_REPLAY = "HISTORICAL ENVIRONMENT MISSION REPLAY · NOT REAL-TIME FORECAST · NOT IN-SITU OBSERVATION"
CONTROL_DISABLED = "DECISION ADVICE ONLY · OPERATOR RETAINS AUTHORITY · REAL VESSEL CONTROL DISABLED"


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
