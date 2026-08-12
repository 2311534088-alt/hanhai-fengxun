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

    def __post_init__(self) -> None:
        for name in ("natural_roll_period_s", "natural_roll_frequency_rad_s"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive or null")
        if (self.natural_roll_period_s is None) != (self.natural_roll_frequency_rad_s is None):
            raise ValueError("period and frequency must both be available or unavailable")


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
