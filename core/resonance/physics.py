"""Pre-SAC physical interface; unavailable values are never guessed."""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, pi, radians


@dataclass(frozen=True, slots=True)
class ResonanceAssessment:
    encounter_frequency_rad_s: float | None
    natural_roll_frequency_rad_s: float | None
    resonance_margin_rad_s: float | None
    roll_amplification_indicator: float | None
    status: str


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
    roll_natural_period_s: float | None,
    measured_roll_deg: float | None = None,
) -> ResonanceAssessment:
    encountered = encounter_frequency(Tp_s, vessel_speed_m_s, relative_wave_angle_deg)
    natural = 2 * pi / roll_natural_period_s if roll_natural_period_s is not None and roll_natural_period_s > 0 else None
    if encountered is None or natural is None:
        return ResonanceAssessment(encountered, natural, None, None, "unavailable")
    margin = abs(encountered - natural)
    amplification = abs(measured_roll_deg) if measured_roll_deg is not None else None
    return ResonanceAssessment(encountered, natural, margin, amplification, "available_preliminary")

