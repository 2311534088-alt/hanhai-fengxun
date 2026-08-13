import unittest
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

from core.marine import MarineEnvironment, MarineQualityFlag
from core.mission import (
    CausalEnvironmentStore, EnvironmentUse, FutureDataLeakageError, MissionCase,
    MissionEvent, MissionState, MissionTimeline, ReplayPolicy, action_outcome_status,
    assess_endurance, compute_risk_exposure, evaluate_business_value_gate,
    evaluate_spatiotemporal_route, mission_saved, replay_complete_mission,
    summarize_complete_replay,
)
from core.mission.causal_replay import MissionReplayResult, RouteRiskSample
from core.mission.decision import MissionAction, MissionOutcomeStatus
from core.resonance import load_engineering_estimate


UTC = timezone.utc
T0 = datetime(2026, 2, 5, tzinfo=UTC)


def environment(at, lat=39.2, lon=122.2, hs=0.1, tp=4.0, direction=0.0):
    return MarineEnvironment(
        timestamp=at, latitude=lat, longitude=lon, Hs=hs, Tp=tp,
        wave_direction=direction, source="Copernicus WAVERYS:test",
        quality_flag=MarineQualityFlag.PUBLIC_PRODUCT_FILE,
    )


def completed_result(case_id="x", elapsed=3600, high_time=0):
    timeline = MissionTimeline(T0, [
        MissionEvent(MissionState.PRE_DEPARTURE, T0, "MISSION_RELEASED", "SIMULATED"),
        MissionEvent(MissionState.OUTBOUND, T0, "OUTBOUND_STARTED", "SIMULATED"),
        MissionEvent(MissionState.ON_STATION, T0, "TASK_POINT_REACHED", "SIMULATED"),
        MissionEvent(MissionState.ON_STATION, T0, "SIMULATED_INSPECTION_SERVICE_COMPLETED", "SIMULATED MISSION PARAMETER"),
        MissionEvent(MissionState.RETURNING, T0, "RETURN_STARTED", "SIMULATED"),
        MissionEvent(MissionState.COMPLETED, T0, "SAFE_RETURN_AND_MISSION_CLOSED", "SIMULATED"),
    ], outbound_time_s=elapsed / 3, inspection_service_time_s=elapsed / 3, return_time_s=elapsed / 3)
    sample = RouteRiskSample(
        T0, 39.2, 122.2, .2, 4, 0, 1,
        "RESIDUAL_HIGH_RISK_UNDER_PARAMETER_UNCERTAINTY" if high_time else "ROBUST_NORMAL",
        high_time or elapsed,
    )
    exposure = compute_risk_exposure((sample,))
    return MissionReplayResult(
        case_id, "TEST", "INTERNAL SIMULATION BASELINE", MissionOutcomeStatus.COMPLETED,
        MissionState.COMPLETED, timeline, (MissionAction.CONTINUE,), exposure,
        assess_endurance(elapsed), False, False,
    )


class CausalMissionReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parameters, _ = load_engineering_estimate()

    def test_hold_action_is_pending_not_completed(self):
        self.assertEqual(action_outcome_status(MissionAction.HOLD_AND_REASSESS), MissionOutcomeStatus.PENDING_REASSESSMENT)

    def test_reroute_action_is_in_progress_not_completed(self):
        self.assertEqual(action_outcome_status(MissionAction.REROUTE), MissionOutcomeStatus.IN_PROGRESS)

    def test_only_completed_state_with_full_flow_counts(self):
        result = completed_result()
        self.assertTrue(result.mission_completed)
        result.timeline.events.pop()
        self.assertFalse(result.mission_completed)

    def test_action_selection_cannot_read_t_plus_three(self):
        store = CausalEnvironmentStore((environment(T0), environment(T0 + timedelta(hours=3))))
        with self.assertRaises(FutureDataLeakageError):
            store.nearest(timestamp=T0 + timedelta(hours=3), latitude=39.2, longitude=122.2,
                          decision_timestamp=T0, purpose=EnvironmentUse.ACTION_SELECTION)

    def test_future_environment_is_available_only_to_outcome_evaluation(self):
        store = CausalEnvironmentStore((environment(T0), environment(T0 + timedelta(hours=3))))
        selected = store.nearest(timestamp=T0 + timedelta(hours=3), latitude=39.2, longitude=122.2,
                                 decision_timestamp=T0, purpose=EnvironmentUse.OUTCOME_EVALUATION)
        self.assertEqual(selected.timestamp, T0 + timedelta(hours=3))
        self.assertEqual(store.access_log[-1].reason, "OUTCOME_ONLY_ACCESS")

    def test_hold_cost_is_three_hours_and_energy_unavailable(self):
        records = (
            environment(T0, hs=3.0, tp=1.7, direction=90),
            environment(T0 + timedelta(hours=3), hs=.1, tp=4, direction=0),
            environment(T0 + timedelta(hours=6), hs=.1, tp=4, direction=0),
        )
        case = MissionCase("hold", T0, (39.2, 122.2), (39.199, 122.199))
        result = replay_complete_mission(
            case=case, policy=ReplayPolicy.HANHAI_MISSION_CONTINUITY,
            store=CausalEnvironmentStore(records), parameters=self.parameters,
        )
        if result.hold_used:
            self.assertEqual(result.timeline.hold_time_s, 10_800)
            self.assertIsNone(result.hold_energy)
            self.assertEqual(result.hold_energy_status, "REQUIRES REAL POWER DATA")

    def test_over_four_hours_is_endurance_unverified(self):
        result = assess_endurance(4.1 * 3600)
        self.assertEqual(result.published_reference_comparison, "EXCEEDS_PUBLISHED_MINIMUM_REFERENCE")
        self.assertEqual(result.mission_time_feasibility_status, "ENDURANCE_FEASIBILITY_UNVERIFIED")

    def test_complete_task_requires_return(self):
        timeline = completed_result().timeline
        timeline.events = [item for item in timeline.events if item.state is not MissionState.RETURNING]
        self.assertFalse(timeline.mission_completed)

    def test_route_advances_time_and_space(self):
        records = tuple(environment(T0 + timedelta(hours=h), lat, lon) for h in range(4)
                        for lat, lon in ((39.2, 122.2), (39.19, 122.19)))
        result = evaluate_spatiotemporal_route(
            route_id="test", waypoints=((39.2, 122.2), (39.19, 122.19)), started_at=T0,
            speed_m_s=1.8, store=CausalEnvironmentStore(records), parameters=self.parameters,
            sampling_interval_s=60,
        )
        self.assertGreater(len(result.samples), 1)
        self.assertGreater(result.samples[-1].timestamp, result.samples[0].timestamp)
        self.assertNotEqual(result.samples[-1].latitude, result.samples[0].latitude)

    def test_risk_exposure_is_computed_not_return_flag(self):
        samples = (
            RouteRiskSample(T0, 0, 0, 1, 2, 3, 4, "RESIDUAL_HIGH_RISK_UNDER_PARAMETER_UNCERTAINTY", 600),
            RouteRiskSample(T0, 0, 0, 1, 2, 3, 4, "ROBUST_NORMAL", 400),
        )
        metric = compute_risk_exposure(samples)
        self.assertEqual(metric.high_risk_exposure_time_s, 600)
        self.assertAlmostEqual(metric.risk_exposure_ratio, .6)

    def test_mission_saved_requires_full_evidence_supported_completion(self):
        baseline = completed_result("same")
        baseline = MissionReplayResult(
            baseline.case_id, baseline.policy_name, baseline.policy_definition,
            MissionOutcomeStatus.RETURNED_UNPLANNED, MissionState.RETURNING,
            baseline.timeline, (MissionAction.RETURN,), baseline.exposure,
            baseline.endurance, False, False,
        )
        self.assertTrue(mission_saved(baseline, completed_result("same")))
        self.assertFalse(mission_saved(baseline, completed_result("same", elapsed=5 * 3600)))

    def test_batch_summary_has_denominator_counts_and_internal_label(self):
        metrics = summarize_complete_replay((completed_result("a"), completed_result("b")))
        self.assertEqual(metrics.denominator_N, 2)
        self.assertEqual(metrics.completed_missions, 2)
        self.assertEqual(metrics.baseline_status, "INTERNAL SIMULATION BASELINE")

    def test_business_gate_fails_and_passes_correctly(self):
        result = completed_result()
        passed = evaluate_business_value_gate(results=(result,), future_action_leakage_count=0)
        failed = evaluate_business_value_gate(results=(result,), future_action_leakage_count=1)
        self.assertEqual(passed.business_value_evidence, "DEVELOPMENT_PASS")
        self.assertEqual(failed.business_value_evidence, "FAIL")

    def test_labels_are_not_lost(self):
        result = completed_result()
        self.assertIn("REAL PUBLIC", result.environment_source)
        self.assertEqual(result.vessel_state_source, "SIMULATED VESSEL STATE")
        self.assertEqual(result.parameter_source, "ENGINEERING_ESTIMATE")

    def test_v07_evidence_has_120_cases_counts_and_causal_gate(self):
        path = Path(__file__).resolve().parents[1] / "data/results/v0.7_causal_mission_replay.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["selection"]["total_cases_N"], 120)
        self.assertEqual(len(data["case_outcomes"]), 120)
        for policy in data["policy_summaries"].values():
            self.assertEqual(policy["denominator_N"], 120)
            self.assertEqual(policy["baseline_status"], "INTERNAL SIMULATION BASELINE")
        self.assertEqual(data["business_value_gate"]["business_value_evidence"], "DEVELOPMENT_PASS")
        self.assertEqual(data["replay_integrity_gate"], "PASS")
        self.assertEqual(data["business_value_status"], "NOT_ESTABLISHED")
        self.assertIn("DEPRECATED", data["legacy_business_value_evidence_status"])
        self.assertFalse(data["oracle_experiment"]["used_for_business_metrics"])

    def test_v07_stress_case_is_complete_but_endurance_unverified(self):
        path = Path(__file__).resolve().parents[1] / "data/results/v0.7_causal_mission_replay.json"
        result = json.loads(path.read_text(encoding="utf-8"))["scenario_2026_02_05"]
        self.assertIn("STRESS-TEST SIMULATED ROUTE", result["route_status"])
        self.assertTrue(result["result"]["mission_completed"])
        self.assertEqual(
            result["result"]["endurance"]["mission_time_feasibility_status"],
            "ENDURANCE_FEASIBILITY_UNVERIFIED",
        )
        self.assertEqual(result["causal_access_audit"]["future_action_access_count"], 0)


if __name__ == "__main__":
    unittest.main()
