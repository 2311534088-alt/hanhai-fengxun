import json
import unittest
from pathlib import Path

from core.mission import MissionState
from core.mission.decision import (
    HistoricalReplayMode, HistoricalWindow, MissionAction, RouteEvaluation, calibration_warning,
    decide_mission_action, manufacturer_operating_context,
)
from core.resonance import load_engineering_estimate
from core.roll_response import assess_roll_response


ROOT = Path(__file__).resolve().parents[1]
HIGH = "RESIDUAL_HIGH_RISK_UNDER_PARAMETER_UNCERTAINTY"


def route(acceptable: bool) -> RouteEvaluation:
    return RouteEvaluation(
        "DETOUR", ((39.2, 122.2), (39.1, 122.3), (39.0, 122.0)),
        10.0, 0 if acceptable else 1, 30_000, 16_667, 10.0, acceptable,
    )


def window(acceptable: bool) -> HistoricalWindow:
    return HistoricalWindow(3, 0.69, 3.35, 176.81, 5.52, "ROBUST_NORMAL" if acceptable else HIGH, acceptable)


class MissionDecisionTests(unittest.TestCase):
    def test_predeparture_high_risk_delays_and_never_returns(self):
        result = decide_mission_action(
            mission_state=MissionState.PRE_DEPARTURE, current_robust_status=HIGH,
            constrained_adjustment_acceptable=False,
        )
        self.assertEqual(result.technical_outcome.preferred_mission_action, MissionAction.DELAY_MISSION)
        self.assertNotEqual(result.technical_outcome.preferred_mission_action, MissionAction.RETURN)

    def test_oracle_three_hour_window_is_explicit_upper_bound(self):
        result = decide_mission_action(
            mission_state=MissionState.OUTBOUND, current_robust_status=HIGH,
            constrained_adjustment_acceptable=False, historical_windows=(window(True),),
            replay_mode=HistoricalReplayMode.ORACLE,
        )
        self.assertEqual(result.technical_outcome.preferred_mission_action, MissionAction.HOLD_AND_REASSESS)
        self.assertTrue(result.business_outcome.hold_used)
        self.assertIn("ORACLE UPPER BOUND", result.technical_outcome.decision_reason)

    def test_safe_route_prefers_reroute_over_hold_and_return(self):
        result = decide_mission_action(
            mission_state=MissionState.OUTBOUND, current_robust_status=HIGH,
            constrained_adjustment_acceptable=False, route_candidates=(route(True),),
            historical_windows=(window(True),), replay_mode=HistoricalReplayMode.ORACLE,
        )
        self.assertEqual(result.technical_outcome.preferred_mission_action, MissionAction.REROUTE)
        self.assertTrue(result.business_outcome.reroute_used)

    def test_oracle_explicit_failed_windows_return(self):
        result = decide_mission_action(
            mission_state=MissionState.OUTBOUND, current_robust_status=HIGH,
            constrained_adjustment_acceptable=False, route_candidates=(route(False),),
            historical_windows=(window(False),), replay_mode=HistoricalReplayMode.ORACLE,
        )
        self.assertEqual(result.technical_outcome.preferred_mission_action, MissionAction.RETURN)
        self.assertTrue(result.technical_outcome.return_last_resort)
        self.assertTrue(result.business_outcome.unplanned_return)

    def test_causal_mode_ignores_even_acceptable_future_window(self):
        result = decide_mission_action(
            mission_state=MissionState.OUTBOUND, current_robust_status=HIGH,
            constrained_adjustment_acceptable=False, historical_windows=(window(True),),
        )
        self.assertEqual(result.technical_outcome.preferred_mission_action, MissionAction.HOLD_AND_REASSESS)
        self.assertNotIn("shows an acceptable window", result.technical_outcome.decision_reason)

    def test_causal_policy_holds_without_reading_future_window(self):
        result = decide_mission_action(
            mission_state=MissionState.OUTBOUND, current_robust_status=HIGH,
            constrained_adjustment_acceptable=False,
        )
        self.assertEqual(result.technical_outcome.preferred_mission_action, MissionAction.HOLD_AND_REASSESS)
        self.assertFalse(result.business_outcome.mission_completed)
        self.assertEqual(result.business_outcome.estimated_extra_travel_time_s, 10_800)

    def test_safety_deterioration_never_forces_continue_to_reduce_returns(self):
        result = decide_mission_action(
            mission_state=MissionState.ON_STATION, current_robust_status=HIGH,
            constrained_adjustment_acceptable=False,
        )
        self.assertNotEqual(result.technical_outcome.preferred_mission_action, MissionAction.CONTINUE)

    def test_manufacturer_context_is_not_absolute_safety_claim(self):
        context = manufacturer_operating_context()
        self.assertEqual(context["wind_force"], 4)
        self.assertEqual(context["sea_state"], 3)
        self.assertIn("NOT PROOF", context["interpretation_limit"])
        self.assertIsNotNone(calibration_warning(0.38, 29.296))


