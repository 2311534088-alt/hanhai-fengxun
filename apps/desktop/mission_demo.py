"""Console V0.3 task demo driven by committed real-environment evidence."""

from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULT = PROJECT_ROOT / "data" / "results" / "v0.3_mission_demo.json"


def run_demo(result_path: Path = DEFAULT_RESULT) -> None:
    result = json.loads(result_path.read_text(encoding="utf-8"))
    print(result["demo_name"])
    print(f"Environment: {result['environment_source']}")
    print(f"Vessel state: {result['vessel_state_source']}")
    print(f"Roll parameters: {result['parameter_source']} / {result['parameter_status']}")
    print(result["algorithm_status"])
    print(result["control_status"])
    print("\nMission flow: " + " -> ".join(result["mission_flow"]))
    for scenario in result["scenarios"]:
        before = scenario["before"]
        after = scenario["after"]
        print(f"\n[{scenario['scenario_id']}] Hs={scenario['environment']['Hs']:.2f} m, "
              f"Tp={scenario['environment']['Tp']:.2f} s, "
              f"wave_direction={scenario['environment']['wave_direction']:.2f} deg")
        print(f"  before: SOG={before['SOG']:.2f} m/s, HDG={before['HDG']:.2f} deg, "
              f"status={before['resonance_status']}, margin={before['resonance_margin_ratio']:.4f}, "
              f"risk={before['risk_score']:.2f}/10")
        print(f"  after:  SOG={after['SOG']:.2f} m/s, HDG={after['HDG']:.2f} deg, "
              f"status={after['resonance_status']}, margin={after['resonance_margin_ratio']:.4f}, "
              f"risk={after['risk_score']:.2f}/10")
        print(f"  decision: {scenario['decision_reason']}")
    print("\nEnergy model: REQUIRES REAL SPEED-POWER DATA")


def main() -> None:
    run_demo()


if __name__ == "__main__":
    main()
