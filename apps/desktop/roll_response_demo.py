"""V0.4 evidence replay; decision advice only, no control output."""

from __future__ import annotations

import json
from pathlib import Path


RESULT = Path(__file__).resolve().parents[2] / "data" / "results" / "v0.4_roll_response_demo.json"


def main() -> None:
    data = json.loads(RESULT.read_text(encoding="utf-8"))
    print(data["demo_name"])
    print(data["environment_source"])
    print(data["vessel_state_source"])
    print(data["parameter_classification"])
    print(f"{data['response_model_status']} / {data['response_validation_status']}")
    for scenario in data["scenarios"]:
        before, after = scenario["before"], scenario["after"]
        print(f"\n[{scenario['scenario_id']}] Hs={scenario['environment']['Hs']:.2f} m "
              f"Tp={scenario['environment']['Tp']:.2f} s wave={scenario['environment']['wave_direction']:.2f} deg")
        print(f"  before SOG/HDG={before['SOG']:.2f}/{before['HDG']:.2f}, "
              f"proximity={before['resonance_proximity_status']}, "
              f"estimated roll={before['estimated_roll_response_deg']:.3f} deg, "
              f"risk={before['roll_response_risk']}")
        print(f"  after  SOG/HDG={after['SOG']:.2f}/{after['HDG']:.2f}, "
              f"proximity={after['resonance_proximity_status']}, "
              f"estimated roll={after['estimated_roll_response_deg']:.3f} deg, "
              f"risk={after['roll_response_risk']}")
        print(f"  {scenario['reduction_label']}: {scenario['estimated_roll_reduction_percent']:.2f}%")
    print("\nNOT SAC / REAL VESSEL CONTROL DISABLED")


if __name__ == "__main__":
    main()
