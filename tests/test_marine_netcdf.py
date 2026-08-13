import io
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

try:
    import numpy as np
    import xarray as xr
except ImportError:  # Optional production dependency.
    np = None
    xr = None

from adapters.marine_data import copernicus_current, copernicus_wave, era5, gebco
from adapters.marine_data.config import load_study_region
from adapters.marine_data.netcdf import (
    MarineDataSchemaError, StudyRegion, direction_of_travel, from_direction_to_travel,
)
from adapters.marine_data.pipeline import (
    build_provenance_manifest, ingest_local_public_files, write_canonical_csv,
)
from adapters.marine_data.sampler import MarineEnvironmentSampler, SamplingTolerance
from core.marine import MarineQualityFlag


REGION = StudyRegion()


@unittest.skipIf(xr is None, "optional marine dependencies are not installed")
class MarineNetCDFTests(unittest.TestCase):
    def test_era5_vector_conversion_and_clipping(self):
        dataset = xr.Dataset(
            {
                "u10": (("time", "latitude", "longitude"), [[[3.0, 8.0]], [[4.0, 9.0]]], {"units": "m s-1"}),
                "v10": (("time", "latitude", "longitude"), [[[4.0, 6.0]], [[0.0, 7.0]]], {"units": "m s-1"}),
            },
            coords={
                "time": np.array(["2026-01-15", "2026-07-15"], dtype="datetime64[ns]"),
                "latitude": [39.6], "longitude": [122.5, 130.0],
            },
        )
        records = era5.records_from_dataset(dataset, "fixture.nc", REGION)
        self.assertEqual(len(records), 1)
        self.assertAlmostEqual(records[0].wind_speed, 5.0)
        self.assertAlmostEqual(records[0].wind_direction, 36.8698976458)
        self.assertEqual(records[0].quality_flag, MarineQualityFlag.PUBLIC_PRODUCT_FILE)

    def test_descending_latitude_and_360_longitude_are_subset_before_expansion(self):
        dataset = xr.Dataset(
            {
                "u10": (("time", "latitude", "longitude"), np.ones((2, 3, 3)), {"units": "m/s"}),
                "v10": (("time", "latitude", "longitude"), np.ones((2, 3, 3)), {"units": "m/s"}),
            },
            coords={
                "time": np.array(["2026-01-15", "2026-07-15"], dtype="datetime64[ns]"),
                "latitude": [41.0, 39.5, 38.0],
                "longitude": [121.0, 122.5, 300.0],
            },
        )
        expanded_sizes = []
        original_to_dataframe = xr.Dataset.to_dataframe

        def capture_sizes(selected, *args, **kwargs):
            expanded_sizes.append(dict(selected.sizes))
            return original_to_dataframe(selected, *args, **kwargs)

        with patch.object(xr.Dataset, "to_dataframe", new=capture_sizes):
            records = era5.records_from_dataset(dataset, "fixture.nc", REGION)
        self.assertEqual(len(records), 1)
        self.assertEqual(expanded_sizes, [{"time": 1, "latitude": 1, "longitude": 1}])
        self.assertEqual(records[0].latitude, 39.5)
        self.assertEqual(records[0].longitude, 122.5)

    def test_waverys_from_direction_becomes_travel_direction(self):
        dataset = xr.Dataset(
            {
                "VHM0": (("time", "latitude", "longitude"), [[[1.5]]], {"units": "m"}),
                "VTPK": (("time", "latitude", "longitude"), [[[5.2]]], {"units": "s"}),
                "VMDR": (("time", "latitude", "longitude"), [[[350.0]]], {"units": "degree"}),
            },
            coords={"time": np.array(["2026-02-01"], dtype="datetime64[ns]"), "latitude": [39.6], "longitude": [122.5]},
        )
        record = copernicus_wave.records_from_dataset(dataset, "fixture.nc", REGION)[0]
        self.assertEqual(record.wave_direction, 170.0)
        self.assertEqual(record.source, "Copernicus WAVERYS:fixture.nc")

    def test_glorys_selects_surface_and_converts_vector(self):
        dataset = xr.Dataset(
            {
                "uo": (("time", "depth", "latitude", "longitude"), [[[[1.0]], [[9.0]]]], {"units": "m/s"}),
                "vo": (("time", "depth", "latitude", "longitude"), [[[[0.0]], [[9.0]]]], {"units": "m/s"}),
            },
            coords={
                "time": np.array(["2026-03-01"], dtype="datetime64[ns]"),
                "depth": [0.5, 10.0], "latitude": [39.6], "longitude": [122.5],
            },
        )
        record = copernicus_current.records_from_dataset(dataset, "fixture.nc", REGION)[0]
        self.assertEqual(record.surface_current_speed, 1.0)
        self.assertEqual(record.surface_current_direction, 90.0)

    def test_gebco_negative_elevation_becomes_depth_and_land_is_excluded(self):
        dataset = xr.Dataset(
            {"elevation": (("lat", "lon"), [[-25.0, 4.0]], {"units": "m"})},
            coords={"lat": [39.6], "lon": [122.5, 122.6]},
        )
        records = gebco.records_from_dataset(
            dataset, "fixture.nc", datetime(2026, 1, 1, tzinfo=timezone.utc), REGION,
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].water_depth, 25.0)

    def test_missing_or_wrong_units_are_rejected(self):
        dataset = xr.Dataset(
            {
                "u10": (("time", "latitude", "longitude"), [[[1.0]]], {"units": "knots"}),
                "v10": (("time", "latitude", "longitude"), [[[1.0]]], {"units": "knots"}),
            },
            coords={"time": np.array(["2026-01-01"], dtype="datetime64[ns]"), "latitude": [39.6], "longitude": [122.5]},
        )
        with self.assertRaises(MarineDataSchemaError):
            era5.records_from_dataset(dataset, "fixture.nc", REGION)

    def test_canonical_csv_and_provenance_are_explicit(self):
        dataset = xr.Dataset(
            {
                "u10": (("time", "latitude", "longitude"), [[[0.0]]], {"units": "m s-1"}),
                "v10": (("time", "latitude", "longitude"), [[[2.0]]], {"units": "m s-1"}),
            },
            coords={"time": np.array(["2026-01-01"], dtype="datetime64[ns]"), "latitude": [39.6], "longitude": [122.5]},
        )
        records = era5.records_from_dataset(dataset, "fixture.nc", REGION)
        stream = io.StringIO()
        self.assertEqual(write_canonical_csv(records, stream), 1)
        self.assertIn("PUBLIC_PRODUCT_FILE", stream.getvalue())
        source_file = Path(__file__).resolve()
        manifest = build_provenance_manifest(
            {"ERA5": source_file}, {"ERA5": "reanalysis-era5-single-levels"}, records, REGION,
        )
        self.assertIn("NOT IN-SITU", manifest["artifact_type"])
        self.assertEqual(len(manifest["inputs"]["ERA5"]["sha256"]), 64)
        self.assertEqual(manifest["inputs"]["ERA5"]["product_id"], "reanalysis-era5-single-levels")


