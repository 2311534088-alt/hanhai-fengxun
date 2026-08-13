"""Safety-first mission-continuity advisory policy."""

from __future__ import annotations

from core.mission import MissionState
from core.mission.decision.models import (
    BusinessOutcome, HistoricalWindow, MissionAction, MissionDecision, RouteEvaluation,
    TechnicalOutcome,
)


def decide_mission_action(
    *, mission_state: MissionState, current_robust_status: str,
    constrained_adjustment_acceptable: bool,
    route_candidates: tuple[RouteEvaluation, ...] = (),
    historical_windows: tuple[HistoricalWindow, ...] = (),
    manufacturer_operating_context: dict | None = None,
    model_calibration_warning: str | None = None,
) -> MissionDecision:
    high = current_robust_status == "RESIDUAL_HIGH_RISK_UNDER_PARAMETER_UNCERTAINTY"
    safe_routes = [item for item in route_candidates if item.acceptable]
    safe_windows = [item for item in historical_windows if item.acceptable]
    if not high:
        action, reason = MissionAction.CONTINUE, "Robust response proxy is acceptable; continue with monitoring."
    elif mission_state is MissionState.PRE_DEPARTURE:
        action, reason = MissionAction.DELAY_MISSION, "High risk before departure; wait for an acceptable historical-window analogue."
    elif constrained_adjustment_acceptable:
        action, reason = MissionAction.ADJUST_SPEED_HEADING, "A constrained local advisory reduces robust risk to an acceptable level."
    elif safe_routes:
        action, reason = MissionAction.REROUTE, "A simulated route lowers high-risk exposure within the configured time penalty."
    elif safe_windows:
        earliest = min(safe_windows, key=lambda item: item.offset_hours)
        action = MissionAction.HOLD_AND_REASSESS
        reason = f"Historical replay shows an acceptable window after {earliest.offset_hours} h; hold before return assessment."
    elif mission_state is MissionState.RETURNING:
        action, reason = MissionAction.HOLD_AND_REASSESS, "Already returning; hold/reassess advice does not reverse into a new return command."
    else:
        action, reason = MissionAction.RETURN, "Local adjustment, route advisory and 6 h historical replay found no acceptable alternative."
    extra_time = 0.0
    if action is MissionAction.REROUTE and safe_routes:
        direct = next((item for item in route_candidates if item.route_id == "DIRECT"), None)
        selected = min(safe_routes, key=lambda item: item.estimated_travel_time_s)
        extra_time = max(0.0, selected.estimated_travel_time_s - (direct.estimated_travel_time_s if direct else 0.0))
    if action is MissionAction.HOLD_AND_REASSESS and safe_windows:
        extra_time = min(item.offset_hours for item in safe_windows) * 3600.0
    interrupted = action in (MissionAction.RETURN, MissionAction.DELAY_MISSION)
    business = BusinessOutcome(
        mission_completed=action in (MissionAction.CONTINUE, MissionAction.ADJUST_SPEED_HEADING, MissionAction.REROUTE, MissionAction.HOLD_AND_REASSESS),
        mission_interrupted=interrupted,
        unplanned_return=action is MissionAction.RETURN,
        mission_delayed=action in (MissionAction.DELAY_MISSION, MissionAction.HOLD_AND_REASSESS),
        reroute_used=action is MissionAction.REROUTE,
        hold_used=action is MissionAction.HOLD_AND_REASSESS,
        estimated_extra_travel_time_s=extra_time,
        high_risk_exposure_duration_or_steps=0 if action is not MissionAction.RETURN else 1,
    )
    return MissionDecision(
        mission_state=mission_state,
        technical_outcome=TechnicalOutcome(
            action, current_robust_status, reason, True, bool(route_candidates),
            bool(historical_windows), action is MissionAction.RETURN,
        ),
        business_outcome=business,
        manufacturer_operating_context=manufacturer_operating_context or {},
        model_calibration_warning=model_calibration_warning,
    )
