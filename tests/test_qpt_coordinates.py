import unittest

from backend.qpt_coordinates import (
    focus_astigmatism_to_qpt,
    qpt_to_focus_astigmatism,
)


class QptCoordinateTests(unittest.TestCase):
    def assertTripletAlmostEqual(self, actual, expected):
        for got, want in zip(actual, expected):
            self.assertAlmostEqual(got, want, places=9)

    def test_focus_endpoints_ignore_astigmatism(self):
        for astigmatism in (0.0, 25.0, 50.0, 75.0, 100.0):
            self.assertTripletAlmostEqual(
                focus_astigmatism_to_qpt(0.0, astigmatism),
                (0.0, 0.0, 0.0),
            )
            self.assertTripletAlmostEqual(
                focus_astigmatism_to_qpt(100.0, astigmatism),
                (6000.0, 6000.0, 6000.0),
            )

    def test_neutral_astigmatism_sets_all_psus_equal(self):
        self.assertTripletAlmostEqual(
            focus_astigmatism_to_qpt(50.0, 50.0),
            (3000.0, 3000.0, 3000.0),
        )

    def test_astigmatism_extremes_at_half_focus(self):
        self.assertTripletAlmostEqual(
            focus_astigmatism_to_qpt(50.0, 100.0),
            (6000.0, 3000.0, 0.0),
        )
        self.assertTripletAlmostEqual(
            focus_astigmatism_to_qpt(50.0, 0.0),
            (0.0, 3000.0, 6000.0),
        )

    def test_voltage_headroom_limits_astigmatism(self):
        self.assertTripletAlmostEqual(
            focus_astigmatism_to_qpt(75.0, 100.0),
            (6000.0, 4500.0, 3000.0),
        )

    def test_round_trip_inside_focus_range(self):
        for focus in (10.0, 25.0, 50.0, 75.0, 90.0):
            for astigmatism in (0.0, 20.0, 50.0, 80.0, 100.0):
                qpt = focus_astigmatism_to_qpt(focus, astigmatism)
                recovered = qpt_to_focus_astigmatism(*qpt)
                self.assertAlmostEqual(recovered[0], focus, places=9)
                self.assertAlmostEqual(recovered[1], astigmatism, places=9)


if __name__ == "__main__":
    unittest.main()
