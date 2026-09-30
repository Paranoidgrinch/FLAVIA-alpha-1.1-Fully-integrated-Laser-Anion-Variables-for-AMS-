from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace

from backend.backend import Backend


class ShutdownWorker:
    def __init__(self, name, calls):
        self.name=name
        self.calls=calls
    def shutdown(self):
        self.calls.append(self.name+":shutdown")
    def join(self, timeout=None):
        self.calls.append(self.name+":join")


class BackendShutdownTests(unittest.TestCase):
    def test_shutdown_cancels_ramp_and_stops_nonstandard_workers(self):
        calls=[]
        b=Backend.__new__(Backend)
        b._started=True
        b._ramp_cancel=threading.Event()
        b.sample_exposure=SimpleNamespace(stop=lambda: calls.append("sample"))
        b.stepper=ShutdownWorker("stepper",calls)
        b.magnet=ShutdownWorker("magnet",calls)
        b.gaussmeter=ShutdownWorker("gauss",calls)
        b.logging=SimpleNamespace(shutdown=lambda: calls.append("logging"))
        b.rfq=SimpleNamespace(stop=lambda: calls.append("rfq"))
        b.mqtt=SimpleNamespace(stop=lambda: calls.append("mqtt"))
        b.cup=SimpleNamespace(stop=lambda: calls.append("cup"))
        b.keithley=SimpleNamespace(stop=lambda: calls.append("keithley"))

        Backend.stop(b)

        self.assertTrue(b._ramp_cancel.is_set())
        self.assertIn("stepper:shutdown",calls)
        self.assertIn("magnet:shutdown",calls)
        self.assertIn("gauss:shutdown",calls)
        self.assertIn("stepper:join",calls)
        self.assertIn("magnet:join",calls)
        self.assertIn("gauss:join",calls)


if __name__ == "__main__":
    unittest.main()
