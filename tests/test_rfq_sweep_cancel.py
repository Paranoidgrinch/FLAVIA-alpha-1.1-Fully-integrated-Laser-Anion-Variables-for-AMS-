from __future__ import annotations

import unittest
from types import SimpleNamespace

from backend.services.rfq_service import RFQService
from backend.workers.rfq_worker import RFQWorker


class RfqSweepCancelTests(unittest.TestCase):
    def test_worker_cancel_uses_thread_safe_event(self):
        worker = RFQWorker()
        worker.cancel_sweep()
        self.assertTrue(worker._sweep_cancel_event.is_set())

    def test_cancel_event_can_interrupt_dwell_immediately(self):
        worker = RFQWorker()
        worker._sweep_cancel_event.set()
        self.assertTrue(worker._sweep_cancel_event.wait(10.0))

    def test_service_cancel_reaches_worker_directly(self):
        calls=[]
        service=SimpleNamespace(
            worker=SimpleNamespace(cancel_sweep=lambda: calls.append("direct")),
            _cancelSweep=SimpleNamespace(emit=lambda: calls.append("queued")),
        )
        RFQService.cancel_sweep(service)
        self.assertEqual(calls,["direct"])


if __name__ == "__main__":
    unittest.main()
