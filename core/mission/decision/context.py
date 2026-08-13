"""Manufacturer context and conservative-model warning helpers."""

from __future__ import annotations


def manufacturer_operating_context(wind_force: int = 4, sea_state: int = 3) -> dict:
    return {
        "wind_force": wind_force,
        "sea_state": sea_state,
        "source": "MANUFACTURER CAPABILITY CONTEXT PROVIDED BY PROJECT",
        "interpretation_limit": (
            "CONTEXT ONLY - NOT PROOF THAT EVERY CONDITION IN THIS CATEGORY IS SAFE; "
            "AN UNCALIBRATED RESPONSE PROXY MUST NOT OVERRIDE MANUFACTURER CAPABILITY BY ITSELF"
        ),
    }


def calibration_warning(Hs_m: float, roll_response_proxy: float) -> str | None:
    if Hs_m <= 1.25 and roll_response_proxy >= 15.0:
        return (
            "MODEL_CALIBRATION_WARNING: LOW-FIDELITY RESPONSE MODEL MAY BE CONSERVATIVE / "
            "REQUIRES REAL ROLL VALIDATION"
        )
    return None