class ResponseProxyContractTests(unittest.TestCase):
    def test_unknown_transfer_gain_keeps_actual_roll_unavailable(self):
        parameters, _ = load_engineering_estimate()
        result = assess_roll_response(
            Hs_m=0.38, Tp_s=2.02, vessel_speed_m_s=1.8,
            relative_wave_angle_deg=105.0, parameters=parameters,
        )
        self.assertIsNotNone(result.roll_response_proxy)
        self.assertIsNone(result.roll_transfer_gain)
        self.assertIsNone(result.actual_roll_response_deg)
        self.assertEqual(result.response_proxy_status, "LOW_FIDELITY_RESPONSE_PROXY")
        self.assertEqual(result.angle_prediction_status, "NOT A CALIBRATED ROLL ANGLE PREDICTION")
        self.assertIn("DEPRECATED", result.estimated_roll_response_deg_deprecation)

    def test_heading_boundary_is_not_described_as_real_optimum(self):
        data = json.loads((ROOT / "data" / "results" / "v0.5_robust_avoidance_demo.json").read_text())
        candidate = data["constrained_recommendation"]["candidate"]
        self.assertTrue(candidate["heading_search_boundary_hit"])
        self.assertIn("SIMULATION_SEARCH_BOUNDARY", candidate["boundary_status"])
        self.assertNotIn("optimal operational", candidate["decision_confidence_warning"].lower())


class MissionEvidenceTests(unittest.TestCase):
    def test_policy_sources_and_business_metrics_are_simulation_labels(self):
        data = json.loads((ROOT / "data" / "results" / "v0.6_mission_policy_demo.json").read_text())
        self.assertIn("ORACLE_HISTORICAL_LOOKAHEAD", data["historical_replay_status"])
        self.assertFalse(data["used_for_business_metrics"])
        self.assertIsNone(data["actual_roll_response_deg"])
        self.assertEqual(data["response_model_status"], "LOW_FIDELITY_RESPONSE_PROXY")
        self.assertEqual(data["mission_decision"]["technical_outcome"]["preferred_mission_action"], "HOLD_AND_REASSESS")
        self.assertFalse(data["mission_decision"]["business_outcome"]["mission_completed"])
        self.assertEqual(len(data["policy_replay_comparison"]), 2)
        for policy in data["policy_replay_comparison"]:
            self.assertEqual(policy["result_status"], "MODEL-BASED / HISTORICAL-ENVIRONMENT REPLAY")
            self.assertEqual(policy["performance_status"], "NOT REAL WIND-FARM OPERATIONAL PERFORMANCE")
        self.assertEqual(data["policy_replay_comparison"][0]["policy_name"], "BASELINE_CONSERVATIVE_POLICY")
        self.assertEqual(data["policy_replay_comparison"][1]["policy_name"], "HANHAI_MISSION_CONTINUITY_POLICY")
        self.assertIn("INTERNAL SIMULATION BASELINE", data["policy_replay_comparison"][0]["policy_definition"])
        self.assertIn("SIMULATED VESSEL STATE", data["vessel_state_source"])
        self.assertEqual(data["parameter_source"], "ENGINEERING_ESTIMATE")


if __name__ == "__main__":
    unittest.main()
