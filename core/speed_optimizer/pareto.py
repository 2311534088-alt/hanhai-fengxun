"""Pareto contract only; this is not the final speed optimizer."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParetoCandidate:
    candidate_speed: float
    safety_cost: float
    time_cost: float
    energy_cost: float | None
    energy_model_status: str


def evaluate_candidates(
    candidate_speeds: Iterable[float],
    safety_cost: Callable[[float], float],
    distance_m: float,
    energy_cost: Callable[[float], float] | None = None,
) -> list[ParetoCandidate]:
    if distance_m < 0:
        raise ValueError("distance_m cannot be negative")
    results: list[ParetoCandidate] = []
    for speed in candidate_speeds:
        if speed <= 0:
            raise ValueError("candidate_speed must be positive")
        results.append(ParetoCandidate(
            candidate_speed=speed,
            safety_cost=safety_cost(speed),
            time_cost=distance_m / speed,
            energy_cost=energy_cost(speed) if energy_cost else None,
            energy_model_status="DEMO ONLY" if energy_cost else "unavailable",
        ))
    return results

