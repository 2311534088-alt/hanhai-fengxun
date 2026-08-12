import unittest

from core.mission import MissionState, MissionStateMachine, MissionStatistics


class MissionTests(unittest.TestCase):
    def test_valid_full_mission(self):
        machine = MissionStateMachine()
        for state in (MissionState.OUTBOUND, MissionState.ON_STATION, MissionState.RETURNING, MissionState.COMPLETED):
            machine.transition(state)
        self.assertEqual(machine.state, MissionState.COMPLETED)

    def test_invalid_transition(self):
        machine = MissionStateMachine()
        with self.assertRaises(ValueError):
            machine.transition(MissionState.COMPLETED)

    def test_abort_from_active_state(self):
        machine = MissionStateMachine(MissionState.OUTBOUND)
        machine.transition(MissionState.ABORTED)
        self.assertEqual(machine.state, MissionState.ABORTED)

    def test_unknown_statistics_remain_null(self):
        stats = MissionStatistics()
        self.assertIsNone(stats.mission_completed)
        self.assertIsNone(stats.distance_travelled)

