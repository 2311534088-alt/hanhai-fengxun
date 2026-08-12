"""Pre-SAC resonance physics; parameter sources remain explicit."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import cos, pi, radians

from core.resonance.parameters import (
    ParameterSource, ResonanceThresholds, RollDynamicsParameters, unavailable_parameters,
)


class ResonanceStatus(str, Enum):
    HIGH_RISK = "HIGH_RISK"
    WARNING = "WARNING"
    NORMAL = "NORMAL"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class ResonanceAssessment:
    encounter_frequency_rad_s: float | None
    natural_roll_frequency_rad_s: float | None
    natural_roll_period_s: float | None
    resonance_margin_rad_s: float | None
    resonance_margin_ratio: float | None
    resonance_status: ResonanceStatus
    parameter_source: ParameterSource
    parameter_status: str
    roll_amplification_indicator: float | None


def encounter_frequency(Tp_s: float | None, vessel_speed_m_s: float | None, relative_wave_angle_deg: float | None) -> float | None:
    if Tp_s is None or Tp_s <= 0 or vessel_speed_m_s is None or relative_wave_angle_deg is None:
        return None
    omega = 2 * pi / Tp_s
    wave_number = omega * omega / 9.80665  # Deep-water approximation; preliminary interface only.
    return max(0.0, omega - wave_number * vessel_speed_m_s * cos(radians(relative_wave_angle_deg)))


def assess_resonance(
    Tp_s: float | None,
    vessel_speed_m_s: float | None,
    relative_wave_angle_deg: float | None,
    roll_natural_period_s: float | None = None,
    measured_roll_deg: float | None = None,
    *,
    parameters: RollDynamicsParameters | None = None,
    thresholds: ResonanceThresholds | None = None,
) -> ResonanceAssessment:
    if parameters is None:
        parameters = (
            RollDynamicsParameters(
                natural_roll_period_s=roll_natural_period_s,
                natural_roll_frequency_rad_s=2 * pi / roll_natural_period_s,
                parameter_source=ParameterSource.MEASURED,
                parameter_status="LEGACY_CALLER_SUPPLIED",
            )
            if roll_natural_period_s is not None and roll_natural_period_s > 0
            else unavailable_parameters()
        )
    thresholds = thresholds or ResonanceThresholds()
    encountered = encounter_frequency(Tp_s, vessel_speed_m_s, relative_wave_angle_deg)
    natural = parameters.natural_roll_frequency_rad_s
    period = parameters.natural_roll_period_s
    amplification = abs(measured_roll_deg) if measured_roll_deg is not None else None
    if encountered is None or natural is None:
        return ResonanceAssessment(
            encountered, natural, period, None, None, ResonanceStatus.UNAVAILABLE,
            parameters.parameter_source, parameters.parameter_status, amplification,
        )
    margin = abs(encountered - natural)
    ratio = margin / natural
    if ratio < thresholds.high_risk_below_ratio:
        status = ResonanceStatus.HIGH_RISK
    elif ratio < thresholds.warning_below_ratio:
        status = ResonanceStatus.WARNING
    else:
        status = ResonanceStatus.NORMAL
    return ResonanceAssessment(
        encountered, natural, period, margin, ratio, status,
        parameters.parameter_source, parameters.parameter_status, amplification,
    )
