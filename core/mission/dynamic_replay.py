"""V0.8 dynamic causal mission replay with safety and evidence constraints.

This module executes simulated mission geometry against historical public
environment data.  It contains decision advice only and no actuator commands.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from math import asin, atan2, cos, degrees, radians, sin, sqrt
from typing import Iterable, Sequence

from adapters.marine_data.sampler import MarineEnvironmentSampler, SamplingTolerance
from core.marine import MarineEnvironment
from core.mission.causal_replay import (
    CAUSAL_MODE, ENERGY_STATUS, INTERNAL_BASELINE, MODEL_BASED_REPLAY,
    NOT_OPERATIONAL_PERFORMANCE, REAL_ENVIRONMENT, SIMULATED_INSPECTION,
    SIMULATED_VESSEL, STRESS_TEST_ROUTE, EnvironmentUse, FutureDataLeakageError,
    assess_endurance,
)
from core.mission.decision.models import MissionAction, MissionOutcomeStatus
from core.mission.state import MissionState
from core.models import TelemetryRecord
from core.navigation import relative_wave_angle
from core.resonance.parameters import RollDynamicsParameters
from core.resonance.robust_avoidance import search_robust_roll_avoidance
from core.risk import BaselineRiskEvaluator, RiskLevel, VesselParameters
from core.roll_response import RobustDecisionStatus, scan_roll_response_uncertainty


DYNAMIC_MODE = "DYNAMIC_CAUSAL_MISSION_REPLAY"
DECISION_INTERVAL_S = 1800.0
DECISION_INTERVAL_STATUS = "PRELIMINARY MISSION POLICY PARAMETER"
HOLDING_HEADING_STATUS = "UNKNOWN_WITHOUT_STATION_KEEPING_MODEL"
HOLD_POSITION_UNSAFE = "HOLD_POSITION_UNSAFE"
HOLD_POSITION_ACCEPTABLE = "HOLD_POSITION_ACCEPTABLE_UNDER_HEADING_SENSITIVITY_SCAN"
MANEUVER_STATUS = "SIMULATED MISSION MANEUVER"
ADVISORY_ONLY = "ADVISORY_ONLY"
RISK_BURDEN_STATUS = "PRELIMINARY SAFETY METRIC - NOT ACCIDENT PROBABILITY"
MULTISOURCE_STATUS = "TOLERANCE-CONTROLLED NEAREST SAMPLING - NOT FINAL MULTI-SOURCE FUSION"
REPLAY_INTEGRITY_PASS = "PASS"
BUSINESS_NOT_ESTABLISHED = "NOT_ESTABLISHED"
EARTH_RADIUS_M = 6_371_008.8


class CompletionEvidenceStatus(str, Enum):
    QUALIFIED = "QUALIFIED_WITHIN_PUBLISHED_REFERENCE"
    ENDURANCE_UNVERIFIED = "ENDURANCE_UNVERIFIED"
    INCOMPLETE = "INCOMPLETE"


class DurationReferenceStatus(str, Enum):
    COMPATIBLE = "WITHIN_PUBLISHED_MINIMUM_WORK_TIME_REFERENCE"
    EXCEEDED = "PUBLISHED_MINIMUM_WORK_TIME_REFERENCE_EXCEEDED"
    INCOMPLETE = "INCOMPLETE"


class DynamicAction(str, Enum):
    CONTINUE = "CONTINUE"
    ADJUST_SPEED_HEADING = "ADJUST_SPEED_HEADING"
    REROUTE = "REROUTE_TO_LOWER_RISK_AREA"
    SAFE_HOLD = "SAFE_HOLD"
    RETURN = "RETURN_ASSESSMENT"
    PREDEPARTURE_DELAY = "PREDEPARTURE_DELAY"
    PREDEPARTURE_ABORT = "PREDEPARTURE_ABORT"
    CONTINUE_RETURN = "CONTINUE_RETURN"
    ADJUST_RETURN_SPEED_HEADING = "ADJUST_RETURN_SPEED_HEADING"
    REROUTE_RETURN = "REROUTE_RETURN"
    SAFE_HOLD_RETURN = "SAFE_HOLD_RETURN"
    CONTINUE_RETURN_TO_BASE = "CONTINUE_RETURN_TO_BASE"


class DynamicPolicy(str, Enum):
    BASELINE_CONSERVATIVE = "BASELINE_CONSERVATIVE"
    LOCAL_ADJUST_ONLY = "LOCAL_ADJUST_ONLY"
    HANHAI_MISSION_CONTINUITY = "HANHAI_MISSION_CONTINUITY"


POLICY_DEFINITIONS = {
    DynamicPolicy.BASELINE_CONSERVATIVE: (
        "INTERNAL SIMULATION BASELINE: dynamic residual high risk after departure -> return"
    ),
    DynamicPolicy.LOCAL_ADJUST_ONLY: (
        "INTERNAL SIMULATION BASELINE: dynamic executed local maneuver; failure -> return"
    ),
    DynamicPolicy.HANHAI_MISSION_CONTINUITY: (
        "INTERNAL SIMULATION BASELINE: executed adjust -> reroute -> safe hold -> return last"
    ),
}


@dataclass(frozen=True, slots=True)
class DynamicReplayConfig:
    decision_interval_s: float = DECISION_INTERVAL_S
    maneuver_duration_s: float = 600.0
    safe_hold_duration_s: float = DECISION_INTERVAL_S
    heading_sensitivity_deg: tuple[float, ...] = tuple(float(value) for value in range(0, 360, 45))
    maximum_reroute_time_penalty_percent: float = 35.0
    maximum_acceptable_high_risk_ratio: float = 0.0
    status: str = DECISION_INTERVAL_STATUS

    def __post_init__(self) -> None:
        if self.decision_interval_s <= 0 or self.maneuver_duration_s <= 0 or self.safe_hold_duration_s <= 0:
            raise ValueError("dynamic replay intervals must be positive")
        if self.status != DECISION_INTERVAL_STATUS:
            raise ValueError("decision interval must retain preliminary policy label")


@dataclass(frozen=True, slots=True)
class DynamicMissionGeometry:
    geometry_id: str
    start: tuple[float, float]
    task_point: tuple[float, float]
    source_status: str


@dataclass(frozen=True, slots=True)
class DynamicMissionCase:
    case_id: str
    departure_time: datetime
    geometry: DynamicMissionGeometry
    SOG_m_s: float = 1.8
    inspection_service_time_s: float = 1800.0
    selection_rule: str = "PREDECLARED HISTORICAL REPLAY SCENARIO"
    initial_phase: MissionState = MissionState.PRE_DEPARTURE
    initial_position: tuple[float, float] | None = None


@dataclass(frozen=True, slots=True)
class HoldFeasibilityAssessment:
    status: str
    holding_heading_status: str
    heading_sensitivity_deg: tuple[float, ...]
    grid_q90_proxy_by_heading: tuple[float, ...]
    robust_status_by_heading: tuple[str, ...]
    worst_case_grid_q90_proxy: float
    hold_allowed: bool
    parameter_source: str
    parameter_status: str


@dataclass(frozen=True, slots=True)
class SnapshotRouteEvaluation:
    route_id: str
    waypoints: tuple[tuple[float, float], ...]
    snapshot_integrated_risk_burden: float
    snapshot_high_risk_fraction: float
    distance_m: float
    distance_penalty_percent: float
    estimated_travel_time_s: float
    minimum_depth_m: float | None
    depth_availability_fraction: float
    mean_current_speed_m_s: float | None
    acceptable: bool
    status: str = "CURRENT-SNAPSHOT PERSISTENCE SCREEN - NOT A WEATHER FORECAST"


@dataclass(frozen=True, slots=True)
class SnapshotRouteScreen:
    screen_id: str
    decision_timestamp: datetime
    destination_role: str
    candidates: tuple[SnapshotRouteEvaluation, ...]
    selected_route_id: str | None
    future_actual_environment_used: bool = False
    status: str = "CAUSAL_CURRENT_SNAPSHOT_ROUTE_SCREEN"


@dataclass(frozen=True, slots=True)
class CandidateRollout:
    rollout_id: str
    decision_timestamp: datetime
    candidate_SOG_m_s: float
    candidate_HDG_deg: float
    horizon_s: float
    risk_burden: float
    high_risk_fraction: float
    goal_progress_m: float
    heading_change_deg: float
    speed_change_percent: float
    extra_distance_m: float
    acceptable: bool
    status: str = "CURRENT-SNAPSHOT PERSISTENCE ASSUMPTION - NOT A WEATHER FORECAST"
    future_actual_environment_used: bool = False


@dataclass(frozen=True, slots=True)
class DynamicMissionState:
    timestamp: datetime
    latitude: float
    longitude: float
    mission_state: MissionState
    SOG_m_s: float
    HDG_deg: float
    Hs_m: float | None
    Tp_s: float | None
    wave_direction_deg: float | None
    wind_speed_m_s: float | None
    wind_direction_deg: float | None
    surface_current_speed_m_s: float | None
    surface_current_direction_deg: float | None
    water_depth_m: float | None
    single_vessel_risk_score: float
    single_vessel_risk_level: str
    risk_components: dict[str, float]
    roll_response_grid_q90_proxy: float | None
    robust_status: str
    environment_provenance_by_field: dict
    environment_source: str = REAL_ENVIRONMENT
    vessel_state_source: str = SIMULATED_VESSEL
    risk_baseline_status: str = "PRELIMINARY / NEEDS CALIBRATION"
    multi_source_sampling_status: str = MULTISOURCE_STATUS


@dataclass(frozen=True, slots=True)
class DynamicDecision:
    timestamp: datetime
    mission_state: MissionState
    action: DynamicAction
    reason: str
    state: DynamicMissionState
    recommended_SOG_m_s: float | None = None
    recommended_HDG_deg: float | None = None
    execution_status: str | None = None
    hold_feasibility: HoldFeasibilityAssessment | None = None
    route_screen_id: str | None = None
    rollout_id: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutedSegment:
    segment_id: str
    segment_type: str
    start_time: datetime
    end_time: datetime
    start: tuple[float, float]
    end: tuple[float, float]
    executed_SOG_m_s: float
    executed_HDG_deg: float
    source_status: str

    @property
    def distance_m(self) -> float:
        return _distance(self.start, self.end)


@dataclass(frozen=True, slots=True)
class DynamicRiskSample:
    timestamp: datetime
    latitude: float
    longitude: float
    duration_s: float
    robust_status: str
    single_vessel_risk_level: str
    roll_response_proxy: float | None
    risk_score: float
    segment_id: str | None = None
    actual_SOG_m_s: float | None = None
    actual_HDG_deg: float | None = None
    actual_mission_state: MissionState | None = None
    state_timestamp: datetime | None = None
    state_latitude: float | None = None
    state_longitude: float | None = None


@dataclass(frozen=True, slots=True)
class DynamicRiskExposure:
    high_risk_exposure_steps: int
    high_risk_exposure_time_s: float
    moderate_risk_exposure_time_s: float
    total_evaluated_time_s: float
    high_risk_exposure_ratio: float
    maximum_continuous_high_risk_time_s: float
    risk_burden_level_seconds: float
    risk_burden_status: str = RISK_BURDEN_STATUS
    calculation_status: str = "COMPUTED_FROM_DYNAMIC_SPATIOTEMPORAL_SAMPLES"


def validate_segment_sample_invariants(
    segments: Sequence[ExecutedSegment], samples: Sequence[DynamicRiskSample],
) -> None:
    """Fail fast when a sample carries stale state from before an executed segment."""
    if len(segments) != len(samples):
        raise ValueError("each executed segment must have exactly one duration-weighted sample")
    for segment, sample in zip(segments, samples, strict=True):
        checks = (
            sample.segment_id == segment.segment_id,
            sample.timestamp == segment.start_time,
            sample.state_timestamp == segment.start_time,
            abs(sample.latitude - segment.start[0]) < 1e-10,
            abs(sample.longitude - segment.start[1]) < 1e-10,
            sample.actual_SOG_m_s == segment.executed_SOG_m_s,
            sample.actual_HDG_deg == segment.executed_HDG_deg,
            abs(sample.duration_s - (segment.end_time - segment.start_time).total_seconds()) < 1e-9,
        )
        if not all(checks):
            raise ValueError(f"stale or inconsistent state for segment {segment.segment_id}")


@dataclass(frozen=True, slots=True)
class DynamicMissionResult:
    case_id: str
    geometry_id: str
    policy_name: str
    policy_definition: str
    outcome_status: MissionOutcomeStatus
    final_mission_state: MissionState
    technical_completed: bool
    evidence_qualified_completion: bool
    completion_evidence_status: CompletionEvidenceStatus
    mission_elapsed_time_s: float
    nominal_mission_time_s: float
    time_penalty_s: float
    endurance: dict
    unplanned_return: bool
    predeparture_delay: bool
    predeparture_abort: bool
    hold_used_count: int
    reroute_used_count: int
    actions: tuple[DynamicDecision, ...]
    executed_segments: tuple[ExecutedSegment, ...]
    exposure: DynamicRiskExposure
    returned_to_base: bool
    duration_reference_compatible_completion: bool = False
    duration_reference_status: DurationReferenceStatus = DurationReferenceStatus.INCOMPLETE
    energy_feasibility_status: str = "NOT VERIFIED ENERGY FEASIBILITY"
    signed_mission_time_delta_s: float = 0.0
    positive_time_penalty_s: float = 0.0
    time_saving_s: float = 0.0
    extra_distance_m: float = 0.0
    maneuver_distance_m: float = 0.0
    maneuver_count: int = 0
    affected_by_decision: bool = False
    route_screens: tuple[SnapshotRouteScreen, ...] = ()
    candidate_rollouts: tuple[CandidateRollout, ...] = ()
    risk_samples: tuple[DynamicRiskSample, ...] = ()
    environment_source: str = REAL_ENVIRONMENT
    vessel_state_source: str = SIMULATED_VESSEL
    parameter_source: str = "ENGINEERING_ESTIMATE"
    parameter_status: str = "NOT_EXPERIMENTALLY_CALIBRATED"
    replay_mode: str = DYNAMIC_MODE
    result_status: str = MODEL_BASED_REPLAY
    performance_status: str = NOT_OPERATIONAL_PERFORMANCE
    control_status: str = "DECISION ADVICE ONLY - REAL VESSEL CONTROL DISABLED"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TimePenaltyDistribution:
    average_s: float
    median_s: float
    p90_s: float
    p95_s: float
    maximum_s: float
    average_among_affected_missions_s: float
    affected_mission_count: int


@dataclass(frozen=True, slots=True)
class DynamicPolicySummary:
    policy_name: str
    policy_definition: str
    denominator_N: int
    technical_completed_count: int
    technical_completion_rate: float
    evidence_qualified_completed_count: int
    evidence_qualified_completion_rate: float
    unplanned_return_count: int
    unplanned_return_rate: float
    predeparture_delay_count: int
    predeparture_abort_count: int
    hold_count: int
    reroute_count: int
    high_risk_exposure_time_s: float
    high_risk_exposure_ratio: float
    maximum_continuous_high_risk_time_s: float
    risk_burden_level_seconds: float
    time_penalty: TimePenaltyDistribution
    observation_interval_s: float = DECISION_INTERVAL_S
    action_constraint_status: str = "COMMON SPEED/HEADING CONSTRAINTS ACROSS ALL POLICIES"
    baseline_status: str = INTERNAL_BASELINE
    result_status: str = MODEL_BASED_REPLAY
    performance_status: str = NOT_OPERATIONAL_PERFORMANCE
    duration_reference_compatible_completed_count: int = 0
    duration_reference_compatible_completion_rate: float = 0.0
    maneuver_used_count: int = 0
    safe_hold_used_count: int = 0
    signed_mission_time_delta_s: float = 0.0
    time_saving_s: float = 0.0
    extra_distance_m: float = 0.0
    maneuver_distance_m: float = 0.0
    maneuver_count: int = 0
    affected_by_decision_count: int = 0


@dataclass(frozen=True, slots=True)
class MissionSavedAssessment:
    scenario_id: str
    saved: bool
    rejection_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ValueAssessment:
    replay_integrity_gate: str
    business_value_status: str
    safety_comparison_status: str
    mission_saved_count: int
    explanation: str


BLOCKER_CATEGORIES = (
    "BASELINE_ALREADY_COMPLETED", "PREDEPARTURE_DELAY", "NO_SAFE_LOCAL_CANDIDATE",
    "NO_SAFE_REROUTE", "HOLD_POSITION_UNSAFE", "ENDURANCE_REFERENCE_EXCEEDED",
    "HIGH_RISK_EXPOSURE_INCREASE", "RISK_BURDEN_INCREASE", "MISSION_NOT_COMPLETED", "OTHER",
)


@dataclass(frozen=True, slots=True)
class MissionValueBlockerReport:
    total_scenarios: int
    blocker_counts: dict[str, int]
    top_five: tuple[tuple[str, int], ...]
    assignment_rule: str = "ONE PRIMARY BLOCKER PER SCENARIO; COUNTS SUM TO COHORT N"
    status: str = "MISSION_VALUE_BLOCKER_REPORT"


@dataclass(frozen=True, slots=True)
class DecisionRelevantSelection:
    scenario_id: str
    selected: bool
    initial_residual_high: bool
    direct_route_snapshot_high_risk: bool
    selection_rule: str = (
        "POLICY-INDEPENDENT: FIXED DIRECT ROUTE + FIXED NOMINAL VESSEL STATE + "
        "CURRENT PUBLIC ENVIRONMENT BEFORE POLICY REPLAY"
    )


def _percentile(sorted_values: Sequence[float], quantile: float) -> float:
    if not sorted_values:
        return 0.0
    position = (len(sorted_values) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction


def summarize_dynamic_results(results: Sequence[DynamicMissionResult]) -> DynamicPolicySummary:
    if not results:
        raise ValueError("dynamic policy summary requires results")
    n = len(results)
    penalties = sorted(0.0 if item.time_penalty_s < 1.0 else item.time_penalty_s for item in results)
    affected = [value for value in penalties if value >= 1.0]
    total_exposure = sum(item.exposure.total_evaluated_time_s for item in results)
    high_exposure = sum(item.exposure.high_risk_exposure_time_s for item in results)
    technical = sum(item.technical_completed for item in results)
    qualified = sum(item.evidence_qualified_completion for item in results)
    duration_compatible = sum(item.duration_reference_compatible_completion for item in results)
    returns = sum(item.unplanned_return for item in results)
    return DynamicPolicySummary(
        results[0].policy_name, results[0].policy_definition, n, technical, technical / n,
        qualified, qualified / n, returns, returns / n,
        sum(item.predeparture_delay for item in results),
        sum(item.predeparture_abort for item in results),
        sum(item.hold_used_count for item in results),
        sum(item.reroute_used_count for item in results), high_exposure,
        high_exposure / total_exposure if total_exposure else 0.0,
        max(item.exposure.maximum_continuous_high_risk_time_s for item in results),
        sum(item.exposure.risk_burden_level_seconds for item in results),
        TimePenaltyDistribution(
            sum(penalties) / n, _percentile(penalties, .5), _percentile(penalties, .9),
            _percentile(penalties, .95), penalties[-1],
            sum(affected) / len(affected) if affected else 0.0, len(affected),
        ),
        duration_reference_compatible_completed_count=duration_compatible,
        duration_reference_compatible_completion_rate=duration_compatible / n,
        maneuver_used_count=sum(item.maneuver_count > 0 for item in results),
        safe_hold_used_count=sum(item.hold_used_count > 0 for item in results),
        signed_mission_time_delta_s=sum(item.signed_mission_time_delta_s for item in results),
        time_saving_s=sum(item.time_saving_s for item in results),
        extra_distance_m=sum(item.extra_distance_m for item in results),
        maneuver_distance_m=sum(item.maneuver_distance_m for item in results),
        maneuver_count=sum(item.maneuver_count for item in results),
        affected_by_decision_count=sum(item.affected_by_decision for item in results),
    )


def assess_mission_saved(
    baseline: DynamicMissionResult, hanhai: DynamicMissionResult,
    *, future_action_leakage_count: int = 0,
    maximum_exposure_increase_s: float = 1e-9,
) -> MissionSavedAssessment:
    reasons: list[str] = []
    if baseline.case_id != hanhai.case_id:
        reasons.append("SCENARIO_MISMATCH")
    if baseline.technical_completed:
        reasons.append("BASELINE_ALREADY_COMPLETED")
    if not hanhai.technical_completed:
        reasons.append("HANHAI_NOT_TECHNICALLY_COMPLETED")
    if not hanhai.duration_reference_compatible_completion:
        reasons.append("ENDURANCE_REFERENCE_EXCEEDED")
    if hanhai.completion_evidence_status is CompletionEvidenceStatus.ENDURANCE_UNVERIFIED:
        reasons.append("ENDURANCE_FEASIBILITY_UNVERIFIED")
    if (
        hanhai.exposure.high_risk_exposure_time_s
        > baseline.exposure.high_risk_exposure_time_s + maximum_exposure_increase_s
    ):
        reasons.append("UNACCEPTABLE_HIGH_RISK_EXPOSURE_INCREASE")
    if hanhai.exposure.high_risk_exposure_ratio > baseline.exposure.high_risk_exposure_ratio + 1e-12:
        reasons.append("UNACCEPTABLE_HIGH_RISK_EXPOSURE_RATIO_INCREASE")
    if (
        hanhai.exposure.maximum_continuous_high_risk_time_s
        > baseline.exposure.maximum_continuous_high_risk_time_s + maximum_exposure_increase_s
    ):
        reasons.append("UNACCEPTABLE_CONTINUOUS_HIGH_RISK_INCREASE")
    if (
        hanhai.exposure.risk_burden_level_seconds
        > baseline.exposure.risk_burden_level_seconds + maximum_exposure_increase_s
    ):
        reasons.append("UNACCEPTABLE_PRELIMINARY_RISK_BURDEN_INCREASE")
    if future_action_leakage_count:
        reasons.append("FUTURE_DATA_LEAKAGE")
    return MissionSavedAssessment(hanhai.case_id, not reasons, tuple(reasons))


def assess_value_status(
    *, baseline: DynamicPolicySummary, hanhai: DynamicPolicySummary,
    saved: Sequence[MissionSavedAssessment], future_action_leakage_count: int,
    all_timeline_times_computed: bool = True,
) -> ValueAssessment:
    integrity = (
        REPLAY_INTEGRITY_PASS
        if future_action_leakage_count == 0 and all_timeline_times_computed else "FAIL"
    )
    completion_gain = hanhai.evidence_qualified_completed_count > baseline.evidence_qualified_completed_count
    safety_worse = (
        hanhai.high_risk_exposure_time_s > baseline.high_risk_exposure_time_s + 1e-9
        or hanhai.maximum_continuous_high_risk_time_s
        > baseline.maximum_continuous_high_risk_time_s + 1e-9
        or hanhai.risk_burden_level_seconds > baseline.risk_burden_level_seconds + 1e-9
    )
    saved_count = sum(item.saved for item in saved)
    if completion_gain and safety_worse:
        comparison = "COMPLETION_GAIN_WITH_SAFETY_TRADEOFF"
        status = BUSINESS_NOT_ESTABLISHED
    elif integrity != REPLAY_INTEGRITY_PASS or saved_count == 0:
        comparison = "NO_EVIDENCE_QUALIFIED_NON_INFERIOR_MISSION_GAIN"
        status = BUSINESS_NOT_ESTABLISHED
    else:
        comparison = "SAFETY_NON_INFERIOR_DEVELOPMENT_EVIDENCE"
        status = "DEVELOPMENT_EVIDENCE"
    return ValueAssessment(
        integrity, status, comparison, saved_count,
        "Development replay status only; not empirical business value or operational performance.",
    )


def build_mission_value_blocker_report(
    baseline: Sequence[DynamicMissionResult], hanhai: Sequence[DynamicMissionResult],
    saved: Sequence[MissionSavedAssessment],
) -> MissionValueBlockerReport:
    """Assign exactly one diagnostic blocker to each replay scenario."""
    if not (len(baseline) == len(hanhai) == len(saved)):
        raise ValueError("blocker report inputs must have equal scenario counts")
    counts = {category: 0 for category in BLOCKER_CATEGORIES}
    for base, candidate, assessment in zip(baseline, hanhai, saved, strict=True):
        if base.case_id != candidate.case_id or candidate.case_id != assessment.scenario_id:
            blocker = "OTHER"
        elif assessment.saved:
            blocker = "OTHER"
        elif base.technical_completed:
            blocker = "BASELINE_ALREADY_COMPLETED"
        elif candidate.predeparture_delay:
            blocker = "PREDEPARTURE_DELAY"
        elif not candidate.technical_completed:
            reasons = " ".join(decision.reason for decision in candidate.actions)
            if HOLD_POSITION_UNSAFE in reasons and "no safe" in reasons.lower():
                blocker = "NO_SAFE_REROUTE"
            elif "No executable acceptable local candidate" in reasons:
                blocker = "NO_SAFE_LOCAL_CANDIDATE"
            elif HOLD_POSITION_UNSAFE in reasons:
                blocker = "HOLD_POSITION_UNSAFE"
            else:
                blocker = "MISSION_NOT_COMPLETED"
        elif not candidate.duration_reference_compatible_completion:
            blocker = "ENDURANCE_REFERENCE_EXCEEDED"
        elif candidate.exposure.high_risk_exposure_time_s > base.exposure.high_risk_exposure_time_s + 1e-9:
            blocker = "HIGH_RISK_EXPOSURE_INCREASE"
        elif candidate.exposure.risk_burden_level_seconds > base.exposure.risk_burden_level_seconds + 1e-9:
            blocker = "RISK_BURDEN_INCREASE"
        else:
            blocker = "OTHER"
        counts[blocker] += 1
    if sum(counts.values()) != len(baseline):
        raise AssertionError("blocker counts must equal scenario count")
    ordered = tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5])
    return MissionValueBlockerReport(len(baseline), counts, ordered)


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lat2 = radians(a[0]), radians(b[0])
    dlat, dlon = lat2 - lat1, radians(b[1] - a[1])
    value = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(value))


def _bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lat2 = radians(a[0]), radians(b[0])
    dlon = radians(b[1] - a[1])
    return (degrees(atan2(
        sin(dlon) * cos(lat2),
        cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(dlon),
    )) + 360.0) % 360.0


def _destination(start: tuple[float, float], heading_deg: float, distance_m: float) -> tuple[float, float]:
    angular = distance_m / EARTH_RADIUS_M
    lat1, lon1, heading = radians(start[0]), radians(start[1]), radians(heading_deg)
    lat2 = asin(sin(lat1) * cos(angular) + cos(lat1) * sin(angular) * cos(heading))
    lon2 = lon1 + atan2(
        sin(heading) * sin(angular) * cos(lat1),
        cos(angular) - sin(lat1) * sin(lat2),
    )
    return degrees(lat2), ((degrees(lon2) + 180.0) % 360.0) - 180.0


def _interpolate(start: tuple[float, float], end: tuple[float, float], fraction: float) -> tuple[float, float]:
    return start[0] + (end[0] - start[0]) * fraction, start[1] + (end[1] - start[1]) * fraction


class CausalMultiSourceStore:
    """Indexed causal wrapper that delegates field assembly to the existing sampler."""

    def __init__(self, records: Sequence[MarineEnvironment], tolerance: SamplingTolerance | None = None) -> None:
        if not records:
            raise ValueError("multi-source store requires records")
        self.records = tuple(records)
        self.tolerance = tolerance or SamplingTolerance(max_time_offset_seconds=90_000, max_spatial_distance_m=30_000)
        self.access_log: list[dict] = []
        by_source_time: dict[str, dict[datetime, list[MarineEnvironment]]] = {}
        for record in self.records:
            source_family = record.source.split(":", 1)[0]
            by_source_time.setdefault(source_family, {}).setdefault(record.timestamp, []).append(record)
        self._source_times = {
            source: tuple(sorted(by_time)) for source, by_time in by_source_time.items()
        }
        self._records_by_source_time = {
            source: {time: tuple(values) for time, values in by_time.items()}
            for source, by_time in by_source_time.items()
        }
        self._spatial_indexes = {
            source: {
                time: {(round(item.latitude, 8), round(item.longitude, 8)): item for item in values}
                for time, values in by_time.items()
            }
            for source, by_time in self._records_by_source_time.items()
        }
        self._grid_axes = {}
        for source, by_time in self._records_by_source_time.items():
            first = next(iter(by_time.values()))
            self._grid_axes[source] = (
                tuple(sorted({item.latitude for item in first})),
                tuple(sorted({item.longitude for item in first})),
            )
        self._cache: dict[tuple, MarineEnvironment] = {}

    def _nearest_record(
        self, source: str, selected_time: datetime, latitude: float, longitude: float,
    ) -> MarineEnvironment | None:
        spatial = self._records_by_source_time[source][selected_time]
        if not spatial:
            return None
        latitudes, longitudes = self._grid_axes[source]
        nearest_lat = min(latitudes, key=lambda value: abs(value - latitude))
        nearest_lon = min(longitudes, key=lambda value: abs(value - longitude))
        indexed = self._spatial_indexes[source][selected_time].get(
            (round(nearest_lat, 8), round(nearest_lon, 8))
        )
        return indexed or min(spatial, key=lambda item: (
            (item.latitude - latitude) ** 2 + (item.longitude - longitude) ** 2
        ))

    def sample(
        self, *, timestamp: datetime, latitude: float, longitude: float,
        decision_timestamp: datetime, purpose: EnvironmentUse,
    ) -> MarineEnvironment:
        if purpose is EnvironmentUse.ACTION_SELECTION and timestamp > decision_timestamp:
            self.access_log.append({"accepted": False, "purpose": purpose.value, "reason": "FUTURE_FORBIDDEN"})
            raise FutureDataLeakageError("future environment is forbidden for action selection")
        key = (timestamp, round(latitude, 5), round(longitude, 5), decision_timestamp, purpose)
        if key in self._cache:
            return self._cache[key]
        candidates: list[MarineEnvironment] = []
        for source, times in self._source_times.items():
            if purpose is EnvironmentUse.ACTION_SELECTION:
                index = bisect_right(times, decision_timestamp) - 1
                if index < 0:
                    continue
                selected_time = times[index]
            else:
                selected_time = min(times, key=lambda item: abs((item - timestamp).total_seconds()))
            nearest = self._nearest_record(source, selected_time, latitude, longitude)
            if nearest is not None:
                candidates.append(nearest)
        sampled = MarineEnvironmentSampler(candidates, self.tolerance).sample(timestamp, latitude, longitude)
        self.access_log.append({
            "accepted": True, "purpose": purpose.value, "requested_timestamp": timestamp,
            "decision_timestamp": decision_timestamp,
        })
        self._cache[key] = sampled
        return sampled

    def sample_current_snapshot(
        self, *, snapshot_timestamp: datetime, latitude: float, longitude: float,
        decision_timestamp: datetime,
    ) -> MarineEnvironment:
        """Sample a spatial field available at decision time; never future truth."""
        if snapshot_timestamp > decision_timestamp:
            self.access_log.append({
                "accepted": False, "purpose": EnvironmentUse.ACTION_SELECTION.value,
                "reason": "FUTURE_FORBIDDEN_IN_CURRENT_SNAPSHOT_SCREEN",
            })
            raise FutureDataLeakageError("snapshot route screen cannot access future environment")
        candidates: list[MarineEnvironment] = []
        for source, times in self._source_times.items():
            index = bisect_right(times, decision_timestamp) - 1
            if index >= 0:
                nearest = self._nearest_record(source, times[index], latitude, longitude)
                if nearest is not None:
                    candidates.append(nearest)
        sampled = MarineEnvironmentSampler(candidates, self.tolerance).sample(
            snapshot_timestamp, latitude, longitude,
        )
        self.access_log.append({
            "accepted": True, "purpose": EnvironmentUse.ACTION_SELECTION.value,
            "requested_timestamp": snapshot_timestamp, "decision_timestamp": decision_timestamp,
            "screen_status": "CURRENT-SNAPSHOT PERSISTENCE SCREEN - NOT A WEATHER FORECAST",
        })
        return sampled

    @property
    def future_action_access_count(self) -> int:
        return sum(not item["accepted"] and item["purpose"] == EnvironmentUse.ACTION_SELECTION.value for item in self.access_log)


def assess_hold_feasibility(
    environment: MarineEnvironment, parameters: RollDynamicsParameters,
    config: DynamicReplayConfig | None = None,
) -> HoldFeasibilityAssessment:
    config = config or DynamicReplayConfig()
    if None in (environment.Hs, environment.Tp, environment.wave_direction):
        return HoldFeasibilityAssessment(
            "DATA_UNAVAILABLE", HOLDING_HEADING_STATUS, config.heading_sensitivity_deg,
            (), (), float("inf"), False, parameters.parameter_source.value, parameters.parameter_status,
        )
    proxies, statuses = [], []
    for heading in config.heading_sensitivity_deg:
        grid = scan_roll_response_uncertainty(
            Hs_m=environment.Hs, Tp_s=environment.Tp, vessel_speed_m_s=0.0,
            relative_wave_angle_deg=relative_wave_angle(environment.wave_direction, heading),
            parameters=parameters,
        )
        proxies.append(grid.grid_q90_roll_response_proxy)
        statuses.append(grid.robust_decision_status.value)
    allowed = not any(value == RobustDecisionStatus.RESIDUAL_HIGH_RISK.value for value in statuses)
    return HoldFeasibilityAssessment(
        HOLD_POSITION_ACCEPTABLE if allowed else HOLD_POSITION_UNSAFE,
        HOLDING_HEADING_STATUS, config.heading_sensitivity_deg, tuple(proxies), tuple(statuses),
        max(proxies), allowed, parameters.parameter_source.value, parameters.parameter_status,
    )


def compute_dynamic_exposure(samples: Iterable[DynamicRiskSample]) -> DynamicRiskExposure:
    values = tuple(samples)
    high_time = 0.0
    moderate_time = 0.0
    current_high = 0.0
    max_high = 0.0
    burden = 0.0
    high_steps = 0
    for item in values:
        robust_high = item.robust_status == RobustDecisionStatus.RESIDUAL_HIGH_RISK.value
        risk_high = item.single_vessel_risk_level == RiskLevel.HIGH.value
        robust_moderate = item.robust_status == RobustDecisionStatus.ROBUST_MODERATE.value
        risk_moderate = item.single_vessel_risk_level == RiskLevel.MEDIUM.value
        if robust_high or risk_high:
            high_time += item.duration_s
            current_high += item.duration_s
            high_steps += 1
            level = 3.0
        else:
            max_high = max(max_high, current_high)
            current_high = 0.0
            if robust_moderate or risk_moderate:
                moderate_time += item.duration_s
                level = 2.0
            else:
                level = 1.0
        burden += level * item.duration_s
    max_high = max(max_high, current_high)
    total = sum(item.duration_s for item in values)
    return DynamicRiskExposure(
        high_steps, high_time, moderate_time, total, high_time / total if total else 0.0,
        max_high, burden,
    )


class DynamicMissionEngine:
    """Thirty-minute receding-horizon replay for one simulated scenario."""

    def __init__(
        self, store: CausalMultiSourceStore, parameters: RollDynamicsParameters,
        config: DynamicReplayConfig | None = None,
    ) -> None:
        self.store = store
        self.parameters = parameters
        self.config = config or DynamicReplayConfig()
        self.risk = BaselineRiskEvaluator()
        self.vessel = VesselParameters(
            model="ZLUSV-200", length_overall_m=2.02, beam_m=0.88,
            draft_m=0.25, hull_mass_approx_kg=50.0,
            full_load_displacement_min_kg=100.0,
        )
        self._state_cache: dict[tuple, DynamicMissionState] = {}
        self._search_cache: dict[tuple, object] = {}
        self._route_screens: dict[str, SnapshotRouteScreen] = {}
        self._rollouts: dict[str, CandidateRollout] = {}

    def select_decision_relevant(self, case: DynamicMissionCase) -> DecisionRelevantSelection:
        """Pre-policy cohort screen; no policy result or mission-saved outcome is accepted."""
        start, task = case.geometry.start, case.geometry.task_point
        heading = _bearing(start, task)
        state = self._state(
            case.departure_time, start, case.initial_phase, case.SOG_m_s, heading,
        )
        screen = self._route_screen(
            at=case.departure_time, position=start, destination=task,
            phase=case.initial_phase, speed=case.SOG_m_s, destination_role="TASK_POINT",
        )
        direct = next(candidate for candidate in screen.candidates if candidate.route_id == "DIRECT")
        initial_high = self._unsafe(state)
        route_high = direct.snapshot_high_risk_fraction > 0.0
        return DecisionRelevantSelection(case.case_id, initial_high or route_high, initial_high, route_high)

    def _state(
        self, at: datetime, position: tuple[float, float], phase: MissionState,
        speed: float, heading: float,
    ) -> DynamicMissionState:
        environment = self.store.sample(
            timestamp=at, latitude=position[0], longitude=position[1],
            decision_timestamp=at, purpose=EnvironmentUse.ACTION_SELECTION,
        )
        return self._state_from_environment(at, position, phase, speed, heading, environment)

    def _state_from_environment(
        self, at: datetime, position: tuple[float, float], phase: MissionState,
        speed: float, heading: float, environment: MarineEnvironment,
    ) -> DynamicMissionState:
        key = (
            environment.timestamp, round(position[0], 4), round(position[1], 4),
            phase, round(speed, 3), round(heading, 2), environment.Hs, environment.Tp,
            environment.wave_direction, environment.wind_speed, environment.wind_direction,
            environment.surface_current_speed,
        )
        cached = self._state_cache.get(key)
        if cached is not None:
            return cached
        record = TelemetryRecord(
            timestamp=at, latitude=position[0], longitude=position[1],
            Hs=environment.Hs, Tp=environment.Tp, wave_direction=environment.wave_direction,
            wind_speed=environment.wind_speed, wind_direction=environment.wind_direction,
            surface_current_speed=environment.surface_current_speed,
            surface_current_direction=environment.surface_current_direction,
            SOG=speed, COG=heading, HDG=heading, roll=None, pitch=None, roll_rate=None,
            battery=None, mission_state=phase, data_label=SIMULATED_VESSEL,
        )
        risk = self.risk.evaluate(record, self.vessel)
        proxy = None
        robust = RobustDecisionStatus.UNAVAILABLE.value
        if None not in (environment.Hs, environment.Tp, environment.wave_direction):
            grid = scan_roll_response_uncertainty(
                Hs_m=environment.Hs, Tp_s=environment.Tp, vessel_speed_m_s=speed,
                relative_wave_angle_deg=relative_wave_angle(environment.wave_direction, heading),
                parameters=self.parameters,
            )
            proxy = grid.grid_q90_roll_response_proxy
            robust = grid.robust_decision_status.value
        state = DynamicMissionState(
            at, position[0], position[1], phase, speed, heading,
            environment.Hs, environment.Tp, environment.wave_direction,
            environment.wind_speed, environment.wind_direction,
            environment.surface_current_speed, environment.surface_current_direction,
            environment.water_depth, risk.risk_score, risk.risk_level.value,
            risk.risk_components, proxy, robust,
            {name: asdict(value) for name, value in environment.provenance_by_field.items()},
        )
        self._state_cache[key] = state
        return state

    def _snapshot_state(
        self, decision_time: datetime, position: tuple[float, float], phase: MissionState,
        speed: float, heading: float,
    ) -> DynamicMissionState:
        environment = self.store.sample_current_snapshot(
            snapshot_timestamp=decision_time, latitude=position[0], longitude=position[1],
            decision_timestamp=decision_time,
        )
        return self._state_from_environment(
            decision_time, position, phase, speed, heading, environment,
        )

    def _search(self, state: DynamicMissionState):
        if None in (state.Hs_m, state.Tp_s, state.wave_direction_deg):
            return None
        key = (
            state.Hs_m, state.Tp_s, state.wave_direction_deg,
            state.SOG_m_s, state.HDG_deg, self.parameters,
        )
        value = self._search_cache.get(key)
        if value is None:
            value = search_robust_roll_avoidance(
                Hs_m=state.Hs_m, Tp_s=state.Tp_s,
                wave_direction_deg=state.wave_direction_deg,
                current_speed_m_s=state.SOG_m_s,
                current_heading_deg=state.HDG_deg,
                parameters=self.parameters,
            )
            self._search_cache[key] = value
        return value

    @staticmethod
    def _burden_level(state: DynamicMissionState) -> float:
        if (
            state.robust_status == RobustDecisionStatus.RESIDUAL_HIGH_RISK.value
            or state.single_vessel_risk_level == RiskLevel.HIGH.value
        ):
            return 3.0
        if (
            state.robust_status == RobustDecisionStatus.ROBUST_MODERATE.value
            or state.single_vessel_risk_level == RiskLevel.MEDIUM.value
        ):
            return 2.0
        return 1.0

    def _route_screen(
        self, *, at: datetime, position: tuple[float, float], destination: tuple[float, float],
        phase: MissionState, speed: float, destination_role: str,
    ) -> SnapshotRouteScreen:
        direct_distance = _distance(position, destination)
        base_heading = _bearing(position, destination)
        offset_distance = min(2_000.0, direct_distance * 0.35)
        midpoint = _interpolate(position, destination, .5)
        definitions = (
            ("DIRECT", (position, destination)),
            ("DETOUR_LEFT", (position, _destination(midpoint, base_heading - 90.0, offset_distance), destination)),
            ("DETOUR_RIGHT", (position, _destination(midpoint, base_heading + 90.0, offset_distance), destination)),
        )
        evaluations: list[SnapshotRouteEvaluation] = []
        for route_id, waypoints in definitions:
            route_distance = sum(_distance(a, b) for a, b in zip(waypoints, waypoints[1:]))
            penalty = (route_distance / direct_distance - 1.0) * 100.0 if direct_distance else 0.0
            states: list[DynamicMissionState] = []
            currents: list[float] = []
            depths: list[float] = []
            for start, end in zip(waypoints, waypoints[1:]):
                heading = _bearing(start, end)
                for fraction in (0.0, .25, .5, .75, 1.0):
                    point = _interpolate(start, end, fraction)
                    state = self._snapshot_state(at, point, phase, speed, heading)
                    states.append(state)
                    if state.surface_current_speed_m_s is not None:
                        currents.append(state.surface_current_speed_m_s)
                    if state.water_depth_m is not None:
                        depths.append(state.water_depth_m)
            high_count = sum(self._unsafe(item) for item in states)
            fraction = high_count / len(states) if states else 1.0
            burden = sum(self._burden_level(item) for item in states) / len(states) if states else float("inf")
            depth_fraction = len(depths) / len(states) if states else 0.0
            acceptable = (
                fraction == 0.0
                and penalty <= self.config.maximum_reroute_time_penalty_percent
                and depth_fraction > 0.0
            )
            evaluations.append(SnapshotRouteEvaluation(
                route_id, waypoints, burden, fraction, route_distance, penalty,
                route_distance / speed if speed > 0 else float("inf"),
                min(depths) if depths else None, depth_fraction,
                sum(currents) / len(currents) if currents else None, acceptable,
            ))
        acceptable = [item for item in evaluations if item.acceptable]
        selected = min(
            acceptable,
            key=lambda item: (
                item.snapshot_integrated_risk_burden, item.snapshot_high_risk_fraction,
                item.distance_penalty_percent,
            ),
            default=None,
        )
        screen_id = f"ROUTE-SCREEN-{len(self._route_screens)+1}"
        screen = SnapshotRouteScreen(
            screen_id, at, destination_role, tuple(evaluations),
            selected.route_id if selected else None,
        )
        self._route_screens[screen_id] = screen
        return screen

    def _candidate_rollout(
        self, *, state: DynamicMissionState, candidate_speed: float, candidate_heading: float,
        destination: tuple[float, float],
    ) -> CandidateRollout:
        horizon = self.config.decision_interval_s
        maneuver_duration = min(self.config.maneuver_duration_s, horizon)
        start = (state.latitude, state.longitude)
        maneuver_end = _destination(start, candidate_heading, candidate_speed * maneuver_duration)
        rejoin_heading = _bearing(maneuver_end, destination)
        remaining = horizon - maneuver_duration
        rejoin_travel = min(candidate_speed * remaining, _distance(maneuver_end, destination))
        rejoin_end = _destination(maneuver_end, rejoin_heading, rejoin_travel)
        rejoin_duration = rejoin_travel / candidate_speed if candidate_speed > 0 else 0.0
        legs = (
            (start, maneuver_end, candidate_heading, maneuver_duration),
            (maneuver_end, rejoin_end, rejoin_heading, rejoin_duration),
        )
        values: list[tuple[DynamicMissionState, float]] = []
        for leg_start, leg_end, heading, duration in legs:
            if duration <= 0:
                continue
            for fraction in (0.0, .5, 1.0):
                point = _interpolate(leg_start, leg_end, fraction)
                values.append((self._snapshot_state(
                    state.timestamp, point, state.mission_state, candidate_speed, heading,
                ), duration / 3.0))
        total = sum(duration for _, duration in values)
        high = sum(duration for item, duration in values if self._unsafe(item))
        burden = sum(self._burden_level(item) * duration for item, duration in values)
        progress = _distance(start, destination) - _distance(rejoin_end, destination)
        path_distance = sum(_distance(a, b) for a, b, _, _ in legs)
        direct_progress_distance = min(_distance(start, destination), candidate_speed * horizon)
        rollout_id = f"ROLLOUT-{len(self._rollouts)+1}"
        rollout = CandidateRollout(
            rollout_id, state.timestamp, candidate_speed, candidate_heading, horizon,
            burden, high / total if total else 1.0, progress,
            abs((candidate_heading - state.HDG_deg + 180.0) % 360.0 - 180.0),
            (candidate_speed - state.SOG_m_s) / state.SOG_m_s * 100.0 if state.SOG_m_s else 0.0,
            max(0.0, path_distance - direct_progress_distance),
            high == 0.0 and progress > 0.0,
        )
        self._rollouts[rollout_id] = rollout
        return rollout

    @staticmethod
    def _unsafe(state: DynamicMissionState) -> bool:
        return (
            state.robust_status == RobustDecisionStatus.RESIDUAL_HIGH_RISK.value
            or state.single_vessel_risk_level == RiskLevel.HIGH.value
        )

    def _decision(
        self, state: DynamicMissionState, policy: DynamicPolicy,
        *, predeparture: bool = False, destination: tuple[float, float] | None = None,
    ) -> DynamicDecision:
        if not self._unsafe(state):
            action = (
                DynamicAction.CONTINUE_RETURN_TO_BASE
                if state.mission_state is MissionState.RETURNING else DynamicAction.CONTINUE
            )
            return DynamicDecision(state.timestamp, state.mission_state, action,
                                   "Current dynamic multi-source and robust assessments are acceptable.", state)
        if (
            state.mission_state is MissionState.RETURNING and destination is not None
            and _distance((state.latitude, state.longitude), destination) < 1.0
        ):
            return DynamicDecision(
                state.timestamp, state.mission_state, DynamicAction.CONTINUE_RETURN_TO_BASE,
                "Base has been reached; no further return maneuver or reroute is required.", state,
            )
        if predeparture:
            return DynamicDecision(
                state.timestamp, MissionState.PRE_DEPARTURE, DynamicAction.PREDEPARTURE_DELAY,
                "Same predeparture safety screen for all policies; departure not initiated.", state,
            )
        if policy is DynamicPolicy.BASELINE_CONSERVATIVE:
            action = DynamicAction.CONTINUE_RETURN if state.mission_state is MissionState.RETURNING else DynamicAction.RETURN
            return DynamicDecision(state.timestamp, state.mission_state, action,
                                   "Dynamic residual/high risk after departure; conservative return.", state)
        search = self._search(state) if state.SOG_m_s > 0 else None
        if search is not None:
            recommendation = search.constrained_recommendation
            if recommendation.robust_status is not RobustDecisionStatus.RESIDUAL_HIGH_RISK:
                candidate = recommendation.candidate
                candidate_state = self._state(
                    state.timestamp, (state.latitude, state.longitude), state.mission_state,
                    candidate.SOG_m_s, candidate.HDG_deg,
                )
                rollout = self._candidate_rollout(
                    state=state, candidate_speed=candidate.SOG_m_s,
                    candidate_heading=candidate.HDG_deg,
                    destination=destination or (state.latitude, state.longitude),
                )
                if candidate_state.single_vessel_risk_level != RiskLevel.HIGH.value and rollout.acceptable:
                    action = (
                        DynamicAction.ADJUST_RETURN_SPEED_HEADING
                        if state.mission_state is MissionState.RETURNING
                        else DynamicAction.ADJUST_SPEED_HEADING
                    )
                    return DynamicDecision(
                        state.timestamp, state.mission_state, action,
                        "Constrained candidate passes the 30 min causal current-snapshot rollout and will be executed as a simulated maneuver segment.",
                        state, candidate.SOG_m_s, candidate.HDG_deg, MANEUVER_STATUS,
                        rollout_id=rollout.rollout_id,
                    )
        if policy is DynamicPolicy.LOCAL_ADJUST_ONLY:
            action = DynamicAction.CONTINUE_RETURN if state.mission_state is MissionState.RETURNING else DynamicAction.RETURN
            return DynamicDecision(state.timestamp, state.mission_state, action,
                                   "No executable acceptable local candidate; return.", state)
        environment = MarineEnvironment(
            timestamp=state.timestamp, latitude=state.latitude, longitude=state.longitude,
            Hs=state.Hs_m, Tp=state.Tp_s, wave_direction=state.wave_direction_deg,
            wind_speed=state.wind_speed_m_s, wind_direction=state.wind_direction_deg,
            surface_current_speed=state.surface_current_speed_m_s,
            surface_current_direction=state.surface_current_direction_deg,
            water_depth=state.water_depth_m, source="DYNAMIC_STATE", quality_flag=__import__(
                "core.marine", fromlist=["MarineQualityFlag"]
            ).MarineQualityFlag.PUBLIC_PRODUCT_FILE,
        )
        hold = assess_hold_feasibility(environment, self.parameters, self.config)
        if hold.hold_allowed:
            action = (
                DynamicAction.SAFE_HOLD_RETURN
                if state.mission_state is MissionState.RETURNING else DynamicAction.SAFE_HOLD
            )
            return DynamicDecision(
                state.timestamp, state.mission_state, action,
                "Holding is allowed only after heading-sensitivity grid shows no residual high risk.",
                state, 0.0, None, "SIMULATED SAFE HOLD", hold,
            )
        if destination is not None:
            screen = self._route_screen(
                at=state.timestamp, position=(state.latitude, state.longitude),
                destination=destination, phase=state.mission_state, speed=max(state.SOG_m_s, .5),
                destination_role="BASE" if state.mission_state is MissionState.RETURNING else "TASK_POINT",
            )
            selected = next((item for item in screen.candidates if item.route_id == screen.selected_route_id), None)
            if selected is not None and selected.route_id != "DIRECT":
                action = DynamicAction.REROUTE_RETURN if state.mission_state is MissionState.RETURNING else DynamicAction.REROUTE
                return DynamicDecision(
                    state.timestamp, state.mission_state, action,
                    "HOLD_POSITION_UNSAFE; causal current-snapshot multi-point route screen selected a detour.",
                    state, state.SOG_m_s, _bearing(selected.waypoints[0], selected.waypoints[1]),
                    "SIMULATED MISSION REROUTE", hold, route_screen_id=screen.screen_id,
                )
        action = DynamicAction.CONTINUE_RETURN if state.mission_state is MissionState.RETURNING else DynamicAction.RETURN
        return DynamicDecision(
            state.timestamp, state.mission_state, action,
            "HOLD_POSITION_UNSAFE and no safe local or snapshot-route candidate; return assessment.",
            state, hold_feasibility=hold,
        )

    def _sample_for_duration(
        self, state: DynamicMissionState, duration_s: float,
        segment: ExecutedSegment | None = None,
    ) -> DynamicRiskSample:
        return DynamicRiskSample(
            state.timestamp, state.latitude, state.longitude, duration_s,
            state.robust_status, state.single_vessel_risk_level,
            state.roll_response_grid_q90_proxy, state.single_vessel_risk_score,
            segment.segment_id if segment else None,
            segment.executed_SOG_m_s if segment else state.SOG_m_s,
            segment.executed_HDG_deg if segment else state.HDG_deg,
            state.mission_state, state.timestamp, state.latitude, state.longitude,
        )

    def _record_segment(
        self, segments: list[ExecutedSegment], samples: list[DynamicRiskSample],
        segment: ExecutedSegment, phase: MissionState,
    ) -> DynamicMissionState:
        """Record one execution sample whose kinematics exactly match its segment."""
        executed_state = self._state(
            segment.start_time, segment.start, phase,
            segment.executed_SOG_m_s, segment.executed_HDG_deg,
        )
        segments.append(segment)
        samples.append(self._sample_for_duration(
            executed_state, (segment.end_time - segment.start_time).total_seconds(), segment,
        ))
        return executed_state

    def _causal_reroute_candidate(
        self, *, at: datetime, position: tuple[float, float], destination: tuple[float, float],
        phase: MissionState, speed: float,
    ) -> tuple[tuple[float, float], DynamicMissionState] | None:
        direct = _distance(position, destination)
        if direct < 100.0:
            return None
        base_heading = _bearing(position, destination)
        offset_distance = min(2_000.0, direct * 0.35)
        candidates = []
        for offset in (-60.0, 60.0):
            point = _destination(position, (base_heading + offset) % 360.0, offset_distance)
            penalty = (
                (_distance(position, point) + _distance(point, destination)) / direct - 1.0
            ) * 100.0
            if penalty > self.config.maximum_reroute_time_penalty_percent:
                continue
            heading = _bearing(position, point)
            state = self._state(at, position, phase, speed, heading)
            if not self._unsafe(state):
                candidates.append((state.single_vessel_risk_score, state.roll_response_grid_q90_proxy or 0.0, point, state))
        if not candidates:
            return None
        _, _, point, state = min(candidates)
        return point, state

    def run(self, case: DynamicMissionCase, policy: DynamicPolicy) -> DynamicMissionResult:
        self._route_screens = {}
        self._rollouts = {}
        start, task = case.geometry.start, case.geometry.task_point
        nominal = 2.0 * _distance(start, task) / case.SOG_m_s + case.inspection_service_time_s
        now = case.departure_time
        position = case.initial_position or start
        phase = case.initial_phase
        heading = _bearing(start, task)
        speed = case.SOG_m_s
        decisions: list[DynamicDecision] = []
        segments: list[ExecutedSegment] = []
        samples: list[DynamicRiskSample] = []
        holds = reroutes = 0
        maneuver_phases: set[MissionState] = set()
        reroute_phases: set[MissionState] = set()
        inspection_remaining = case.inspection_service_time_s
        returned_to_base = False
        outbound_started = False
        if phase is MissionState.PRE_DEPARTURE:
            pre_state = self._state(now, position, phase, speed, heading)
            pre = self._decision(pre_state, policy, predeparture=True)
            decisions.append(pre)
            if pre.action in (DynamicAction.PREDEPARTURE_DELAY, DynamicAction.PREDEPARTURE_ABORT):
                exposure = compute_dynamic_exposure(samples)
                endurance = assess_endurance(0.0)
                return DynamicMissionResult(
                    case.case_id, case.geometry.geometry_id, policy.value, POLICY_DEFINITIONS[policy],
                    MissionOutcomeStatus.DELAYED if pre.action is DynamicAction.PREDEPARTURE_DELAY else MissionOutcomeStatus.ABORTED,
                    MissionState.PRE_DEPARTURE if pre.action is DynamicAction.PREDEPARTURE_DELAY else MissionState.ABORTED,
                    False, False, CompletionEvidenceStatus.INCOMPLETE, 0.0, nominal, 0.0,
                    asdict(endurance), False, pre.action is DynamicAction.PREDEPARTURE_DELAY,
                    pre.action is DynamicAction.PREDEPARTURE_ABORT, 0, 0, tuple(decisions), (),
                    exposure, False,
                )
            phase = MissionState.OUTBOUND
            outbound_started = True
        else:
            outbound_started = phase in (MissionState.OUTBOUND, MissionState.ON_STATION, MissionState.RETURNING)
        waypoints: list[tuple[float, float]] = [task]
        elapsed = 0.0
        terminal_status: MissionOutcomeStatus | None = None
        max_elapsed = 48 * 3600.0
        while elapsed < max_elapsed:
            if phase is MissionState.ON_STATION:
                heading = heading % 360.0
                state = self._state(now, position, phase, 0.0, heading)
            else:
                destination = start if phase is MissionState.RETURNING else waypoints[0]
                heading = _bearing(position, destination) if _distance(position, destination) > 0.5 else heading
                state = self._state(now, position, phase, speed, heading)
            destination = waypoints[0]
            decision = self._decision(state, policy, destination=destination)
            if decision.action in (DynamicAction.ADJUST_SPEED_HEADING, DynamicAction.ADJUST_RETURN_SPEED_HEADING):
                if phase in maneuver_phases:
                    decision = DynamicDecision(
                        now, phase,
                        DynamicAction.CONTINUE_RETURN if phase is MissionState.RETURNING else DynamicAction.RETURN,
                        "One simulated maneuver was already executed in this mission phase; do not cycle local adjustments.",
                        state,
                    )
            if decision.action in (DynamicAction.REROUTE, DynamicAction.REROUTE_RETURN):
                if phase in reroute_phases:
                    decision = DynamicDecision(
                        now, phase,
                        DynamicAction.CONTINUE_RETURN if phase is MissionState.RETURNING else DynamicAction.RETURN,
                        "One causal snapshot reroute was already executed in this mission phase; do not cycle detours.",
                        state,
                    )
            decisions.append(decision)
            interval = self.config.decision_interval_s
            if decision.action is DynamicAction.RETURN and phase is not MissionState.RETURNING:
                terminal_status = MissionOutcomeStatus.RETURNED_UNPLANNED
                phase = MissionState.RETURNING
                waypoints = [start]
                continue
            if decision.action in (DynamicAction.REROUTE, DynamicAction.REROUTE_RETURN):
                screen = self._route_screens.get(decision.route_screen_id or "")
                selected = next(
                    (candidate for candidate in screen.candidates
                     if candidate.route_id == screen.selected_route_id), None,
                ) if screen else None
                if selected is not None:
                    waypoints = list(selected.waypoints[1:])
                    reroutes += 1
                    reroute_phases.add(phase)
                    destination = waypoints[0]
            if decision.action in (DynamicAction.SAFE_HOLD, DynamicAction.SAFE_HOLD_RETURN):
                if holds >= 1:
                    if phase is MissionState.RETURNING:
                        decisions[-1] = DynamicDecision(
                            now, phase, DynamicAction.CONTINUE_RETURN,
                            "One safe-hold epoch did not clear risk; continue return assessment to base.",
                            state, hold_feasibility=decision.hold_feasibility,
                        )
                    else:
                        decisions[-1] = DynamicDecision(
                            now, phase, DynamicAction.RETURN,
                            "One safe-hold epoch did not clear the dynamic risk; return assessment.",
                            state, hold_feasibility=decision.hold_feasibility,
                        )
                        terminal_status = MissionOutcomeStatus.RETURNED_UNPLANNED
                        phase = MissionState.RETURNING
                        waypoints = [start]
                        continue
                duration = min(interval, self.config.safe_hold_duration_s)
                holds += 1
                segment = ExecutedSegment(
                    f"HOLD-{len(segments)+1}", "SAFE_HOLD", now, now + timedelta(seconds=duration),
                    position, position, 0.0, heading, "SIMULATED HOLD - ENERGY UNAVAILABLE / " + ENERGY_STATUS,
                )
                self._record_segment(segments, samples, segment, phase)
                now += timedelta(seconds=duration)
                elapsed += duration
                continue
            remaining_interval = interval
            if decision.action in (
                DynamicAction.ADJUST_SPEED_HEADING, DynamicAction.ADJUST_RETURN_SPEED_HEADING,
            ):
                if decision.recommended_HDG_deg is None or decision.recommended_SOG_m_s is None:
                    decision = DynamicDecision(
                        decision.timestamp, decision.mission_state, decision.action,
                        decision.reason, decision.state, decision.recommended_SOG_m_s,
                        decision.recommended_HDG_deg, ADVISORY_ONLY,
                    )
                else:
                    duration = min(self.config.maneuver_duration_s, remaining_interval)
                    maneuver_end = _destination(position, decision.recommended_HDG_deg,
                                                decision.recommended_SOG_m_s * duration)
                    segment = ExecutedSegment(
                        f"MANEUVER-{len(segments)+1}", "MANEUVER_SEGMENT", now,
                        now + timedelta(seconds=duration), position, maneuver_end,
                        decision.recommended_SOG_m_s, decision.recommended_HDG_deg, MANEUVER_STATUS,
                    )
                    self._record_segment(segments, samples, segment, phase)
                    maneuver_phases.add(phase)
                    position = maneuver_end
                    speed = decision.recommended_SOG_m_s
                    heading = decision.recommended_HDG_deg
                    now += timedelta(seconds=duration)
                    elapsed += duration
                    remaining_interval -= duration
            if phase is MissionState.ON_STATION:
                duration = min(remaining_interval, inspection_remaining)
                segment = ExecutedSegment(
                    f"INSPECTION-{len(segments)+1}", "SIMULATED_INSPECTION_SERVICE", now,
                    now + timedelta(seconds=duration), position, position, 0.0, heading, SIMULATED_INSPECTION,
                )
                self._record_segment(segments, samples, segment, phase)
                inspection_remaining -= duration
                now += timedelta(seconds=duration)
                elapsed += duration
                if inspection_remaining <= 1e-9:
                    phase = MissionState.RETURNING
                    waypoints = [start]
                continue
            destination = waypoints[0]
            distance = _distance(position, destination)
            duration = min(remaining_interval, distance / speed if speed > 0 else remaining_interval)
            fraction = min(1.0, speed * duration / distance) if distance > 0 else 1.0
            end = _interpolate(position, destination, fraction)
            executed_heading = _bearing(position, destination) if distance > 0.5 else heading
            segment = ExecutedSegment(
                f"ROUTE-{len(segments)+1}", "ROUTE_SEGMENT", now,
                now + timedelta(seconds=duration), position, end, speed, executed_heading,
                case.geometry.source_status,
            )
            self._record_segment(segments, samples, segment, phase)
            position = end
            heading = executed_heading
            now += timedelta(seconds=duration)
            elapsed += duration
            if fraction >= 1.0 - 1e-9:
                if phase is MissionState.OUTBOUND:
                    if len(waypoints) > 1:
                        waypoints.pop(0)
                    else:
                        phase = MissionState.ON_STATION
                        position = task
                elif phase is MissionState.RETURNING:
                    if len(waypoints) > 1:
                        waypoints.pop(0)
                    else:
                        returned_to_base = True
                        position = start
                        break
        validate_segment_sample_invariants(segments, samples)
        exposure = compute_dynamic_exposure(samples)
        technical = returned_to_base and terminal_status is None and inspection_remaining <= 1e-9
        outcome = MissionOutcomeStatus.COMPLETED if technical else (
            terminal_status or MissionOutcomeStatus.INTERRUPTED
        )
        final_state = MissionState.COMPLETED if technical else (
            MissionState.ABORTED if returned_to_base else phase
        )
        endurance = assess_endurance(elapsed)
        evidence_status = (
            CompletionEvidenceStatus.QUALIFIED
            if technical and endurance.mission_time_feasibility_status == "WITHIN_PUBLISHED_MINIMUM_REFERENCE"
            else CompletionEvidenceStatus.ENDURANCE_UNVERIFIED
            if technical else CompletionEvidenceStatus.INCOMPLETE
        )
        duration_compatible = technical and (
            endurance.mission_time_feasibility_status == "WITHIN_PUBLISHED_MINIMUM_REFERENCE"
        )
        duration_status = (
            DurationReferenceStatus.COMPATIBLE if duration_compatible else
            DurationReferenceStatus.EXCEEDED if technical else DurationReferenceStatus.INCOMPLETE
        )
        executed_distance = sum(segment.distance_m for segment in segments)
        nominal_distance = 2.0 * _distance(start, task)
        signed_delta = elapsed - nominal
        maneuver_segments = [segment for segment in segments if segment.segment_type == "MANEUVER_SEGMENT"]
        maneuver_distance = sum(segment.distance_m for segment in maneuver_segments)
        affected_actions = {
            DynamicAction.ADJUST_SPEED_HEADING, DynamicAction.ADJUST_RETURN_SPEED_HEADING,
            DynamicAction.REROUTE, DynamicAction.REROUTE_RETURN,
            DynamicAction.SAFE_HOLD, DynamicAction.SAFE_HOLD_RETURN,
            DynamicAction.RETURN, DynamicAction.PREDEPARTURE_DELAY, DynamicAction.PREDEPARTURE_ABORT,
        }
        extra_distance = max(0.0, executed_distance - nominal_distance)
        if extra_distance < 1.0:
            extra_distance = 0.0
        return DynamicMissionResult(
            case.case_id, case.geometry.geometry_id, policy.value, POLICY_DEFINITIONS[policy],
            outcome, final_state, technical, evidence_status is CompletionEvidenceStatus.QUALIFIED,
            evidence_status, elapsed, nominal, max(0.0, signed_delta), asdict(endurance),
            bool(terminal_status is MissionOutcomeStatus.RETURNED_UNPLANNED and outbound_started),
            False, False, holds, reroutes, tuple(decisions), tuple(segments), exposure,
            returned_to_base, duration_compatible, duration_status,
            "NOT VERIFIED ENERGY FEASIBILITY", signed_delta, max(0.0, signed_delta),
            max(0.0, -signed_delta), extra_distance,
            maneuver_distance, len(maneuver_segments),
            any(decision.action in affected_actions for decision in decisions),
            tuple(self._route_screens.values()), tuple(self._rollouts.values()), tuple(samples),
        )
