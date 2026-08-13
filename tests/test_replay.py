import unittest
from pathlib import Path

from adapters.replay import CSVReplay


ROOT = Path(__file__).resolve().parents[1]


class ReplayTests(unittest.TestCase):
    def test_reads_sample_in_time_order(self):
        records = list(CSVReplay(ROOT / "data/samples/sample_mission_001.csv"))
        self.assertEqual(len(records), 11)
        self.assertEqual([r.timestamp for r in records], sorted(r.timestamp for r in records))
        self.assertTrue(all(r.data_label == "SIMULATED / DEMO ONLY" for r in records))
        self.assertTrue(any(r.surface_current_speed is not None for r in records))
        self.assertTrue(any(r.roll_rate is not None for r in records))

    def test_rejects_out_of_order_csv(self):
        with self.assertRaises(ValueError):
            list(CSVReplay(ROOT / "tests/fixtures/out_of_order.csv"))
