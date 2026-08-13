import unittest
import json
from pathlib import Path
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from core.marine import MarineEnvironment, MarineQualityFlag
from core.mission.dynamic_replay import (
    CausalMultiSourceStore, DurationReferenceStatus, DynamicAction, DynamicMissionCase,
    DynamicMissionEngine, DynamicMissionGeometry, DynamicPolicy, MissionSavedAssessment,
    build_mission_value_blocker_report, validate_segment_sample_invariants,
)
from core.mission.state import MissionState
from core.resonance import load_engineering_estimate


T0 = datetime(2026, 2, 5, tzinfo=timezone.utc)


def records(hs=.1, tp=4.0, direction=0.0):
    values = []
    for at in (T0, T0 + timedelta(minutes=30), T0 + timedelta(hours=1)):
        values.extend((
            MarineEnvironment(at, 39.2, 122.2, Hs=hs, Tp=tp, wave_direction=direction,
                              source="Copernicus WAVERYS:test", quality_flag=MarineQualityFlag.PUBLIC_PRODUCT_FILE),
            MarineEnvironment(at, 39.2, 122.2, wind_speed=3, wind_direction=20,
                              source="ERA5:test", quality_flag=MarineQualityFlag.PUBLIC_PRODUCT_FILE),
            MarineEnvironment(at, 39.2, 122.2, surface_current_speed=.1, surface_current_direction=180,
                              source="Copernicus GLORYS:test", quality_flag=MarineQualityFlag.PUBLIC_PRODUCT_FILE),
        ))
    values.append(MarineEnvironment(T0, 39.2, 122.2, water_depth=12, source="GEBCO:test",
                                    quality_flag=MarineQualityFlag.PUBLIC_PRODUCT_FILE))
    return tuple(values)


