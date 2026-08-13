"""Replay V0.6 mission-policy evidence; never emits vessel commands."""

from __future__ import annotations

import json
from pathlib import Path


RESULT = Path(__file__).resolve().parents[2] / "data" / "results" / "v0.6_mission_policy_demo.json"


def main() -> None:
    data = json.loads(RESULT.read_text(encoding="utf-8"))
    print(data["demo_name"])
    print(f"{data['response_model_status']} / {data['angle_prediction_status']}")
    print(f"actual_roll_response_deg={data['actual_roll_response_deg']}")
    print(data["historical_replay_status"])
    for window in data["historical_windows"]:
        print(f"+{window['offset_hours']}h: Hs={window['Hs_m']:.2f} m, Tp={window['Tp_s']:.2f} s, "
              f"GRID_Q90 proxy={window['grid_q90_roll_response_proxy']:.3f}, {window['robust_status']}")
    decision = data["mission_decision"]["technical_outcome"]
    print(f"preferred_mission_action={decision['preferred_mission_action']}")
    print(decision["decision_reason"])
    for policy in data["policy_replay_comparison"]:
        print(f"{policy['policy_name']}: completion={policy['simulated_mission_completion_rate']:.0%}, "
              f"interruption={policy['simulated_interruption_rate']:.0%}, "
              f"return={policy['simulated_unplanned_return_rate']:.0%}")
    print("MODEL-BASED / HISTORICAL-ENVIRONMENT REPLAY")
    print("NOT SAC / REAL VESSEL CONTROL DISABLED")


if __name__ == "__main__":
    main()
