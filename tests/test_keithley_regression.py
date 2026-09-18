from __future__ import annotations

import copy
import importlib.util
import pathlib
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

# Keep the Keithley core tests independent of optional GUI/MQTT dependencies.
# FLAVIA's backend/__init__.py imports the full application backend, so install a
# lightweight package shell before importing backend.model / backend.workers.
_ROOT = pathlib.Path(__file__).resolve().parents[1]
if "backend" not in sys.modules:
    backend_pkg = types.ModuleType("backend")
    backend_pkg.__path__ = [str(_ROOT / "backend")]
    sys.modules["backend"] = backend_pkg
if "backend.workers" not in sys.modules:
    workers_pkg = types.ModuleType("backend.workers")
    workers_pkg.__path__ = [str(_ROOT / "backend" / "workers")]
    sys.modules["backend.workers"] = workers_pkg

from backend.model import DataModel
from backend.workers.keithley_6485_worker import (
    AvgFilterSettings,
    Keithley6485,
    Keithley6485Worker,
    KeithleySettings,
    RangeSettings,
    _BucketState,
    _poll_sleep_s,
    _select_fixed_range_nA,
)


class FakeScpi:
    """Minimal hardware-free SCPI transport for Keithley regression tests."""

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.sent = []
        self.queries = []

    def send(self, cmd: str) -> None:
        self.sent.append(cmd)

    def query(self, cmd: str) -> str:
        self.queries.append(cmd)
        if not self.responses:
            raise AssertionError(f"No fake response queued for {cmd!r}")
        return str(self.responses.pop(0))


class KeithleyReadRegressionTests(unittest.TestCase):
    def test_read_current_queries_read_and_preserves_magnitude_semantics(self):
        scpi = FakeScpi(["-5.0e-11"])
        dev = Keithley6485(scpi, lambda _msg: None)

        value = dev.read_current_A()

        self.assertEqual(scpi.queries, ["READ?"])
        self.assertAlmostEqual(value, 5.0e-11)

    def test_invalid_read_response_returns_zero_and_logs_parse_error(self):
        scpi = FakeScpi(["not-a-number"])
        logs = []
        dev = Keithley6485(scpi, logs.append)

        value = dev.read_current_A()

        self.assertEqual(value, 0.0)
        self.assertTrue(any("Parse error for READ?" in msg for msg in logs))


class KeithleyZeroRegressionTests(unittest.TestCase):
    def test_zero_cycle_acquires_fresh_correction_before_enabling_it(self):
        scpi = FakeScpi()
        dev = Keithley6485(scpi, lambda _msg: None)

        with patch('backend.workers.keithley_6485_worker.time.sleep'):
            dev.zero_cycle()

        self.assertEqual(
            scpi.sent,
            [
                ':SYST:ZCH ON',
                ':SYST:ZCOR OFF',
                'INIT',
                ':SYST:ZCOR:ACQ',
                ':SYST:ZCH OFF',
                ':SYST:ZCOR ON',
            ],
        )

    def test_initialize_basic_acquires_zero_before_enabling_correction(self):
        scpi = FakeScpi()
        dev = Keithley6485(scpi, lambda _msg: None)

        with patch('backend.workers.keithley_6485_worker.time.sleep'):
            dev.initialize_basic()

        self.assertEqual(
            scpi.sent,
            [
                '*RST',
                ':FORM:ELEM READ',
                ":SENS:FUNC 'CURR'",
                ':SENS:CURR:RANG:AUTO ON',
                ':SENS:CURR:NPLC 0.1',
                ':SYST:ZCH ON',
                ':SYST:ZCOR OFF',
                'INIT',
                ':SYST:ZCOR:ACQ',
                ':SYST:ZCH OFF',
                ':SYST:ZCOR ON',
            ],
        )

    def test_worker_zero_resets_software_accumulators(self):
        worker = Keithley6485Worker(DataModel())
        calls = []
        worker.connected = True
        worker.dev = SimpleNamespace(zero_cycle=lambda: calls.append('zero'))
        worker._stats.start = 1.0
        worker._stats.t0 = 1.0
        worker._stats.vals = [10.0, 11.0]
        worker._trace.start = 2.0
        worker._trace.t0 = 2.0
        worker._trace.vals = [20.0, 21.0]

        worker._perform_zero_cycle()

        self.assertEqual(calls, ['zero'])
        self.assertIsNone(worker._stats.start)
        self.assertIsNone(worker._stats.t0)
        self.assertEqual(worker._stats.vals, [])
        self.assertIsNone(worker._trace.start)
        self.assertIsNone(worker._trace.t0)
        self.assertEqual(worker._trace.vals, [])
        self.assertEqual(worker.model.get('keithley/trace/n').value, 0)


