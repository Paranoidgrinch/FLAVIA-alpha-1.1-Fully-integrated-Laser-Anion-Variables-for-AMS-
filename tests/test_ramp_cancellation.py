from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.backend import Backend


class DeferredThread:
    instances = []

    def __init__(self, target=None, *args, **kwargs):
        self.target = target
        self.__class__.instances.append(self)

    def start(self):
        pass


class RampCancellationTests(unittest.TestCase):
    def setUp(self):
        DeferredThread.instances.clear()

    def _backend(self):
        backend = Backend.__new__(Backend)
        backend._ramp_cancel = threading.Event()
        backend._ramp_thread = None
        backend._channel_numeric_value = lambda key, fallback=0.0: 0.0
        backend.model = SimpleNamespace(get=lambda key: SimpleNamespace(value=0.0))
        backend.rfq = SimpleNamespace(set_fg=lambda f, v: None)
        backend.set_magnet_current = lambda value: None
        return backend

    def test_new_simple_ramp_really_cancels_previous_thread(self):
        backend = self._backend()
        calls = []
        backend.set_channel = lambda key, value: calls.append((key, value))

        with patch("backend.backend.threading.Thread", DeferredThread), patch("backend.backend.time.sleep"):
            backend._ramp_targets({"test": 10.0}, ramp_s=1.0)
            first_thread = DeferredThread.instances[-1]
            backend._ramp_targets({"test": 20.0}, ramp_s=1.0)
            first_thread.target()

        self.assertEqual(calls, [])

    def test_new_config_ramp_really_cancels_previous_thread(self):
        backend = self._backend()
        calls = []
        backend.set_channel = lambda key, value: calls.append((key, value))
        backend.set_bool = lambda key, value: None
        first = SimpleNamespace(setpoints={"test": 10.0}, states={}, extras={})
        second = SimpleNamespace(setpoints={"test": 20.0}, states={}, extras={})

        with patch("backend.backend.threading.Thread", DeferredThread), patch("backend.backend.time.sleep"):
            backend.apply_config(first, ramp_s=1.0)
            first_thread = DeferredThread.instances[-1]
            backend.apply_config(second, ramp_s=1.0)
            first_thread.target()

        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
