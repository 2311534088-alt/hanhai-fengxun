import unittest

from adapters.ros_zlusv200 import CONTROL_MODE, READ_ONLY, send_control_command
from core.risk import VesselParameters
from core.resonance import ParameterSource, load_engineering_estimate


class SafetyTests(unittest.TestCase):
    def test_real_control_is_disabled(self):
        self.assertEqual(CONTROL_MODE, "disabled")
        self.assertTrue(READ_ONLY)
        with self.assertRaises(RuntimeError):
            send_control_command(speed=1.0)

    def test_unknown_vessel_dynamics_stay_null(self):
        vessel = VesselParameters(model="ZLUSV-200")
        self.assertIsNone(vessel.roll_natural_period_s)
        self.assertIsNone(vessel.metacentric_height_m)
        self.assertIsNone(vessel.roll_damping_ratio)
        self.assertIsNone(vessel.roll_moment_of_inertia_kg_m2)

    def test_engineering_estimate_does_not_modify_known_parameter_model(self):
        vessel = VesselParameters(model="ZLUSV-200")
        estimate, _ = load_engineering_estimate()
        self.assertIsNone(vessel.roll_natural_period_s)
        self.assertEqual(estimate.parameter_source, ParameterSource.ENGINEERING_ESTIMATE)
