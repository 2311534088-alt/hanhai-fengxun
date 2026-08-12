"""Explainable speed/heading search for preliminary resonance avoidance advice."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite

from core.navigation import relative_wave_angle
from core.resonance.parameters import ResonanceThresholds, RollDynamicsParameters
from core.resonance.physics import ResonanceAssessment, ResonanceStatus, assess_resonance


class SearchMode(str, Enum):
    SPEED_ONLY = "SPEED_ONLY"
    HEADING_ONLY = "HEADING_ONLY"
    JOINT_SPEED_HEADING = "JOINT_SPEED_HEADING"


class DecisionStatus(str, Enum):
    RECOMMENDED = "RECOMMENDED"
    CURRENT_STATE_ACCEPTABLE = "CURRENT_STATE_ACCEPTABLE"
    NO_SAFE_CANDIDATE = "NO_SAFE_CANDIDATE_WITHIN_SEARCH_LIMITS"


STATUS_RANK = {
    ResonanceStatus.UNAVAILABLE: -1,
    ResonanceStatus.HIGH_RISK: 0,
    ResonanceStatus.WARNING: 1,
    ResonanceStatus.NORMAL: 2,
}


@dataclass(frozen=True, slots=True)
class SearchLimits:
    minimum_speed_m_s: float = 0.5
    maximum_speed_m_s: float = 3.0
    speed_step_m_s: float = 0.1
    heading_offsets_deg: tuple[float, ...] = (-15.0, -10.0, -5.0, 0.0, 5.0, 10.0, 15.0)

    def __post_init__(self) -> None:
        if not 0.5 <= self.minimum_speed_m_s <= self.maximum_speed_m_s <= 3.0:
            raise ValueError("speed search must stay within 0.5 to 3.0 m/s")
        if self.speed_step_m_s <= 0:
            raise ValueError("speed_step_m_s must be positive")
        if not self.heading_offsets_deg or 0.0 not in self.heading_offsets_deg:
            raise ValueError("heading offsets must include 0 degrees")
        allowed_offsets = {-15.0, -10.0, -5.0, 0.0, 5.0, 10.0, 15.0}
        if any(value not in allowed_offsets for value in self.heading_offsets_deg):
            raise ValueError("heading offsets must be selected from current HDG 0/+/-5/+/-10/+/-15 degrees")

    def speeds(self) -> tuple[float, ...]:
        count = int(round((self.maximum_speed_m_s - self.minimum_speed_m_s) / self.speed_step_m_s))
        values = [self.minimum_speed_m_s + index * self.speed_step_m_s for index in range(count + 1)]
        if values[-1] < self.maximum_speed_m_s - 1e-9:
            values.append(self.maximum_speed_m_s)
        return tuple(round(min(value, self.maximum_speed_m_s), 10) for value in values)


@dataclass(frozen=True, slots=True)
class CandidateAssessment:
    SOG_m_s: float
    HDG_deg: float
    relative_wave_angle_deg: float
    encounter_frequency_rad_s: float
    resonance_margin_ratio: float
    resonance_status: ResonanceStatus
    parameter_source: str
    parameter_status: str
    speed_change_percent: float
    heading_change_deg: float


@dataclass(frozen=True, slots=True)
class AvoidancePlan:
    mode: SearchMode
    decision_status: DecisionStatus
    current: CandidateAssessment
    recommended: CandidateAssessment | None
    decision_reason: str
    speed_loss_percent: float | None
    estimated_travel_time_change_percent: float | None
    energy_cost: None = None
    energy_model_status: str = "REQUIRES REAL SPEED-POWER DATA"
    control_output_status: str = "DECISION ADVICE ONLY - NO REAL ACTUATOR COMMAND"


@dataclass(frozen=True, slots=True)
class AvoidanceSearchResult:
    current: CandidateAssessment
    speed_only: AvoidancePlan
    heading_only: AvoidancePlan
    joint: AvoidancePlan
    recommended_mode: SearchMode | None
    recommended: CandidateAssessment | None
    decision_status: DecisionStatus
    decision_reason: str

    @property
    def current_speed(self) -> float:
        return self.current.SOG_m_s

    @property
    def recommended_speed(self) -> float | None:
        return self.recommended.SOG_m_s if self.recommended else None

    @property
    def current_resonance_status(self) -> ResonanceStatus:
        return self.current.resonance_status

    @property
    def recommended_resonance_status(self) -> ResonanceStatus | None:
        return self.recommended.resonance_status if self.recommended else None

    @property
    def current_margin_ratio(self) -> float:
        return self.current.resonance_margin_ratio

    @property
    def recommended_margin_ratio(self) -> float | None:
        return self.recommended.resonance_margin_ratio if self.recommended else None

    @property
    def speed_change_percent(self) -> float | None:
        return self.recommended.speed_change_percent if self.recommended else None


def _candidate(
    Tp_s: float,
    wave_direction_deg: float,
    speed_m_s: float,
    heading_deg: float,
    current_speed_m_s: float,
    current_heading_deg: float,
    parameters: RollDynamicsParameters,
    thresholds: ResonanceThresholds,
) -> CandidateAssessment:
    relative_angle = relative_wave_angle(wave_direction_deg, heading_deg)
    assessment: ResonanceAssessment = assess_resonance(
        Tp_s, speed_m_s, relative_angle, parameters=parameters, thresholds=thresholds,
    )
    if assessment.encounter_frequency_rad_s is None or assessment.resonance_margin_ratio is None:
        raise ValueError("resonance assessment is unavailable for the supplied search inputs")
    heading_delta = ((heading_deg - current_heading_deg + 180.0) % 360.0) - 180.0
    return CandidateAssessment(
        SOG_m_s=speed_m_s,
        HDG_deg=heading_deg % 360.0,
        relative_wave_angle_deg=relative_angle,
        encounter_frequency_rad_s=assessment.encounter_frequency_rad_s,
        resonance_margin_ratio=assessment.resonance_margin_ratio,
        resonance_status=assessment.resonance_status,
        parameter_source=assessment.parameter_source.value,
        parameter_status=assessment.parameter_status,
        speed_change_percent=(speed_m_s - current_speed_m_s) / current_speed_m_s * 100.0,
        heading_change_deg=heading_delta,
    )


def _plan(
    mode: SearchMode,
    current: CandidateAssessment,
    candidates: list[CandidateAssessment],
) -> AvoidancePlan:
    if current.resonance_status == ResonanceStatus.NORMAL:
        return AvoidancePlan(
            mode, DecisionStatus.CURRENT_STATE_ACCEPTABLE, current, current,
            "Current resonance status is NORMAL; retain speed and heading to avoid unnecessary adjustment.",
            0.0, 0.0,
        )
    improved = [
        item for item in candidates
        if STATUS_RANK[item.resonance_status] > STATUS_RANK[current.resonance_status]
    ]
    if not improved:
        return AvoidancePlan(
            mode, DecisionStatus.NO_SAFE_CANDIDATE, current, None,
            "NO_SAFE_CANDIDATE_WITHIN_SEARCH_LIMITS; PAUSE / RETURN ASSESSMENT recommended.",
            None, None,
        )

    def rank(item: CandidateAssessment) -> tuple[float, float, float, float]:
        speed_fraction = abs(item.speed_change_percent) / 100.0
        heading_fraction = abs(item.heading_change_deg) / 15.0
        return (
            speed_fraction + heading_fraction,
            abs(item.speed_change_percent),
            abs(item.heading_change_deg),
            -STATUS_RANK[item.resonance_status],
        )

    recommended = min(improved, key=rank)
    speed_loss = max(0.0, -recommended.speed_change_percent)
    travel_time_change = (current.SOG_m_s / recommended.SOG_m_s - 1.0) * 100.0
    return AvoidancePlan(
        mode, DecisionStatus.RECOMMENDED, current, recommended,
        (
            f"Improve resonance status from {current.resonance_status.value} to "
            f"{recommended.resonance_status.value}; satisfy status improvement, then minimize adjustment."
        ),
        speed_loss, travel_time_change,
    )


def search_resonance_avoidance(
    *,
    Tp_s: float,
    wave_direction_deg: float,
    current_speed_m_s: float,
    current_heading_deg: float,
    parameters: RollDynamicsParameters,
    thresholds: ResonanceThresholds,
    limits: SearchLimits | None = None,
) -> AvoidanceSearchResult:
    """Compare speed-only, heading-only and joint decision-advice searches.

    This deterministic engineering search is not SAC or reinforcement learning
    and never emits real propulsion or rudder commands.
    """

    limits = limits or SearchLimits()
    for name, value in (
        ("Tp_s", Tp_s), ("wave_direction_deg", wave_direction_deg),
        ("current_speed_m_s", current_speed_m_s), ("current_heading_deg", current_heading_deg),
    ):
        if not isinstance(value, (int, float)) or not isfinite(value):
            raise ValueError(f"{name} must be finite")
    if Tp_s <= 0 or current_speed_m_s <= 0:
        raise ValueError("Tp_s and current_speed_m_s must be positive")
    if not limits.minimum_speed_m_s <= current_speed_m_s <= limits.maximum_speed_m_s:
        raise ValueError("current speed must be within configured search limits")
    if not 0 <= wave_direction_deg < 360 or not 0 <= current_heading_deg < 360:
        raise ValueError("wave direction and heading must be in [0, 360)")

    current = _candidate(
        Tp_s, wave_direction_deg, current_speed_m_s, current_heading_deg,
        current_speed_m_s, current_heading_deg, parameters, thresholds,
    )
    speeds = limits.speeds()
    headings = tuple((current_heading_deg + offset) % 360.0 for offset in limits.heading_offsets_deg)
    speed_candidates = [
        _candidate(
            Tp_s, wave_direction_deg, speed, current_heading_deg,
            current_speed_m_s, current_heading_deg, parameters, thresholds,
        )
        for speed in speeds
    ]
    heading_candidates = [
        _candidate(
            Tp_s, wave_direction_deg, current_speed_m_s, heading,
            current_speed_m_s, current_heading_deg, parameters, thresholds,
        )
        for heading in headings
    ]
    joint_candidates = [
        _candidate(
            Tp_s, wave_direction_deg, speed, (current_heading_deg + offset) % 360.0,
            current_speed_m_s, current_heading_deg, parameters, thresholds,
        )
        for speed in speeds for offset in limits.heading_offsets_deg
        if abs(speed - current_speed_m_s) > 1e-9 and abs(offset) > 1e-9
    ]
    plans = (
        _plan(SearchMode.SPEED_ONLY, current, speed_candidates),
        _plan(SearchMode.HEADING_ONLY, current, heading_candidates),
        _plan(SearchMode.JOINT_SPEED_HEADING, current, joint_candidates),
    )
    successful = [plan for plan in plans if plan.recommended is not None]
    if not successful:
        return AvoidanceSearchResult(
            current, plans[0], plans[1], plans[2], None, None,
            DecisionStatus.NO_SAFE_CANDIDATE,
            "NO_SAFE_CANDIDATE_WITHIN_SEARCH_LIMITS; PAUSE / RETURN ASSESSMENT recommended.",
        )

    def plan_rank(plan: AvoidancePlan) -> tuple[float, float, float, float]:
        item = plan.recommended
        return (
            abs(item.speed_change_percent),
            abs(item.heading_change_deg),
            -STATUS_RANK[item.resonance_status],
            -item.resonance_margin_ratio,
        )

    selected = min(successful, key=plan_rank)
    overall_status = (
        DecisionStatus.CURRENT_STATE_ACCEPTABLE
        if current.resonance_status == ResonanceStatus.NORMAL
        else DecisionStatus.RECOMMENDED
    )
    return AvoidanceSearchResult(
        current, plans[0], plans[1], plans[2], selected.mode, selected.recommended,
        overall_status, selected.decision_reason,
    )
