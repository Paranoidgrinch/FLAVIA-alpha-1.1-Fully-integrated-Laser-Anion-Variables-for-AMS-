import importlib.util
import unittest
from types import SimpleNamespace


@unittest.skipUnless(importlib.util.find_spec("PyQt5"), "PyQt5 required")
class TracerResetHandshakeTests(unittest.TestCase):
    def test_1d_waits_for_reset_ack_before_measurement(self):
        from gui.windows.tracer_1d import Tracer1DDialog
        backend = SimpleNamespace(
            reset_keithley_trace=lambda: 5,
            keithley_trace_reset_acknowledged=lambda request_id: request_id == 5,
        )
        obj = SimpleNamespace(
            current_step_index=-1,
            step_values=[1.0],
            param=SimpleNamespace(channel="p"),
            settle_time=0.0,
            step_elapsed=0.0,
            step_phase=None,
            backend=backend,
            status_label=SimpleNamespace(setText=lambda _text: None),
            _set_param_value=lambda _ch, _value: None,
            _finish_trace=lambda: None,
        )
        Tracer1DDialog._next_step(obj)
        self.assertEqual(obj.step_phase, "reset_wait")
        self.assertEqual(obj._trace_reset_request_id, 5)
        obj.tracing_active = True
        obj._tick_dt_s = 0.1
        Tracer1DDialog._on_timer_tick(obj)
        self.assertEqual(obj.step_phase, "measure")
        self.assertEqual(obj.step_elapsed, 0.0)

    def test_2d_waits_for_reset_ack_before_measurement(self):
        from gui.windows.tracer_2d import Tracer2DDialog
        backend = SimpleNamespace(
            reset_keithley_trace=lambda: 9,
            keithley_trace_reset_acknowledged=lambda request_id: request_id == 9,
        )
        obj = SimpleNamespace(
            i=-1,
            j=0,
            v1=[1.0],
            v2=[10.0],
            param1=SimpleNamespace(channel="p1"),
            param2=SimpleNamespace(channel="p2"),
            settle_s=0.0,
            elapsed_s=0.0,
            point_phase=None,
            backend=backend,
            status=SimpleNamespace(setText=lambda _text: None),
            _set_param_value=lambda _ch, _value: None,
            _finish=lambda: None,
        )
        Tracer2DDialog._next_point(obj)
        self.assertEqual(obj.point_phase, "reset_wait")
        self.assertEqual(obj._trace_reset_request_id, 9)
        obj.running = True
        obj._tick_dt_s = 0.1
        Tracer2DDialog._tick(obj)
        self.assertEqual(obj.point_phase, "measure")
        self.assertEqual(obj.elapsed_s, 0.0)


if __name__ == "__main__":
    unittest.main()
