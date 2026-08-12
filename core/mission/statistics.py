"""Mission-level result contract; unknown measurements remain null."""

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True, slots=True)
class MissionStatistics:
    mission_completed: bool | None = None
    mission_aborted: bool | None = None
    unplanned_return: bool | None = None
    mission_duration: timedelta | None = None
    distance_travelled: float | None = None
    energy_consumed: float | None = None

    def __post_init__(self) -> None:
        for name in ("distance_travelled", "energy_consumed"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.mission_duration is not None and self.mission_duration.total_seconds() < 0:
            raise ValueError("mission_duration cannot be negative")

