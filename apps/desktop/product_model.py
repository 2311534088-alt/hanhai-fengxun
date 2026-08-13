"""V1.0 read-only presentation model over the frozen deterministic core."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import Any

from adapters.replay.csv_replay import CSVReplay
from core.navigation import relative_wave_angle
from core.resonance import assess_resonance, load_engineering_estimate
from core.resonance.avoidance import AvoidancePlan, search_resonance_avoidance
from core.risk import BaselineRiskEvaluator, VesselParameters
from core.roll_response import assess_roll_response


REAL_ENVIRONMENT = "REAL PUBLIC ENVIRONMENT"
PUBLIC_GEOSPATIAL = "PUBLIC GEOSPATIAL REFERENCE"
SIMULATED_VESSEL = "SIMULATED VESSEL STATE"
ENGINEERING_ESTIMATE = "ENGINEERING ESTIMATE"
UNAVAILABLE = "UNAVAILABLE / REQUIRES VALIDATION"
HISTORICAL_REPLAY = (
    "REAL PUBLIC ENVIRONMENT SNAPSHOT REPLAY - "
    "NOT A CONTINUOUS WEATHER SERIES / NOT REAL-TIME FORECAST"
)
CONTROL_DISABLED = "DECISION ADVICE ONLY - REAL VESSEL CONTROL DISABLED"

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENVIRONMENT_EVIDENCE = ROOT / "data/results/v0.4_roll_response_demo.json"


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
    recommendation: str
    risk_components: dict[str, float]
    encounter_frequency: float | None
    resonance_margin_ratio: float | None
    resonance_status: str
    roll_response_proxy_deg: float | None
    roll_response_risk: str
    decision_action: str
    decision_reason: str
    environment_timestamp: str
    environment_latitude: float
    environment_longitude: float
    environment_source: str
    vessel_state_source: str
    parameter_source: str
    environment_scenario: str
    provenance_by_field: dict[str, Any]
    candidate_summaries: dict[str, str]


class ProductReplay:
    """Read-only historical demonstration; no actuator or online forecast path exists."""

    def __init__(
        self,
        csv_path: Path,
        environment_evidence_path: Path = DEFAULT_ENVIRONMENT_EVIDENCE,
    ) -> None:
        self.records = tuple(CSVReplay(csv_path))
        if not self.records:
            raise ValueError("product replay requires at least one record")
        self.environment_scenarios = self._load_environment_evidence(environment_evidence_path)
        self.parameters, self.resonance_thresholds = load_engineering_estimate()
        self.risk = BaselineRiskEvaluator()
        self.vessel = VesselParameters(
            model="ZLUSV-200", length_overall_m=2.02, beam_m=0.88,
            draft_m=0.25, hull_mass_approx_kg=50,
            full_load_displacement_min_kg=100,
        )
        self.index = 0
        self.snapshots = tuple(self._build_snapshot(index) for index in range(len(self.records)))

    def seek(self, index: int) -> ProductSnapshot:
        self.index = max(0, min(index, len(self.records) - 1))
        return self.snapshot()

    def next(self) -> ProductSnapshot:
        return self.seek(self.index + 1)

    def previous(self) -> ProductSnapshot:
        return self.seek(self.index - 1)

    def snapshot(self) -> ProductSnapshot:
        return self.snapshots[self.index]

    def _build_snapshot(self, index: int) -> ProductSnapshot:
        vessel_record = self.records[index]
        scenario = self._scenario_for_index(index)
        environment = scenario["environment"]
        record = replace(
            vessel_record,
            Hs=self._optional_float(environment, "Hs"),
            Tp=self._optional_float(environment, "Tp"),
            wave_direction=self._optional_float(environment, "wave_direction"),
            wind_speed=self._optional_float(environment, "wind_speed"),
            wind_direction=self._optional_float(environment, "wind_direction"),
            surface_current_speed=self._optional_float(environment, "surface_current_speed"),
            surface_current_direction=self._optional_float(environment, "surface_current_direction"),
            data_label=f"{REAL_ENVIRONMENT} + {SIMULATED_VESSEL}",
        )
        risk = self.risk.evaluate(record, self.vessel)
        relative = (
            relative_wave_angle(record.wave_direction, record.HDG)
            if record.wave_direction is not None and record.HDG is not None else None
        )
        resonance = assess_resonance(
            record.Tp, record.SOG, relative, parameters=self.parameters,
        )
        roll_proxy = None
        roll_risk = "UNAVAILABLE"
        if None not in (record.Hs, record.Tp, record.SOG, relative):
            response = assess_roll_response(
                Hs_m=record.Hs, Tp_s=record.Tp, vessel_speed_m_s=record.SOG,
                relative_wave_angle_deg=relative, parameters=self.parameters,
            )
            roll_proxy = response.estimated_roll_response_deg
            roll_risk = response.roll_response_risk.value
        action, reason = self._decision(
            risk.risk_level.value,
            resonance.resonance_status.value,
            roll_risk,
        )
        return ProductSnapshot(
            index=index,
            total=len(self.records),
            timestamp=vessel_record.timestamp.isoformat(),
            latitude=record.latitude,
            longitude=record.longitude,
            mission_state=record.mission_state.value,
            Hs=record.Hs,
            Tp=record.Tp,
            wave_direction=record.wave_direction,
            wind_speed=record.wind_speed,
            wind_direction=record.wind_direction,
            current_speed=record.surface_current_speed,
            current_direction=record.surface_current_direction,
            water_depth=self._optional_float(environment, "water_depth"),
            SOG=record.SOG,
            HDG=record.HDG,
            battery=record.battery,
            risk_score=risk.risk_score,
            risk_level=risk.risk_level.value,
            primary_risk=risk.primary_risk,
            recommendation=risk.recommendation,
            risk_components=risk.risk_components,
            encounter_frequency=resonance.encounter_frequency_rad_s,
            resonance_margin_ratio=resonance.resonance_margin_ratio,
            resonance_status=resonance.resonance_status.value,
            roll_response_proxy_deg=roll_proxy,
            roll_response_risk=roll_risk,
            decision_action=action,
            decision_reason=reason,
            environment_timestamp=str(environment["timestamp"]),
            environment_latitude=float(environment["latitude"]),
            environment_longitude=float(environment["longitude"]),
            environment_source=str(scenario["environment_source"]),
            vessel_state_source=SIMULATED_VESSEL,
            parameter_source=str(scenario["parameter_classification"]),
            environment_scenario=str(scenario["scenario_id"]),
            provenance_by_field=dict(environment["provenance_by_field"]),
            candidate_summaries=self._candidate_summaries(record),
        )

    def _candidate_summaries(self, record) -> dict[str, str]:
        keys = ("current", "speed_only", "heading_only", "joint")
        if None in (record.Hs, record.Tp, record.wave_direction, record.SOG, record.HDG):
            return {name: "UNAVAILABLE" for name in keys}
        if not 0.5 <= record.SOG <= 3.0:
            return {
                "current": f"{record.SOG:.1f} m/s / {record.HDG:.0f}°",
                "speed_only": "UNAVAILABLE", "heading_only": "UNAVAILABLE", "joint": "UNAVAILABLE",
            }
        result = search_resonance_avoidance(
            Tp_s=record.Tp, Hs_m=record.Hs,
            wave_direction_deg=record.wave_direction,
            current_speed_m_s=record.SOG,
            current_heading_deg=record.HDG,
            parameters=self.parameters,
            thresholds=self.resonance_thresholds,
        )

        def format_plan(plan: AvoidancePlan) -> str:
            candidate = plan.recommended
            if candidate is None:
                return plan.decision_status.value
            risk = candidate.roll_response_risk.value if candidate.roll_response_risk else "UNAVAILABLE"
            return f"{candidate.SOG_m_s:.1f} m/s / {candidate.HDG_deg:.0f}° · {risk}"

        current_risk = result.current.roll_response_risk.value if result.current.roll_response_risk else "UNAVAILABLE"
        return {
            "current": f"{result.current.SOG_m_s:.1f} m/s / {result.current.HDG_deg:.0f}° · {current_risk}",
            "speed_only": format_plan(result.speed_only),
            "heading_only": format_plan(result.heading_only),
            "joint": format_plan(result.joint),
        }

    @staticmethod
    def _optional_float(mapping: dict[str, Any], key: str) -> float | None:
        value = mapping.get(key)
        return None if value is None else float(value)

    @staticmethod
    def _load_environment_evidence(path: Path) -> dict[str, dict[str, Any]]:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        expected_label = "REAL PUBLIC ENVIRONMENT DATA - NOT IN-SITU ZHUANGHE OBSERVATION"
        if payload.get("environment_source") != expected_label:
            raise ValueError("V1.0 environment evidence must be labelled real public, not in-situ")
        scenarios = {str(item["scenario_id"]): item for item in payload.get("scenarios", [])}
        required = {
            "FREQUENCY_CLOSE_LOW_EXCITATION",
            "MODERATE_ROLL_RESPONSE_RISK",
            "HIGH_ROLL_RESPONSE_RISK",
        }
        if not required.issubset(scenarios):
            raise ValueError("V1.0 environment evidence is missing representative scenarios")
        return scenarios

    def _scenario_for_index(self, index: int) -> dict[str, Any]:
        progress = index / max(len(self.records) - 1, 1)
        if progress < 0.25 or progress >= 0.85:
            scenario_id = "FREQUENCY_CLOSE_LOW_EXCITATION"
        elif progress < 0.45 or progress >= 0.70:
            scenario_id = "MODERATE_ROLL_RESPONSE_RISK"
        else:
            scenario_id = "HIGH_ROLL_RESPONSE_RISK"
        return self.environment_scenarios[scenario_id]

    @staticmethod
    def _decision(
        risk_level: str,
        resonance_status: str,
        roll_response_risk: str,
    ) -> tuple[str, str]:
        if risk_level == "HIGH":
            return "RETURN", "Single-vessel baseline is HIGH; pause/return assessment requires operator review."
        if roll_response_risk == "HIGH":
            return "ADJUST", "Low-fidelity roll-response proxy is HIGH; compare advisory candidates before continuing."
        if resonance_status == "HIGH_RISK":
            return "ADJUST", "Resonance proximity is HIGH; compare speed/heading candidates before continuing."
        if risk_level == "MEDIUM" or resonance_status == "WARNING" or roll_response_risk == "MODERATE":
            return "ADJUST", "Moderate assessment output; present conservative speed, heading and reroute advisories."
        return "CONTINUE", "Current frozen deterministic assessments remain within preliminary limits."

    @property
    def track(self) -> tuple[tuple[float, float], ...]:
        return tuple((record.latitude, record.longitude) for record in self.records)

    @property
    def timeline(self) -> tuple[str, ...]:
        return tuple(record.mission_state.value for record in self.records)

    @property
    def action_timeline(self) -> tuple[str, ...]:
        return tuple(snapshot.decision_action for snapshot in self.snapshots)
