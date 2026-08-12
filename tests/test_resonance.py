import unittest
from math import pi

from core.resonance import (
    ParameterSource, ResonanceStatus, RollDynamicsParameters,
    assess_resonance, encounter_frequency, load_engineering_estimate, select_parameters,
)


class ResonanceTests(unittest.TestCase):
    def test_unknown_natural_period_returns_unavailable(self):
        result = assess_resonance(5.0, 1.0, 90.0, None, measured_roll_deg=4.0)
        self.assertEqual(result.resonance_status, ResonanceStatus.UNAVAILABLE)
        self.assertEqual(result.parameter_source, ParameterSource.UNAVAILABLE)
        self.assertIsNone(result.natural_roll_frequency_rad_s)
        self.assertIsNone(result.resonance_margin_ratio)

    def test_opposing_seas_raise_encounter_frequency(self):
        following = encounter_frequency(5.0, 1.0, 0.0)
        opposing = encounter_frequency(5.0, 1.0, 180.0)
        self.assertIsNotNone(following)
        self.assertGreater(opposing, following)

    def test_engineering_estimate_config_is_explicit_and_complete(self):
        parameters, thresholds = load_engineering_estimate()
        self.assertEqual(parameters.parameter_source, ParameterSource.ENGINEERING_ESTIMATE)
        self.assertEqual(parameters.parameter_status, "NOT_EXPERIMENTALLY_CALIBRATED")
        self.assertEqual(parameters.natural_roll_period_s, 1.70)
        self.assertEqual(parameters.natural_roll_frequency_rad_s, 3.69)
        self.assertEqual(thresholds.status, "PRELIMINARY / NEEDS CALIBRATION")

    def test_parameter_priority_is_measured_then_estimate_then_unavailable(self):
        estimate, _ = load_engineering_estimate()
        measured = RollDynamicsParameters(1.8, 2 * pi / 1.8, ParameterSource.MEASURED, "CALIBRATED")
        unavailable = RollDynamicsParameters(None, None, ParameterSource.UNAVAILABLE, "UNAVAILABLE")
        self.assertIs(select_parameters(unavailable, estimate, measured), measured)
        self.assertIs(select_parameters(unavailable, estimate), estimate)

    def test_resonance_ratio_status_thresholds(self):
        parameters, thresholds = load_engineering_estimate()
        natural = parameters.natural_roll_frequency_rad_s
        cases = (
            (0.05, ResonanceStatus.HIGH_RISK),
            (0.15, ResonanceStatus.WARNING),
            (0.25, ResonanceStatus.NORMAL),
        )
        for ratio, expected in cases:
            encounter_target = natural * (1 - ratio)
            wave_period = 2 * pi / encounter_target
            result = assess_resonance(
                wave_period, 0.0, 90.0, parameters=parameters, thresholds=thresholds,
            )
            with self.subTest(ratio=ratio):
                self.assertAlmostEqual(result.resonance_margin_ratio, ratio, places=6)
                self.assertEqual(result.resonance_status, expected)
                self.assertEqual(result.parameter_source, ParameterSource.ENGINEERING_ESTIMATE)

    def test_example_engineering_estimate_calculation(self):
        parameters, thresholds = load_engineering_estimate()
        result = assess_resonance(1.70, 0.0, 90.0, parameters=parameters, thresholds=thresholds)
        self.assertAlmostEqual(result.encounter_frequency_rad_s, 2 * pi / 1.70, places=6)
        self.assertLess(result.resonance_margin_ratio, 0.01)
        self.assertEqual(result.resonance_status, ResonanceStatus.HIGH_RISK)
        self.assertEqual(result.parameter_status, "NOT_EXPERIMENTALLY_CALIBRATED")
