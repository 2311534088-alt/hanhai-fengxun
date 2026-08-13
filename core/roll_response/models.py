"""Domain models for the unvalidated low-fidelity roll-response estimate."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


MODEL_STATUS = "LOW_FIDELITY_ENGINEERING_ESTIMATE"
VALIDATION_STATUS = "NOT VALIDATED AGAINST REAL ROLL DATA"
THRESHOLD_STATUS = "PRELIMINARY / NEEDS CALIBRATION"
GRID_METHOD = "DETERMINISTIC SENSITIVITY GRID"
GRID_STATISTICAL_STATUS = "NOT A STATISTICAL CONFIDENCE INTERVAL"


class ResonanceProximityStatus(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    HIGH = "HIGH"
    UNAVAILABLE = "UNAVAILABLE"


class RollResponseRisk(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    UNAVAILABLE = "UNAVAILABLE"


class RobustDecisionStatus(str, Enum):
    ROBUST_NORMAL = "ROBUST_NORMAL"
    ROBUST_MODERATE = "ROBUST_MODERATE"
    RESIDUAL_HIGH_RISK = "RESIDUAL_HIGH_RISK_UNDER_PARAMETER_UNCERTAINTY"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class RollResponseThresholds:
    moderate_at_or_above_deg: float
    high_at_or_above_deg: float
    minimum_relative_roll_reduction: float
    threshold_status: str = THRESHOLD_STATUS
    model_status: str = MODEL_STATUS
    validation_status: str = VALIDATION_STATUS

    def __post_init__(self) -> None:
        if not 0 < self.moderate_at_or_above_deg < self.high_at_or_above_deg:
            raise ValueError("roll-response thresholds must be positive and ordered")
        if not 0 <= self.minimum_relative_roll_reduction < 1:
            raise ValueError("minimum relative reduction must be in [0, 1)")
        if self.threshold_status != THRESHOLD_STATUS:
            raise ValueError("roll-response thresholds must be PRELIMINARY / NEEDS CALIBRATION")
        if self.model_status != MODEL_STATUS or self.validation_status != VALIDATION_STATUS:
            raise ValueError("low-fidelity response labels cannot be weakened")


@dataclass(frozen=True, slots=True)
class RollResponseAssessment:
    encounter_frequency_rad_s: float | None
    natural_roll_frequency_rad_s: float | None
    natural_roll_period_s: float | None
    frequency_ratio: float | None
    resonance_margin_ratio: float | None
    resonance_proximity_status: ResonanceProximityStatus
    wave_slope_proxy: float | None
    beam_excitation_factor: float | None
    roll_excitation_proxy: float | None
    dynamic_amplification_factor: float | None
    estimated_roll_response_rad: float | None
    estimated_roll_response_deg: float | None
    roll_response_risk: RollResponseRisk
    classification: str
    parameter_source: str
    parameter_status: str
    response_model_status: str = MODEL_STATUS
    response_validation_status: str = VALIDATION_STATUS
    threshold_status: str = THRESHOLD_STATUS


@dataclass(frozen=True, slots=True)
class RollResponseUncertainty:
    sample_count: int
    nominal_estimated_roll_response_deg: float
    grid_q10_estimated_roll_response_deg: float
    grid_q50_estimated_roll_response_deg: float
    grid_q90_estimated_roll_response_deg: float
    minimum_estimated_roll_response_deg: float
    maximum_estimated_roll_response_deg: float
    nominal_roll_risk: RollResponseRisk
    grid_q90_roll_risk: RollResponseRisk
    worst_case_roll_risk: RollResponseRisk
    robust_decision_status: RobustDecisionStatus
    natural_period_range_s: tuple[float, float]
    damping_ratio_range: tuple[float, float]
    parameter_source: str
    parameter_status: str
    response_model_status: str = MODEL_STATUS
    response_validation_status: str = VALIDATION_STATUS
    grid_method: str = GRID_METHOD
    grid_statistical_status: str = GRID_STATISTICAL_STATUS
