import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

try:
    import numpy as np
    import xarray as xr
except ImportError:
    np = None
    xr = None

from adapters.marine_data.validation import summarize, validate_public_netcdf


@unittest.skipIf(xr is None, "optional marine dependencies are not installed")
class PublicFileValidationTests(unittest.TestCase):
    def test_validation_records_hash_units_missing_stats_and_coordinate_conventions(self):
        path = Path(__file__)
        dataset = xr.Dataset(
            {"u10": (("time", "latitude", "longitude"), [[[1.0], [np.nan]]], {"units": "m s-1"})},
            coords={
                "time": np.array(["2026-02-20"], dtype="datetime64[ns]"),
                "latitude": [40.0, 39.0],
                "longitude": [122.0],
            },
        )
        with patch("xarray.open_dataset", return_value=dataset), patch(
            "adapters.marine_data.validation.source_sha256", return_value="a" * 64,
        ):
            result = validate_public_netcdf(
                path, product_id="ERA5", dataset_id="reanalysis-era5-single-levels",
                variable_units={"u10": {"m s-1"}}, requested_bbox=(121.5, 124.5, 38.5, 40.5),
                requested_time_range=(
                    datetime(2026, 2, 20, tzinfo=timezone.utc),
                    datetime(2026, 2, 20, 23, 59, 59, tzinfo=timezone.utc),
                ), direction_convention="eastward component",
            )
        self.assertEqual(result["status"], "PASSED")
        self.assertEqual(result["latitude_order"], "descending")
        self.assertEqual(result["longitude_convention"], "-180_to_180")
        self.assertEqual(result["variables"]["u10"]["missing_percentage"], 50.0)
        self.assertEqual(len(result["sha256"]), 64)

    def test_wrong_units_fail_validation(self):
        path = Path(__file__)
        dataset = xr.Dataset(
            {"uo": (("time", "latitude", "longitude"), [[[1.0]]], {"units": "knots"})},
            coords={"time": np.array(["2026-02-20"], dtype="datetime64[ns]"), "latitude": [39.0], "longitude": [122.0]},
        )
        with patch("xarray.open_dataset", return_value=dataset), patch(
            "adapters.marine_data.validation.source_sha256", return_value="b" * 64,
        ):
            result = validate_public_netcdf(
                path, product_id="P", dataset_id="D", variable_units={"uo": {"m s-1"}},
                requested_bbox=(121.5, 124.5, 38.5, 40.5),
                requested_time_range=(
                    datetime(2026, 2, 20, tzinfo=timezone.utc),
                    datetime(2026, 2, 20, 23, 59, 59, tzinfo=timezone.utc),
                ), direction_convention="eastward",
            )
        self.assertEqual(result["status"], "FAILED")
        self.assertIn("unexpected units", result["errors"][0])


class SummaryTests(unittest.TestCase):
    def test_summary_percentiles(self):
        result = summarize([1.0, 2.0, 3.0, 4.0], (90, 95))
        self.assertEqual(result["sample_count"], 4)
        self.assertEqual(result["median"], 2.5)
        self.assertGreater(result["p95"], result["p90"])

    def test_empty_summary_remains_null(self):
        result = summarize([], (90,))
        self.assertEqual(result["sample_count"], 0)
        self.assertIsNone(result["maximum"])
