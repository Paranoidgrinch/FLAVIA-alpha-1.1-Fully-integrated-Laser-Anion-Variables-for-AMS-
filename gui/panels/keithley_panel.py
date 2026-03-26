from __future__ import annotations

import copy
import math
import time
from typing import Optional

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QGroupBox, QGridLayout

from gui.qt_adapter import QtBackendAdapter
from gui.windows.keithley_gauge import KeithleyGaugeWindow
from gui.windows.keithley_plot import KeithleyPlotWindow
from gui.windows.keithley_settings import SettingsDialog

from backend.workers.keithley_6485_worker import KeithleySettings


def _choose_unit_factor(value_A: float) -> tuple[float, str]:
    a = abs(float(value_A))
    if a < 1e-9:
        return 1e12, "pA"
    if a < 1e-6:
        return 1e9, "nA"
    return 1e6, "µA"


def format_current_auto(value_A: float, decimals: int = 3) -> tuple[str, str]:
    factor, unit = _choose_unit_factor(value_A)
    return f"{value_A * factor:.{decimals}f}", unit


class KeithleyPanel(QWidget):
    def __init__(self, backend, adapter: QtBackendAdapter, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.adapter = adapter

        self.settings: KeithleySettings = copy.deepcopy(getattr(backend.keithley, "settings", KeithleySettings()))
        self.gauge_win: Optional[KeithleyGaugeWindow] = None
        self.plot_win: Optional[KeithleyPlotWindow] = None

        self._mean_nA: Optional[float] = None
        self._sigma_nA: Optional[float] = None
        self._n: Optional[int] = None
        self._t_s: Optional[float] = None
        self._plot_t0: Optional[float] = None

        self._display_last_perf: Optional[float] = None
        self._display_current_nA: Optional[float] = None

        gb = QGroupBox("Keithley")
        gb.setStyleSheet("QGroupBox { font-size: 14px; font-weight: 700; } QLabel { font-size: 12px; }")
        outer = QVBoxLayout(gb)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        row1 = QHBoxLayout()
        self.lbl_status = QLabel("Not connected")
        self.lbl_status.setStyleSheet("color:#a00; font-weight:bold;")
        self.btn_settings = QPushButton("Settings…")
        self.btn_connect = QPushButton("Connect")
        self.btn_disconnect = QPushButton("Disconnect")
        self.btn_disconnect.setEnabled(False)
        self.btn_settings.clicked.connect(self.open_settings)
        self.btn_connect.clicked.connect(self.backend.keithley.cmd_connect)
        self.btn_disconnect.clicked.connect(self.backend.keithley.cmd_disconnect)
        row1.addWidget(self.lbl_status)
        row1.addStretch(1)
        row1.addWidget(self.btn_settings)
        row1.addWidget(self.btn_connect)
        row1.addWidget(self.btn_disconnect)
        outer.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Mode:"))
        self.cb_mode = QComboBox()
        self.cb_mode.addItems(["TUNE", "TRACE", "MEASURE"])
        self.cb_mode.setCurrentText((self.settings.mode or "TUNE").upper())
        self.cb_mode.currentTextChanged.connect(self.on_mode_changed)
        row2.addWidget(self.cb_mode)
        self.btn_gauge = QPushButton("Gauge")
        self.btn_plot = QPushButton("Plot")
        self.btn_zero = QPushButton("Zero cycle")
        self.btn_restart = QPushButton("Restart (*RST)")
        self.btn_gauge.clicked.connect(self.open_gauge)
        self.btn_plot.clicked.connect(self.open_plot)
        self.btn_zero.clicked.connect(self.backend.keithley.cmd_zero)
        self.btn_restart.clicked.connect(self.backend.keithley.cmd_restart)
        row2.addWidget(self.btn_gauge)
        row2.addWidget(self.btn_plot)
        row2.addWidget(self.btn_zero)
        row2.addWidget(self.btn_restart)
        outer.addLayout(row2)

        g_read = QGroupBox("Readings")
        grid = QGridLayout(g_read)
        self.lbl_instant = QLabel("Current: ---")
        self.lbl_stats = QLabel("Interval avg: ---")
        grid.addWidget(self.lbl_instant, 0, 0, 1, 2)
        grid.addWidget(self.lbl_stats, 1, 0, 1, 2)
        outer.addWidget(g_read)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(gb)

        self.adapter.channelUpdated.connect(self._on_update)
        for ch in [
            "keithley/connected",
            "keithley/mode",
            "keithley/current_A",
            "keithley/stats/mean_nA",
            "keithley/stats/sigma_nA",
            "keithley/stats/n",
            "keithley/stats/t_s",
        ]:
            self.adapter.register_channel(ch)

    def _tau_for_mode(self) -> float:
        mode = (self.settings.mode or "TUNE").upper()
        if mode == "MEASURE":
            return max(0.01, float(self.settings.measure.display_tau_s))
        if mode == "TRACE":
            return max(0.01, float(self.settings.trace.display_tau_s))
        return max(0.01, float(self.settings.tune.display_tau_s))

    def _update_display_value_nA(self, raw_current_A: float) -> float:
        raw_nA = float(raw_current_A) * 1e9
        now = time.perf_counter()
        if self._display_current_nA is None or self._display_last_perf is None:
            self._display_current_nA = raw_nA
            self._display_last_perf = now
            return raw_nA

        dt = max(1e-3, now - self._display_last_perf)
        tau = self._tau_for_mode()
        alpha = 1.0 - math.exp(-dt / tau)
        self._display_current_nA += alpha * (raw_nA - self._display_current_nA)
        self._display_last_perf = now
        return self._display_current_nA

    def _on_plot_cleared(self) -> None:
        self._plot_t0 = None

    def _on_update(self, name: str, value):
        if name == "keithley/connected":
            ok = bool(value)
            self.lbl_status.setText("Connected" if ok else "Not connected")
            self.lbl_status.setStyleSheet("color:#0a0; font-weight:bold;" if ok else "color:#a00; font-weight:bold;")
            self.btn_connect.setEnabled(not ok)
            self.btn_disconnect.setEnabled(ok)
            return

        if name == "keithley/mode":
            mode = str(value).strip().upper()
            if mode in ("TUNE", "TRACE", "MEASURE"):
                self.settings.mode = mode
                self.cb_mode.blockSignals(True)
                self.cb_mode.setCurrentText(mode)
                self.cb_mode.blockSignals(False)
            return

        if name == "keithley/current_A":
            try:
                current_A = float(value)
            except Exception:
                return
            raw_str, raw_unit = format_current_auto(current_A, decimals=3)
            disp_nA = self._update_display_value_nA(current_A)
            disp_str, disp_unit = format_current_auto(disp_nA * 1e-9, decimals=3)
            self.lbl_instant.setText(f"Current: {disp_str} {disp_unit} (raw {raw_str} {raw_unit})")
            if self.gauge_win is not None:
                self.gauge_win.update_current(disp_nA)
            return

        if name == "keithley/stats/mean_nA":
            try:
                self._mean_nA = float(value)
            except Exception:
                self._mean_nA = None
            return

        if name == "keithley/stats/sigma_nA":
            try:
                self._sigma_nA = float(value)
            except Exception:
                self._sigma_nA = None
            return

        if name == "keithley/stats/n":
            try:
                self._n = int(value)
            except Exception:
                self._n = None
            return

        if name == "keithley/stats/t_s":
            try:
                self._t_s = float(value)
            except Exception:
                self._t_s = None
            if self._t_s is None or self._mean_nA is None or self._sigma_nA is None:
                return

            mean_A = self._mean_nA * 1e-9
            sigma_A = self._sigma_nA * 1e-9
            scale_ref = mean_A if abs(mean_A) >= abs(sigma_A) else sigma_A
            factor, unit = _choose_unit_factor(scale_ref)
            n = self._n if self._n is not None else 0
            if n <= 1 and abs(self._sigma_nA) < 1e-12:
                self.lbl_stats.setText(f"Integrated: {mean_A * factor:.3f} {unit}")
            else:
                self.lbl_stats.setText(f"Interval avg: {mean_A * factor:.3f} ± {sigma_A * factor:.3f} {unit} (n={n})")

            if self.plot_win is not None:
                if self._plot_t0 is None:
                    self._plot_t0 = self._t_s
                self.plot_win.add_point(self._t_s - self._plot_t0, self._mean_nA, self._sigma_nA)

    def on_mode_changed(self, mode: str) -> None:
        self.settings.mode = mode.strip().upper()
        self.backend.apply_keithley_settings(self.settings)

    def open_gauge(self) -> None:
        if self.gauge_win is None:
            self.gauge_win = KeithleyGaugeWindow(self)
        if self._display_current_nA is not None:
            self.gauge_win.update_current(self._display_current_nA)
        self.gauge_win.show()
        self.gauge_win.raise_()
        self.gauge_win.activateWindow()

    def open_plot(self) -> None:
        if self.plot_win is None:
            self.plot_win = KeithleyPlotWindow(self)
            self.plot_win.clearRequested.connect(self._on_plot_cleared)
            self.plot_win.destroyed.connect(lambda *_: setattr(self, "plot_win", None))
        self.plot_win.show()
        self.plot_win.raise_()
        self.plot_win.activateWindow()

    def open_settings(self) -> None:
        dlg = SettingsDialog(copy.deepcopy(self.settings), self)
        if dlg.exec_() == dlg.Accepted:
            self.settings = dlg.get_settings()
            self.cb_mode.blockSignals(True)
            self.cb_mode.setCurrentText(self.settings.mode)
            self.cb_mode.blockSignals(False)
            self.backend.apply_keithley_settings(self.settings)
