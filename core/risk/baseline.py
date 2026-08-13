"""Transparent, preliminary risk baseline; not a certified safety model."""

from __future__ import annotations

import json
from math import cos, radians, sin
from pathlib import Path
from typing import Any

from core.models import TelemetryRecord
from core.navigation import relative_wave_angle, relative_wind_angle
from core.risk.models import RiskLevel, RiskResult, VesselParameters


DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "risk_baseline.json"


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


class BaselineRiskEvaluator:
    """Rule-based V0 baseline using configured, uncalibrated normalizers.

    This is not the planned multi-source attention-fusion algorithm. Every
    coefficient is marked preliminary in the external configuration.
    """

    def __init__(self, config_path: str | Path = DEFAULT_CONFIG) -> None:
        self.config: dict[str, Any] = json.loads(Path(config_path).read_text(encoding="utf-8"))
        if self.config.get("status") != "PRELIMINARY / NEEDS CALIBRATION":
            raise ValueError("risk configuration must be marked PRELIMINARY / NEEDS CALIBRATION")

    def evaluate(self, record: TelemetryRecord, vessel: VesselParameters) -> RiskResult:
        normalizers = self.config["normalizers"]
        weights = self.config["component_weights"]
        term_weights = self.config["term_weights"]
        available: set[str] = set()

        wave_terms: dict[str, float] = {}
        if record.Hs is not None:
            length = vessel.length_overall_m
            scale = length * normalizers["wave_height_to_length_ratio"] if length else normalizers["wave_height_m"]
            wave_terms["wave_height"] = _clamp(record.Hs / scale)
            available.add("Hs")
        wave_intensity = wave_terms.get("wave_height", 0.0)
        if record.Tp is not None:
            wave_terms["wave_period"] = wave_intensity * _clamp(
                normalizers["wave_period_reference_s"] / max(record.Tp, 0.1)
            )
            available.add("Tp")
        if record.wave_direction is not None and record.HDG is not None:
            angle = relative_wave_angle(record.wave_direction, record.HDG)
            wave_terms["relative_wave_angle"] = wave_intensity * sin(radians(angle)) ** 2
            available.update(("wave_direction", "HDG"))
            if record.SOG is not None:
                # Head seas increase this preliminary encounter-speed proxy.
                head_factor = (1.0 - cos(radians(angle))) / 2.0
                wave_terms["encounter_speed_proxy"] = wave_intensity * _clamp(
                    record.SOG / normalizers["sog_m_s"] * (0.5 + 0.5 * head_factor)
                )
                available.add("SOG")

        wind_terms: dict[str, float] = {}
        if record.wind_speed is not None:
            wind_terms["wind_speed"] = _clamp(record.wind_speed / normalizers["wind_speed_m_s"])
            available.add("wind_speed")
        wind_intensity = wind_terms.get("wind_speed", 0.0)
        if record.wind_direction is not None and record.HDG is not None:
            angle = relative_wind_angle(record.wind_direction, record.HDG)
            wind_terms["relative_wind_angle"] = wind_intensity * sin(radians(angle)) ** 2
            available.update(("wind_direction", "HDG"))

        motion_terms: dict[str, float] = {}
        for field_name, denominator in (
            ("roll", "roll_deg"), ("pitch", "pitch_deg"), ("roll_rate", "roll_rate_deg_s")
        ):
            value = getattr(record, field_name)
            if value is not None:
                motion_terms[field_name] = _clamp(abs(value) / normalizers[denominator])
                available.add(field_name)

        navigation_terms: dict[str, float] = {}
        if record.surface_current_speed is not None:
            navigation_terms["surface_current"] = _clamp(
                record.surface_current_speed / normalizers["surface_current_m_s"]
            )
            available.add("surface_current_speed")
        if record.SOG is not None:
            navigation_terms["speed"] = _clamp(record.SOG / normalizers["sog_m_s"])
            available.add("SOG")
        if record.battery is not None:
            navigation_terms["low_battery"] = _clamp(
                (normalizers["battery_caution_percent"] - record.battery)
                / normalizers["battery_caution_percent"]
            )
            available.add("battery")

        component_terms = {
            "wave_risk": wave_terms,
            "wind_risk": wind_terms,
            "motion_risk": motion_terms,
            "navigation_risk": navigation_terms,
        }
        components: dict[str, float] = {}
        for name, terms in component_terms.items():
            denominator = sum(term_weights[name][key] for key in terms)
            value = sum(term_weights[name][key] * value for key, value in terms.items()) / denominator if denominator else 0.0
            components[name] = round(10.0 * value, 2)
        weighted = sum(components[name] * weights[name] for name in components)
        score = round(min(10.0, max(0.0, weighted)), 2)
        primary = max(components, key=components.get) if any(components.values()) else "insufficient_data"
        level = RiskLevel.LOW if score < 4 else RiskLevel.MEDIUM if score < 7 else RiskLevel.HIGH
        recommendation = {
            RiskLevel.LOW: "Continue monitoring; operator retains authority.",
            RiskLevel.MEDIUM: "Consider reducing speed or adjusting heading after operator review.",
            RiskLevel.HIGH: "Pause/return assessment recommended; operator decision required.",
        }[level]
        expected = {
            "Hs", "Tp", "wave_direction", "wind_speed", "wind_direction",
            "surface_current_speed", "SOG", "HDG", "roll", "pitch", "roll_rate", "battery",
        }
        data_quality = round(len(available & expected) / len(expected), 2)
        if not any(components.values()):
            recommendation = "Hold decision and verify telemetry; zero is not proof of safety."
        term_text = "; ".join(
            f"{name}: " + (", ".join(f"{key}={value:.2f}" for key, value in terms.items()) or "unavailable")
            for name, terms in component_terms.items()
        )
        return RiskResult(
            risk_score=score,
            risk_level=level,
            primary_risk=primary,
            risk_components=components,
            recommendation=recommendation,
            data_quality=data_quality,
            explanation=(
                f"PRELIMINARY / NEEDS CALIBRATION rule baseline. Components are not trained weights. {term_text}. "
                "Unknown roll dynamics are not inferred."
            ),
        )