class DirectionConversionTests(unittest.TestCase):
    def test_cardinal_vector_directions_are_travel_directions(self):
        self.assertEqual(direction_of_travel(0, 1), 0)
        self.assertEqual(direction_of_travel(1, 0), 90)
        self.assertEqual(direction_of_travel(0, -1), 180)
        self.assertEqual(direction_of_travel(-1, 0), 270)

    def test_from_direction_wraps_to_travel_direction(self):
        self.assertEqual(from_direction_to_travel(0), 180)
        self.assertEqual(from_direction_to_travel(350), 170)

    def test_pipeline_requires_all_product_ids_before_reading_files(self):
        with self.assertRaises(ValueError):
            ingest_local_public_files(
                era5_path="missing.nc", waverys_path="missing.nc",
                glorys_path="missing.nc", gebco_path="missing.nc",
                product_ids={"ERA5": "reanalysis-era5-single-levels"}, region=REGION,
            )

    def test_study_region_config_is_explicitly_not_admin_boundary(self):
        region = load_study_region()
        self.assertEqual(region.longitude_min, 121.5)
        self.assertEqual(region.winter_months, (11, 12, 1, 2, 3))


class MarineSamplerTests(unittest.TestCase):
    def setUp(self):
        self.target_time = datetime(2026, 1, 15, 8, tzinfo=timezone.utc)

    def _record(self, source, *, minutes=0, latitude=39.6, longitude=122.5, **values):
        from datetime import timedelta
        from core.marine import MarineEnvironment
        return MarineEnvironment(
            timestamp=self.target_time + timedelta(minutes=minutes),
            latitude=latitude, longitude=longitude, source=source,
            quality_flag=MarineQualityFlag.PUBLIC_PRODUCT_FILE, **values,
        )

    def test_nearest_sampling_from_different_grids_preserves_field_provenance(self):
        records = [
            self._record("ERA5:wind.nc", minutes=20, latitude=39.61, wind_speed=8.0, wind_direction=90.0),
            self._record("WAVERYS:wave.nc", minutes=-30, longitude=122.52, Hs=1.4, Tp=5.0, wave_direction=170.0),
            self._record(
                "GLORYS:current.nc", minutes=40, latitude=39.58,
                surface_current_speed=0.3, surface_current_direction=45.0,
            ),
            self._record("GEBCO:depth.nc", minutes=-10000, longitude=122.51, water_depth=24.0),
        ]
        result = MarineEnvironmentSampler(records, SamplingTolerance(3600, 5000)).sample(
            self.target_time, 39.6, 122.5,
        )
        self.assertEqual(result.Hs, 1.4)
        self.assertEqual(result.wind_speed, 8.0)
        self.assertEqual(result.surface_current_speed, 0.3)
        self.assertEqual(result.water_depth, 24.0)
        self.assertEqual(result.provenance_by_field["Hs"].source, "WAVERYS:wave.nc")
        self.assertEqual(result.provenance_by_field["wind_speed"].time_offset_seconds, 1200)
        self.assertIsNone(result.provenance_by_field["water_depth"].time_offset_seconds)
        self.assertTrue(result.provenance_by_field["surface_current_speed"].within_tolerance)

    def test_tolerance_excess_returns_null_with_rejection_provenance(self):
        records = [self._record("ERA5:far.nc", minutes=180, latitude=41.0, wind_speed=12.0)]
        result = MarineEnvironmentSampler(records, SamplingTolerance(3600, 5000)).sample(
            self.target_time, 39.6, 122.5,
        )
        self.assertIsNone(result.wind_speed)
        provenance = result.provenance_by_field["wind_speed"]
        self.assertEqual(provenance.source, "ERA5:far.nc")
        self.assertFalse(provenance.within_tolerance)
        self.assertGreater(provenance.time_offset_seconds, 3600)
        self.assertGreater(provenance.spatial_distance_m, 5000)

    def test_valid_candidate_is_preferred_over_closer_but_out_of_tolerance_candidate(self):
        records = [
            self._record("ERA5:too-old.nc", minutes=120, wind_speed=20.0),
            self._record("ERA5:valid.nc", minutes=30, latitude=39.61, wind_speed=7.0),
        ]
        result = MarineEnvironmentSampler(records, SamplingTolerance(3600, 5000)).sample(
            self.target_time, 39.6, 122.5,
        )
        self.assertEqual(result.wind_speed, 7.0)
        self.assertEqual(result.provenance_by_field["wind_speed"].source, "ERA5:valid.nc")
