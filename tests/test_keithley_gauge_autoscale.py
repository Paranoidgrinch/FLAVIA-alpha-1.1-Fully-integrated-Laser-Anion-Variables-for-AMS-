from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
import unittest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if "backend" not in sys.modules:
    backend_pkg = types.ModuleType("backend")
    backend_pkg.__path__ = [str(_ROOT / "backend")]
    sys.modules["backend"] = backend_pkg
if "backend.workers" not in sys.modules:
    workers_pkg = types.ModuleType("backend.workers")
    workers_pkg.__path__ = [str(_ROOT / "backend" / "workers")]
    sys.modules["backend.workers"] = workers_pkg

from backend.workers.keithley_6485_worker import KeithleySettings


RANGES = [
    (0, 100, "pA"),
    (0, 300, "pA"),
    (0, 1, "nA"),
    (0, 3, "nA"),
    (0, 10, "nA"),
    (0, 30, "nA"),
    (0, 100, "nA"),
    (0, 300, "nA"),
    (0, 1, "µA"),
    (0, 3, "µA"),
    (0, 10, "µA"),
    (0, 30, "µA"),
]


class KeithleyGaugeTauTests(unittest.TestCase):
    def test_tune_default_gauge_tau_is_fast_display_only_default(self):
        self.assertAlmostEqual(KeithleySettings().tune.display_tau_s, 0.08)


@unittest.skipUnless(importlib.util.find_spec("PyQt5"), "PyQt5 is required for gauge autoscale tests")
class KeithleyGaugeAutoscaleTests(unittest.TestCase):
    @staticmethod
    def _helpers():
        from gui.windows.keithley_gauge import (
            AUTO_SCALE_DOWN_HOLD_S,
            _auto_scale_step,
            _best_auto_range_index,
        )

        return AUTO_SCALE_DOWN_HOLD_S, _auto_scale_step, _best_auto_range_index

    def test_best_range_targets_headroom(self):
        _hold, _step, best = self._helpers()
        self.assertEqual(best(0.05, RANGES), 0)
        self.assertEqual(best(50.0, RANGES), 6)
        self.assertEqual(best(95.0, RANGES), 7)

    def test_upscale_is_immediate_near_full_scale(self):
        _hold, step, _best = self._helpers()
        idx, since = step(95.0, RANGES, 6, None, 10.0)
        self.assertEqual(idx, 7)
        self.assertIsNone(since)

    def test_downscale_requires_hold_and_then_jumps_to_useful_range(self):
        hold, step, _best = self._helpers()
        idx, since = step(10.0, RANGES, 6, None, 10.0)
        self.assertEqual(idx, 6)
        self.assertEqual(since, 10.0)

        idx, since = step(10.0, RANGES, 6, since, 10.0 + hold / 2.0)
        self.assertEqual(idx, 6)
        self.assertEqual(since, 10.0)

        idx, since = step(10.0, RANGES, 6, since, 10.0 + hold)
        self.assertEqual(idx, 5)
        self.assertIsNone(since)

    def test_mid_scale_signal_cancels_pending_downscale(self):
        _hold, step, _best = self._helpers()
        idx, since = step(10.0, RANGES, 6, None, 10.0)
        self.assertEqual(idx, 6)
        self.assertIsNotNone(since)

        idx, since = step(25.0, RANGES, 6, since, 10.1)
        self.assertEqual(idx, 6)
        self.assertIsNone(since)


if __name__ == "__main__":
    unittest.main()
