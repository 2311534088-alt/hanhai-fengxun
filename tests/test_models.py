import unittest
from datetime import datetime, timezone

from core.mission import MissionState
from core.models import TelemetryRecord


def valid_record(**changes):
    values = dict(
        timestamp=datetime.now(timezone.utc), latitude=39.6, longitude=122.5,
        Hs=1.0, Tp=5.0, wave_direction=90.0, wind_speed=8.0,
        wind_direction=80.0, SOG=2.0, COG=90.0, HDG=91.0,
        surface_current_speed=0.2, surface_current_direction=45.0,
        roll=3.0, pitch=1.0, roll_rate=2.0, battery=80.0,
        mission_state=MissionState.OUTBOUND,
        data_label="SIMULATED / DEMO ONLY",
    )
    values.update(changes)
    return TelemetryRecord(**values)


class TelemetryModelTests(unittest.TestCase):
    def test_required_fields_and_valid_values(self):
        self.assertEqual(valid_record().mission_state, MissionState.OUTBOUND)
        with self.assertRaises(ValueError):
            TelemetryRecord.from_mapping({"timestamp": "2026-01-01T00:00:00+00:00"})

    def test_null_sensor_values_are_allowed(self):
        self.assertIsNone(valid_record(Hs=None, roll=None).Hs)

    def test_abnormal_values_are_rejected(self):
        for changes in ({"battery": 101.0}, {"Hs": -1.0}, {"latitude": 91.0}, {"HDG": 360.0}, {"surface_current_speed": -0.1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                valid_record(**changes)

    def test_data_label_is_required_and_non_empty(self):
        with self.assertRaises(ValueError):
            valid_record(data_label="")
