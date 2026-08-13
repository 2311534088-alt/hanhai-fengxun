import hashlib
import json
import unittest
from pathlib import Path

from apps.desktop.frozen_core_facade import FrozenCoreFacade, MISSION_DECISION_SOURCE
from apps.desktop.product_model import (
    CONTROL_DISABLED, PUBLIC_GEOSPATIAL, SIMULATED_TURBINES, SIMULATED_VESSEL,
    ProductReplay,
)
from core.mission import MissionState
from core.resonance import assess_resonance, search_robust_roll_avoidance
from core.risk import BaselineRiskEvaluator


ROOT = Path(__file__).resolve().parents[1]
REPLAY = ROOT / "data/replay/v1.0b_synchronized_historical_mission.json"
FROZEN_CORE_TREE = "740c15a9a347a08d9d87116734b6fcf86af7914f"
V09_SUMMARY_SHA256 = "1d3326d9e0535b7e8f5f34e829083ee6b944fed910fb1d500bb16503bf579d17"
V09_FREEZE_DOC_SHA256 = "d132d512746d80aea72e2758cc6e12f2f1e1feb407d5baae28fff224e3b9f605"


class V10ProductTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.replay = ProductReplay(REPLAY)

    def test_synchronized_historical_replay_has_one_clock(self):
        self.assertEqual(len(self.replay.records), 11)
        for record, raw in zip(self.replay.records, self.replay.metadata["records"]):
            self.assertEqual(record.timestamp.isoformat(), raw["timestamp"])
            self.assertEqual(raw["simulated_vessel_state"]["source"], SIMULATED_VESSEL)

    def test_environment_time_is_not_progress_scenario_switching(self):
        timestamps = [record.timestamp for record in self.replay.records]
        self.assertEqual(len(set(timestamps)), len(timestamps))
        self.assertTrue(all((b - a).total_seconds() == 10_800 for a, b in zip(timestamps, timestamps[1:])))
        self.assertNotIn("scenario", json.dumps(self.replay.metadata["records"]).lower())

    def test_product_facade_matches_frozen_risk_and_resonance(self):
        record = self.replay.records[5]
        facade = self.replay.facade.assess(record)
        direct_risk = BaselineRiskEvaluator().evaluate(record, self.replay.facade.vessel)
        direct_resonance = assess_resonance(
            record.Tp, record.SOG,
            facade.robust.current.relative_wave_angle_deg,
            parameters=self.replay.facade.parameters,
            thresholds=self.replay.facade.resonance_thresholds,
        )
        snapshot = self.replay.seek(5)
        self.assertEqual(snapshot.risk_score, direct_risk.risk_score)
        self.assertEqual(snapshot.risk_components, direct_risk.risk_components)
        self.assertEqual(snapshot.resonance_status, direct_resonance.resonance_status.value)
        self.assertAlmostEqual(snapshot.encounter_frequency, direct_resonance.encounter_frequency_rad_s)

    def test_product_facade_matches_robust_avoidance_exactly(self):
        record = self.replay.records[5]
        direct = search_robust_roll_avoidance(
            Hs_m=record.Hs, Tp_s=record.Tp, wave_direction_deg=record.wave_direction,
            current_speed_m_s=record.SOG, current_heading_deg=record.HDG,
            parameters=self.replay.facade.parameters,
        )
        snapshot = self.replay.seek(5)
        candidate = direct.constrained_recommendation.candidate
        self.assertEqual(snapshot.current_robust_status, direct.current.response_grid.robust_decision_status.value)
        self.assertEqual(snapshot.recommended_SOG, candidate.SOG_m_s)
        self.assertEqual(snapshot.recommended_HDG, candidate.HDG_deg)
        self.assertEqual(snapshot.recommended_grid_q90, candidate.response_grid.grid_q90_estimated_roll_response_deg)

    def test_gui_presentation_must_not_override_core_decision(self):
        high = next((item for item in self.replay.snapshots if item.risk_level == "HIGH"), None)
        if high is not None:
            self.assertNotEqual(high.decision_source, "apps.desktop.product_model")
            self.assertEqual(high.decision_source, MISSION_DECISION_SOURCE)
            self.assertNotEqual(high.decision_action, "RETURN")
        self.assertFalse(hasattr(ProductReplay, "_decision"))

    def test_continuous_environment_preserves_field_provenance(self):
        for snapshot in self.replay.snapshots:
            provenance = snapshot.provenance_by_field
            for field in ("Hs", "wind_speed", "surface_current_speed", "water_depth"):
                self.assertIn(field, provenance)
                self.assertIn("accepted", provenance[field])
            self.assertIn("WAVERYS", provenance["Hs"]["source"])
            self.assertIn("ERA5", provenance["wind_speed"]["source"])

    def test_map_truth_labels_are_explicit(self):
        self.assertIn("NOT YET LOADED IN MAP", PUBLIC_GEOSPATIAL)
        self.assertEqual(SIMULATED_TURBINES, "SIMULATED TURBINE LAYOUT")
        gui = (ROOT / "apps/desktop/gui.py").read_text(encoding="utf-8")
        self.assertIn("PUBLIC_GEOSPATIAL", gui)
        self.assertIn("SIMULATED_TURBINES", gui)

    def test_v09_frozen_evidence_hashes_match_freeze_document(self):
        summary_hash = hashlib.sha256((ROOT / "data/results/v0.9_summary.json").read_bytes()).hexdigest()
        freeze_hash = hashlib.sha256((ROOT / "docs/V0.9_CORE_FREEZE.md").read_bytes()).hexdigest()
        freeze = (ROOT / "docs/V0.9_CORE_FREEZE.md").read_text(encoding="utf-8")
        self.assertIn("BUSINESS_VALUE_STATUS = NOT_ESTABLISHED", freeze)
        self.assertEqual(summary_hash, V09_SUMMARY_SHA256)
        self.assertEqual(freeze_hash, V09_FREEZE_DOC_SHA256)

    def test_frozen_core_tree_contract_is_documented(self):
        self.assertEqual(FROZEN_CORE_TREE, "740c15a9a347a08d9d87116734b6fcf86af7914f")

    def test_no_control_output_or_actuator_interface(self):
        self.assertIn("DISABLED", CONTROL_DISABLED)
        for name in ("send_command", "set_throttle", "set_rudder"):
            self.assertFalse(hasattr(self.replay, name))
            self.assertFalse(hasattr(FrozenCoreFacade(), name))


if __name__ == "__main__":
    unittest.main()
