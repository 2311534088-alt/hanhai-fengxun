import unittest
from pathlib import Path

from apps.desktop.product_model import (
    CONTROL_DISABLED, ENGINEERING_ESTIMATE, HISTORICAL_REPLAY, REAL_ENVIRONMENT,
    SIMULATED_VESSEL, UNAVAILABLE, ProductReplay,
)


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data/samples/sample_mission_001.csv"


class V10ProductTests(unittest.TestCase):
    def setUp(self):
        self.replay = ProductReplay(SAMPLE)

    def test_product_replay_loads_complete_simulated_mission(self):
        self.assertEqual(len(self.replay.records), 11)
        self.assertEqual(self.replay.timeline[0], "PRE_DEPARTURE")
        self.assertEqual(self.replay.timeline[-1], "COMPLETED")

    def test_snapshot_uses_frozen_core_outputs(self):
        snapshot = self.replay.seek(4)
        self.assertEqual(snapshot.mission_state, "OUTBOUND")
        self.assertGreaterEqual(snapshot.risk_score, 0)
        self.assertLessEqual(snapshot.risk_score, 10)
        self.assertIsNotNone(snapshot.encounter_frequency)
        self.assertIsNotNone(snapshot.roll_response_proxy_deg)
        self.assertIn(snapshot.decision_action, {"CONTINUE", "ADJUST", "RETURN"})

    def test_real_environment_and_simulated_vessel_are_not_conflated(self):
        snapshot = self.replay.seek(5)
        self.assertIn("REAL PUBLIC ENVIRONMENT DATA", snapshot.environment_source)
        self.assertEqual(snapshot.vessel_state_source, SIMULATED_VESSEL)
        self.assertNotEqual(snapshot.timestamp, snapshot.environment_timestamp)
        self.assertEqual(snapshot.environment_scenario, "HIGH_ROLL_RESPONSE_RISK")
        self.assertIsNotNone(snapshot.water_depth)
        self.assertNotEqual(snapshot.latitude, snapshot.environment_latitude)

    def test_environment_provenance_is_preserved_by_field(self):
        provenance = self.replay.snapshot().provenance_by_field
        self.assertIn("WAVERYS", str(provenance["Hs"]))
        self.assertIn("ERA5", str(provenance["wind_speed"]))
        self.assertIn("GLORYS", str(provenance["surface_current_speed"]))
        self.assertIn("GEBCO", str(provenance["water_depth"]))

    def test_candidate_comparison_is_read_only_and_uses_frozen_search(self):
        candidates = self.replay.seek(5).candidate_summaries
        self.assertEqual(set(candidates), {"current", "speed_only", "heading_only", "joint"})
        self.assertTrue(all(value for value in candidates.values()))
        self.assertFalse(any("COMMAND" in value for value in candidates.values()))

    def test_replay_navigation_is_bounded(self):
        self.assertEqual(self.replay.seek(-100).index, 0)
        self.assertEqual(self.replay.seek(999).index, len(self.replay.records) - 1)

    def test_truth_labels_are_explicit_and_control_disabled(self):
        self.assertEqual(REAL_ENVIRONMENT, "REAL PUBLIC ENVIRONMENT")
        self.assertEqual(SIMULATED_VESSEL, "SIMULATED VESSEL STATE")
        self.assertEqual(ENGINEERING_ESTIMATE, "ENGINEERING ESTIMATE")
        self.assertIn("NOT REAL-TIME FORECAST", HISTORICAL_REPLAY)
        self.assertIn("NOT A CONTINUOUS WEATHER SERIES", HISTORICAL_REPLAY)
        self.assertIn("DISABLED", CONTROL_DISABLED)
        self.assertIn("REQUIRES VALIDATION", UNAVAILABLE)

    def test_product_model_has_no_actuator_interface(self):
        self.assertFalse(hasattr(self.replay, "send_command"))
        self.assertFalse(hasattr(self.replay, "set_throttle"))
        self.assertFalse(hasattr(self.replay, "set_rudder"))


if __name__ == "__main__":
    unittest.main()
