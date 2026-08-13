import json
import unittest
from dataclasses import replace
from math import pi
from pathlib import Path

from core.resonance import load_engineering_estimate, search_resonance_avoidance
from core.roll_response import (
    ResonanceProximityStatus, RollResponseRisk, assess_roll_response,
    dynamic_amplification_factor, scan_roll_response_uncertainty,
)


ROOT = Path(__file__).resolve().parents[1]


class RollResponsePhysicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parameters, cls.resonance_thresholds = load_engineering_estimate()

    def test_near_zero_wave_height_stays_low_at_exact_resonance(self):
        exact = replace(
            self.parameters,
            natural_roll_period_s=1.70,
            natural_roll_frequency_rad_s=2 * pi / 1.70,
        )
        result = assess_roll_response(
            Hs_m=1e-6, Tp_s=1.70, vessel_speed_m_s=0.0,
            relative_wave_angle_deg=90.0, parameters=exact,
        )
        self.assertEqual(result.resonance_proximity_status, ResonanceProximityStatus.HIGH)
        self.assertEqual(result.roll_response_risk, RollResponseRisk.LOW)
        self.assertLess(result.estimated_roll_response_deg, 0.01)

    def test_beam_excitation_exceeds_following_and_head_seas_proxy(self):
        following = assess_roll_response(
            Hs_m=0.5, Tp_s=3.0, vessel_speed_m_s=0.0,
            relative_wave_angle_deg=0.0, parameters=self.parameters,
        )
        beam = assess_roll_response(
            Hs_m=0.5, Tp_s=3.0, vessel_speed_m_s=0.0,
            relative_wave_angle_deg=90.0, parameters=self.parameters,
        )
        head = assess_roll_response(
            Hs_m=0.5, Tp_s=3.0, vessel_speed_m_s=0.0,
            relative_wave_angle_deg=180.0, parameters=self.parameters,
        )
        self.assertGreater(beam.roll_excitation_proxy, following.roll_excitation_proxy)
        self.assertGreater(beam.roll_excitation_proxy, head.roll_excitation_proxy)
        self.assertAlmostEqual(following.roll_excitation_proxy, 0.0, places=12)
        self.assertAlmostEqual(head.roll_excitation_proxy, 0.0, places=12)

    def test_exact_resonance_dynamic_amplification_is_one_over_two_zeta(self):
        self.assertAlmostEqual(dynamic_amplification_factor(1.0, 0.18), 1.0 / (2.0 * 0.18), places=12)

    def test_increasing_damping_reduces_dynamic_amplification(self):
        self.assertGreater(dynamic_amplification_factor(1.0, 0.10), dynamic_amplification_factor(1.0, 0.30))

    def test_frequency_close_low_excitation_is_classified_separately(self):
        result = assess_roll_response(
            Hs_m=0.14, Tp_s=2.48, vessel_speed_m_s=2.1,
            relative_wave_angle_deg=135.0, parameters=self.parameters,
        )
        self.assertEqual(result.resonance_proximity_status, ResonanceProximityStatus.HIGH)
        self.assertEqual(result.roll_response_risk, RollResponseRisk.LOW)
        self.assertEqual(result.classification, "FREQUENCY_CLOSE_LOW_EXCITATION")

    def test_uncertainty_scan_preserves_source_and_ordered_percentiles(self):
        result = scan_roll_response_uncertainty(
            Hs_m=0.38, Tp_s=2.02, vessel_speed_m_s=1.8,
            relative_wave_angle_deg=105.0, parameters=self.parameters,
        )
        self.assertEqual(result.sample_count, 55)
        self.assertLessEqual(result.p10_estimated_roll_response_deg, result.p50_estimated_roll_response_deg)
        self.assertLessEqual(result.p50_estimated_roll_response_deg, result.p90_estimated_roll_response_deg)
        self.assertEqual(result.natural_period_range_s, (1.32, 2.32))
        self.assertEqual(result.damping_ratio_range, (0.10, 0.30))
        self.assertEqual(result.parameter_source, "ENGINEERING_ESTIMATE")
        self.assertEqual(result.parameter_status, "NOT_EXPERIMENTALLY_CALIBRATED")
        self.assertEqual(result.response_model_status, "LOW_FIDELITY_ENGINEERING_ESTIMATE")


class RollAwareAvoidanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parameters, cls.resonance_thresholds = load_engineering_estimate()

    def test_roll_aware_search_never_selects_increased_response(self):
        result = search_resonance_avoidance(
            Hs_m=0.38, Tp_s=2.02, wave_direction_deg=109.66,
            current_speed_m_s=1.8, current_heading_deg=214.66,
            parameters=self.parameters, thresholds=self.resonance_thresholds,
        )
        self.assertLess(
            result.recommended.estimated_roll_response_deg,
            result.current.estimated_roll_response_deg,
        )
        for plan in (result.speed_only, result.heading_only, result.joint):
            if plan.recommended is not None:
                self.assertLessEqual(
                    plan.recommended.estimated_roll_response_deg,
                    plan.current.estimated_roll_response_deg,
                )

    def test_low_excitation_frequency_close_case_does_not_force_adjustment(self):
        result = search_resonance_avoidance(
            Hs_m=0.14, Tp_s=2.48, wave_direction_deg=99.93,
            current_speed_m_s=2.1, current_heading_deg=234.93,
            parameters=self.parameters, thresholds=self.resonance_thresholds,
        )
        self.assertEqual(result.current.resonance_proximity_status, ResonanceProximityStatus.HIGH)
        self.assertEqual(result.current.roll_response_risk, RollResponseRisk.LOW)
        self.assertEqual(result.recommended.SOG_m_s, result.current.SOG_m_s)
        self.assertEqual(result.recommended.HDG_deg, result.current.HDG_deg)

    def test_frequency_margin_conflict_is_recorded_while_response_still_decreases(self):
        result = search_resonance_avoidance(
            Hs_m=0.23, Tp_s=2.14, wave_direction_deg=170.48,
            current_speed_m_s=0.9, current_heading_deg=305.48,
            parameters=self.parameters, thresholds=self.resonance_thresholds,
        )
        plan = result.heading_only
        self.assertLess(plan.recommended.resonance_margin_ratio, plan.current.resonance_margin_ratio)
        self.assertLess(plan.recommended.estimated_roll_response_deg, plan.current.estimated_roll_response_deg)
        self.assertIn("Frequency-margin conflict recorded", plan.decision_reason)


class RollResponseEvidenceTests(unittest.TestCase):
    def test_real_environment_simulated_state_and_estimate_labels_are_preserved(self):
        data = json.loads(
            (ROOT / "data" / "results" / "v0.4_roll_response_demo.json").read_text(encoding="utf-8")
        )
        self.assertEqual(data["environment_source"], "REAL PUBLIC ENVIRONMENT DATA - NOT IN-SITU ZHUANGHE OBSERVATION")
        self.assertEqual(data["vessel_state_source"], "SIMULATED VESSEL STATE")
        self.assertEqual(data["parameter_classification"], "ENGINEERING_ESTIMATE / NOT_EXPERIMENTALLY_CALIBRATED")
        self.assertEqual(data["response_model_status"], "LOW_FIDELITY_ENGINEERING_ESTIMATE")
        self.assertEqual(data["response_validation_status"], "NOT VALIDATED AGAINST REAL ROLL DATA")
        self.assertEqual(len(data["scenarios"]), 3)
        self.assertIn("NOT SAC", data["algorithm_status"])
        self.assertIn("CONTROL DISABLED", data["control_status"])
        for scenario in data["scenarios"]:
            self.assertEqual(len(scenario["environment"]["provenance_by_field"]), 8)
            self.assertTrue(all(
                item["decision"] == "ACCEPTED"
                for item in scenario["environment"]["provenance_by_field"].values()
            ))
            self.assertIsNone(scenario["simulated_vessel_state"]["roll"])
            self.assertIsNone(scenario["simulated_vessel_state"]["pitch"])

        classifications = {
            item["scenario_id"]: item["before"]["roll_response_risk"] for item in data["scenarios"]
        }
        self.assertEqual(classifications["FREQUENCY_CLOSE_LOW_EXCITATION"], "LOW")
        self.assertEqual(classifications["MODERATE_ROLL_RESPONSE_RISK"], "MODERATE")
        self.assertEqual(classifications["HIGH_ROLL_RESPONSE_RISK"], "HIGH")


if __name__ == "__main__":
    unittest.main()
