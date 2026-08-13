"""Low-fidelity linear roll frequency-response physics."""

from __future__ import annotations

from math import pi, sqrt


GRAVITY_M_S2 = 9.80665


def deep_water_wave_number(Tp_s: float) -> float:
    if Tp_s <= 0:
        raise ValueError("Tp_s must be positive")
    omega = 2.0 * pi / Tp_s
    return omega * omega / GRAVITY_M_S2


def dynamic_amplification_factor(frequency_ratio: float, damping_ratio: float) -> float:
    """Return the standard SDOF magnification factor.

    The denominator uses a sum of squared terms. A minus sign would make the
    exact-resonance expression non-real and is not the linear SDOF response.
    """

    if frequency_ratio < 0:
        raise ValueError("frequency_ratio cannot be negative")
    if not 0 < damping_ratio < 1:
        raise ValueError("damping_ratio must be between zero and one")
    return 1.0 / sqrt(
        (1.0 - frequency_ratio * frequency_ratio) ** 2
        + (2.0 * damping_ratio * frequency_ratio) ** 2
    )
