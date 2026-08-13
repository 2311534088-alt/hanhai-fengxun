"""Read-only V1.0 product facade over the frozen deterministic core."""

from __future__ import annotations

from dataclasses import dataclass

from core.mission.decision import MissionAction, decide_mission_action
from core.models import TelemetryRecord
from core.navigation import relative_wave_angle
from core.resonance import (
    RobustAvoidanceResult, assess_resonance, load_engineering_estimate,
    search_robust_roll_avoidance,
)
from core.risk import BaselineRiskEvaluator, RiskResult, VesselParameters


FACADE_SOURCE = "FROZEN V0.9 DETERMINISTIC CORE"
MISSION_DECISION_SOURCE = "core.mission.decision.decide_mission_action"
ROBUST_ADVICE_SOURCE = "core.resonance.search_robust_roll_avoidance"
CONTROL_STATUS = "DECISION ADVICE ONLY - REAL VESSEL CONTROL DISABLED"
SEARCH_BOUND_STATUS = "SIMULATION_SEARCH_BOUND - NOT OPERATIONAL SPEED RANGE"
MANEUVER_CONSTRAINT_STATUS = "PRELIMINARY / NEEDS REAL VESSEL VALIDATION"


@dataclass(frozen=True, slots=True)
class FrozenCoreAssessment:
    risk: RiskResult
    resonance: object
    robust: RobustAvoidanceResult | None
    mission_action: MissionAction
    mission_advisory: str
    mission_reason: str
    decision_source: str
    robust_advice_source: str
    control_status: str = CONTROL_STATUS


MISSION_WORDING = {
    MissionAction.CONTINUE: "CONTINUE",
    MissionAction.ADJUST_SPEED_HEADING: "ADJUSTMENT ADVISED",
    MissionAction.REROUTE: "MISSION REVIEW REQUIRED · REROUTE ADVISORY",
    MissionAction.HOLD_AND_REASSESS: "MISSION REVIEW REQUIRED · HOLD/REASSESS",
    MissionAction.DELAY_MISSION: "MISSION REVIEW REQUIRED · DELAY ASSESSMENT",
    MissionAction.RETURN: "RETURN ASSESSMENT",
}


class FrozenCoreFacade:
    """Single read-only integration point; no task policy is implemented here."""

    def __init__(self) -> None:
        self.parameters, self.resonance_thresholds = load_engineering_estimate()
        self.risk_evaluator = BaselineRiskEvaluator()
        self.vessel = VesselParameters(
            model="ZLUSV-200", length_overall_m=2.02, beam_m=0.88,
            draft_m=0.25, hull_mass_approx_kg=50,
            full_load_displacement_min_kg=100,
        )

    def assess(self, record: TelemetryRecord) -> FrozenCoreAssessment:
        risk = self.risk_evaluator.evaluate(record, self.vessel)
        relative = (
            relative_wave_angle(record.wave_direction, record.HDG)
            if record.wave_direction is not None and record.HDG is not None else None
        )
        resonance = assess_resonance(
            record.Tp, record.SOG, relative,
            parameters=self.parameters, thresholds=self.resonance_thresholds,
        )
        robust = None
        if (
            None not in (record.Hs, record.Tp, record.wave_direction, record.SOG, record.HDG)
            and 0.5 <= record.SOG <= 3.0
        ):
            robust = search_robust_roll_avoidance(
                Hs_m=record.Hs, Tp_s=record.Tp,
                wave_direction_deg=record.wave_direction,
                current_speed_m_s=record.SOG, current_heading_deg=record.HDG,
                parameters=self.parameters,
            )
        robust_status = (
            robust.current.response_grid.robust_decision_status.value
            if robust else "UNAVAILABLE"
        )
        constrained_acceptable = (
            robust is not None
            and robust.constrained_recommendation.robust_status.value
            != "RESIDUAL_HIGH_RISK_UNDER_PARAMETER_UNCERTAINTY"
        )
        mission = decide_mission_action(
            mission_state=record.mission_state,
            current_robust_status=robust_status,
            constrained_adjustment_acceptable=constrained_acceptable,
        )
        action = mission.technical_outcome.preferred_mission_action
        return FrozenCoreAssessment(
            risk=risk,
            resonance=resonance,
            robust=robust,
            mission_action=action,
            mission_advisory=MISSION_WORDING[action],
            mission_reason=mission.technical_outcome.decision_reason,
            decision_source=MISSION_DECISION_SOURCE,
            robust_advice_source=ROBUST_ADVICE_SOURCE,
        )
