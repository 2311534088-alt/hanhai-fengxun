import unittest
from datetime import datetime, timezone
from pathlib import Path

from adapters.marine_data.era5 import csv_reader
from adapters.marine_data.merge import merge_environments
from core.marine import MarineEnvironment, MarineQualityFlag


ROOT = Path(__file__).resolve().parents[1]


class MarineDataTests(unittest.TestCase):
    def test_local_csv_maps_to_standard_model(self):
        records = csv_reader(MarineQualityFlag.SIMULATED).read(ROOT / "tests/fixtures/era5_simulated.csv")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].source, "ERA5")
        self.assertEqual(records[0].quality_flag, MarineQualityFlag.SIMULATED)
        self.assertEqual(records[0].wind_speed, 4.0)
        self.assertIsNone(records[0].Hs)

    def test_merge_preserves_missing_values(self):
        common = dict(timestamp=datetime.now(timezone.utc), latitude=39.6, longitude=122.5)
        wind = MarineEnvironment(**common, wind_speed=4.0, source="ERA5", quality_flag=MarineQualityFlag.PROVISIONAL)
        wave = MarineEnvironment(**common, Hs=1.0, source="WAVERYS", quality_flag=MarineQualityFlag.PROVISIONAL)
        merged = merge_environments([wind, wave])
        self.assertEqual(merged.wind_speed, 4.0)
        self.assertEqual(merged.Hs, 1.0)
        self.assertIsNone(merged.surface_current_speed)

    def test_invalid_environment_value_is_rejected(self):
        with self.assertRaises(ValueError):
            MarineEnvironment(
                timestamp=datetime.now(timezone.utc), latitude=39.6, longitude=122.5,
                wind_direction=360, source="test", quality_flag=MarineQualityFlag.PROVISIONAL,
            )

