"""Wave-excitation-aware roll-response assessment and uncertainty scan."""

from __future__ import annotations

import json
from dataclasses import replace
from math import degrees, pi, radians, sin
from pathlib import Path

from core.resonance.parameters import RollDynamicsParameters
from core.resonance.physics import ResonanceStatus, assess_resonance
from core.roll_response.models import (
    MODEL_STATUS, VALIDATION_STATUS, ResonanceProximityStatus, RollResponseAssessment,
    RobustDecisionStatus, RollResponseRisk, RollResponseThresholds, RollResponseUncertainty,
)
from core.roll_response.physics import deep_water_wave_number, dynamic_amplification_factor


DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "roll_response_baseline.json"


def load_roll_response_thresholds(path: str | Path = DEFAULT_CONFIG) -> RollResponseThresholds:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    risk = data["risk_thresholds_deg"]
    return RollResponseThresholds(
        moderate_at_or_above_deg=float(risk["moderate_at_or_above"]),
        high_at_or_above_deg=float(risk["high_at_or_above"]),
        minimum_relative_roll_reduction=float(
            data["candidate_improvement"]["minimum_relative_roll_reduction"]
        ),
        threshold_status=str(data["threshold_status"]),
        model_status=str(data["model_status"]),
        validation_status=str(data["validation_status"]),
    )


def _proximity(status: ResonanceStatus) -> ResonanceProximityStatus:
    return {
        ResonanceStatus.NORMAL: ResonanceProximityStatus.NORMAL,
        ResonanceStatus.WARNING: ResonanceProximityStatus.WARNING,
        ResonanceStatus.HIGH_RISK: ResonanceProximityStatus.HIGH,
        ResonanceStatus.UNAVAILABLE: ResonanceProximityStatus.UNAVAILABLE,
    }[status]


def _risk(response_deg: float, thresholds: RollResponseThresholds) -> RollResponseRisk:
    if response_deg >= thresholds.high_at_or_above_deg:
        return RollResponseRisk.HIGH
    if response_deg >= thresholds.moderate_at_or_above_deg:
        return RollResponseRisk.MODERATE
    return RollResponseRisk.LOW


def robust_status(risk: RollResponseRisk) -> RobustDecisionStatus:
    return {
        RollResponseRisk.LOW: RobustDecisionStatus.ROBUST_NORMAL,
        RollResponseRisk.MODERATE: RobustDecisionStatus.ROBUST_MODERATE,
        RollResponseRisk.HIGH: RobustDecisionStatus.RESIDUAL_HIGH_RISK,
        RollResponseRisk.UNAVAILABLE: RobustDecisionStatus.UNAVAILABLE,
    }[risk]


def assess_roll_response(
    *,
    Hs_m: float,
    Tp_s: float,
    vessel_speed_m_s: float,
    relative_wave_angle_deg: float,
    parameters: RollDynamicsParameters,
    thresholds: RollResponseThresholds | None = None,
    damping_ratio: float | None = None,
) -> RollResponseAssessment:
    """Estimate a response proxy, not a real or validated vessel roll angle."""

    thresholds = thresholds or load_roll_response_thresholds()
    if Hs_m < 0:
        raise ValueError("Hs_m cannot be negative")
    if Tp_s <= 0 or vessel_speed_m_s < 0:
        raise ValueError("Tp_s must be positive and speed cannot be negative")
    if not 0 <= relative_wave_angle_deg <= 180:
        raise ValueError("relative_wave_angle_deg must be in [0, 180]")
    zeta = damping_ratio if damping_ratio is not None else parameters.equivalent_damping_ratio
    if zeta is None:
        raise ValueError("equivalent damping ratio is required for roll-response assessment")
    resonance = assess_resonance(
        Tp_s, vessel_speed_m_s, relative_wave_angle_deg, parameters=parameters,
    )
    if resonance.encounter_frequency_rad_s is None or resonance.natural_roll_frequency_rad_s is None:
        return RollResponseAssessment(
            resonance.encounter_frequency_rad_s, resonance.natural_roll_frequency_rad_s,
            resonance.natural_roll_period_s, None, resonance.resonance_margin_ratio,
            ResonanceProximityStatus.UNAVAILABLE, None, None, None, None, None, None,
            RollResponseRisk.UNAVAILABLE, "UNAVAILABLE", parameters.parameter_source.value,
            parameters.parameter_status,
        )
    ratio = resonance.encounter_frequency_rad_s / resonance.natural_roll_frequency_rad_s
    wave_slope = deep_water_wave_number(Tp_s) * Hs_m / 2.0
    beam_factor = abs(sin(radians(relative_wave_angle_deg)))
    excitation = wave_slope * beam_factor
    amplification = dynamic_amplification_factor(ratio, zeta)
    response_rad = excitation * amplification
    response_deg = degrees(response_rad)
    risk = _risk(response_deg, thresholds)
    proximity = _proximity(resonance.resonance_status)
    classification = (
        "FREQUENCY_CLOSE_LOW_EXCITATION"
        if proximity is ResonanceProximityStatus.HIGH and risk is RollResponseRisk.LOW
        else f"{risk.value}_ROLL_RESPONSE_RISK"
    )
    return RollResponseAssessment(
        resonance.encounter_frequency_rad_s,
        resonance.natural_roll_frequency_rad_s,
        resonance.natural_roll_period_s,
        ratio,
        resonance.resonance_margin_ratio,
        proximity,
        wave_slope,
        beam_factor,
        excitation,
        amplification,
        response_rad,
        response_deg,
        risk,
        classification,
        parameters.parameter_source.value,
        parameters.parameter_status,
        roll_response_proxy=response_deg,
        roll_response_degree_equivalent=response_deg,
    )


