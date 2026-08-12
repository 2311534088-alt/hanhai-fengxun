"""Local public-product files to canonical records and provenance artifacts."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, TextIO

from adapters.marine_data import copernicus_current, copernicus_wave, era5, gebco
from adapters.marine_data.config import load_study_region
from adapters.marine_data.netcdf import StudyRegion, source_sha256
from core.marine import MarineEnvironment


CANONICAL_FIELDS = (
    "timestamp", "latitude", "longitude", "Hs", "Tp", "wave_direction",
    "wind_speed", "wind_direction", "surface_current_speed",
    "surface_current_direction", "water_depth", "source", "quality_flag",
)


def ingest_local_public_files(
    *,
    era5_path: str | Path,
    waverys_path: str | Path,
    glorys_path: str | Path,
    gebco_path: str | Path,
    product_ids: dict[str, str],
    region: StudyRegion,
) -> list[MarineEnvironment]:
    expected_products = {"ERA5", "Copernicus WAVERYS", "Copernicus GLORYS", "GEBCO"}
    if set(product_ids) != expected_products or any(not value.strip() for value in product_ids.values()):
        raise ValueError(f"product_ids must provide non-empty values for {sorted(expected_products)}")
    dynamic = [
        *era5.read_local_netcdf(era5_path, region, f"{product_ids['ERA5']}:{Path(era5_path).name}"),
        *copernicus_wave.read_local_netcdf(
            waverys_path, region, f"{product_ids['Copernicus WAVERYS']}:{Path(waverys_path).name}"
        ),
        *copernicus_current.read_local_netcdf(
            glorys_path, region, f"{product_ids['Copernicus GLORYS']}:{Path(glorys_path).name}"
        ),
    ]
    if not dynamic:
        raise ValueError("no winter records within the configured project clipping region")
    reference_time = min(record.timestamp for record in dynamic)
    static_depth = gebco.read_local_netcdf(
        gebco_path, reference_time, region, f"{product_ids['GEBCO']}:{Path(gebco_path).name}"
    )
    return sorted(
        [*dynamic, *static_depth],
        key=lambda item: (item.timestamp, item.latitude, item.longitude, item.source),
    )


def write_canonical_csv(records: Iterable[MarineEnvironment], stream: TextIO) -> int:
    writer = csv.DictWriter(stream, fieldnames=CANONICAL_FIELDS, lineterminator="\n")
    writer.writeheader()
    count = 0
    for record in records:
        writer.writerow({
            "timestamp": record.timestamp.isoformat(),
            "latitude": record.latitude,
            "longitude": record.longitude,
            "Hs": record.Hs, "Tp": record.Tp, "wave_direction": record.wave_direction,
            "wind_speed": record.wind_speed, "wind_direction": record.wind_direction,
            "surface_current_speed": record.surface_current_speed,
            "surface_current_direction": record.surface_current_direction,
            "water_depth": record.water_depth,
            "source": record.source, "quality_flag": record.quality_flag.value,
        })
        count += 1
    return count


def build_provenance_manifest(
    paths: dict[str, str | Path], product_ids: dict[str, str],
    records: Iterable[MarineEnvironment], region: StudyRegion,
) -> dict[str, Any]:
    items = list(records)
    counts = Counter(record.source.split(":", 1)[0] for record in items)
    return {
        "schema_version": 1,
        "artifact_type": "DERIVED PUBLIC-DATA PIPELINE OUTPUT - NOT IN-SITU OBSERVATION",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "direction_convention": "direction of travel; 0=N, 90=E, range [0,360)",
        "study_region": {
            "warning": "project clipping box, not Zhuanghe administrative boundary",
            "longitude": [region.longitude_min, region.longitude_max],
            "latitude": [region.latitude_min, region.latitude_max],
            "winter_months": list(region.winter_months),
        },
        "inputs": {
            name: {
                "filename": Path(path).name,
                "product_id": product_ids[name],
                "sha256": source_sha256(path),
                "normalized_record_count": counts.get(name, 0),
            }
            for name, path in paths.items()
        },
        "total_records": len(items),
    }


def run_pipeline(args: argparse.Namespace) -> None:
    region = load_study_region(args.region_config)
    paths = {
        "ERA5": args.era5,
        "Copernicus WAVERYS": args.waverys,
        "Copernicus GLORYS": args.glorys,
        "GEBCO": args.gebco,
    }
    product_ids = {
        "ERA5": args.era5_product_id,
        "Copernicus WAVERYS": args.waverys_product_id,
        "Copernicus GLORYS": args.glorys_product_id,
        "GEBCO": args.gebco_product_id,
    }
    records = ingest_local_public_files(
        era5_path=args.era5, waverys_path=args.waverys,
        glorys_path=args.glorys, gebco_path=args.gebco,
        product_ids=product_ids, region=region,
    )
    output = Path(args.output)
    manifest = Path(args.manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as stream:
        write_canonical_csv(records, stream)
    manifest.write_text(
        json.dumps(build_provenance_manifest(paths, product_ids, records, region), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize local ERA5/CMEMS/GEBCO NetCDF files")
    parser.add_argument("--era5", required=True)
    parser.add_argument("--waverys", required=True)
    parser.add_argument("--glorys", required=True)
    parser.add_argument("--gebco", required=True)
    parser.add_argument("--era5-product-id", required=True)
    parser.add_argument("--waverys-product-id", required=True)
    parser.add_argument("--glorys-product-id", required=True)
    parser.add_argument("--gebco-product-id", required=True)
    parser.add_argument("--output", required=True, help="canonical CSV output")
    parser.add_argument("--manifest", required=True, help="JSON provenance output")
    parser.add_argument("--region-config", default=str(Path(__file__).resolve().parents[2] / "configs/zhuanghe.yaml"))
    run_pipeline(parser.parse_args())


if __name__ == "__main__":
    main()
