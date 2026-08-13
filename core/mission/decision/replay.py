"""Internal policy comparison for model-based historical-environment replay."""

from __future__ import annotations

from dataclasses import dataclass


REPLAY_STATUS = "MODEL-BASED / HISTORICAL-ENVIRONMENT REPLAY"
PERFORMANCE_STATUS = "NOT REAL WIND-FARM OPERATIONAL PERFORMANCE"


@dataclass(frozen=True, slots=True)
class SimulatedMissionOutcome:
    mission_completed: bool
    mission_interrupted: bool
    unplanned_return: bool
    mission_delayed: bool
    estimated_extra_travel_time_s: float
    high_risk_exposure_steps: int


@dataclass(frozen=True, slots=True)
class PolicyReplaySummary:
    policy_name: str
    policy_definition: str
    simulated_mission_count: int
    simulated_mission_completion_rate: float
    simulated_interruption_rate: float
    simulated_unplanned_return_rate: float
    simulated_delay_rate: float
    average_time_penalty_s: float
    risk_exposure_metric_steps: int
    result_status: str = REPLAY_STATUS
    performance_status: str = PERFORMANCE_STATUS


def summarize_policy_replay(
    policy_name: str,
    policy_definition: str,
    outcomes: tuple[SimulatedMissionOutcome, ...],
) -> PolicyReplaySummary:
    if not outcomes:
        raise ValueError("policy replay needs at least one simulated mission")
    count = len(outcomes)
    rate = lambda field: sum(bool(getattr(item, field)) for item in outcomes) / count
    return PolicyReplaySummary(
        policy_name=policy_name, policy_definition=policy_definition,
        simulated_mission_count=count,
        simulated_mission_completion_rate=rate("mission_completed"),
        simulated_interruption_rate=rate("mission_interrupted"),
        simulated_unplanned_return_rate=rate("unplanned_return"),
        simulated_delay_rate=rate("mission_delayed"),
        average_time_penalty_s=sum(item.estimated_extra_travel_time_s for item in outcomes) / count,
        risk_exposure_metric_steps=sum(item.high_risk_exposure_steps for item in outcomes),
    )
