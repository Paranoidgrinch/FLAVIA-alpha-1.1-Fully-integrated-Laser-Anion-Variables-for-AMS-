import unittest

from backend.voltage_calibration import (
    CALIBRATION_CURVES,
    calibrated_voltage,
    expected_entry_energy_ev,
)


class VoltageCalibrationTests(unittest.TestCase):
    def test_all_measured_calibration_points_are_reproduced_exactly(self):
        for channel, (set_values, measured_values) in CALIBRATION_CURVES.items():
            self.assertEqual(len(set_values), len(measured_values))
            self.assertGreater(len(set_values), 2)
            for set_v, measured_v in zip(set_values, measured_values):
                self.assertAlmostEqual(
                    calibrated_voltage(channel, set_v),
                    measured_v,
                    places=9,
                    msg=f"{channel} at {set_v} V",
                )

    def test_interpolation_is_linear_between_neighbouring_points(self):
        # Sputter: 100 V -> 100.8 V, 200 V -> 200.9 V.
        self.assertAlmostEqual(
            calibrated_voltage("cs/sputter/set_u_v", 150.0),
            150.85,
            places=9,
        )

    def test_entry_energy_uses_all_three_calibrated_voltages(self):
        extraction_set = 20000.0
        sputter_set = 8000.0
        cooler_set = 28000.0
        expected = (
            calibrated_voltage("cs/extraction/set_u_v", extraction_set)
            + calibrated_voltage("cs/sputter/set_u_v", sputter_set)
            - calibrated_voltage("cs/ion_cooler/set_u_v", cooler_set)
        )
        self.assertAlmostEqual(
            expected_entry_energy_ev(extraction_set, sputter_set, cooler_set),
            expected,
            places=9,
        )

    def test_unknown_channel_is_rejected(self):
        with self.assertRaises(KeyError):
            calibrated_voltage("unknown/channel", 123.0)


if __name__ == "__main__":
    unittest.main()
