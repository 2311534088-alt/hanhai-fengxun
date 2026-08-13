"""V1.0 entry point with GUI and backward-compatible console replay."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from adapters.replay.csv_replay import CSVReplay
from core.risk.baseline import BaselineRiskEvaluator
from core.risk.models import VesselParameters


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SAMPLE = PROJECT_ROOT / "data" / "samples" / "sample_mission_001.csv"
DEFAULT_PRODUCT_REPLAY = PROJECT_ROOT / "data" / "replay" / "v1.0b_synchronized_historical_mission.json"


def run_demo(csv_path: Path = DEFAULT_SAMPLE, delay: float = 0.0) -> None:
    print("寒海风巡 V0.2 baseline — SIMULATED / DEMO ONLY")
    print("Decision support only; real-vessel control is DISABLED.\n")
    evaluator = BaselineRiskEvaluator()
    vessel = VesselParameters(
        model="ZLUSV-200", length_overall_m=2.02, beam_m=0.88,
        draft_m=0.25, hull_mass_approx_kg=50,
        full_load_displacement_min_kg=100,
    )
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
        print(f"     风险分量: {result.risk_components}")
        print(f"     建议: {result.recommendation} | 数据质量={result.data_quality:.2f}")
        if delay:
            time.sleep(delay)


def main() -> None:
    parser = argparse.ArgumentParser(description="寒海风巡 V1.0 产品原型")
    parser.add_argument("--csv", type=Path, default=DEFAULT_SAMPLE, help="console 模拟 CSV")
    parser.add_argument("--replay", type=Path, default=DEFAULT_PRODUCT_REPLAY, help="GUI 同步历史回放 JSON")
    parser.add_argument("--console", action="store_true", help="运行兼容的命令行回放")
    parser.add_argument("--delay", type=float, default=0.0, help="每条记录间隔秒数")
    args = parser.parse_args()
    if args.delay < 0:
        parser.error("--delay 不得为负数")
    if args.console or args.delay:
        run_demo(args.csv, args.delay)
    else:
        from apps.desktop.gui import run_gui
        run_gui(args.replay)


if __name__ == "__main__":
    main()

