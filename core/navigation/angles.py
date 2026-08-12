"""Canonical navigation-angle helpers.

Environmental directions are direction-of-travel bearings: 0° North, 90° East.
Relative angle is 0° following, 90° beam, and 180° opposing.
"""

from math import isfinite


def normalize_bearing(angle: float) -> float:
    if not isinstance(angle, (int, float)) or not isfinite(angle):
        raise ValueError("bearing must be a finite number")
    return float(angle % 360.0)


def relative_environment_angle(environment_direction: float, heading: float) -> float:
    difference = abs(normalize_bearing(environment_direction) - normalize_bearing(heading))
    return min(difference, 360.0 - difference)


def relative_wave_angle(wave_direction: float, heading: float) -> float:
    return relative_environment_angle(wave_direction, heading)


def relative_wind_angle(wind_direction: float, heading: float) -> float:
    return relative_environment_angle(wind_direction, heading)
