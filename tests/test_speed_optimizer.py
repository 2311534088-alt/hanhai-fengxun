import unittest

from core.speed_optimizer import evaluate_candidates


class SpeedOptimizerTests(unittest.TestCase):
    def test_energy_is_unavailable_without_real_or_demo_model(self):
        candidates = evaluate_candidates([1.0, 2.0], lambda speed: speed / 2, distance_m=1000)
        self.assertEqual(len(candidates), 2)
        self.assertTrue(all(item.energy_cost is None for item in candidates))
        self.assertTrue(all(item.energy_model_status == "unavailable" for item in candidates))

    def test_supplied_energy_model_is_explicitly_demo_only(self):
        candidate = evaluate_candidates([1.0], lambda _speed: 0.1, 100, lambda speed: speed ** 2)[0]
        self.assertEqual(candidate.energy_model_status, "DEMO ONLY")

