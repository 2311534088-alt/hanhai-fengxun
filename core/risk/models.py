"""Risk evaluation input/output contracts."""

from dataclasses import dataclass
from enum import Enum


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True, slots=True)
class VesselParameters:
    model: str
    length_overall_m: float | None = None
    beam_m: float | None = None
    draft_m: float | None = None
    hull_mass_approx_kg: float | None = None
    full_load_displacement_min_kg: float | None = None
    roll_natural_period_s: float | None = None
    metacentric_height_m: float | None = None
    roll_damping_ratio: float | None = None
    roll_moment_of_inertia_kg_m2: float | None = None

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("vessel model is required")
        for name in (
            "length_overall_m", "beam_m", "draft_m", "hull_mass_approx_kg",
            "full_load_displacement_min_kg", "roll_natural_period_s",
            "metacentric_height_m", "roll_damping_ratio", "roll_moment_of_inertia_kg_m2",
        ):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive or null")


@dataclass(frozen=True, slots=True)
class RiskResult:
    risk_score: float
    risk_level: RiskLevel
    primary_risk: str
    risk_components: dict[str, float]
    recommendation: str
    data_quality: float
    explanation: str

    def __post_init__(self) -> None:
        if not 0 <= self.risk_score <= 10:
            raise ValueError("risk_score must be in [0, 10]")
        if not 0 <= self.data_quality <= 1:
            raise ValueError("data_quality must be in [0, 1]")
        if any(not 0 <= value <= 10 for value in self.risk_components.values()):
            raise ValueError("risk component scores must be in [0, 10]")

