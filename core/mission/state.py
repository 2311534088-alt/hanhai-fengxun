"""Mission finite-state machine with explicit legal transitions."""

from dataclasses import dataclass
from enum import Enum


class MissionState(str, Enum):
    PRE_DEPARTURE = "PRE_DEPARTURE"
    OUTBOUND = "OUTBOUND"
    ON_STATION = "ON_STATION"
    RETURNING = "RETURNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


LEGAL_TRANSITIONS: dict[MissionState, frozenset[MissionState]] = {
    MissionState.PRE_DEPARTURE: frozenset({MissionState.OUTBOUND, MissionState.ABORTED}),
    MissionState.OUTBOUND: frozenset({MissionState.ON_STATION, MissionState.RETURNING, MissionState.ABORTED}),
    MissionState.ON_STATION: frozenset({MissionState.RETURNING, MissionState.ABORTED}),
    MissionState.RETURNING: frozenset({MissionState.COMPLETED, MissionState.ABORTED}),
    MissionState.COMPLETED: frozenset(),
    MissionState.ABORTED: frozenset(),
}


@dataclass(slots=True)
class MissionStateMachine:
    state: MissionState = MissionState.PRE_DEPARTURE

    def can_transition(self, target: MissionState) -> bool:
        return target in LEGAL_TRANSITIONS[self.state]

    def transition(self, target: MissionState) -> None:
        if not self.can_transition(target):
            raise ValueError(f"illegal mission transition: {self.state.value} -> {target.value}")
        self.state = target