class KeithleyRestartRegressionTests(unittest.TestCase):
    def test_restart_performs_exactly_one_hardware_reset(self):
        scpi = FakeScpi()
        dev = Keithley6485(scpi, lambda _msg: None)

        with patch("backend.workers.keithley_6485_worker.time.sleep"):
            dev.restart(KeithleySettings())

        self.assertEqual(scpi.sent.count("*RST"), 1)
        self.assertEqual(scpi.sent[0], "*RST")


class KeithleyRangeRegressionTests(unittest.TestCase):
    def test_requested_fixed_range_snaps_up_to_real_6485_range(self):
        self.assertEqual(_select_fixed_range_nA(0.05), 2.0)
        self.assertEqual(_select_fixed_range_nA(2.0), 2.0)
        self.assertEqual(_select_fixed_range_nA(2.1), 20.0)
        self.assertEqual(_select_fixed_range_nA(100.0), 200.0)
        self.assertEqual(_select_fixed_range_nA(2000.0), 2000.0)

    def test_requested_fixed_range_is_clamped_to_20mA_maximum(self):
        self.assertEqual(_select_fixed_range_nA(1e9), 20_000_000.0)

    def test_fixed_range_command_uses_real_hardware_range(self):
        settings = KeithleySettings()
        settings.mode = "TUNE"
        settings.tune.range = RangeSettings(auto=False, fixed_range_nA=100.0)
        scpi = FakeScpi()
        dev = Keithley6485(scpi, lambda _msg: None)
        dev.apply_mode(settings)
        self.assertEqual(scpi.sent[0], ":SENS:CURR:RANG:AUTO OFF")
        self.assertEqual(scpi.sent[1], ":SENS:CURR:RANG 2.000000e-07")


class KeithleyModeRegressionTests(unittest.TestCase):
    def _commands_for(self, settings: KeithleySettings):
        scpi = FakeScpi()
        dev = Keithley6485(scpi, lambda _msg: None)
        dev.apply_mode(settings)
        return scpi.sent

    def test_default_tune_mode_scpi_contract(self):
        settings = KeithleySettings()
        settings.mode = "TUNE"

        self.assertEqual(
            self._commands_for(settings),
            [
                ":SENS:CURR:RANG:AUTO ON",
                ":SENS:CURR:NPLC 0.05",
                ":SYST:AZER:STAT OFF",
                ":SENS:AVER:COUNT 10",
                ":SENS:AVER:TCON MOV",
                ":SENS:AVER:STAT OFF",
            ],
        )

    def test_default_trace_mode_scpi_contract(self):
        settings = KeithleySettings()
        settings.mode = "TRACE"

        self.assertEqual(
            self._commands_for(settings),
            [
                ":SENS:CURR:RANG:AUTO ON",
                ":SENS:CURR:NPLC 0.3",
                ":SYST:AZER:STAT OFF",
                ":SENS:AVER:COUNT 5",
                ":SENS:AVER:TCON MOV",
                ":SENS:AVER:STAT OFF",
            ],
        )

    def test_default_measure_mode_scpi_contract(self):
        settings = KeithleySettings()
        settings.mode = "MEASURE"

        self.assertEqual(
            self._commands_for(settings),
            [
                ":SENS:CURR:RANG:AUTO ON",
                ":SENS:CURR:NPLC 1.0",
                ":SYST:AZER:STAT ON",
                ":SENS:AVER:COUNT 10",
                ":SENS:AVER:TCON MOV",
                ":SENS:AVER:STAT ON",
            ],
        )

    def test_fixed_range_is_converted_from_nA_to_A(self):
        settings = KeithleySettings()
        settings.mode = "TUNE"
        settings.tune.range = RangeSettings(auto=False, fixed_range_nA=200.0)
        settings.tune.avg_filter = AvgFilterSettings(enabled=False, count=3, tcon="REP")

        commands = self._commands_for(settings)

        self.assertEqual(commands[0], ":SENS:CURR:RANG:AUTO OFF")
        self.assertEqual(commands[1], ":SENS:CURR:RANG 2.000000e-07")
        self.assertIn(":SENS:AVER:COUNT 3", commands)
        self.assertIn(":SENS:AVER:TCON REP", commands)
        self.assertIn(":SENS:AVER:STAT OFF", commands)

    def test_cmd_apply_settings_queues_a_deep_copy(self):
        worker = Keithley6485Worker(DataModel())
        settings = KeithleySettings()
        settings.mode = "TRACE"

        worker.cmd_apply_settings(settings)
        settings.mode = "MEASURE"
        cmd, queued = worker._cmdq.get_nowait()

        self.assertEqual(cmd, "apply")
        self.assertEqual(queued.mode, "TRACE")
        self.assertIsNot(queued, settings)


