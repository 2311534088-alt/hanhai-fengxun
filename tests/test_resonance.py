import unittest

from core.resonance import assess_resonance, encounter_frequency


class ResonanceTests(unittest.TestCase):
    def test_unknown_natural_period_returns_unavailable(self):
        result = assess_resonance(5.0, 1.0, 90.0, None, measured_roll_deg=4.0)
        self.assertEqual(result.status, "unavailable")
        self.assertIsNone(result.natural_roll_frequency_rad_s)
        self.assertIsNone(result.resonance_margin_rad_s)

    def test_opposing_seas_raise_encounter_frequency(self):
        following = encounter_frequency(5.0, 1.0, 0.0)
        opposing = encounter_frequency(5.0, 1.0, 180.0)
        self.assertIsNotNone(following)
        self.assertGreater(opposing, following)