def _percentile(sorted_values: list[float], quantile: float) -> float:
    position = (len(sorted_values) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction


def scan_roll_response_uncertainty(
    *,
    Hs_m: float,
    Tp_s: float,
    vessel_speed_m_s: float,
    relative_wave_angle_deg: float,
    parameters: RollDynamicsParameters,
    thresholds: RollResponseThresholds | None = None,
    period_samples: int = 11,
    damping_samples: int = 5,
) -> RollResponseUncertainty:
    if period_samples < 2 or damping_samples < 2:
        raise ValueError("uncertainty scan needs at least two samples per parameter")
    period_low = parameters.natural_roll_period_lower_s
    period_high = parameters.natural_roll_period_upper_s
    damping_low = parameters.equivalent_damping_ratio_lower
    damping_high = parameters.equivalent_damping_ratio_upper
    if None in (period_low, period_high, damping_low, damping_high):
        raise ValueError("period and damping uncertainty bounds are required")
    periods = [period_low + (period_high - period_low) * i / (period_samples - 1) for i in range(period_samples)]
    dampings = [damping_low + (damping_high - damping_low) * i / (damping_samples - 1) for i in range(damping_samples)]
    values: list[float] = []
    for period in periods:
        varied = replace(
            parameters,
            natural_roll_period_s=period,
            natural_roll_frequency_rad_s=2.0 * pi / period,
        )
        for damping in dampings:
            assessment = assess_roll_response(
                Hs_m=Hs_m, Tp_s=Tp_s, vessel_speed_m_s=vessel_speed_m_s,
                relative_wave_angle_deg=relative_wave_angle_deg, parameters=varied,
                thresholds=thresholds, damping_ratio=damping,
            )
            values.append(assessment.estimated_roll_response_deg)
    values.sort()
    nominal = assess_roll_response(
        Hs_m=Hs_m, Tp_s=Tp_s, vessel_speed_m_s=vessel_speed_m_s,
        relative_wave_angle_deg=relative_wave_angle_deg, parameters=parameters,
        thresholds=thresholds,
    )
    grid_q90 = _percentile(values, 0.90)
    maximum = values[-1]
    configured_thresholds = thresholds or load_roll_response_thresholds()
    q90_risk = _risk(grid_q90, configured_thresholds)
    worst_risk = _risk(maximum, configured_thresholds)
    return RollResponseUncertainty(
        sample_count=len(values),
        nominal_estimated_roll_response_deg=nominal.estimated_roll_response_deg,
        grid_q10_estimated_roll_response_deg=_percentile(values, 0.10),
        grid_q50_estimated_roll_response_deg=_percentile(values, 0.50),
        grid_q90_estimated_roll_response_deg=grid_q90,
        minimum_estimated_roll_response_deg=values[0],
        maximum_estimated_roll_response_deg=maximum,
        nominal_roll_risk=nominal.roll_response_risk,
        grid_q90_roll_risk=q90_risk,
        worst_case_roll_risk=worst_risk,
        robust_decision_status=robust_status(q90_risk),
        natural_period_range_s=(period_low, period_high),
        damping_ratio_range=(damping_low, damping_high),
        parameter_source=parameters.parameter_source.value,
        parameter_status=parameters.parameter_status,
    )
