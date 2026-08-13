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
DEFAULT_PRODUCT_REPLAY = PROJECT_ROOT / "data" / "replay" / "v1.0c_competition_demo.json"


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


def run_competition_console(replay_path: Path = DEFAULT_PRODUCT_REPLAY, delay: float = 0.0) -> None:
    from apps.desktop.product_model import CompetitionDemoReplay

    replay = CompetitionDemoReplay(replay_path)
    print("寒海风巡 V1.0-C competition demo")
    print("REAL PUBLIC HISTORICAL ENVIRONMENT · SIMULATED VESSEL STATE")
    print("DECISION ADVICE ONLY · SIMULATED ACTION EXECUTED · REAL VESSEL CONTROL DISABLED\n")
    for index, event in enumerate(replay.events, 1):
        print(
            f"[{index:02d}] event={event['event_type']} | timestamp={event['timestamp']} | "
            f"environment_time={event['environment_data_time']} | "
            f"position=({event['latitude']:.6f}, {event['longitude']:.6f}) | "
            f"SOG/HDG={event['SOG']:.2f}/{event['HDG']:.1f} | "
            f"environment=Hs {event['Hs']} m, Tp {event['Tp']} s, wind {event['wind_speed']} m/s"
        )
        print(
            f"     risk={event['single_vessel_risk_score']:.2f} {event['single_vessel_risk_level']} | "
            f"robust={event['robust_status']} | mission_action={event['decision_action']} | "
            f"recommended={event['recommended_SOG']}/{event['recommended_HDG']} | "
            f"executed={event['executed_SOG']}/{event['executed_HDG']}"
        )
        print(f"     sources={event['source_labels']}")
        if delay:
            time.sleep(delay)


def main() -> None:
    parser = argparse.ArgumentParser(description="寒海风巡 V1.0 产品原型")
    parser.add_argument("--csv", type=Path, default=DEFAULT_SAMPLE, help="console 模拟 CSV")
    parser.add_argument("--replay", type=Path, default=DEFAULT_PRODUCT_REPLAY, help="GUI 同步历史回放 JSON")
    parser.add_argument("--console", action="store_true", help="运行 V1.0-C 事件命令行回放")
    parser.add_argument("--legacy-csv", action="store_true", help="运行早期模拟 CSV console")
    parser.add_argument("--delay", type=float, default=0.0, help="每条记录间隔秒数")
    args = parser.parse_args()
    if args.delay < 0:
        parser.error("--delay 不得为负数")
    if args.legacy_csv:
        run_demo(args.csv, args.delay)
    elif args.console or args.delay:
        run_competition_console(args.replay, args.delay)
    else:
        from apps.desktop.gui import run_gui
        run_gui(args.replay)


if __name__ == "__main__":
    main()