class KeithleyBucketRegressionTests(unittest.TestCase):
    def setUp(self):
        self.model = DataModel()
        self.worker = Keithley6485Worker(self.model)

    def _value(self, name):
        ch = self.model.get(name)
        return None if ch is None else ch.value

    def test_bucket_emits_population_mean_sigma_n_and_time(self):
        state = _BucketState()
        with patch(
            "backend.workers.keithley_6485_worker.time.perf_counter",
            side_effect=[10.0, 10.4, 11.0],
        ):
            self.worker._bucket_update("keithley/stats", state, 10.0, 1.0)
            self.worker._bucket_update("keithley/stats", state, 20.0, 1.0)
            self.worker._bucket_update("keithley/stats", state, 30.0, 1.0)

        self.assertAlmostEqual(self._value("keithley/stats/mean_nA"), 20.0)
        self.assertAlmostEqual(
            self._value("keithley/stats/sigma_nA"),
            (200.0 / 3.0) ** 0.5,
        )
        self.assertEqual(self._value("keithley/stats/n"), 3)
        self.assertAlmostEqual(self._value("keithley/stats/t_s"), 0.5)

    def test_boundary_sample_is_not_reused_in_next_bucket(self):
        """K2 contract: a boundary sample belongs to exactly one bucket."""
        state = _BucketState()
        with patch(
            "backend.workers.keithley_6485_worker.time.perf_counter",
            side_effect=[0.0, 0.5, 1.0],
        ):
            self.worker._bucket_update("keithley/stats", state, 1.0, 1.0)
            self.worker._bucket_update("keithley/stats", state, 2.0, 1.0)
            self.worker._bucket_update("keithley/stats", state, 3.0, 1.0)

        self.assertEqual(self._value("keithley/stats/n"), 3)
        self.assertEqual(state.start, 1.0)
        self.assertEqual(state.vals, [])

    def test_trace_reset_clears_only_trace_accumulator_and_trace_channels(self):
        self.worker._stats.start = 1.0
        self.worker._stats.t0 = 1.0
        self.worker._stats.vals = [11.0, 12.0]
        self.worker._trace.start = 2.0
        self.worker._trace.t0 = 2.0
        self.worker._trace.vals = [21.0, 22.0]
        self.model.update("keithley/stats/mean_nA", 11.5)
        self.model.update("keithley/trace/mean_nA", 21.5)
        self.model.update("keithley/trace/sigma_nA", 0.5)
        self.model.update("keithley/trace/n", 2)
        self.model.update("keithley/trace/t_s", 0.5)

        self.worker._reset_trace_accumulator()

        self.assertEqual(self.worker._stats.vals, [11.0, 12.0])
        self.assertEqual(self.worker._stats.start, 1.0)
        self.assertEqual(self.worker._trace.vals, [])
        self.assertIsNone(self.worker._trace.start)
        self.assertIsNone(self.worker._trace.t0)
        self.assertEqual(self._value("keithley/stats/mean_nA"), 11.5)
        self.assertEqual(self._value("keithley/trace/mean_nA"), 0.0)
        self.assertEqual(self._value("keithley/trace/sigma_nA"), 0.0)
        self.assertEqual(self._value("keithley/trace/n"), 0)
        self.assertEqual(self._value("keithley/trace/t_s"), 0.0)

    def test_measure_single_sample_publishes_same_value_to_stats_and_trace(self):
        self.worker._publish_single_sample(50.0, 1.25)

        for prefix in ("keithley/stats", "keithley/trace"):
            self.assertEqual(self._value(f"{prefix}/mean_nA"), 50.0)
            self.assertEqual(self._value(f"{prefix}/sigma_nA"), 0.0)
            self.assertEqual(self._value(f"{prefix}/n"), 1)
            self.assertEqual(self._value(f"{prefix}/t_s"), 1.25)

    def test_default_poll_parameter_contract(self):
        self.worker.settings.mode = "TUNE"
        self.assertEqual(self.worker._current_poll_parameters(), ("TUNE", 1.0 / 15.0, 0.5))

        self.worker.settings.mode = "TRACE"
        self.assertEqual(self.worker._current_poll_parameters(), ("TRACE", 0.1, 1.0))

        self.worker.settings.mode = "MEASURE"
        self.assertEqual(self.worker._current_poll_parameters(), ("MEASURE", 2.0, 2.0))

    def test_poll_scheduler_compensates_read_time_in_tune_and_trace(self):
        # poll_hz describes start-to-start cadence in TUNE/TRACE.
        self.assertAlmostEqual(_poll_sleep_s("TUNE", 0.100, 0.030), 0.070, places=12)
        self.assertAlmostEqual(_poll_sleep_s("TRACE", 0.100, 0.040), 0.060, places=12)
        self.assertEqual(_poll_sleep_s("TRACE", 0.100, 0.120), 0.0)

    def test_measure_interval_keeps_existing_post_read_sleep_semantics(self):
        # K3 deliberately does not change MEASURE timing semantics.
        self.assertEqual(_poll_sleep_s("MEASURE", 2.0, 0.4), 2.0)


