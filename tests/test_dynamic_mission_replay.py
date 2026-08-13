import unittest
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

from core.marine import MarineEnvironment, MarineQualityFlag
from core.mission.dynamic_replay import (
    BUSINESS_NOT_ESTABLISHED, DECISION_INTERVAL_S, DYNAMIC_MODE, HOLD_POSITION_UNSAFE,
    MANEUVER_STATUS, CausalMultiSourceStore, CompletionEvidenceStatus, DynamicAction,
    DynamicMissionCase, DynamicMissionEngine, DynamicMissionGeometry, DynamicMissionResult,
    DynamicPolicy, DynamicRiskExposure, MissionSavedAssessment, assess_hold_feasibility,
    assess_mission_saved, assess_value_status, summarize_dynamic_results,
)
from core.mission.decision.models import MissionOutcomeStatus
from core.mission.state import MissionState
from core.resonance import load_engineering_estimate


UTC = timezone.utc
T0 = datetime(2026, 2, 5, tzinfo=UTC)


def multi_source_records(wave_schedule, *, wind_speed=3.0, current_speed=.1):
    values = []
    for at, hs, tp, wave_direction in wave_schedule:
        values.extend((
            MarineEnvironment(at, 39.2, 122.2, Hs=hs, Tp=tp, wave_direction=wave_direction,
                              source="Copernicus WAVERYS:test", quality_flag=MarineQualityFlag.PUBLIC_PRODUCT_FILE),
            MarineEnvironment(at, 39.2, 122.2, wind_speed=wind_speed, wind_direction=20,
                              source="ERA5:test", quality_flag=MarineQualityFlag.PUBLIC_PRODUCT_FILE),
            MarineEnvironment(at, 39.2, 122.2, surface_current_speed=current_speed,
                              surface_current_direction=180, source="Copernicus GLORYS:test",
                              quality_flag=MarineQualityFlag.PUBLIC_PRODUCT_FILE),
        ))
    values.append(MarineEnvironment(T0, 39.2, 122.2, water_depth=12,
                                    source="GEBCO:test", quality_flag=MarineQualityFlag.PUBLIC_PRODUCT_FILE))
    return tuple(values)


def small_case(case_id="case"):
    geometry = DynamicMissionGeometry(
        "SHORT_ROUTE", (39.2, 122.2), (39.199, 122.201),
        "SIMULATED SHORT_ROUTE - NOT ACTUAL WIND-FARM DISTANCE",
    )
    return DynamicMissionCase(case_id, T0, geometry, inspection_service_time_s=60)


class DynamicReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parameters, _ = load_engineering_estimate()

    def test_local_recommended_heading_is_executed_by_maneuver_segment(self):
        records = multi_source_records((
            (T0, .1, 4.0, 0.0),
            *tuple((T0 + timedelta(minutes=30 * index), .3, 2.0, 90.0) for index in range(1, 8)),
        ))
        engine = DynamicMissionEngine(CausalMultiSourceStore(records), self.parameters)
        geometry = DynamicMissionGeometry(
            "MEDIUM_ROUTE", (39.2, 122.2), (39.17, 122.17),
            "SIMULATED MEDIUM_ROUTE - NOT ACTUAL WIND-FARM DISTANCE",
        )
        result = engine.run(
            DynamicMissionCase("heading", T0, geometry, inspection_service_time_s=60),
            DynamicPolicy.LOCAL_ADJUST_ONLY,
        )
        decisions = [item for item in result.actions if item.action is DynamicAction.ADJUST_SPEED_HEADING]
        maneuvers = [item for item in result.executed_segments if item.segment_type == "MANEUVER_SEGMENT"]
        self.assertTrue(decisions)
        self.assertTrue(maneuvers)
        self.assertEqual(maneuvers[0].executed_HDG_deg, decisions[0].recommended_HDG_deg)
        self.assertEqual(maneuvers[0].executed_SOG_m_s, decisions[0].recommended_SOG_m_s)
        self.assertEqual(maneuvers[0].source_status, MANEUVER_STATUS)

    def test_mid_route_risk_change_triggers_redecision(self):
        schedule = (
            (T0, .1, 4.0, 0),
            (T0 + timedelta(minutes=30), .3, 2.0, 135),
            (T0 + timedelta(hours=1), .3, 2.0, 135),
        )
        geometry = DynamicMissionGeometry("MEDIUM", (39.2, 122.2), (39.17, 122.17), "SIMULATED")
        result = DynamicMissionEngine(CausalMultiSourceStore(multi_source_records(schedule)), self.parameters).run(
            DynamicMissionCase("dynamic", T0, geometry, inspection_service_time_s=60),
            DynamicPolicy.BASELINE_CONSERVATIVE,
        )
        self.assertGreaterEqual(len(result.actions), 2)
        self.assertTrue(any(item.action is DynamicAction.RETURN for item in result.actions[1:]))

    def test_unsafe_hold_position_cannot_hold(self):
        environment = MarineEnvironment(
            T0, 39.2, 122.2, Hs=3, Tp=1.7, wave_direction=90,
            source="WAVERYS:test", quality_flag=MarineQualityFlag.PUBLIC_PRODUCT_FILE,
        )
        hold = assess_hold_feasibility(environment, self.parameters)
        self.assertFalse(hold.hold_allowed)
        self.assertEqual(hold.status, HOLD_POSITION_UNSAFE)

    def test_hold_assessment_does_not_claim_risk_reduction(self):
        environment = MarineEnvironment(
            T0, 39.2, 122.2, Hs=.1, Tp=4, wave_direction=0,
            source="WAVERYS:test", quality_flag=MarineQualityFlag.PUBLIC_PRODUCT_FILE,
        )
        hold = assess_hold_feasibility(environment, self.parameters)
        self.assertFalse(hasattr(hold, "risk_reduction"))
        self.assertIn("UNKNOWN_WITHOUT", hold.holding_heading_status)

    def test_endurance_unverified_is_not_evidence_qualified(self):
        result = self._result("x", technical=True, qualified=False, elapsed=5 * 3600)
        self.assertTrue(result.technical_completed)
        self.assertFalse(result.evidence_qualified_completion)
        self.assertEqual(result.completion_evidence_status, CompletionEvidenceStatus.ENDURANCE_UNVERIFIED)

    def test_predeparture_delay_is_not_unplanned_return(self):
        records = multi_source_records(((T0, 3, 1.7, 90),))
        result = DynamicMissionEngine(CausalMultiSourceStore(records), self.parameters).run(
            small_case("pre"), DynamicPolicy.BASELINE_CONSERVATIVE,
        )
        self.assertTrue(result.predeparture_delay)
        self.assertFalse(result.unplanned_return)

    def test_postdeparture_return_reaches_base_and_counts_time_exposure(self):
        schedule = ((T0, .1, 4, 0), (T0 + timedelta(minutes=30), 3, 1.7, 90))
        geometry = DynamicMissionGeometry("MEDIUM", (39.2, 122.2), (39.17, 122.17), "SIMULATED")
        result = DynamicMissionEngine(CausalMultiSourceStore(multi_source_records(schedule)), self.parameters).run(
            DynamicMissionCase("return", T0, geometry, inspection_service_time_s=60),
            DynamicPolicy.BASELINE_CONSERVATIVE,
        )
        self.assertTrue(result.unplanned_return)
        self.assertTrue(result.returned_to_base)
        self.assertGreater(result.mission_elapsed_time_s, DECISION_INTERVAL_S)
        self.assertGreater(result.exposure.total_evaluated_time_s, DECISION_INTERVAL_S)

    def test_safety_tradeoff_cannot_establish_business_value(self):
        baseline_results = (self._result("x", technical=False, qualified=False, high=0),)
        hanhai_results = (self._result("x", technical=True, qualified=True, high=100),)
        value = assess_value_status(
            baseline=summarize_dynamic_results(baseline_results),
            hanhai=summarize_dynamic_results(hanhai_results),
            saved=(MissionSavedAssessment("x", False, ("UNSAFE",)),), future_action_leakage_count=0,
        )
        self.assertEqual(value.business_value_status, BUSINESS_NOT_ESTABLISHED)
        self.assertEqual(value.safety_comparison_status, "COMPLETION_GAIN_WITH_SAFETY_TRADEOFF")

    def test_time_penalty_summary_has_tail_metrics(self):
        values = tuple(self._result(str(i), elapsed=1000 + i * 100, nominal=1000) for i in range(10))
        distribution = summarize_dynamic_results(values).time_penalty
        self.assertGreaterEqual(distribution.p95_s, distribution.p90_s)
        self.assertGreaterEqual(distribution.maximum_s, distribution.p95_s)
        self.assertGreater(distribution.average_among_affected_missions_s, 0)

    def test_mission_saved_rejects_endurance_and_safety_failures(self):
        baseline = self._result("same", technical=False, qualified=False, high=0)
        hanhai = self._result("same", technical=True, qualified=False, elapsed=5 * 3600, high=100)
        assessment = assess_mission_saved(baseline, hanhai)
        self.assertFalse(assessment.saved)
        self.assertIn("ENDURANCE_FEASIBILITY_UNVERIFIED", assessment.rejection_reasons)
        self.assertIn("UNACCEPTABLE_HIGH_RISK_EXPOSURE_INCREASE", assessment.rejection_reasons)
        self.assertIn("UNACCEPTABLE_HIGH_RISK_EXPOSURE_RATIO_INCREASE", assessment.rejection_reasons)
        self.assertIn("UNACCEPTABLE_CONTINUOUS_HIGH_RISK_INCREASE", assessment.rejection_reasons)
        self.assertIn("UNACCEPTABLE_PRELIMINARY_RISK_BURDEN_INCREASE", assessment.rejection_reasons)

    def test_policies_share_observation_interval_and_constraints(self):
        summaries = [summarize_dynamic_results((self._result(policy.value),)) for policy in DynamicPolicy]
        self.assertEqual({item.observation_interval_s for item in summaries}, {DECISION_INTERVAL_S})
        self.assertEqual(len({item.action_constraint_status for item in summaries}), 1)

    def test_dynamic_state_contains_multisource_risk_fields(self):
        records = multi_source_records(((T0, .1, 4, 0),))
        engine = DynamicMissionEngine(CausalMultiSourceStore(records), self.parameters)
        result = engine.run(small_case("multi"), DynamicPolicy.BASELINE_CONSERVATIVE)
        state = result.actions[0].state
        self.assertIsNotNone(state.wind_speed_m_s)
        self.assertIsNotNone(state.surface_current_speed_m_s)
        self.assertIsNotNone(state.water_depth_m)
        self.assertIn("wind_risk", state.risk_components)
        self.assertEqual(state.risk_baseline_status, "PRELIMINARY / NEEDS CALIBRATION")

    def test_result_labels_are_model_based_and_no_control(self):
        result = self._result("label")
        self.assertEqual(result.replay_mode, DYNAMIC_MODE)
        self.assertEqual(result.result_status, "MODEL-BASED HISTORICAL REPLAY")
        self.assertIn("DISABLED", result.control_status)

    def test_v08_evidence_has_360_scenarios_and_dual_gate(self):
        path = Path(__file__).resolve().parents[1] / "data/results/v0.8_dynamic_mission_replay.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["selection"]["total_scenario_N"], 360)
        self.assertEqual(len(data["scenario_results"]), 360)
        self.assertIn("NOT INDEPENDENT REAL MISSIONS", data["selection"]["scenario_wording"])
        self.assertEqual(data["replay_integrity_gate"], "PASS")
        self.assertEqual(data["business_value_status"], "NOT_ESTABLISHED")
        for summary in data["policy_summaries"].values():
            self.assertEqual(summary["denominator_N"], 360)
            self.assertIn("p95_s", summary["time_penalty"])

    def test_v08_stress_case_rejects_unsafe_hold_and_returns_to_base(self):
        path = Path(__file__).resolve().parents[1] / "data/results/v0.8_dynamic_mission_replay.json"
        stress = json.loads(path.read_text(encoding="utf-8"))["scenario_2026_02_05"]
        result = stress["result"]
        self.assertEqual(stress["future_action_access_count"], 0)
        self.assertEqual(result["actions"][0]["hold_feasibility"]["status"], "HOLD_POSITION_UNSAFE")
        self.assertFalse(any(item["action"] == "SAFE_HOLD" for item in result["actions"]))
        self.assertTrue(result["returned_to_base"])
        self.assertFalse(result["technical_completed"])
        self.assertFalse(result["evidence_qualified_completion"])

    @staticmethod
    def _result(case_id, technical=True, qualified=True, elapsed=1000, nominal=1000, high=0):
        exposure = DynamicRiskExposure(
            int(bool(high)), high, 0, max(elapsed, 1), high / max(elapsed, 1), high,
            elapsed + 2 * high,
        )
        endurance_unverified = technical and elapsed > 4 * 3600
        status = (
            CompletionEvidenceStatus.QUALIFIED if qualified
            else CompletionEvidenceStatus.ENDURANCE_UNVERIFIED if endurance_unverified
            else CompletionEvidenceStatus.INCOMPLETE
        )
        return DynamicMissionResult(
            case_id, "SHORT", "TEST", "INTERNAL SIMULATION BASELINE",
            MissionOutcomeStatus.COMPLETED if technical else MissionOutcomeStatus.RETURNED_UNPLANNED,
            MissionState.COMPLETED if technical else MissionState.ABORTED,
            technical, qualified, status, elapsed, nominal, max(0, elapsed - nominal),
            {"mission_time_feasibility_status": "ENDURANCE_FEASIBILITY_UNVERIFIED" if endurance_unverified else "WITHIN_PUBLISHED_MINIMUM_REFERENCE"},
            not technical, False, False, 0, 0, (), (), exposure, True,
        )


if __name__ == "__main__":
    unittest.main()
