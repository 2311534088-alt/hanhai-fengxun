"""Minimal V0.1 replay demo. This module never sends vessel commands."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from adapters.replay.csv_replay import CSVReplay
from core.risk.baseline import BaselineRiskEvaluator
from core.risk.models import VesselParameters


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SAMPLE = PROJECT_ROOT / "data" / "samples" / "sample_mission_001.csv"


def run_demo(csv_path: Path = DEFAULT_SAMPLE, delay: float = 0.0) -> None:
    print("寒海风巡 V0.1 — SIMULATED / DEMO ONLY")
    print("Decision support only; real-vessel control is DISABLED.\n")
    evaluator = BaselineRiskEvaluator()
    vessel = VesselParameters(model="ZLUSV-200")
    for index, record in enumerate(CSVReplay(csv_path), start=1):
        result = evaluator.evaluate(record, vessel)
        print(
            f"[{index:02d}] {record.timestamp.isoformat()} | {record.mission_state.value} | "
            f"位置=({record.latitude:.5f}, {record.longitude:.5f}) | "
            f"SOG={record.SOG if record.SOG is not None else 'N/A'} m/s | "
            f"风险={result.risk_score:.1f}/10 {result.risk_level.value}"
        )
        print(f"     主要风险: {result.primary_risk}")
        print(f"     解释: {result.explanation}")
        print(f"     建议: {result.recommendation} | 置信度={result.confidence:.2f}")
        if delay:
            time.sleep(delay)


def main() -> None:
    parser = argparse.ArgumentParser(description="寒海风巡 V0.1 CSV 回放 Demo")
    parser.add_argument("--csv", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--delay", type=float, default=0.0, help="每条记录间隔秒数")
    args = parser.parse_args()
    if args.delay < 0:
        parser.error("--delay 不得为负数")
    run_demo(args.csv, args.delay)


if __name__ == "__main__":
    main()

