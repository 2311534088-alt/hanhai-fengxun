import unittest
from pathlib import Path

from adapters.replay import CSVReplay
from core.risk import BaselineRiskEvaluator, VesselParameters
from tests.test_models import valid_record


class RiskTests(unittest.TestCase):
    def setUp(self):
        self.evaluator = BaselineRiskEvaluator()
        self.vessel = VesselParameters(model="ZLUSV-200", length_overall_m=2.02, beam_m=0.88)

    def test_score_always_clamped_to_zero_ten(self):
        for record in (valid_record(), valid_record(Hs=100.0, wind_speed=100.0, roll=180.0)):
            result = self.evaluator.evaluate(record, self.vessel)
            self.assertGreaterEqual(result.risk_score, 0)
            self.assertLessEqual(result.risk_score, 10)

    def test_all_null_baseline_fields_are_handled(self):
        record = valid_record(
            Hs=None, Tp=None, wave_direction=None, wind_speed=None, wind_direction=None,
            surface_current_speed=None, surface_current_direction=None, SOG=None, HDG=None,
            roll=None, pitch=None, roll_rate=None, battery=None,
        )
        result = self.evaluator.evaluate(record, self.vessel)
        self.assertEqual(result.data_quality, 0)
        self.assertEqual(result.primary_risk, "insufficient_data")

    def test_v02_inputs_affect_components(self):
        result = self.evaluator.evaluate(valid_record(Tp=2.0, wave_direction=181, HDG=1), self.vessel)
        self.assertGreater(result.risk_components["wave_risk"], 0)
        self.assertIn("PRELIMINARY / NEEDS CALIBRATION", result.explanation)

    def test_simulated_mission_shows_peak_and_recovery(self):
        path = Path(__file__).resolve().parents[1] / "data/samples/sample_mission_001.csv"
        results = [self.evaluator.evaluate(record, self.vessel) for record in CSVReplay(path)]
        scores = [result.risk_score for result in results]
        peak = scores.index(max(scores))
        self.assertGreaterEqual(max(scores), 7)
        self.assertLess(scores[peak + 1], scores[peak])
        self.assertGreater(results[peak].risk_components["motion_risk"], 7)

    def test_invalid_known_vessel_parameter_is_rejected(self):
        with self.assertRaises(ValueError):
            VesselParameters(model="ZLUSV-200", length_overall_m=0)