@unittest.skipUnless(importlib.util.find_spec("PyQt5"), "PyQt5 is required for gauge contract tests")
class GaugeDisplayContractTests(unittest.TestCase):
    def test_display_ema_is_separate_and_uses_configured_mode_tau(self):
        from gui.panels.keithley_panel import KeithleyPanel

        obj = SimpleNamespace()
        obj._tau_for_mode = lambda: KeithleyPanel._tau_for_mode(obj)
        obj.settings = KeithleySettings()
        obj.settings.mode = "TUNE"
        obj.settings.tune.display_tau_s = 0.20
        obj._display_last_perf = None
        obj._display_current_nA = None

        with patch("gui.panels.keithley_panel.time.perf_counter", side_effect=[0.0, 0.2]):
            first = KeithleyPanel._update_display_value_nA(obj, 0.0)
            second = KeithleyPanel._update_display_value_nA(obj, 1.0e-9)

        self.assertEqual(first, 0.0)
        self.assertAlmostEqual(second, 1.0 - __import__("math").exp(-1.0), places=12)


@unittest.skipUnless(importlib.util.find_spec("PyQt5"), "PyQt5 is required for tracer contract tests")
class TracerKeithleyContractTests(unittest.TestCase):
    @staticmethod
    def _backend_with_trace(mean_nA, n):
        model = DataModel()
        model.update("keithley/trace/mean_nA", mean_nA)
        model.update("keithley/trace/n", n)
        return SimpleNamespace(model=model)

    def test_1d_tracer_consumes_trace_mean_only_when_n_is_positive(self):
        from gui.windows.tracer_1d import Tracer1DDialog

        obj = SimpleNamespace()
        obj.backend = self._backend_with_trace(12.5, 0)
        self.assertIsNone(Tracer1DDialog._get_trace_mean_nA(obj))

        obj.backend = self._backend_with_trace(12.5, 3)
        self.assertEqual(Tracer1DDialog._get_trace_mean_nA(obj), 12.5)

    def test_2d_tracer_consumes_trace_mean_only_when_n_is_positive(self):
        from gui.windows.tracer_2d import Tracer2DDialog

        obj = SimpleNamespace()
        obj.backend = self._backend_with_trace(7.25, 0)
        self.assertIsNone(Tracer2DDialog._get_trace_mean(obj))

        obj.backend = self._backend_with_trace(7.25, 4)
        self.assertEqual(Tracer2DDialog._get_trace_mean(obj), 7.25)

    def test_1d_tracer_restores_saved_keithley_settings_once(self):
        from gui.windows.tracer_1d import Tracer1DDialog

        original = KeithleySettings()
        original.mode = "TUNE"
        applied = []
        obj = SimpleNamespace()
        obj._saved_keithley_settings = original
        obj.backend = SimpleNamespace(apply_keithley_settings=lambda s: applied.append(copy.deepcopy(s)))

        Tracer1DDialog._restore_keithley_settings(obj)

        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0].mode, "TUNE")
        self.assertIsNone(obj._saved_keithley_settings)

    def test_2d_tracer_restores_saved_keithley_settings_once(self):
        from gui.windows.tracer_2d import Tracer2DDialog

        original = KeithleySettings()
        original.mode = "TUNE"
        applied = []
        obj = SimpleNamespace()
        obj._saved_keithley_settings = original
        obj.backend = SimpleNamespace(apply_keithley_settings=lambda s: applied.append(copy.deepcopy(s)))

        Tracer2DDialog._restore_keithley_settings(obj)

        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0].mode, "TUNE")
        self.assertIsNone(obj._saved_keithley_settings)


if __name__ == "__main__":
    unittest.main()
