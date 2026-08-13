"""Mission-level advisory models; no real command semantics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.mission import MissionState


class MissionAction(str, Enum):
    CONTINUE = "CONTINUE"
    ADJUST_SPEED_HEADING = "ADJUST_SPEED_HEADING"
    REROUTE = "REROUTE"
    HOLD_AND_REASSESS = "HOLD_AND_REASSESS"
    DELAY_MISSION = "DELAY_MISSION"
    RETURN = "RETURN"


@dataclass(frozen=True, slots=True)
class HistoricalWindow:
    offset_hours: int
    Hs_m: float
    Tp_s: float
    wave_direction_deg: float
    grid_q90_roll_response_proxy: float
    robust_status: str
    acceptable: bool
    source_status: str = "HISTORICAL_ENVIRONMENT_REPLAY - NOT A FORECAST"


@dataclass(frozen=True, slots=True)
class RouteEvaluation:
    route_id: str
    waypoints: tuple[tuple[float, float], ...]
    integrated_roll_response_proxy_risk: float
    high_risk_exposure_steps: int
    estimated_travel_distance_m: float
    estimated_travel_time_s: float
    estimated_time_penalty_percent: float
    acceptable: bool
    source_status: str = "SIMULATED MISSION ROUTE"


@dataclass(frozen=True, slots=True)
class TechnicalOutcome:
    preferred_mission_action: MissionAction
    robust_status: str
    decision_reason: str
    local_adjustment_checked: bool
    reroute_checked: bool
    historical_windows_checked: bool
    return_last_resort: bool
    control_status: str = "DECISION ADVICE ONLY - REAL VESSEL CONTROL DISABLED"


@dataclass(frozen=True, slots=True)
class BusinessOutcome:
    mission_completed: bool
    mission_interrupted: bool
    unplanned_return: bool
    mission_delayed: bool
    reroute_used: bool
    hold_used: bool
    estimated_extra_travel_time_s: float
    high_risk_exposure_duration_or_steps: int
    result_status: str = "MODEL-BASED / HISTORICAL-ENVIRONMENT REPLAY"
    performance_status: str = "NOT REAL WIND-FARM OPERATIONAL PERFORMANCE"


@dataclass(frozen=True, slots=True)
class MissionDecision:
    mission_state: MissionState
    technical_outcome: TechnicalOutcome
    business_outcome: BusinessOutcome
    manufacturer_operating_context: dict
    model_calibration_warning: str | None