class V09DynamicConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parameters, _ = load_engineering_estimate()
        cls.geometry = DynamicMissionGeometry(
            "SHORT", (39.2, 122.2), (39.199, 122.201), "SIMULATED ROUTE",
        )

    def run_case(self, source=None, policy=DynamicPolicy.BASELINE_CONSERVATIVE, phase=MissionState.OUTBOUND):
        engine = DynamicMissionEngine(CausalMultiSourceStore(source or records()), self.parameters)
        case = DynamicMissionCase("v09", T0, self.geometry, inspection_service_time_s=60, initial_phase=phase)
        return engine, engine.run(case, policy)

    def test_every_segment_sample_uses_actual_state(self):
        _, result = self.run_case()
        validate_segment_sample_invariants(result.executed_segments, result.risk_samples)
        self.assertEqual(len(result.executed_segments), len(result.risk_samples))

    def test_executed_sample_invariant_rejects_mismatch(self):
        engine, result = self.run_case()
        segment = result.executed_segments[0]
        sample = engine._sample_for_duration(engine._state(
            segment.start_time, segment.start, MissionState.OUTBOUND,
            segment.executed_SOG_m_s, segment.executed_HDG_deg,
        ), (segment.end_time-segment.start_time).total_seconds(), segment)
        validate_segment_sample_invariants((segment,), (sample,))
        with self.assertRaises(ValueError):
            validate_segment_sample_invariants((segment,), (replace(sample, actual_HDG_deg=999),))

    def test_returning_high_risk_is_safety_decision_not_plain_continue(self):
        engine = DynamicMissionEngine(CausalMultiSourceStore(records(3, 1.7, 90)), self.parameters)
        state = engine._state(T0, self.geometry.task_point, MissionState.RETURNING, 1.8, 0)
        decision = engine._decision(state, DynamicPolicy.HANHAI_MISSION_CONTINUITY,
                                    destination=self.geometry.start)
        self.assertNotEqual(decision.action, DynamicAction.CONTINUE)
        self.assertIn(decision.action, {
            DynamicAction.CONTINUE_RETURN, DynamicAction.ADJUST_RETURN_SPEED_HEADING,
            DynamicAction.REROUTE_RETURN, DynamicAction.SAFE_HOLD_RETURN,
        })

    def test_return_route_screen_destination_is_base(self):
        engine = DynamicMissionEngine(CausalMultiSourceStore(records()), self.parameters)
        screen = engine._route_screen(at=T0, position=self.geometry.task_point,
                                      destination=self.geometry.start, phase=MissionState.RETURNING,
                                      speed=1.8, destination_role="BASE")
        self.assertEqual(screen.destination_role, "BASE")
        self.assertTrue(all(candidate.waypoints[-1] == self.geometry.start for candidate in screen.candidates))

    def test_snapshot_screen_has_no_future_access(self):
        engine = DynamicMissionEngine(CausalMultiSourceStore(records()), self.parameters)
        screen = engine._route_screen(at=T0, position=self.geometry.start,
                                      destination=self.geometry.task_point, phase=MissionState.OUTBOUND,
                                      speed=1.8, destination_role="TASK_POINT")
        self.assertFalse(screen.future_actual_environment_used)
        self.assertEqual(engine.store.future_action_access_count, 0)

    def test_rollout_has_no_future_access(self):
        engine = DynamicMissionEngine(CausalMultiSourceStore(records()), self.parameters)
        state = engine._state(T0, self.geometry.start, MissionState.OUTBOUND, 1.8, 0)
        rollout = engine._candidate_rollout(state=state, candidate_speed=1.8,
                                            candidate_heading=0, destination=self.geometry.task_point)
        self.assertFalse(rollout.future_actual_environment_used)
        self.assertEqual(engine.store.future_action_access_count, 0)

    def test_instant_candidate_is_rejected_when_rollout_deteriorates(self):
        source = records(.3, 2.0, 90)
        engine = DynamicMissionEngine(CausalMultiSourceStore(source), self.parameters)
        state = engine._state(T0, self.geometry.start, MissionState.OUTBOUND, 1.8, 0)
        original = engine._candidate_rollout

        def deteriorated(**kwargs):
            rollout = original(**kwargs)
            return replace(rollout, high_risk_fraction=1.0, acceptable=False)

        engine._candidate_rollout = deteriorated
        decision = engine._decision(state, DynamicPolicy.LOCAL_ADJUST_ONLY,
                                    destination=self.geometry.task_point)
        self.assertNotEqual(decision.action, DynamicAction.ADJUST_SPEED_HEADING)

    def test_duration_reference_is_not_energy_feasibility(self):
        _, result = self.run_case()
        self.assertEqual(result.duration_reference_status, DurationReferenceStatus.COMPATIBLE)
        self.assertEqual(result.energy_feasibility_status, "NOT VERIFIED ENERGY FEASIBILITY")

    def test_signed_delta_and_extra_distance_are_separate(self):
        _, result = self.run_case()
        self.assertAlmostEqual(result.signed_mission_time_delta_s,
                               result.mission_elapsed_time_s-result.nominal_mission_time_s)
        self.assertGreaterEqual(result.extra_distance_m, 0)

    def test_decision_relevant_selection_is_pre_policy(self):
        engine = DynamicMissionEngine(CausalMultiSourceStore(records()), self.parameters)
        case = DynamicMissionCase("select", T0, self.geometry, initial_phase=MissionState.OUTBOUND)
        selection = engine.select_decision_relevant(case)
        self.assertIn("POLICY-INDEPENDENT", selection.selection_rule)
        self.assertNotIn("OUTCOME", selection.selection_rule)
        self.assertNotIn("mission_saved", selection.selection_rule.lower())

    def test_blocker_report_counts_equal_scenarios(self):
        _, result = self.run_case()
        baseline = replace(result, technical_completed=True)
        candidate = replace(result, technical_completed=False)
        report = build_mission_value_blocker_report(
            (baseline,), (candidate,), (MissionSavedAssessment(result.case_id, False, ("X",)),),
        )
        self.assertEqual(sum(report.blocker_counts.values()), report.total_scenarios)

    def test_v09_summary_has_two_predeclared_cohorts_and_strict_gate(self):
        path = Path(__file__).resolve().parents[1] / "data/results/v0.9_summary.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        population = data["cohorts"]["WINTER_POPULATION_COHORT"]
        relevant = data["cohorts"]["DECISION_RELEVANT_COHORT"]
        self.assertEqual(population["N"], 360)
        self.assertEqual(relevant["N"], 9)
        self.assertEqual(data["REPLAY_INTEGRITY_GATE"], "PASS")
        self.assertEqual(data["BUSINESS_VALUE_STATUS"], "NOT_ESTABLISHED")
        self.assertTrue(all(
            value["mission_saved"] == 0 for cohort in data["cohorts"].values()
            for value in cohort["policies"].values()
        ))

    def test_v09_summary_keeps_representative_return_and_truth_labels(self):
        path = Path(__file__).resolve().parents[1] / "data/results/v0.9_summary.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        stress = data["representative_case_2026_02_05"]
        self.assertEqual(stress["future_action_access_count"], 0)
        self.assertTrue(stress["action_chain"])
        self.assertTrue(stress["returned_to_base"])
        self.assertGreater(stress["high_risk_exposure_s"], 0)
        self.assertEqual(data["data_sources"]["energy"], "NOT VERIFIED ENERGY FEASIBILITY")


if __name__ == "__main__":
    unittest.main()
