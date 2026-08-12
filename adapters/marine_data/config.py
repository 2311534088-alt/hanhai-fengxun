"""Load the JSON-compatible YAML study-region configuration."""

from __future__ import annotations

import json
from pathlib import Path

from adapters.marine_data.netcdf import StudyRegion


DEFAULT_REGION_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "zhuanghe.yaml"


def load_study_region(path: str | Path = DEFAULT_REGION_CONFIG) -> StudyRegion:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("warning") != "not_an_administrative_boundary":
        raise ValueError("study-region config must state that it is not an administrative boundary")
    return StudyRegion(
        longitude_min=float(data["longitude_deg_east"]["min"]),
        longitude_max=float(data["longitude_deg_east"]["max"]),
        latitude_min=float(data["latitude_deg_north"]["min"]),
        latitude_max=float(data["latitude_deg_north"]["max"]),
        winter_months=tuple(int(month) for month in data["winter_months"]),
    )
