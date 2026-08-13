"""Causal, complete and reproducible historical mission replay primitives.

All outputs remain model-based replay.  No object in this module is a real-vessel
command and future historical observations are never action-selection inputs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from bisect import bisect_right
from math import atan2, cos, radians, sin, sqrt
from typing import Iterable, Sequence

from core.marine import MarineEnvironment
from core.mission.state import MissionState
from core.mission.decision.models import MissionAction, MissionOutcomeStatus
from core.resonance.parameters import RollDynamicsParameters
from core.resonance.robust_avoidance import search_robust_roll_avoidance
from core.roll_response import RobustDecisionStatus, scan_roll_response_uncertainty


MODEL_BASED_REPLAY = "MODEL-BASED HISTORICAL REPLAY"
NOT_OPERATIONAL_PERFORMANCE = "NOT REAL OPERATIONAL PERFORMANCE"
INTERNAL_BASELINE = "INTERNAL SIMULATION BASELINE"
REAL_ENVIRONMENT = "REAL PUBLIC ENVIRONMENT DATA - NOT IN-SITU ZHUANGHE OBSERVATION"
SIMULATED_VESSEL = "SIMULATED VESSEL STATE"
SIMULATED_INSPECTION = "SIMULATED MISSION PARAMETER"
STRESS_TEST_ROUTE = "STRESS-TEST SIMULATED ROUTE - NOT ZHUANGHE ACTUAL INSPECTION DISTANCE"
CAUSAL_MODE = "CAUSAL_HISTORICAL_REPLAY"
ORACLE_MODE = "ORACLE_HISTORICAL_LOOKAHEAD - ORACLE UPPER BOUND - NOT OPERATIONALLY AVAILABLE"
PUBLISHED_WORK_TIME_REFERENCE_H = 4.0
PUBLISHED_WORK_TIME_STATUS = "MINIMUM PUBLISHED WORK-TIME REFERENCE - NOT MAXIMUM ENDURANCE"
ENERGY_STATUS = "REQUIRES REAL POWER DATA"
EARTH_RADIUS_M = 6_371_000.0


class EnvironmentUse(str, Enum):
    ACTION_SELECTION = "ACTION_SELECTION"
    OUTCOME_EVALUATION = "OUTCOME_EVALUATION"


class FutureDataLeakageError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class EnvironmentAccess:
    requested_timestamp: datetime
    selected_timestamp: datetime | None
    decision_timestamp: datetime
    purpose: EnvironmentUse
    accepted: bool
    reason: str


class CausalEnvironmentStore:
    """Nearest historical environment access with an auditable causal barrier."""

    def __init__(self, records: Sequence[MarineEnvironment]) -> None:
        if not records:
            raise ValueError("causal environment store requires records")
        self.records = tuple(records)
        self.access_log: list[EnvironmentAccess] = []
        self._response_cache: dict[tuple, object] = {}
        self._grid_cache: dict[tuple, object] = {}
        by_time: dict[datetime, list[MarineEnvironment]] = {}
        for item in self.records:
            by_time.setdefault(item.timestamp, []).append(item)
        self._by_time = {key: tuple(value) for key, value in by_time.items()}
        self._times = tuple(sorted(self._by_time))

    def nearest(
        self, *, timestamp: datetime, latitude: float, longitude: float,
        decision_timestamp: datetime, purpose: EnvironmentUse,
    ) -> MarineEnvironment:
        if purpose is EnvironmentUse.ACTION_SELECTION and timestamp > decision_timestamp:
            self.access_log.append(EnvironmentAccess(
                timestamp, None, decision_timestamp, purpose, False,
                "FUTURE_ENVIRONMENT_FORBIDDEN_FOR_ACTION_SELECTION",
            ))
            raise FutureDataLeakageError(
                f"action at {decision_timestamp.isoformat()} cannot access {timestamp.isoformat()}"
            )
        if purpose is EnvironmentUse.ACTION_SELECTION:
            upper = bisect_right(self._times, decision_timestamp)
            available_times = self._times[:upper]
            if not available_times:
                raise ValueError("no causal historical environment at or before decision time")
        else:
            available_times = self._times
        selected_time = min(available_times, key=lambda item: abs((item - timestamp).total_seconds()))
        selected = min(self._by_time[selected_time], key=lambda item: (
            (item.latitude - latitude) ** 2 + (item.longitude - longitude) ** 2,
        ))
        self.access_log.append(EnvironmentAccess(
            timestamp, selected.timestamp, decision_timestamp, purpose, True,
            "CAUSAL_ACCESS" if purpose is EnvironmentUse.ACTION_SELECTION else "OUTCOME_ONLY_ACCESS",
        ))
        return selected

    @property
    def future_action_access_count(self) -> int:
        return sum(
            not item.accepted and item.purpose is EnvironmentUse.ACTION_SELECTION
            for item in self.access_log
        )


@dataclass(frozen=True, slots=True)
class MissionEvent:
    state: MissionState
    timestamp: datetime
    event: str
    source_status: str


@dataclass(slots=True)
class MissionTimeline:
    started_at: datetime
    events: list[MissionEvent] = field(default_factory=list)
    outbound_time_s: float = 0.0
    hold_time_s: float = 0.0
    reroute_extra_time_s: float = 0.0
    inspection_service_time_s: float = 0.0
    return_time_s: float = 0.0

    @property
    def mission_elapsed_time_s(self) -> float:
        return (
            self.outbound_time_s + self.hold_time_s + self.reroute_extra_time_s
            + self.inspection_service_time_s + self.return_time_s
        )

    @property
    def final_state(self) -> MissionState:
        return self.events[-1].state if self.events else MissionState.PRE_DEPARTURE

    @property
    def has_complete_flow(self) -> bool:
        states = [item.state for item in self.events]
        required = [
            MissionState.PRE_DEPARTURE, MissionState.OUTBOUND, MissionState.ON_STATION,
            MissionState.RETURNING, MissionState.COMPLETED,
        ]
        cursor = 0
        for state in states:
            if cursor < len(required) and state is required[cursor]:
                cursor += 1
        return (
            cursor == len(required)
            and any(item.event == "SIMULATED_INSPECTION_SERVICE_COMPLETED" for item in self.events)
        )

    @property
    def mission_completed(self) -> bool:
        return self.final_state is MissionState.COMPLETED and self.has_complete_flow


@dataclass(frozen=True, slots=True)
class EnduranceAssessment:
    manufacturer_guaranteed_work_time_reference_h: float
    reference_status: str
    elapsed_time_h: float
    published_reference_comparison: str
    mission_time_feasibility_status: str


def assess_endurance(elapsed_time_s: float) -> EnduranceAssessment:
    hours = elapsed_time_s / 3600.0
    comparison = (
        "WITHIN_PUBLISHED_MINIMUM_REFERENCE"
        if hours <= PUBLISHED_WORK_TIME_REFERENCE_H
        else "EXCEEDS_PUBLISHED_MINIMUM_REFERENCE"
    )
    feasibility = (
        comparison if comparison == "WITHIN_PUBLISHED_MINIMUM_REFERENCE"
        else "ENDURANCE_FEASIBILITY_UNVERIFIED"
    )
    return EnduranceAssessment(
        PUBLISHED_WORK_TIME_REFERENCE_H, PUBLISHED_WORK_TIME_STATUS, hours,
        comparison, feasibility,
    )


@dataclass(frozen=True, slots=True)
class RouteRiskSample:
    timestamp: datetime
    latitude: float
    longitude: float
    Hs_m: float
    Tp_s: float
    wave_direction_deg: float
    roll_response_proxy: float
    robust_status: str
    represented_duration_s: float
    environment_source: str = REAL_ENVIRONMENT


@dataclass(frozen=True, slots=True)
class RiskExposureMetrics:
    high_risk_exposure_steps: int
    high_risk_exposure_time_s: float
    moderate_risk_exposure_time_s: float
    total_evaluated_time_s: float
    risk_exposure_ratio: float
    calculation_status: str = "COMPUTED_FROM_SPATIOTEMPORAL_ROUTE_SAMPLES"


def compute_risk_exposure(samples: Iterable[RouteRiskSample]) -> RiskExposureMetrics:
    values = tuple(samples)
    high = tuple(item for item in values if item.robust_status == RobustDecisionStatus.RESIDUAL_HIGH_RISK.value)
    moderate = tuple(item for item in values if item.robust_status == RobustDecisionStatus.ROBUST_MODERATE.value)
    high_time = sum(item.represented_duration_s for item in high)
    moderate_time = sum(item.represented_duration_s for item in moderate)
    total = sum(item.represented_duration_s for item in values)
    return RiskExposureMetrics(
        len(high), high_time, moderate_time, total, high_time / total if total else 0.0,
    )


@dataclass(frozen=True, slots=True)
class SpatiotemporalRouteReplay:
    route_id: str
    waypoints: tuple[tuple[float, float], ...]
    started_at: datetime
    ended_at: datetime
    distance_m: float
    travel_time_s: float
    samples: tuple[RouteRiskSample, ...]
    exposure: RiskExposureMetrics
    route_source_status: str
    evaluation_method: str = "SPATIOTEMPORAL ROUTE REPLAY"


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lat2 = radians(a[0]), radians(b[0])
    dlat, dlon = lat2 - lat1, radians(b[1] - a[1])
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return EARTH_RADIUS_M * 2 * atan2(sqrt(h), sqrt(max(0.0, 1.0 - h)))


def _bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lat2 = radians(a[0]), radians(b[0])
    dlon = radians(b[1] - a[1])
    return (atan2(
        sin(dlon) * cos(lat2),
        cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(dlon),
    ) * 180.0 / 3.141592653589793 + 360.0) % 360.0


def _relative_angle(wave_direction: float, heading: float) -> float:
    return abs((wave_direction - heading + 180.0) % 360.0 - 180.0)


def evaluate_spatiotemporal_route(
    *, route_id: str, waypoints: tuple[tuple[float, float], ...], started_at: datetime,
    speed_m_s: float, store: CausalEnvironmentStore, parameters: RollDynamicsParameters,
    sampling_interval_s: float = 900.0, route_source_status: str = "SIMULATED MISSION ROUTE",
) -> SpatiotemporalRouteReplay:
    if len(waypoints) < 2:
        raise ValueError("route needs at least two waypoints")
    if speed_m_s <= 0 or sampling_interval_s <= 0:
        raise ValueError("speed and sampling interval must be positive")
    elapsed = 0.0
    total_distance = 0.0
    samples: list[RouteRiskSample] = []
    for start, end in zip(waypoints, waypoints[1:]):
        distance = _distance(start, end)
        duration = distance / speed_m_s
        heading = _bearing(start, end)
        offset = 0.0
        while offset < duration - 1e-9:
            represented = min(sampling_interval_s, duration - offset)
            fraction = offset / duration if duration else 0.0
            latitude = start[0] + (end[0] - start[0]) * fraction
            longitude = start[1] + (end[1] - start[1]) * fraction
            timestamp = started_at + timedelta(seconds=elapsed + offset)
            environment = store.nearest(
                timestamp=timestamp, latitude=latitude, longitude=longitude,
                decision_timestamp=started_at, purpose=EnvironmentUse.OUTCOME_EVALUATION,
            )
            if None in (environment.Hs, environment.Tp, environment.wave_direction):
                raise ValueError("route replay requires Hs, Tp and wave direction")
            relative = _relative_angle(environment.wave_direction, heading)
            key = (
                environment.timestamp, environment.latitude, environment.longitude,
                speed_m_s, relative, parameters,
            )
            response = store._grid_cache.get(key)
            if response is None:
                response = scan_roll_response_uncertainty(
                    Hs_m=environment.Hs, Tp_s=environment.Tp, vessel_speed_m_s=speed_m_s,
                    relative_wave_angle_deg=relative, parameters=parameters,
                )
                store._grid_cache[key] = response
            samples.append(RouteRiskSample(
                timestamp, latitude, longitude, environment.Hs, environment.Tp,
                environment.wave_direction, response.grid_q90_roll_response_proxy,
                response.robust_decision_status.value, represented,
            ))
            offset += represented
        elapsed += duration
        total_distance += distance
    exposure = compute_risk_exposure(samples)
    return SpatiotemporalRouteReplay(
        route_id, waypoints, started_at, started_at + timedelta(seconds=elapsed),
        total_distance, elapsed, tuple(samples), exposure, route_source_status,
    )


@dataclass(frozen=True, slots=True)
class MissionReplayResult:
    case_id: str
    policy_name: str
    policy_definition: str
    outcome_status: MissionOutcomeStatus
    final_mission_state: MissionState
    timeline: MissionTimeline
    actions: tuple[MissionAction, ...]
    exposure: RiskExposureMetrics
    endurance: EnduranceAssessment
    reroute_used: bool
    hold_used: bool
    hold_energy: None = None
    hold_energy_status: str = ENERGY_STATUS
    environment_source: str = REAL_ENVIRONMENT
    vessel_state_source: str = SIMULATED_VESSEL
    parameter_source: str = "ENGINEERING_ESTIMATE"
    parameter_status: str = "NOT_EXPERIMENTALLY_CALIBRATED"
    replay_mode: str = CAUSAL_MODE
    result_status: str = MODEL_BASED_REPLAY
    performance_status: str = NOT_OPERATIONAL_PERFORMANCE

    @property
    def mission_completed(self) -> bool:
        return (
            self.outcome_status is MissionOutcomeStatus.COMPLETED
            and self.final_mission_state is MissionState.COMPLETED
            and self.timeline.mission_completed
        )

    def to_dict(self) -> dict:
        value = asdict(self)
        value["mission_completed"] = self.mission_completed
        return value


def combine_exposures(*metrics: RiskExposureMetrics) -> RiskExposureMetrics:
    total = sum(item.total_evaluated_time_s for item in metrics)
    high = sum(item.high_risk_exposure_time_s for item in metrics)
    return RiskExposureMetrics(
        sum(item.high_risk_exposure_steps for item in metrics), high,
        sum(item.moderate_risk_exposure_time_s for item in metrics), total,
        high / total if total else 0.0,
    )


def action_outcome_status(action: MissionAction) -> MissionOutcomeStatus:
    return {
        MissionAction.CONTINUE: MissionOutcomeStatus.IN_PROGRESS,
        MissionAction.ADJUST_SPEED_HEADING: MissionOutcomeStatus.IN_PROGRESS,
        MissionAction.REROUTE: MissionOutcomeStatus.IN_PROGRESS,
        MissionAction.HOLD_AND_REASSESS: MissionOutcomeStatus.PENDING_REASSESSMENT,
        MissionAction.DELAY_MISSION: MissionOutcomeStatus.DELAYED,
        MissionAction.RETURN: MissionOutcomeStatus.RETURNED_UNPLANNED,
    }[action]


class ReplayPolicy(str, Enum):
    BASELINE_CONSERVATIVE = "BASELINE_CONSERVATIVE"
    LOCAL_ADJUST_ONLY = "LOCAL_ADJUST_ONLY"
    HANHAI_MISSION_CONTINUITY = "HANHAI_MISSION_CONTINUITY"


POLICY_DEFINITIONS = {
    ReplayPolicy.BASELINE_CONSERVATIVE: (
        "INTERNAL SIMULATION BASELINE: persistent residual high risk -> RETURN"
    ),
    ReplayPolicy.LOCAL_ADJUST_ONLY: (
        "INTERNAL SIMULATION BASELINE: local speed/heading adjustment only; failure -> RETURN"
    ),
    ReplayPolicy.HANHAI_MISSION_CONTINUITY: (
        "INTERNAL SIMULATION BASELINE: adjust -> reroute -> causal hold/reassess -> return last"
    ),
}


@dataclass(frozen=True, slots=True)
class MissionCase:
    case_id: str
    departure_time: datetime
    start: tuple[float, float]
    task_point: tuple[float, float]
    SOG_m_s: float = 1.8
    HDG_deg: float = 214.66
    inspection_service_time_s: float = 1800.0
    route_source_status: str = "SIMULATED MISSION ROUTE"
    selection_rule: str = "DETERMINISTIC_REPLAY_CASE"


def _response_at(
    store: CausalEnvironmentStore, case: MissionCase, at: datetime,
    parameters: RollDynamicsParameters,
):
    environment = store.nearest(
        timestamp=at, latitude=case.start[0], longitude=case.start[1],
        decision_timestamp=at, purpose=EnvironmentUse.ACTION_SELECTION,
    )
    if None in (environment.Hs, environment.Tp, environment.wave_direction):
        raise ValueError("mission decision requires Hs, Tp and wave direction")
    key = (
        environment.timestamp, environment.latitude, environment.longitude,
        environment.Hs, environment.Tp, environment.wave_direction,
        case.SOG_m_s, case.HDG_deg, parameters,
    )
    search = store._response_cache.get(key)
    if search is None:
        search = search_robust_roll_avoidance(
            Hs_m=environment.Hs, Tp_s=environment.Tp,
            wave_direction_deg=environment.wave_direction,
            current_speed_m_s=case.SOG_m_s, current_heading_deg=case.HDG_deg,
            parameters=parameters,
        )
        store._response_cache[key] = search
    return environment, search


def _stationary_exposure(
    *, store: CausalEnvironmentStore, case: MissionCase, started_at: datetime,
    duration_s: float, parameters: RollDynamicsParameters, interval_s: float = 900.0,
) -> RiskExposureMetrics:
    samples: list[RouteRiskSample] = []
    offset = 0.0
    while offset < duration_s - 1e-9:
        represented = min(interval_s, duration_s - offset)
        at = started_at + timedelta(seconds=offset)
        environment = store.nearest(
            timestamp=at, latitude=case.start[0], longitude=case.start[1],
            decision_timestamp=started_at, purpose=EnvironmentUse.OUTCOME_EVALUATION,
        )
        if None in (environment.Hs, environment.Tp, environment.wave_direction):
            raise ValueError("stationary replay requires wave variables")
        relative = _relative_angle(environment.wave_direction, case.HDG_deg)
        key = (environment.timestamp, environment.latitude, environment.longitude, 0.0, relative, parameters)
        response = store._grid_cache.get(key)
        if response is None:
            response = scan_roll_response_uncertainty(
                Hs_m=environment.Hs, Tp_s=environment.Tp,
                vessel_speed_m_s=0.0, relative_wave_angle_deg=relative,
                parameters=parameters,
            )
            store._grid_cache[key] = response
        samples.append(RouteRiskSample(
            at, case.start[0], case.start[1], environment.Hs, environment.Tp,
            environment.wave_direction, response.grid_q90_roll_response_proxy,
            response.robust_decision_status.value, represented,
        ))
        offset += represented
    return compute_risk_exposure(samples)


def _reroute_waypoints(case: MissionCase) -> tuple[tuple[float, float], ...]:
    if case.route_source_status == STRESS_TEST_ROUTE:
        return (case.start, (39.0, 122.4), case.task_point)
    midpoint = (
        (case.start[0] + case.task_point[0]) / 2.0 + 0.006,
        (case.start[1] + case.task_point[1]) / 2.0 - 0.006,
    )
    return (case.start, midpoint, case.task_point)


def _causal_reroute_is_acceptable(
    environment: MarineEnvironment, case: MissionCase, parameters: RollDynamicsParameters,
) -> bool:
    """Current-snapshot persistence screen; it never reads a future observation."""
    if None in (environment.Hs, environment.Tp, environment.wave_direction):
        return False
    direct_distance = _distance(case.start, case.task_point)
    detour = _reroute_waypoints(case)
    detour_distance = sum(_distance(a, b) for a, b in zip(detour, detour[1:]))
    if direct_distance == 0 or (detour_distance / direct_distance - 1.0) * 100.0 > 35.0:
        return False
    statuses = []
    for start, end in zip(detour, detour[1:]):
        grid = scan_roll_response_uncertainty(
            Hs_m=environment.Hs, Tp_s=environment.Tp,
            vessel_speed_m_s=case.SOG_m_s,
            relative_wave_angle_deg=_relative_angle(environment.wave_direction, _bearing(start, end)),
            parameters=parameters,
        )
        statuses.append(grid.robust_decision_status)
    return all(item is not RobustDecisionStatus.RESIDUAL_HIGH_RISK for item in statuses)


def _terminal_return(
    *, case: MissionCase, policy: ReplayPolicy, timeline: MissionTimeline,
    actions: list[MissionAction], exposures: list[RiskExposureMetrics],
    reroute_used: bool, hold_used: bool,
) -> MissionReplayResult:
    exposure = combine_exposures(*exposures) if exposures else compute_risk_exposure(())
    timeline.return_time_s = max(timeline.return_time_s, exposure.total_evaluated_time_s)
    at = case.departure_time + timedelta(seconds=timeline.mission_elapsed_time_s)
    timeline.events.append(MissionEvent(
        MissionState.RETURNING, at, "UNPLANNED_RETURN_OR_INTERRUPTION",
        "SIMULATED MISSION OUTCOME",
    ))
    actions.append(MissionAction.RETURN)
    return MissionReplayResult(
        case.case_id, policy.value, POLICY_DEFINITIONS[policy],
        MissionOutcomeStatus.RETURNED_UNPLANNED, timeline.final_state, timeline,
        tuple(actions), exposure, assess_endurance(timeline.mission_elapsed_time_s),
        reroute_used, hold_used,
    )


def replay_complete_mission(
    *, case: MissionCase, policy: ReplayPolicy, store: CausalEnvironmentStore,
    parameters: RollDynamicsParameters, hold_duration_s: float = 10_800.0,
    sampling_interval_s: float = 900.0,
) -> MissionReplayResult:
    """Replay one full simulated task using only causal data for every decision."""
    timeline = MissionTimeline(case.departure_time)
    timeline.events.append(MissionEvent(
        MissionState.PRE_DEPARTURE, case.departure_time, "MISSION_RELEASED",
        "SIMULATED MISSION TIMELINE",
    ))
    timeline.events.append(MissionEvent(
        MissionState.OUTBOUND, case.departure_time, "OUTBOUND_STARTED",
        "SIMULATED VESSEL STATE",
    ))
    actions: list[MissionAction] = []
    exposures: list[RiskExposureMetrics] = []
    reroute_used = False
    hold_used = False
    environment, search = _response_at(store, case, case.departure_time, parameters)
    residual = search.current.response_grid.robust_decision_status is RobustDecisionStatus.RESIDUAL_HIGH_RISK
    selected_speed = case.SOG_m_s
    outbound_waypoints = (case.start, case.task_point)

    if residual:
        if policy is ReplayPolicy.BASELINE_CONSERVATIVE:
            exposures.append(_stationary_exposure(
                store=store, case=case, started_at=case.departure_time,
                duration_s=sampling_interval_s, parameters=parameters,
                interval_s=sampling_interval_s,
            ))
            return _terminal_return(
                case=case, policy=policy, timeline=timeline, actions=actions,
                exposures=exposures, reroute_used=False, hold_used=False,
            )
        local = search.constrained_recommendation
        local_ok = local.robust_status is not RobustDecisionStatus.RESIDUAL_HIGH_RISK
        if local_ok:
            actions.append(MissionAction.ADJUST_SPEED_HEADING)
            selected_speed = local.candidate.SOG_m_s
        elif policy is ReplayPolicy.LOCAL_ADJUST_ONLY:
            exposures.append(_stationary_exposure(
                store=store, case=case, started_at=case.departure_time,
                duration_s=sampling_interval_s, parameters=parameters,
                interval_s=sampling_interval_s,
            ))
            return _terminal_return(
                case=case, policy=policy, timeline=timeline, actions=actions,
                exposures=exposures, reroute_used=False, hold_used=False,
            )
        elif _causal_reroute_is_acceptable(environment, case, parameters):
            actions.append(MissionAction.REROUTE)
            reroute_used = True
            outbound_waypoints = _reroute_waypoints(case)
        else:
            actions.append(MissionAction.HOLD_AND_REASSESS)
            hold_used = True
            timeline.hold_time_s += hold_duration_s
            timeline.events.append(MissionEvent(
                MissionState.OUTBOUND, case.departure_time,
                "HOLD_AND_REASSESS_STARTED_3H", "CAUSAL POLICY - FUTURE UNKNOWN",
            ))
            exposures.append(_stationary_exposure(
                store=store, case=case, started_at=case.departure_time,
                duration_s=hold_duration_s, parameters=parameters,
                interval_s=sampling_interval_s,
            ))
            reassessment_time = case.departure_time + timedelta(seconds=hold_duration_s)
            timeline.events.append(MissionEvent(
                MissionState.OUTBOUND, reassessment_time,
                "CAUSAL_REASSESSMENT_AFTER_HOLD", "OBSERVATION AVAILABLE ONLY AT REASSESSMENT TIME",
            ))
            _, reassessed = _response_at(store, case, reassessment_time, parameters)
            if reassessed.current.response_grid.robust_decision_status is RobustDecisionStatus.RESIDUAL_HIGH_RISK:
                return _terminal_return(
                    case=case, policy=policy, timeline=timeline, actions=actions,
                    exposures=exposures, reroute_used=False, hold_used=True,
                )
            actions.append(MissionAction.CONTINUE)
    else:
        actions.append(MissionAction.CONTINUE)

    outbound_start = case.departure_time + timedelta(seconds=timeline.hold_time_s)
    outbound = evaluate_spatiotemporal_route(
        route_id="OUTBOUND", waypoints=outbound_waypoints, started_at=outbound_start,
        speed_m_s=selected_speed, store=store, parameters=parameters,
        sampling_interval_s=sampling_interval_s, route_source_status=case.route_source_status,
    )
    direct_time = _distance(case.start, case.task_point) / selected_speed
    timeline.outbound_time_s = min(outbound.travel_time_s, direct_time)
    timeline.reroute_extra_time_s = max(0.0, outbound.travel_time_s - direct_time)
    exposures.append(outbound.exposure)
    on_station_at = outbound.ended_at
    timeline.events.append(MissionEvent(
        MissionState.ON_STATION, on_station_at, "TASK_POINT_REACHED",
        "SIMULATED MISSION POSITION",
    ))
    timeline.inspection_service_time_s = case.inspection_service_time_s
    inspection_exposure = _stationary_exposure(
        store=store, case=MissionCase(
            case.case_id, on_station_at, case.task_point, case.task_point,
            case.SOG_m_s, case.HDG_deg, case.inspection_service_time_s,
            case.route_source_status, case.selection_rule,
        ), started_at=on_station_at, duration_s=case.inspection_service_time_s,
        parameters=parameters, interval_s=sampling_interval_s,
    )
    exposures.append(inspection_exposure)
    inspection_done = on_station_at + timedelta(seconds=case.inspection_service_time_s)
    timeline.events.append(MissionEvent(
        MissionState.ON_STATION, inspection_done,
        "SIMULATED_INSPECTION_SERVICE_COMPLETED", SIMULATED_INSPECTION,
    ))
    timeline.events.append(MissionEvent(
        MissionState.RETURNING, inspection_done, "RETURN_STARTED", "SIMULATED MISSION TIMELINE",
    ))
    returning = evaluate_spatiotemporal_route(
        route_id="RETURN", waypoints=(case.task_point, case.start), started_at=inspection_done,
        speed_m_s=selected_speed, store=store, parameters=parameters,
        sampling_interval_s=sampling_interval_s, route_source_status=case.route_source_status,
    )
    timeline.return_time_s = returning.travel_time_s
    exposures.append(returning.exposure)
    timeline.events.append(MissionEvent(
        MissionState.COMPLETED, returning.ended_at, "SAFE_RETURN_AND_MISSION_CLOSED",
        "SIMULATED MISSION OUTCOME",
    ))
    exposure = combine_exposures(*exposures)
    return MissionReplayResult(
        case.case_id, policy.value, POLICY_DEFINITIONS[policy], MissionOutcomeStatus.COMPLETED,
        timeline.final_state, timeline, tuple(actions), exposure,
        assess_endurance(timeline.mission_elapsed_time_s), reroute_used, hold_used,
    )


@dataclass(frozen=True, slots=True)
class PolicyReplayMetrics:
    policy_name: str
    policy_definition: str
    denominator_N: int
    total_missions: int
    completed_missions: int
    pending_missions: int
    interrupted_missions: int
    unplanned_returns: int
    delayed_missions: int
    reroute_used_count: int
    hold_used_count: int
    completion_rate: float
    interruption_rate: float
    unplanned_return_rate: float
    average_total_mission_time_s: float
    average_time_penalty_s: float
    high_risk_exposure_time_s: float
    high_risk_exposure_ratio: float
    baseline_status: str = INTERNAL_BASELINE
    result_status: str = MODEL_BASED_REPLAY
    performance_status: str = NOT_OPERATIONAL_PERFORMANCE


def summarize_complete_replay(
    results: Sequence[MissionReplayResult], baseline_times: dict[str, float] | None = None,
) -> PolicyReplayMetrics:
    if not results:
        raise ValueError("complete replay summary needs results")
    n = len(results)
    completed = sum(item.mission_completed for item in results)
    pending = sum(item.outcome_status is MissionOutcomeStatus.PENDING_REASSESSMENT for item in results)
    interrupted = sum(item.outcome_status in {
        MissionOutcomeStatus.INTERRUPTED, MissionOutcomeStatus.RETURNED_UNPLANNED,
        MissionOutcomeStatus.ABORTED,
    } for item in results)
    returns = sum(item.outcome_status is MissionOutcomeStatus.RETURNED_UNPLANNED for item in results)
    delayed = sum(item.hold_used or item.outcome_status is MissionOutcomeStatus.DELAYED for item in results)
    total_time = sum(item.timeline.mission_elapsed_time_s for item in results)
    penalties = [
        max(0.0, item.timeline.mission_elapsed_time_s - (baseline_times or {}).get(item.case_id, item.timeline.mission_elapsed_time_s))
        for item in results
    ]
    high_time = sum(item.exposure.high_risk_exposure_time_s for item in results)
    evaluated = sum(item.exposure.total_evaluated_time_s for item in results)
    return PolicyReplayMetrics(
        results[0].policy_name, results[0].policy_definition, n, n, completed, pending,
        interrupted, returns, delayed, sum(item.reroute_used for item in results),
        sum(item.hold_used for item in results), completed / n, interrupted / n,
        returns / n, total_time / n, sum(penalties) / n, high_time,
        high_time / evaluated if evaluated else 0.0,
    )


def mission_saved(
    baseline: MissionReplayResult, hanhai: MissionReplayResult,
    *, maximum_acceptable_high_risk_ratio: float = 0.0,
) -> bool:
    baseline_failed = baseline.outcome_status in {
        MissionOutcomeStatus.INTERRUPTED, MissionOutcomeStatus.RETURNED_UNPLANNED,
        MissionOutcomeStatus.ABORTED,
    }
    evidence_supported = (
        hanhai.endurance.mission_time_feasibility_status
        == "WITHIN_PUBLISHED_MINIMUM_REFERENCE"
    )
    acceptable_risk = hanhai.exposure.risk_exposure_ratio <= maximum_acceptable_high_risk_ratio
    return baseline_failed and hanhai.mission_completed and evidence_supported and acceptable_risk


@dataclass(frozen=True, slots=True)
class BusinessValueGate:
    hold_never_directly_completed: bool
    no_future_action_leakage: bool
    exposure_computed_from_samples: bool
    saved_requires_full_completion: bool
    total_mission_time_computed: bool
    business_value_evidence: str
    interpretation: str = "DEVELOPMENT PASS DOES NOT ESTABLISH EMPIRICAL BUSINESS VALUE"


def evaluate_business_value_gate(
    *, results: Sequence[MissionReplayResult], future_action_leakage_count: int,
    saved_pairs: Sequence[tuple[MissionReplayResult, MissionReplayResult]] = (),
) -> BusinessValueGate:
    hold_ok = all(not (item.actions and item.actions[-1] is MissionAction.HOLD_AND_REASSESS and item.mission_completed) for item in results)
    exposure_ok = all(item.exposure.calculation_status == "COMPUTED_FROM_SPATIOTEMPORAL_ROUTE_SAMPLES" for item in results)
    time_ok = all(item.timeline.mission_elapsed_time_s >= 0 for item in results)
    saved_ok = all(
        not mission_saved(base, hanhai) or hanhai.mission_completed
        for base, hanhai in saved_pairs
    )
    values = (hold_ok, future_action_leakage_count == 0, exposure_ok, saved_ok, time_ok)
    return BusinessValueGate(
        hold_ok, values[1], exposure_ok, saved_ok, time_ok,
        "DEVELOPMENT_PASS" if all(values) else "FAIL",
    )
