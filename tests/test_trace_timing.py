import unittest

from backend.trace_timing import build_trace_point_timing


class TracePointTimingTests(unittest.TestCase):

    def test_default_two_second_dwell_uses_last_second_for_measurement(self):
        timing = build_trace_point_timing(2.0, 1.0, 10.0)
        self.assertEqual(timing.dwell_s, 2.0)
        self.assertEqual(timing.settle_s, 1.0)
        self.assertEqual(timing.measure_s, 1.0)
        self.assertEqual(timing.timeout_s, 1.5)

    def test_minimum_dwell_has_no_settling(self):
        timing = build_trace_point_timing(1.0, 1.0, 10.0)
        self.assertEqual(timing.settle_s, 0.0)
        self.assertEqual(timing.measure_s, 1.0)

    def test_dwell_shorter_than_bucket_is_rejected(self):
        with self.assertRaises(ValueError):
            build_trace_point_timing(0.5, 1.0, 10.0)

    def test_invalid_bucket_or_poll_rate_is_rejected(self):
        with self.assertRaises(ValueError):
            build_trace_point_timing(2.0, 0.0, 10.0)
        with self.assertRaises(ValueError):
            build_trace_point_timing(2.0, 1.0, 0.0)


if __name__ == '__main__':
    unittest.main()
