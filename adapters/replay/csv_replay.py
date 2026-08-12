"""Chronological CSV replay adapter."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path

from core.models import TelemetryRecord


class CSVReplay:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def __iter__(self) -> Iterator[TelemetryRecord]:
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        with self.path.open("r", encoding="utf-8-sig", newline="") as stream:
            records = [TelemetryRecord.from_mapping(row) for row in csv.DictReader(stream)]
        timestamps = [record.timestamp for record in records]
        if timestamps != sorted(timestamps):
            raise ValueError("CSV records must be ordered by timestamp")
        yield from records

