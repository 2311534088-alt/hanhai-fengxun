"""V0.5 robust-decision evidence replay; no actuator output."""

from __future__ import annotations

import json
from pathlib import Path


RESULT = Path(__file__).resolve().parents[2] / "data" / "results" / "v0.5_robust_avoidance_demo.json"


def main() -> None:
    data = json.loads(RESULT.read_text(encoding="utf-8"))
    print(data["demo_name"])
    print(data["environment_source"])
    print(data["vessel_state_source"])
    print(f"{data['parameter_source']} / {data['parameter_status']}")
    print(f"{data['parameter_grid_method']} / {data['parameter_grid_statistical_status']}")
    for label in ("before", "unrestricted_simulation_best", "constrained_recommendation"):
        item = data[label]
        candidate = item if label == "before" else item["candidate"]
        grid = candidate["response_grid"]
        print(f"\n[{label.upper()}] SOG={candidate['SOG']:.2f}, HDG={candidate['HDG']:.2f}")
        print(f"  nominal={grid['nominal_estimated_roll_response_deg']:.3f} deg, "
              f"GRID_Q90={grid['grid_q90_estimated_roll_response_deg']:.3f} deg, "
              f"maximum={grid['maximum_estimated_roll_response_deg']:.3f} deg")
        print(f"  robust={grid['robust_decision_status']}, boundary={candidate['boundary_status']}")
        if label != "before":
            print(f"  advice={item['operator_advice']}")
    print("\n3.0 m/s = SIMULATION_SEARCH_BOUND, NOT OPERATIONAL SPEED")
    print("NOT SAC / REAL VESSEL CONTROL DISABLED")


if __name__ == "__main__":
    main()
