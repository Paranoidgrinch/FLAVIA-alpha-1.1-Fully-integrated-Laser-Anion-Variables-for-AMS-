# backend/services/rfq_service.py
from __future__ import annotations

from PyQt5 import QtCore

from backend.workers.rfq_worker import RFQWorker


class RFQService(QtCore.QObject):
    """
    Backend-managed RFQ worker (Mathieu+LC).
    Owns a QThread + RFQWorker and re-emits signals for the GUI.
    """

    # ---------- Re-emitted worker signals ----------
    fgStatus = QtCore.pyqtSignal(float, float)          # freq, ampl
    fgError = QtCore.pyqtSignal(str)

    piStatus = QtCore.pyqtSignal(bool, str)
    lcReadResult = QtCore.pyqtSignal(float, str, float, str)  # C, C_err, L, L_err
    lcSendResult = QtCore.pyqtSignal(float, float, str, str)  # C, L, errC, errL
    lcError = QtCore.pyqtSignal(str)

    scopeStatus = QtCore.pyqtSignal(bool)
    scopeMeasurement = QtCore.pyqtSignal(float, float, object, object)  # vpp2, vpp3, wave2, wave3
    scopeError = QtCore.pyqtSignal(str)

    sweepProgress = QtCore.pyqtSignal(int, int, float)
    sweepLog = QtCore.pyqtSignal(str)
    sweepResult = QtCore.pyqtSignal(object, object, object, object, object, float, float, str)
    sweepError = QtCore.pyqtSignal(str)

    # ---------- Commands (GUI -> worker) ----------
    _requestFgStatus = QtCore.pyqtSignal()
    _setFg = QtCore.pyqtSignal(float, float)

    _connectPi = QtCore.pyqtSignal()
    _setLc = QtCore.pyqtSignal(float, float)
    _readLc = QtCore.pyqtSignal()

    _testScope = QtCore.pyqtSignal()
    _measureScope = QtCore.pyqtSignal()

    _runSweepL = QtCore.pyqtSignal(float, float, float, float, bool)
    _cancelSweep = QtCore.pyqtSignal()
    _shutdown = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread = QtCore.QThread()
        self.worker = RFQWorker()
        self.worker.moveToThread(self.thread)

        # GUI -> worker
        self._requestFgStatus.connect(self.worker.request_fg_status)
        self._setFg.connect(self.worker.set_fg)

        self._connectPi.connect(self.worker.connect_pi)
        self._setLc.connect(self.worker.set_lc)
        self._readLc.connect(self.worker.read_lc)

        self._testScope.connect(self.worker.test_scope)
        self._measureScope.connect(self.worker.measure_scope)

        self._runSweepL.connect(self.worker.run_sweep_L)
        self._cancelSweep.connect(self.worker.cancel_sweep)

        self._shutdown.connect(self.worker.shutdown)

        # worker -> re-emit
        self.worker.fgStatus.connect(self.fgStatus)
        self.worker.fgError.connect(self.fgError)

        self.worker.piStatus.connect(self.piStatus)
        self.worker.lcReadResult.connect(self.lcReadResult)
        self.worker.lcSendResult.connect(self.lcSendResult)
        self.worker.lcError.connect(self.lcError)

        self.worker.scopeStatus.connect(self.scopeStatus)
        self.worker.scopeMeasurement.connect(self.scopeMeasurement)
        self.worker.scopeError.connect(self.scopeError)

        self.worker.sweepProgress.connect(self.sweepProgress)
        self.worker.sweepLog.connect(self.sweepLog)
        self.worker.sweepResult.connect(self.sweepResult)
        self.worker.sweepError.connect(self.sweepError)

        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self.thread.start()

        # NEW: periodic FG polling (every 60s)
        if not hasattr(self, "_poll_timer"):
            self._poll_timer = QtCore.QTimer()
            self._poll_timer.setInterval(60000)
            self._poll_timer.timeout.connect(self.request_fg_status)
        self._poll_timer.start()

    def stop(self) -> None:
        # safe to call multiple times
        try:
            self._cancelSweep.emit()
        except Exception:
            pass

        try:
            if hasattr(self, "_poll_timer"):
                self._poll_timer.stop()
        except Exception:
            pass

        try:
            self._shutdown.emit()
        except Exception:
            pass
        try:
            self.thread.quit()
            self.thread.wait(2000)
        except Exception:
            pass
        self._started = False

    # ---------- Public API (GUI thread) ----------
    def request_fg_status(self) -> None:
        self._requestFgStatus.emit()

    def set_fg(self, freq_hz: float, vpp: float) -> None:
        self._setFg.emit(float(freq_hz), float(vpp))

    def connect_pi(self) -> None:
        self._connectPi.emit()

    def set_lc(self, C_pF: float, L_uH: float) -> None:
        self._setLc.emit(float(C_pF), float(L_uH))

    def read_lc(self) -> None:
        self._readLc.emit()

    def test_scope(self) -> None:
        self._testScope.emit()

    def measure_scope(self) -> None:
        self._measureScope.emit()

    def run_sweep_L(self, center_L: float, span: float, step: float, dwell_ms: float, measure_scope: bool) -> None:
        self._runSweepL.emit(float(center_L), float(span), float(step), float(dwell_ms), bool(measure_scope))

    def cancel_sweep(self) -> None:
        self._cancelSweep.emit()