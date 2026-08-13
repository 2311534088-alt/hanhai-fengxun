import json
import unittest
from pathlib import Path

from core.resonance import (
    SearchLimits, constrained_speed_interval, load_engineering_estimate,
    load_maneuver_constraint, search_robust_roll_avoidance,
)
from core.roll_response import RobustDecisionStatus, RollResponseRisk


ROOT = Path(__file__).resolve().parents[1]


class RobustAvoidanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parameters, _ = load_engineering_estimate()
        cls.result = search_robust_roll_avoidance(
            Hs_m=0.38, Tp_s=2.02, wave_direction_deg=109.66,
            current_speed_m_s=1.8, current_heading_deg=214.66,
            parameters=cls.parameters,
        )

    def test_nominal_improvement_with_high_grid_q90_is_not_robust_safe(self):
        candidate = self.result.unrestricted_simulation_best.candidate
        self.assertLess(
            candidate.response_grid.nominal_estimated_roll_response_deg,
            self.result.current.response_grid.nominal_estimated_roll_response_deg,
        )
        self.assertEqual(candidate.response_grid.grid_q90_roll_risk, RollResponseRisk.HIGH)
        self.assertEqual(
            self.result.unrestricted_simulation_best.robust_status,
            RobustDecisionStatus.RESIDUAL_HIGH_RISK,
        )
        self.assertEqual(candidate.conflict_status, "NOMINAL_IMPROVES_BUT_ROBUST_RISK_REMAINS_HIGH")

    def test_selected_candidate_grid_q90_never_worsens(self):
        for recommendation in (
            self.result.unrestricted_simulation_best,
            self.result.constrained_recommendation,
        ):
            self.assertLessEqual(
                recommendation.candidate.response_grid.grid_q90_estimated_roll_response_deg,
                self.result.current.response_grid.grid_q90_estimated_roll_response_deg,
            )

    def test_three_metre_boundary_hit_warns_and_is_not_operational_maximum(self):
        recommendation = self.result.unrestricted_simulation_best
        self.assertEqual(recommendation.candidate.SOG_m_s, 3.0)
        self.assertTrue(recommendation.candidate.speed_search_boundary_hit)
        self.assertEqual(recommendation.candidate.boundary_status, "OPTIMUM_LIES_ON_SIMULATION_SEARCH_BOUNDARY")
        self.assertIsNotNone(recommendation.candidate.decision_confidence_warning)
        self.assertEqual(recommendation.search_bound_status, "SIMULATION_SEARCH_BOUND")
        self.assertEqual(recommendation.operational_range_status, "NOT ZLUSV-200 OPERATIONAL SPEED RANGE")

    def test_unknown_operational_speed_is_not_replaced_with_simulation_bound(self):
        config = (ROOT / "configs" / "zlusv200.yaml").read_text(encoding="utf-8")
        self.assertIn("maximum_operational_speed_m_s: null", config)
        self.assertIn("requires manufacturer data or a real speed test", config.lower())

    def test_twenty_percent_constrained_speed_interval(self):
        constraint = load_maneuver_constraint()
        lower, upper = constrained_speed_interval(1.8, constraint, SearchLimits())
        self.assertAlmostEqual(lower, 1.44)
        self.assertAlmostEqual(upper, 2.16)
        self.assertEqual(constraint.status, "PRELIMINARY_MANEUVER_CONSTRAINT")
        self.assertEqual(constraint.validation_status, "PRELIMINARY / NEEDS REAL VESSEL VALIDATION")

    def test_constrained_and_unrestricted_are_separate(self):
        constrained = self.result.constrained_recommendation
        unrestricted = self.result.unrestricted_simulation_best
        self.assertEqual(constrained.label, "CONSTRAINED_RECOMMENDATION")
        self.assertEqual(unrestricted.label, "UNRESTRICTED_SIMULATION_BEST")
        self.assertNotEqual(constrained.candidate.SOG_m_s, unrestricted.candidate.SOG_m_s)
        self.assertLessEqual(abs(constrained.candidate.speed_change_percent), 20.0)
        self.assertGreater(abs(unrestricted.candidate.speed_change_percent), 20.0)

    def test_grid_quantiles_are_explicitly_not_confidence_intervals(self):
        grid = self.result.current.response_grid
        self.assertEqual(grid.grid_method, "DETERMINISTIC SENSITIVITY GRID")
        self.assertEqual(grid.grid_statistical_status, "NOT A STATISTICAL CONFIDENCE INTERVAL")
        self.assertFalse(any(name.startswith("p90") for name in grid.__dataclass_fields__))

    def test_no_robust_candidate_returns_residual_high_and_pause_return(self):
        recommendation = self.result.constrained_recommendation
        self.assertEqual(recommendation.robust_status, RobustDecisionStatus.RESIDUAL_HIGH_RISK)
        self.assertEqual(recommendation.operator_advice, "PAUSE / RETURN ASSESSMENT")


class RobustEvidenceTests(unittest.TestCase):
    def test_sources_and_bound_meanings_are_preserved(self):
        data = json.loads(
            (ROOT / "data" / "results" / "v0.5_robust_avoidance_demo.json").read_text(encoding="utf-8")
        )
        self.assertEqual(data["environment_source"], "REAL PUBLIC ENVIRONMENT DATA - NOT IN-SITU ZHUANGHE OBSERVATION")
        self.assertEqual(data["vessel_state_source"], "SIMULATED VESSEL STATE")
        self.assertEqual(data["parameter_source"], "ENGINEERING_ESTIMATE")
        self.assertEqual(data["parameter_status"], "NOT_EXPERIMENTALLY_CALIBRATED")
        self.assertIsNone(data["maximum_operational_speed_m_s"])
        self.assertTrue(data["residual_high_risk"])
        self.assertIn("NOT SAC", data["algorithm_status"])
        self.assertIn("CONTROL DISABLED", data["control_status"])


if __name__ == "__main__":
    unittest.main()
