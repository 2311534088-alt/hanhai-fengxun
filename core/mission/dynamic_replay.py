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


class DynamicAction(str, Enum):
    CONTINUE = "CONTINUE"
    ADJUST_SPEED_HEADING = "ADJUST_SPEED_HEADING"
    REROUTE = "REROUTE_TO_LOWER_RISK_AREA"
    SAFE_HOLD = "SAFE_HOLD"
    RETURN = "RETURN_ASSESSMENT"
    PREDEPARTURE_DELAY = "PREDEPARTURE_DELAY"
    PREDEPARTURE_ABORT = "PREDEPARTURE_ABORT"


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
    if not hanhai.evidence_qualified_completion:
        reasons.append("HANHAI_COMPLETION_NOT_EVIDENCE_QUALIFIED")
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
        self._cache: dict[tuple, MarineEnvironment] = {}

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
            spatial = self._records_by_source_time[source][selected_time]
            if spatial:
                candidates.append(min(spatial, key=lambda item: (
                    (item.latitude - latitude) ** 2 + (item.longitude - longitude) ** 2
                )))
        sampled = MarineEnvironmentSampler(candidates, self.tolerance).sample(timestamp, latitude, longitude)
        self.access_log.append({
            "accepted": True, "purpose": purpose.value, "requested_timestamp": timestamp,
            "decision_timestamp": decision_timestamp,
        })
        self._cache[key] = sampled
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

    def _state(
        self, at: datetime, position: tuple[float, float], phase: MissionState,
        speed: float, heading: float,
    ) -> DynamicMissionState:
        environment = self.store.sample(
            timestamp=at, latitude=position[0], longitude=position[1],
            decision_timestamp=at, purpose=EnvironmentUse.ACTION_SELECTION,
        )
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
    def _unsafe(state: DynamicMissionState) -> bool:
        return (
            state.robust_status == RobustDecisionStatus.RESIDUAL_HIGH_RISK.value
            or state.single_vessel_risk_level == RiskLevel.HIGH.value
        )

    def _decision(
        self, state: DynamicMissionState, policy: DynamicPolicy,
        *, predeparture: bool = False,
    ) -> DynamicDecision:
        if not self._unsafe(state):
            return DynamicDecision(state.timestamp, state.mission_state, DynamicAction.CONTINUE,
                                   "Current dynamic multi-source and robust assessments are acceptable.", state)
        if predeparture:
            return DynamicDecision(
                state.timestamp, MissionState.PRE_DEPARTURE, DynamicAction.PREDEPARTURE_DELAY,
                "Same predeparture safety screen for all policies; departure not initiated.", state,
            )
        if state.mission_state is MissionState.RETURNING:
            return DynamicDecision(
                state.timestamp, state.mission_state, DynamicAction.CONTINUE,
                "Return already in progress; continue simulated route to base while accumulating exposure.", state,
            )
        if policy is DynamicPolicy.BASELINE_CONSERVATIVE:
            return DynamicDecision(state.timestamp, state.mission_state, DynamicAction.RETURN,
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
                if candidate_state.single_vessel_risk_level != RiskLevel.HIGH.value:
                    return DynamicDecision(
                        state.timestamp, state.mission_state, DynamicAction.ADJUST_SPEED_HEADING,
                        "Constrained candidate passes both roll-response and multi-source risk screens and will be executed as a simulated maneuver segment.",
                        state, candidate.SOG_m_s, candidate.HDG_deg, MANEUVER_STATUS,
                    )
        if policy is DynamicPolicy.LOCAL_ADJUST_ONLY:
            return DynamicDecision(state.timestamp, state.mission_state, DynamicAction.RETURN,
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
            return DynamicDecision(
                state.timestamp, state.mission_state, DynamicAction.SAFE_HOLD,
                "Holding is allowed only after heading-sensitivity grid shows no residual high risk.",
                state, 0.0, None, "SIMULATED SAFE HOLD", hold,
            )
        return DynamicDecision(
            state.timestamp, state.mission_state, DynamicAction.RETURN,
            "HOLD_POSITION_UNSAFE and no executable local candidate; return assessment.",
            state, hold_feasibility=hold,
        )

    def _sample_for_duration(self, state: DynamicMissionState, duration_s: float) -> DynamicRiskSample:
        return DynamicRiskSample(
            state.timestamp, state.latitude, state.longitude, duration_s,
            state.robust_status, state.single_vessel_risk_level,
            state.roll_response_grid_q90_proxy, state.single_vessel_risk_score,
        )

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
        start, task = case.geometry.start, case.geometry.task_point
        nominal = 2.0 * _distance(start, task) / case.SOG_m_s + case.inspection_service_time_s
        now = case.departure_time
        position = start
        phase = case.initial_phase
        heading = _bearing(start, task)
        speed = case.SOG_m_s
        decisions: list[DynamicDecision] = []
        segments: list[ExecutedSegment] = []
        samples: list[DynamicRiskSample] = []
        holds = reroutes = 0
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
            decision = self._decision(state, policy)
            if (
                decision.action is DynamicAction.RETURN
                and policy is DynamicPolicy.HANHAI_MISSION_CONTINUITY
                and phase is not MissionState.RETURNING
                and decision.hold_feasibility is not None
                and not decision.hold_feasibility.hold_allowed
                and reroutes == 0
            ):
                destination = waypoints[-1] if waypoints else task
                reroute = self._causal_reroute_candidate(
                    at=now, position=position, destination=destination,
                    phase=phase, speed=speed,
                )
                if reroute is not None:
                    point, reroute_state = reroute
                    decision = DynamicDecision(
                        now, phase, DynamicAction.REROUTE,
                        "HOLD_POSITION_UNSAFE; current-epoch causal screen found a lower-risk simulated waypoint.",
                        state, speed, reroute_state.HDG_deg, "SIMULATED MISSION REROUTE",
                        decision.hold_feasibility,
                    )
                    reroutes += 1
                    final_destination = waypoints[-1] if waypoints else task
                    waypoints = [point, final_destination]
            decisions.append(decision)
            interval = self.config.decision_interval_s
            if decision.action is DynamicAction.RETURN and phase is not MissionState.RETURNING:
                terminal_status = MissionOutcomeStatus.RETURNED_UNPLANNED
                phase = MissionState.RETURNING
                waypoints = [start]
                continue
            if decision.action is DynamicAction.SAFE_HOLD:
                if holds >= 1:
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
                samples.append(self._sample_for_duration(state, duration))
                segments.append(ExecutedSegment(
                    f"HOLD-{len(segments)+1}", "SAFE_HOLD", now, now + timedelta(seconds=duration),
                    position, position, 0.0, heading, "SIMULATED HOLD - ENERGY UNAVAILABLE / " + ENERGY_STATUS,
                ))
                now += timedelta(seconds=duration)
                elapsed += duration
                continue
            remaining_interval = interval
            if decision.action is DynamicAction.ADJUST_SPEED_HEADING:
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
                    segments.append(ExecutedSegment(
                        f"MANEUVER-{len(segments)+1}", "MANEUVER_SEGMENT", now,
                        now + timedelta(seconds=duration), position, maneuver_end,
                        decision.recommended_SOG_m_s, decision.recommended_HDG_deg, MANEUVER_STATUS,
                    ))
                    executed_state = self._state(
                        now, position, phase, decision.recommended_SOG_m_s,
                        decision.recommended_HDG_deg,
                    )
                    samples.append(self._sample_for_duration(executed_state, duration))
                    position = maneuver_end
                    speed = decision.recommended_SOG_m_s
                    heading = decision.recommended_HDG_deg
                    now += timedelta(seconds=duration)
                    elapsed += duration
                    remaining_interval -= duration
            if phase is MissionState.ON_STATION:
                duration = min(remaining_interval, inspection_remaining)
                samples.append(self._sample_for_duration(state, duration))
                segments.append(ExecutedSegment(
                    f"INSPECTION-{len(segments)+1}", "SIMULATED_INSPECTION_SERVICE", now,
                    now + timedelta(seconds=duration), position, position, 0.0, heading, SIMULATED_INSPECTION,
                ))
                inspection_remaining -= duration
                now += timedelta(seconds=duration)
                elapsed += duration
                if inspection_remaining <= 1e-9:
                    phase = MissionState.RETURNING
                    waypoints = [start]
                continue
            destination = start if phase is MissionState.RETURNING else waypoints[0]
            distance = _distance(position, destination)
            duration = min(remaining_interval, distance / speed if speed > 0 else remaining_interval)
            fraction = min(1.0, speed * duration / distance) if distance > 0 else 1.0
            end = _interpolate(position, destination, fraction)
            executed_heading = _bearing(position, destination) if distance > 0.5 else heading
            segments.append(ExecutedSegment(
                f"ROUTE-{len(segments)+1}", "ROUTE_SEGMENT", now,
                now + timedelta(seconds=duration), position, end, speed, executed_heading,
                case.geometry.source_status,
            ))
            samples.append(self._sample_for_duration(state, duration))
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
                    returned_to_base = True
                    position = start
                    break
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
        return DynamicMissionResult(
            case.case_id, case.geometry.geometry_id, policy.value, POLICY_DEFINITIONS[policy],
            outcome, final_state, technical, evidence_status is CompletionEvidenceStatus.QUALIFIED,
            evidence_status, elapsed, nominal, max(0.0, elapsed - nominal), asdict(endurance),
            bool(terminal_status is MissionOutcomeStatus.RETURNED_UNPLANNED and outbound_started),
            False, False, holds, reroutes, tuple(decisions), tuple(segments), exposure,
            returned_to_base,
        )
