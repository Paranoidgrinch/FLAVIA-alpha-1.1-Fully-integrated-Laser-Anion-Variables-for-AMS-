import importlib.util
import unittest
from types import SimpleNamespace


@unittest.skipUnless(importlib.util.find_spec("PyQt5"), "PyQt5 required")
class Tracer2DIterationTests(unittest.TestCase):

    def test_grid_starts_at_first_row_and_visits_each_cell_once(self):
        from gui.windows.tracer_2d import Tracer2DDialog

        calls = []
        finishes = []

        obj = SimpleNamespace(
            i=-1,
            j=0,
            v1=[1.0, 2.0],
            v2=[10.0, 20.0],
            param1=SimpleNamespace(channel="p1"),
            param2=SimpleNamespace(channel="p2"),
            settle_s=1.0,
            elapsed_s=0.0,
            point_phase=None,
            status=SimpleNamespace(setText=lambda text: None),
        )

        obj._set_param_value = lambda ch, value: calls.append((ch, float(value)))
        obj._finish = lambda: finishes.append(True)

        for _ in range(4):
            Tracer2DDialog._next_point(obj)

        self.assertEqual(
            calls,
            [
                ("p2", 10.0), ("p1", 1.0),
                ("p2", 10.0), ("p1", 2.0),
                ("p2", 20.0), ("p1", 1.0),
                ("p2", 20.0), ("p1", 2.0),
            ],
        )
        self.assertEqual((obj.i, obj.j), (1, 1))
        self.assertEqual(finishes, [])

        Tracer2DDialog._next_point(obj)

        self.assertEqual(finishes, [True])
        self.assertEqual(len(calls), 8)


if __name__ == "__main__":
    unittest.main()
