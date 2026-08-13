"""Small route-level advisory evaluator for simulated mission routes."""

from __future__ import annotations

from math import atan2, cos, radians, sin, sqrt

from core.mission.decision.models import RouteEvaluation
from core.resonance.parameters import RollDynamicsParameters
from core.roll_response import RobustDecisionStatus, scan_roll_response_uncertainty


EARTH_RADIUS_M = 6_371_000.0


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lat2 = radians(a[0]), radians(b[0])
    dlat, dlon = lat2 - lat1, radians(b[1] - a[1])
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return EARTH_RADIUS_M * 2 * atan2(sqrt(h), sqrt(1 - h))


def _bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lat2 = radians(a[0]), radians(b[0])
    dlon = radians(b[1] - a[1])
    return (atan2(sin(dlon) * cos(lat2), cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(dlon)) * 180 / 3.141592653589793 + 360) % 360


def evaluate_simulated_route(
    *, route_id: str, waypoints: tuple[tuple[float, float], ...],
    environment_at, speed_m_s: float, parameters: RollDynamicsParameters,
    direct_distance_m: float | None = None, maximum_time_penalty_percent: float = 35.0,
) -> RouteEvaluation:
    if len(waypoints) < 2:
        raise ValueError("route needs at least two waypoints")
    proxies, high_steps, distance = [], 0, 0.0
    for start, end in zip(waypoints, waypoints[1:]):
        environment = environment_at(*start)
        heading = _bearing(start, end)
        relative = abs((environment.wave_direction - heading + 180) % 360 - 180)
        grid = scan_roll_response_uncertainty(
            Hs_m=environment.Hs, Tp_s=environment.Tp, vessel_speed_m_s=speed_m_s,
            relative_wave_angle_deg=relative, parameters=parameters,
        )
        proxies.append(grid.grid_q90_estimated_roll_response_deg)
        high_steps += int(grid.robust_decision_status is RobustDecisionStatus.RESIDUAL_HIGH_RISK)
        distance += _distance(start, end)
    direct = direct_distance_m or distance
    penalty = (distance / direct - 1.0) * 100.0 if direct else 0.0
    return RouteEvaluation(
        route_id, waypoints, sum(proxies), high_steps, distance, distance / speed_m_s,
        penalty, high_steps == 0 and penalty <= maximum_time_penalty_percent,
    )
