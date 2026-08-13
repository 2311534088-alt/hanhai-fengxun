import hashlib
import json
import unittest
from datetime import datetime
from pathlib import Path

from apps.desktop.product_model import CompetitionDemoReplay, DYNAMIC_CORE_SOURCE
from core.mission.dynamic_replay import DynamicAction, DynamicMissionEngine
from core.risk import RiskLevel
from core.roll_response import RobustDecisionStatus


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "data/replay/v1.0c_competition_demo.json"
CONTEXT = ROOT / "data/context/zhuanghe_public_operational_context.json"
GENERATOR = ROOT / "tools/build_v10c_competition_demo.py"
GUI = ROOT / "apps/desktop/gui.py"
FROZEN_CORE_TREE = "740c15a9a347a08d9d87116734b6fcf86af7914f"
V09_SUMMARY_SHA256 = "1d3326d9e0535b7e8f5f34e829083ee6b944fed910fb1d500bb16503bf579d17"
V09_FREEZE_DOC_SHA256 = "d132d512746d80aea72e2758cc6e12f2f1e1feb407d5baae28fff224e3b9f605"


class V10CCompetitionDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads(DEMO.read_text(encoding="utf-8"))
        cls.events = cls.payload["event_markers"]
        cls.by_type = {item["event_type"]: item for item in cls.events}
        cls.replay = CompetitionDemoReplay(DEMO)
        cls.generator_source = GENERATOR.read_text(encoding="utf-8")

    def test_task_actions_come_from_dynamic_mission_engine(self):
        self.assertEqual(self.payload["core_source"], DYNAMIC_CORE_SOURCE)
        self.assertEqual(self.by_type["ADVISORY_ISSUED"]["decision_action"], DynamicAction.ADJUST_SPEED_HEADING.value)
        self.assertNotIn("decide_mission_action", self.payload["core_source"])

    def test_single_vessel_high_is_unsafe_even_without_roll_high(self):
        class State:
            robust_status = RobustDecisionStatus.ROBUST_NORMAL.value
            single_vessel_risk_level = RiskLevel.HIGH.value
        self.assertTrue(DynamicMissionEngine._unsafe(State()))

    def test_recommended_and_executed_maneuver_match(self):
        advisory = self.by_type["ADVISORY_ISSUED"]
        executed = self.payload["before_after_evidence"]["executed_maneuver"]
        self.assertEqual(advisory["recommended_SOG"], executed["executed_SOG_m_s"])
        self.assertEqual(advisory["recommended_HDG"], executed["executed_HDG_deg"])

    def test_executed_maneuver_changes_position(self):
        segment = self.payload["before_after_evidence"]["executed_maneuver"]
        self.assertNotEqual(segment["start"], segment["end"])
        self.assertGreater(segment["distance_m"], 0.0)

    def test_after_state_is_recomputed_at_executed_segment_end(self):
        segment = self.payload["before_after_evidence"]["executed_maneuver"]
        after = self.payload["before_after_evidence"]["after"]
        self.assertEqual(after["timestamp"], segment["end_time"])
        self.assertEqual(after["SOG"], segment["executed_SOG_m_s"])
        self.assertEqual(after["HDG"], segment["executed_HDG_deg"])
        self.assertAlmostEqual(after["latitude"], segment["end"][0])
        self.assertAlmostEqual(after["longitude"], segment["end"][1])

    def test_after_risk_is_not_a_manual_literal(self):
        self.assertIn("engine._state(", self.generator_source)
        self.assertNotIn('"after risk"', self.generator_source.lower())
        reassessed = self.by_type["RISK_REASSESSED"]
        self.assertEqual(reassessed["after"], self.payload["before_after_evidence"]["after"])

    def test_risk_improved_requires_actual_model_improvement(self):
        before = self.by_type["RISK_IMPROVED"]["before"]
        after = self.by_type["RISK_IMPROVED"]["after"]
        robust_better = before["robust_status"] != after["robust_status"]
        q90_better = after["GRID_Q90"] < before["GRID_Q90"]
        risk_better = after["single_vessel_risk_score"] < before["single_vessel_risk_score"]
        self.assertTrue(robust_better or q90_better or risk_better)
        self.assertNotEqual(after["single_vessel_risk_level"], "HIGH")

    def test_selection_rule_forbids_business_and_saved_outcomes(self):
        forbidden = self.payload["selection_forbidden_inputs"]
        self.assertIn("mission_saved", forbidden)
        self.assertIn("business_outcome", forbidden)
        rule = self.payload["selection_rule"]
        self.assertIn("never reads mission_saved", rule)
        self.assertIn("business", rule)
        self.assertNotIn("mission_saved(", self.generator_source)
        self.assertNotIn("assess_value_status", self.generator_source)

    def test_target_reached_is_distance_triggered_not_index_triggered(self):
        target = self.by_type["TARGET_REACHED"]
        self.assertLessEqual(target["arrival_distance_m"], target["target_radius_m"])
        self.assertEqual(target["trigger"], "EXECUTED_TRACK_DISTANCE_TO_TARGET")
        self.assertNotRegex(self.generator_source, r"index\s*==\s*\d+")

    def test_inspection_area_and_payload_remain_simulated(self):
        self.assertEqual(self.by_type["INSPECTION_AREA_ENTERED"]["inspection_area_source"], "SIMULATED INSPECTION AREA")
        payload = self.by_type["INSPECTION_PAYLOAD_ACTIVE"]["payload_status"]
        self.assertIn("SIMULATED", payload)
        self.assertIn("NO DEFECT DETECTION CLAIM", payload)
        for claim in ("CRACK DETECTED", "BLADE DAMAGE DETECTED", "LIGHTNING FAULT DETECTED"):
            self.assertNotIn(claim, json.dumps(self.payload).upper())

    def test_public_port_distance_is_not_demo_route(self):
        mission = self.payload["mission"]
        self.assertFalse(mission["port_to_farm_route_used"])
        self.assertLess(mission["route_length_m"], 30_000)
        self.assertEqual(mission["deployment_mode"], "SIMULATED NEAR-FARM DEPLOYMENT")

    def test_72_turbines_are_context_but_locations_are_simulated(self):
        self.assertEqual(self.payload["public_operational_context"]["turbine_count"], 72)
        labels = self.payload["truth_labels"]
        self.assertTrue(any("SIMULATED TURBINE LAYOUT" in item for item in labels))
        gui = GUI.read_text(encoding="utf-8")
        self.assertIn("for idx in range(72)", gui)
        self.assertIn("NOT OFFICIAL COORDINATES", gui)

    def test_public_context_is_product_only_not_algorithm_config(self):
        context = self.payload["public_operational_context"]
        self.assertEqual(context["algorithm_use"], "PROHIBITED - PRODUCT SCENE AND BUSINESS CONTEXT ONLY")
        self.assertNotIn("risk_threshold", json.dumps(context).lower())
        self.assertTrue(CONTEXT.exists())

    def test_environment_and_display_times_are_truthful(self):
        for event in self.events:
            datetime.fromisoformat(event["timestamp"])
            if event["environment_data_time"] != "STATIC":
                self.assertLessEqual(datetime.fromisoformat(event["environment_data_time"]), datetime.fromisoformat(event["timestamp"]))
        self.assertIn("UNDERLYING HISTORICAL TIMESTAMPS UNCHANGED", self.payload["display_status"])

    def test_event_order_is_legal_and_improvement_after_execution(self):
        types = [item["event_type"] for item in self.events]
        required = [
            "MISSION_START", "NORMAL_NAVIGATION", "RISK_RISING", "RISK_DETECTED",
            "ADVISORY_ISSUED", "SIMULATED_ACTION_ACCEPTED", "SIMULATED_ACTION_EXECUTED",
            "RISK_REASSESSED", "RISK_IMPROVED", "TARGET_APPROACH", "TARGET_REACHED",
            "INSPECTION_AREA_ENTERED", "INSPECTION_PAYLOAD_READY", "RETURN_START",
        ]
        self.assertTrue(all(item in types for item in required))
        self.assertLess(types.index("SIMULATED_ACTION_EXECUTED"), types.index("RISK_IMPROVED"))
        self.assertLess(types.index("TARGET_REACHED"), types.index("INSPECTION_AREA_ENTERED"))
        timestamps = [datetime.fromisoformat(item["timestamp"]) for item in self.events]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_public_geospatial_and_simulated_geometry_are_distinct(self):
        labels = self.payload["truth_labels"]
        self.assertIn("PUBLIC GEOSPATIAL REFERENCE", labels)
        self.assertIn("SIMULATED NEAR-FARM MISSION GEOMETRY", labels)
        self.assertNotEqual(self.payload["environment_reference_point"], self.payload["mission"]["target_position"])

    def test_gebco_and_sea_ice_boundaries_remain_explicit(self):
        bathymetry = self.payload["public_bathymetry_comparison"]
        self.assertIn("NOT FOR NAVIGATIONAL SAFETY", bathymetry["navigation_status"])
        self.assertTrue(any("SEA ICE / ICE RISK: UNAVAILABLE" in item for item in self.payload["truth_labels"]))

    def test_no_actuator_interface(self):
        for object_ in (self.replay, CompetitionDemoReplay):
            for name in ("send_command", "set_throttle", "set_rudder", "actuator"):
                self.assertFalse(hasattr(object_, name))
        self.assertIn("REAL VESSEL CONTROL DISABLED", json.dumps(self.payload))

    def test_frozen_contract_hashes(self):
        self.assertEqual(FROZEN_CORE_TREE, "740c15a9a347a08d9d87116734b6fcf86af7914f")
        summary = hashlib.sha256((ROOT / "data/results/v0.9_summary.json").read_bytes()).hexdigest()
        freeze = hashlib.sha256((ROOT / "docs/V0.9_CORE_FREEZE.md").read_bytes()).hexdigest()
        self.assertEqual(summary, V09_SUMMARY_SHA256)
        self.assertEqual(freeze, V09_FREEZE_DOC_SHA256)
        self.assertEqual(self.payload["dynamic_result_summary"]["business_value_status"], "NOT_ESTABLISHED")


if __name__ == "__main__":
    unittest.main()
