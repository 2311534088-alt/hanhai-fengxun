"""Configuration-driven roll dynamics with explicit source priority."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


DEFAULT_ESTIMATE_CONFIG = Path(__file__).resolve().parents[2] / "configs/zlusv200_estimated_dynamics.yaml"


class ParameterSource(str, Enum):
    MEASURED = "MEASURED"
    ENGINEERING_ESTIMATE = "ENGINEERING_ESTIMATE"
    UNAVAILABLE = "UNAVAILABLE"


SOURCE_PRIORITY = {
    ParameterSource.UNAVAILABLE: 0,
    ParameterSource.ENGINEERING_ESTIMATE: 1,
    ParameterSource.MEASURED: 2,
}


@dataclass(frozen=True, slots=True)
class RollDynamicsParameters:
    natural_roll_period_s: float | None
    natural_roll_frequency_rad_s: float | None
    parameter_source: ParameterSource
    parameter_status: str
    natural_roll_period_lower_s: float | None = None
    natural_roll_period_upper_s: float | None = None
    equivalent_damping_ratio: float | None = None
    equivalent_damping_ratio_lower: float | None = None
    equivalent_damping_ratio_upper: float | None = None

    def __post_init__(self) -> None:
        for name in ("natural_roll_period_s", "natural_roll_frequency_rad_s"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive or null")
        if (self.natural_roll_period_s is None) != (self.natural_roll_frequency_rad_s is None):
            raise ValueError("period and frequency must both be available or unavailable")
        for name in ("natural_roll_period_lower_s", "natural_roll_period_upper_s"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive or null")
        for name in (
            "equivalent_damping_ratio", "equivalent_damping_ratio_lower",
            "equivalent_damping_ratio_upper",
        ):
            value = getattr(self, name)
            if value is not None and not 0 < value < 1:
                raise ValueError(f"{name} must be between zero and one or null")
        if (self.natural_roll_period_lower_s is None) != (self.natural_roll_period_upper_s is None):
            raise ValueError("natural roll period uncertainty bounds must both be available or unavailable")
        if (self.equivalent_damping_ratio_lower is None) != (self.equivalent_damping_ratio_upper is None):
            raise ValueError("damping uncertainty bounds must both be available or unavailable")
        if self.natural_roll_period_s is not None and self.natural_roll_period_lower_s is not None:
            if not self.natural_roll_period_lower_s <= self.natural_roll_period_s <= self.natural_roll_period_upper_s:
                raise ValueError("natural roll period bounds must contain nominal")
        if self.equivalent_damping_ratio is not None and self.equivalent_damping_ratio_lower is not None:
            if not self.equivalent_damping_ratio_lower <= self.equivalent_damping_ratio <= self.equivalent_damping_ratio_upper:
                raise ValueError("damping ratio bounds must contain nominal")


@dataclass(frozen=True, slots=True)
class ResonanceThresholds:
    high_risk_below_ratio: float = 0.10
    warning_below_ratio: float = 0.20
    status: str = "PRELIMINARY / NEEDS CALIBRATION"

    def __post_init__(self) -> None:
        if not 0 < self.high_risk_below_ratio < self.warning_below_ratio:
            raise ValueError("resonance ratio thresholds must be positive and ordered")
        if self.status != "PRELIMINARY / NEEDS CALIBRATION":
            raise ValueError("resonance thresholds must be marked PRELIMINARY / NEEDS CALIBRATION")


def unavailable_parameters() -> RollDynamicsParameters:
    return RollDynamicsParameters(None, None, ParameterSource.UNAVAILABLE, "UNAVAILABLE")


def load_roll_dynamics(path: str | Path) -> tuple[RollDynamicsParameters, ResonanceThresholds]:
    data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    source = ParameterSource(data["parameter_source"])
    parameters = RollDynamicsParameters(
        natural_roll_period_s=float(data["natural_roll_period_s"]["nominal"]),
        natural_roll_frequency_rad_s=float(data["natural_roll_frequency_rad_s"]["nominal"]),
        parameter_source=source,
        parameter_status=str(data["parameter_status"]),
        natural_roll_period_lower_s=float(data["natural_roll_period_s"]["lower"]),
        natural_roll_period_upper_s=float(data["natural_roll_period_s"]["upper"]),
        equivalent_damping_ratio=float(data["equivalent_damping_ratio"]["nominal"]),
        equivalent_damping_ratio_lower=float(data["equivalent_damping_ratio"]["lower"]),
        equivalent_damping_ratio_upper=float(data["equivalent_damping_ratio"]["upper"]),
    )
    thresholds_data = data["resonance_thresholds"]
    thresholds = ResonanceThresholds(
        high_risk_below_ratio=float(thresholds_data["high_risk_below_ratio"]),
        warning_below_ratio=float(thresholds_data["warning_below_ratio"]),
        status=str(thresholds_data["status"]),
    )
    return parameters, thresholds


def load_engineering_estimate(
    path: str | Path = DEFAULT_ESTIMATE_CONFIG,
) -> tuple[RollDynamicsParameters, ResonanceThresholds]:
    parameters, thresholds = load_roll_dynamics(path)
    if parameters.parameter_source != ParameterSource.ENGINEERING_ESTIMATE:
        raise ValueError("engineering estimate config must use ENGINEERING_ESTIMATE source")
    if parameters.parameter_status != "NOT_EXPERIMENTALLY_CALIBRATED":
        raise ValueError("engineering estimate must be marked NOT_EXPERIMENTALLY_CALIBRATED")
    return parameters, thresholds


def select_parameters(*candidates: RollDynamicsParameters) -> RollDynamicsParameters:
    return max(candidates or (unavailable_parameters(),), key=lambda item: SOURCE_PRIORITY[item.parameter_source])
