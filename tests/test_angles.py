import unittest

from core.navigation import (
    normalize_bearing, relative_environment_angle,
    relative_wave_angle, relative_wind_angle,
)


class AngleTests(unittest.TestCase):
    def test_normalizes_across_zero(self):
        self.assertEqual(normalize_bearing(360), 0)
        self.assertEqual(normalize_bearing(-10), 350)

    def test_relative_angle_crosses_zero(self):
        self.assertEqual(relative_environment_angle(350, 10), 20)
        self.assertEqual(relative_environment_angle(10, 350), 20)

    def test_following_beam_and_opposing(self):
        self.assertEqual(relative_environment_angle(10, 10), 0)
        self.assertEqual(relative_environment_angle(100, 10), 90)
        self.assertEqual(relative_environment_angle(190, 10), 180)

    def test_named_wave_and_wind_helpers(self):
        self.assertEqual(relative_wave_angle(350, 10), 20)
        self.assertEqual(relative_wind_angle(100, 10), 90)
