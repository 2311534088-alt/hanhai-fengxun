import json
import unittest
from pathlib import Path

from core.resonance import (
    DecisionStatus,
    ResonanceStatus,
    SearchLimits,
    load_engineering_estimate,
    search_resonance_avoidance,
)


ROOT = Path(__file__).resolve().parents[1]


class ResonanceAvoidanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parameters, cls.thresholds = load_engineering_estimate()

    def _high_risk_search(self, limits=None):
        return search_resonance_avoidance(
            Tp_s=2.48,
            wave_direction_deg=99.93,
            current_speed_m_s=2.1,
            current_heading_deg=234.93,
            parameters=self.parameters,
            thresholds=self.thresholds,
            limits=limits,
        )

    def test_high_risk_search_recommends_a_genuinely_better_candidate(self):
        result = self._high_risk_search()
        self.assertEqual(result.current.resonance_status, ResonanceStatus.HIGH_RISK)
        self.assertEqual(result.decision_status, DecisionStatus.RECOMMENDED)
        self.assertIsNotNone(result.recommended)
        self.assertGreater(result.recommended.resonance_margin_ratio, result.current.resonance_margin_ratio)
        self.assertIn(result.recommended.resonance_status, (ResonanceStatus.WARNING, ResonanceStatus.NORMAL))
        self.assertEqual(result.current_speed, 2.1)
        self.assertEqual(result.recommended_speed, result.recommended.SOG_m_s)
        self.assertEqual(result.current_margin_ratio, result.current.resonance_margin_ratio)
        self.assertEqual(result.recommended_margin_ratio, result.recommended.resonance_margin_ratio)
        self.assertEqual(result.speed_change_percent, result.recommended.speed_change_percent)

    def test_no_safe_candidate_is_explicit_when_limits_allow_no_change(self):
        limits = SearchLimits(
            minimum_speed_m_s=2.1,
            maximum_speed_m_s=2.1,
            speed_step_m_s=0.1,
            heading_offsets_deg=(0.0,),
        )
        result = self._high_risk_search(limits)
        self.assertEqual(result.decision_status, DecisionStatus.NO_SAFE_CANDIDATE)
        self.assertIsNone(result.recommended)
        self.assertIn("PAUSE / RETURN ASSESSMENT", result.decision_reason)

    def test_recommendations_never_exceed_speed_or_heading_limits(self):
        result = self._high_risk_search()
        for plan in (result.speed_only, result.heading_only, result.joint):
            if plan.recommended is None:
                continue
            self.assertGreaterEqual(plan.recommended.SOG_m_s, 0.5)
            self.assertLessEqual(plan.recommended.SOG_m_s, 3.0)
            self.assertLessEqual(abs(plan.recommended.heading_change_deg), 15.0)
        self.assertNotEqual(result.joint.recommended.SOG_m_s, result.current.SOG_m_s)
        self.assertNotEqual(result.joint.recommended.heading_change_deg, 0.0)

    def test_currently_safe_state_is_retained_without_large_adjustment(self):
        result = search_resonance_avoidance(
            Tp_s=3.17,
            wave_direction_deg=124.78,
            current_speed_m_s=1.5,
            current_heading_deg=304.78,
            parameters=self.parameters,
            thresholds=self.thresholds,
        )
        self.assertEqual(result.current.resonance_status, ResonanceStatus.NORMAL)
        self.assertEqual(result.decision_status, DecisionStatus.CURRENT_STATE_ACCEPTABLE)
        self.assertEqual(result.recommended.SOG_m_s, 1.5)
        self.assertEqual(result.recommended.HDG_deg, 304.78)
        self.assertEqual(result.recommended.speed_change_percent, 0.0)
        self.assertEqual(result.recommended.heading_change_deg, 0.0)

    def test_parameter_source_and_status_are_preserved(self):
        result = self._high_risk_search()
        for candidate in (result.current, result.recommended):
            self.assertEqual(candidate.parameter_source, "ENGINEERING_ESTIMATE")
            self.assertEqual(candidate.parameter_status, "NOT_EXPERIMENTALLY_CALIBRATED")

    def test_invalid_search_ranges_are_rejected(self):
        with self.assertRaises(ValueError):
            SearchLimits(minimum_speed_m_s=0.4, maximum_speed_m_s=3.1, heading_offsets_deg=(0.0, 20.0))


class MissionScenarioEvidenceTests(unittest.TestCase):
    def test_three_scenarios_keep_source_labels_and_provenance(self):
        expected = {
            "normal_mission.json": "NORMAL",
            "warning_mission.json": "WARNING",
            "high_risk_mission.json": "HIGH_RISK",
        }
        for filename, status in expected.items():
            with self.subTest(filename=filename):
                scenario = json.loads((ROOT / "data" / "scenarios" / filename).read_text(encoding="utf-8"))
                self.assertEqual(
                    scenario["environment_source"],
                    "REAL PUBLIC ENVIRONMENT DATA - NOT IN-SITU ZHUANGHE OBSERVATION",
                )
                self.assertEqual(scenario["vessel_state_source"], "SIMULATED VESSEL STATE")
                self.assertEqual(scenario["parameter_source"], "ENGINEERING_ESTIMATE")
                self.assertEqual(scenario["parameter_status"], "NOT_EXPERIMENTALLY_CALIBRATED")
                self.assertEqual(scenario["before"]["resonance_status"], status)
                self.assertIsNone(scenario["simulated_vessel_state"]["roll"])
                self.assertIsNone(scenario["simulated_vessel_state"]["pitch"])
                self.assertEqual(len(scenario["environment"]["provenance_by_field"]), 8)
                self.assertTrue(all(
                    item["decision"] == "ACCEPTED"
                    for item in scenario["environment"]["provenance_by_field"].values()
                ))
                self.assertIsNone(scenario["energy_cost"])
                self.assertEqual(scenario["energy_model_status"], "REQUIRES REAL SPEED-POWER DATA")

    def test_high_risk_evidence_improves_margin_and_has_no_actuator_command(self):
        result = json.loads(
            (ROOT / "data" / "results" / "v0.3_mission_demo.json").read_text(encoding="utf-8")
        )
        high = result["high_risk_evidence"]
        self.assertGreater(high["after"]["resonance_margin_ratio"], high["before"]["resonance_margin_ratio"])
        self.assertEqual(high["before"]["resonance_status"], "HIGH_RISK")
        self.assertIn(high["after"]["resonance_status"], ("WARNING", "NORMAL"))
        self.assertEqual(high["after"]["recommended_SOG"], high["after"]["SOG"])
        self.assertEqual(high["after"]["recommended_HDG"], high["after"]["HDG"])
        self.assertIn("NOT SAC", result["algorithm_status"])
        self.assertIn("REAL VESSEL CONTROL DISABLED", result["control_status"])


if __name__ == "__main__":
    unittest.main()
