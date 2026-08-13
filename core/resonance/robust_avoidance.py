"""Parameter-grid-aware simulation search for robust roll-response advice."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from core.navigation import relative_wave_angle
from core.resonance.avoidance import SearchLimits
from core.resonance.parameters import RollDynamicsParameters
from core.roll_response import (
    GRID_METHOD, GRID_STATISTICAL_STATUS, RobustDecisionStatus, RollResponseRisk,
    RollResponseThresholds, RollResponseUncertainty, load_roll_response_thresholds,
    scan_roll_response_uncertainty,
)


DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "roll_response_baseline.json"
RISK_RANK = {
    RollResponseRisk.LOW: 0,
    RollResponseRisk.MODERATE: 1,
    RollResponseRisk.HIGH: 2,
    RollResponseRisk.UNAVAILABLE: 3,
}


@dataclass(frozen=True, slots=True)
class ManeuverConstraint:
    maximum_relative_speed_change: float
    status: str
    validation_status: str

    def __post_init__(self) -> None:
        if not 0 < self.maximum_relative_speed_change < 1:
            raise ValueError("maximum relative speed change must be in (0, 1)")
        if self.status != "PRELIMINARY_MANEUVER_CONSTRAINT":
            raise ValueError("maneuver constraint must retain its preliminary label")
        if self.validation_status != "PRELIMINARY / NEEDS REAL VESSEL VALIDATION":
            raise ValueError("maneuver constraint must require real-vessel validation")


@dataclass(frozen=True, slots=True)
class RobustCandidate:
    SOG_m_s: float
    HDG_deg: float
    relative_wave_angle_deg: float
    speed_change_percent: float
    heading_change_deg: float
    response_grid: RollResponseUncertainty
    speed_search_boundary_hit: bool
    heading_search_boundary_hit: bool
    boundary_status: str | None
    decision_confidence_warning: str | None
    conflict_status: str | None


@dataclass(frozen=True, slots=True)
class RobustRecommendation:
    label: str
    candidate: RobustCandidate
    robust_status: RobustDecisionStatus
    operator_advice: str
    evaluated_candidate_count: int
    search_bound_status: str = "SIMULATION_SEARCH_BOUND"
    operational_range_status: str = "NOT ZLUSV-200 OPERATIONAL SPEED RANGE"


@dataclass(frozen=True, slots=True)
class RobustAvoidanceResult:
    current: RobustCandidate
    constrained_recommendation: RobustRecommendation
    unrestricted_simulation_best: RobustRecommendation
    maneuver_constraint: ManeuverConstraint
    parameter_grid_method: str = GRID_METHOD
    parameter_grid_statistical_status: str = GRID_STATISTICAL_STATUS
    parameter_source: str = "ENGINEERING_ESTIMATE"
    parameter_status: str = "NOT_EXPERIMENTALLY_CALIBRATED"


def load_maneuver_constraint(path: str | Path = DEFAULT_CONFIG) -> ManeuverConstraint:
    data = json.loads(Path(path).read_text(encoding="utf-8"))["preliminary_maneuver_constraint"]
    return ManeuverConstraint(
        maximum_relative_speed_change=float(data["maximum_relative_speed_change"]),
        status=str(data["status"]), validation_status=str(data["validation_status"]),
    )


def constrained_speed_interval(
    current_speed_m_s: float,
    constraint: ManeuverConstraint,
    limits: SearchLimits,
) -> tuple[float, float]:
    fraction = constraint.maximum_relative_speed_change
    return (
        max(limits.minimum_speed_m_s, current_speed_m_s * (1.0 - fraction)),
        min(limits.maximum_speed_m_s, current_speed_m_s * (1.0 + fraction)),
    )


def _candidate(
    *, Hs_m: float, Tp_s: float, wave_direction_deg: float, speed_m_s: float,
    heading_deg: float, current_speed_m_s: float, current_heading_deg: float,
    parameters: RollDynamicsParameters, thresholds: RollResponseThresholds,
    limits: SearchLimits, current_grid: RollResponseUncertainty | None,
) -> RobustCandidate:
    relative_angle = relative_wave_angle(wave_direction_deg, heading_deg)
    grid = scan_roll_response_uncertainty(
        Hs_m=Hs_m, Tp_s=Tp_s, vessel_speed_m_s=speed_m_s,
        relative_wave_angle_deg=relative_angle, parameters=parameters, thresholds=thresholds,
    )
    heading_change = ((heading_deg - current_heading_deg + 180.0) % 360.0) - 180.0
    speed_boundary = (
        abs(speed_m_s - limits.minimum_speed_m_s) < 1e-9
        or abs(speed_m_s - limits.maximum_speed_m_s) < 1e-9
    )
    heading_boundary = abs(heading_change) == max(abs(value) for value in limits.heading_offsets_deg)
    boundary_status = "OPTIMUM_LIES_ON_SIMULATION_SEARCH_BOUNDARY" if speed_boundary or heading_boundary else None
    conflict = None
    if current_grid is not None:
        if (
            grid.nominal_estimated_roll_response_deg < current_grid.nominal_estimated_roll_response_deg
            and grid.grid_q90_roll_risk is RollResponseRisk.HIGH
        ):
            conflict = "NOMINAL_IMPROVES_BUT_ROBUST_RISK_REMAINS_HIGH"
    warning = (
        "Simulation search boundary reached; not a validated real-vessel speed recommendation."
        if boundary_status else None
    )
    return RobustCandidate(
        SOG_m_s=speed_m_s, HDG_deg=heading_deg % 360.0,
        relative_wave_angle_deg=relative_angle,
        speed_change_percent=(speed_m_s - current_speed_m_s) / current_speed_m_s * 100.0,
        heading_change_deg=heading_change, response_grid=grid,
        speed_search_boundary_hit=speed_boundary,
        heading_search_boundary_hit=heading_boundary,
        boundary_status=boundary_status, decision_confidence_warning=warning,
        conflict_status=conflict,
    )


def _rank(candidate: RobustCandidate) -> tuple[float, float, float, float, float]:
    grid = candidate.response_grid
    return (
        RISK_RANK[grid.grid_q90_roll_risk],
        grid.grid_q90_estimated_roll_response_deg,
        grid.nominal_estimated_roll_response_deg,
        abs(candidate.speed_change_percent),
        abs(candidate.heading_change_deg),
    )


def _recommendation(label: str, candidates: list[RobustCandidate]) -> RobustRecommendation:
    best = min(candidates, key=_rank)
    status = best.response_grid.robust_decision_status
    advice = (
        "PAUSE / RETURN ASSESSMENT"
        if status is RobustDecisionStatus.RESIDUAL_HIGH_RISK
        else "OPERATOR REVIEW REQUIRED - DECISION ADVICE ONLY"
    )
    return RobustRecommendation(label, best, status, advice, len(candidates))


def search_robust_roll_avoidance(
    *, Hs_m: float, Tp_s: float, wave_direction_deg: float,
    current_speed_m_s: float, current_heading_deg: float,
    parameters: RollDynamicsParameters,
    thresholds: RollResponseThresholds | None = None,
    limits: SearchLimits | None = None,
    maneuver_constraint: ManeuverConstraint | None = None,
) -> RobustAvoidanceResult:
    """Return separate constrained advice and unrestricted simulation sensitivity best."""

    thresholds = thresholds or load_roll_response_thresholds()
    limits = limits or SearchLimits()
    maneuver_constraint = maneuver_constraint or load_maneuver_constraint()
    current = _candidate(
        Hs_m=Hs_m, Tp_s=Tp_s, wave_direction_deg=wave_direction_deg,
        speed_m_s=current_speed_m_s, heading_deg=current_heading_deg,
        current_speed_m_s=current_speed_m_s, current_heading_deg=current_heading_deg,
        parameters=parameters, thresholds=thresholds, limits=limits, current_grid=None,
    )
    speeds = limits.speeds()
    heading_offsets = limits.heading_offsets_deg
    unrestricted = [
        _candidate(
            Hs_m=Hs_m, Tp_s=Tp_s, wave_direction_deg=wave_direction_deg,
            speed_m_s=speed, heading_deg=(current_heading_deg + offset) % 360.0,
            current_speed_m_s=current_speed_m_s, current_heading_deg=current_heading_deg,
            parameters=parameters, thresholds=thresholds, limits=limits,
            current_grid=current.response_grid,
        )
        for speed in speeds for offset in heading_offsets
    ]
    lower, upper = constrained_speed_interval(current_speed_m_s, maneuver_constraint, limits)
    constrained = [item for item in unrestricted if lower - 1e-9 <= item.SOG_m_s <= upper + 1e-9]
    if not constrained:
        raise ValueError("preliminary maneuver constraint produced no speed candidates")
    return RobustAvoidanceResult(
        current=current,
        constrained_recommendation=_recommendation("CONSTRAINED_RECOMMENDATION", constrained),
        unrestricted_simulation_best=_recommendation("UNRESTRICTED_SIMULATION_BEST", unrestricted),
        maneuver_constraint=maneuver_constraint,
        parameter_source=parameters.parameter_source.value,
        parameter_status=parameters.parameter_status,
    )
