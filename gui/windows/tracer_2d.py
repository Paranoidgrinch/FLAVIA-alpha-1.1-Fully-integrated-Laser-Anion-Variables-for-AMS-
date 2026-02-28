from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, List, Tuple

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QLabel, QComboBox, QDoubleSpinBox,
    QHBoxLayout, QPushButton, QMessageBox
)

from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

from backend.channels import range_for, step_for
from gui.panels.common import pretty_name

from backend.channels import GROUPS, CHANNELS, unit_for


def _default_range_for_unit(unit: str) -> Tuple[float, float]:
    if unit == "V":
        return (-5000.0, 5000.0)
    if unit == "A":
        return (0.0, 5.0)
    if unit == "mA":
        return (0.0, 50.0)
    return (-1000.0, 1000.0)


def _traceable_set_channels() -> List[str]:
    allowed_groups = ["Ion Source", "Ion Optics", "Ion Cooler"]
    s: List[str] = []
    for g in allowed_groups:
        for ch in GROUPS.get(g, []):
            c = CHANNELS.get(ch)
            if c and c.kind == "set" and c.topic_cmd:
                s.append(ch)
    return sorted(set(s))


def _pretty_label(ch: str) -> str:
    return pretty_name(ch)


@dataclass
class ParamInfo:
    channel: str
    unit: str
    vmin: float
    vmax: float


class Tracer2DDialog(QDialog):
    """MQTT-only 2D tracer (nested scan) -> heatmap of Keithley mean_nA."""

    def __init__(self, backend, adapter, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.adapter = adapter

        self.setWindowTitle("Parameter Tracer (2D)")
        self.setModal(False)
        self.resize(1200, 720)

        self.param1: Optional[ParamInfo] = None
        self.param2: Optional[ParamInfo] = None

        self.orig1: Optional[float] = None
        self.orig2: Optional[float] = None
        self.applied: Optional[Tuple[float, float]] = None

        self.v1: List[float] = []
        self.v2: List[float] = []
        self.grid: List[List[float]] = []  # [j][i] (param2 index j, param1 index i)

        self.i = -1
        self.j = -1
        self.dwell_s = 2.0
        self.elapsed = 0.0
        self.running = False

        self.sel_i: Optional[int] = None
        self.sel_j: Optional[int] = None

        self._build_ui()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

        self.adapter.register_channel("keithley/stats/mean_nA")

        if self.param1_combo.count() > 0:
            self.param1_combo.setCurrentIndex(0)
        if self.param2_combo.count() > 1:
            self.param2_combo.setCurrentIndex(1)
        self._update_params()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        form = QGridLayout()
        row = 0

        params = _traceable_set_channels()

        form.addWidget(QLabel("Parameter 1:"), row, 0)
        self.param1_combo = QComboBox()
        for ch in params:
            self.param1_combo.addItem(_pretty_label(ch), userData=ch)
        form.addWidget(self.param1_combo, row, 1)

        form.addWidget(QLabel("Parameter 2:"), row, 2)
        self.param2_combo = QComboBox()
        for ch in params:
            self.param2_combo.addItem(_pretty_label(ch), userData=ch)
        form.addWidget(self.param2_combo, row, 3)

        self.param1_combo.currentIndexChanged.connect(self._update_params)
        self.param2_combo.currentIndexChanged.connect(self._update_params)

        row += 1
        form.addWidget(QLabel("P1 start/end/step:"), row, 0)
        self.p1_start = QDoubleSpinBox(); self.p1_end = QDoubleSpinBox(); self.p1_step = QDoubleSpinBox()
        for sp in (self.p1_start, self.p1_end, self.p1_step):
            sp.setDecimals(3); sp.setSingleStep(0.1)
        self.p1_step.setMinimum(0.0001)
        form.addWidget(self.p1_start, row, 1)
        form.addWidget(self.p1_end, row, 2)
        form.addWidget(self.p1_step, row, 3)

        row += 1
        form.addWidget(QLabel("P2 start/end/step:"), row, 0)
        self.p2_start = QDoubleSpinBox(); self.p2_end = QDoubleSpinBox(); self.p2_step = QDoubleSpinBox()
        for sp in (self.p2_start, self.p2_end, self.p2_step):
            sp.setDecimals(3); sp.setSingleStep(0.1)
        self.p2_step.setMinimum(0.0001)
        form.addWidget(self.p2_start, row, 1)
        form.addWidget(self.p2_end, row, 2)
        form.addWidget(self.p2_step, row, 3)

        row += 1
        form.addWidget(QLabel("Dwell per point (s):"), row, 0)
        self.dwell_spin = QDoubleSpinBox()
        self.dwell_spin.setDecimals(1)
        self.dwell_spin.setRange(1.0, 600.0)
        self.dwell_spin.setSingleStep(0.5)
        self.dwell_spin.setValue(2.0)
        form.addWidget(self.dwell_spin, row, 1)

        self.status = QLabel("Ready.")
        form.addWidget(self.status, row, 2, 1, 2)

        layout.addLayout(form)

        # plot
        self.fig = Figure(figsize=(7, 4), dpi=100)
        self.canvas = FigureCanvas(self.fig)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xlabel("Param1")
        self.ax.set_ylabel("Param2")
        self.im = None
        self.marker = self.ax.plot([], [], marker="o", markersize=10, linestyle="")[0]
        self.canvas.mpl_connect("button_press_event", self._on_click)

        layout.addWidget(self.canvas, 1)

        # buttons
        rowb = QHBoxLayout()
        self.btn_start = QPushButton("Start 2D Trace")
        self.btn_stop = QPushButton("Stop")
        self.btn_apply = QPushButton("Apply & Close")
        self.btn_cancel = QPushButton("Cancel")

        self.btn_stop.setEnabled(False)
        self.btn_apply.setEnabled(False)

        self.btn_start.clicked.connect(self.start_trace)
        self.btn_stop.clicked.connect(self.stop_trace)
        self.btn_apply.clicked.connect(self.apply_and_close)
        self.btn_cancel.clicked.connect(self.close)

        rowb.addWidget(self.btn_start)
        rowb.addWidget(self.btn_stop)
        rowb.addStretch()
        rowb.addWidget(self.btn_apply)
        rowb.addWidget(self.btn_cancel)
        layout.addLayout(rowb)


    def _set_param_value(self, ch: str, value: float) -> None:
        if ch == "magnet_current_set":
            self.backend.set_magnet_current(float(value))
        else:
            self.backend.set_channel(ch, float(value))



    def _get_set_value(self, ch: str) -> float:
        c = self.backend.model.get(ch)
        try:
            return float(c.value) if c and c.value is not None else 0.0
        except Exception:
            return 0.0

    def _get_keithley_mean(self) -> Optional[float]:
        c = self.backend.model.get("keithley/stats/mean_nA")
        if not c or c.value is None:
            return None
        try:
            return float(c.value)
        except Exception:
            return None

    def _gen_steps(self, start: float, end: float, step: float) -> List[float]:
        vals: List[float] = []
        if start < end:
            v = start
            while v < end - 1e-12:
                vals.append(v); v += step
            vals.append(end)
        else:
            v = start
            while v > end + 1e-12:
                vals.append(v); v -= step
            vals.append(end)
        return vals

    def _update_params(self):
        ch1 = self.param1_combo.currentData()
        ch2 = self.param2_combo.currentData()
        if not ch1 or not ch2:
            return

        u1 = (CHANNELS.get(ch1).unit if CHANNELS.get(ch1) else unit_for(ch1))
        u2 = (CHANNELS.get(ch2).unit if CHANNELS.get(ch2) else unit_for(ch2))

        r1 = range_for(ch1) or (0.0, 10000.0)
        r2 = range_for(ch2) or (0.0, 10000.0)

        self.param1 = ParamInfo(ch1, u1, r1[0], r1[1])
        self.param2 = ParamInfo(ch2, u2, r2[0], r2[1])

        cur1 = self._get_set_value(ch1)
        cur2 = self._get_set_value(ch2)

        for sp in (self.p1_start, self.p1_end, self.p1_step):
            sp.blockSignals(True); sp.setRange(r1[0], r1[1]); sp.blockSignals(False)
        for sp in (self.p2_start, self.p2_end, self.p2_step):
            sp.blockSignals(True); sp.setRange(r2[0], r2[1]); sp.blockSignals(False)

        st1 = step_for(ch1) or max((r1[1]-r1[0]) / 10.0, 0.001)
        st2 = step_for(ch2) or max((r2[1]-r2[0]) / 10.0, 0.001)

        self.p1_start.setValue(cur1); self.p1_end.setValue(cur1); self.p1_step.setValue(float(st1))
        self.p2_start.setValue(cur2); self.p2_end.setValue(cur2); self.p2_step.setValue(float(st2))

        self.status.setText("Ready.")

    def start_trace(self):
        if self.running:
            return
        if self.param1 is None or self.param2 is None:
            return

        s1,e1,st1 = self.p1_start.value(), self.p1_end.value(), self.p1_step.value()
        s2,e2,st2 = self.p2_start.value(), self.p2_end.value(), self.p2_step.value()
        if st1 <= 0 or st2 <= 0:
            QMessageBox.warning(self, "2D Tracer", "Step sizes must be > 0.")
            return
        if s1 == e1 or s2 == e2:
            QMessageBox.warning(self, "2D Tracer", "Start and End must differ for both parameters.")
            return

        self.v1 = self._gen_steps(s1,e1,st1)
        self.v2 = self._gen_steps(s2,e2,st2)
        if not self.v1 or not self.v2:
            QMessageBox.warning(self, "2D Tracer", "No steps generated.")
            return

        self.orig1 = self._get_set_value(self.param1.channel)
        self.orig2 = self._get_set_value(self.param2.channel)
        self.applied = None

        self.grid = [[float("nan") for _ in self.v1] for __ in self.v2]
        self.i = -1; self.j = -1
        self.sel_i = None; self.sel_j = None

        self.dwell_s = float(self.dwell_spin.value())
        self.elapsed = 0.0
        self.running = True

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_apply.setEnabled(False)

        self.timer.start(1000)
        self._next_point()

    def _next_point(self):
        # advance indices
        self.i += 1
        if self.i >= len(self.v1):
            self.i = 0
            self.j += 1
        if self.j >= len(self.v2):
            self._finish()
            return

        # set both params
        try:
            self._set_param_value(self.param2.channel, float(self.v2[self.j]))
            self._set_param_value(self.param1.channel, float(self.v1[self.i]))
        except Exception:
            pass

        self.elapsed = 0.0
        self.status.setText(f"Point ({self.j+1}/{len(self.v2)}, {self.i+1}/{len(self.v1)}): waiting...")

    def _tick(self):
        if not self.running:
            return
        self.elapsed += 1.0
        rem = max(0.0, self.dwell_s - self.elapsed)
        self.status.setText(f"Point ({self.j+1}/{len(self.v2)}, {self.i+1}/{len(self.v1)}): waiting... ({rem:.0f}s)")
        if self.elapsed < self.dwell_s:
            return

        y = self._get_keithley_mean()
        if y is None:
            y = float("nan")
        self.grid[self.j][self.i] = float(y)
        self._draw_heatmap()

        self._next_point()

    def _finish(self):
        self.running = False
        self.timer.stop()
        self.btn_stop.setEnabled(False)
        self.btn_start.setEnabled(True)

        # select maximum (ignoring NaN)
        best = None
        best_i = best_j = None
        for j in range(len(self.v2)):
            for i in range(len(self.v1)):
                val = self.grid[j][i]
                if val != val:
                    continue
                if best is None or val > best:
                    best = val
                    best_i, best_j = i, j

        if best_i is not None and best_j is not None:
            self._select(best_i, best_j)
            self.btn_apply.setEnabled(True)
            self.status.setText(f"Finished. Max at P1={self.v1[best_i]:.3f}, P2={self.v2[best_j]:.3f}, Keithley={best:.2f} nA.")
        else:
            self.status.setText("Finished (no valid data).")

    def stop_trace(self):
        if not self.running:
            return
        self.running = False
        self.timer.stop()
        self.btn_stop.setEnabled(False)
        self.btn_start.setEnabled(True)
        self.status.setText("Stopped.")

    def _draw_heatmap(self):
        self.ax.clear()
        self.ax.set_xlabel(self.param1.channel)
        self.ax.set_ylabel(self.param2.channel)

        import numpy as np
        Z = np.array(self.grid, dtype=float)
        self.im = self.ax.imshow(
            Z,
            origin="lower",
            aspect="auto",
            interpolation="nearest",
        )
        self.fig.colorbar(self.im, ax=self.ax, label="Keithley mean [nA]")

        if self.sel_i is not None and self.sel_j is not None:
            self.ax.plot(self.sel_i, self.sel_j, marker="o", markersize=10, color="red", linestyle="")

        self.canvas.draw_idle()

    def _on_click(self, event):
        if event.inaxes != self.ax or self.im is None:
            return
        if event.xdata is None or event.ydata is None:
            return
        i = int(round(event.xdata))
        j = int(round(event.ydata))
        if 0 <= i < len(self.v1) and 0 <= j < len(self.v2):
            self._select(i, j)
            self.btn_apply.setEnabled(True)

    def _select(self, i: int, j: int):
        self.sel_i, self.sel_j = i, j
        self._draw_heatmap()
        val = self.grid[j][i]
        self.status.setText(
            f"Selected: P1={self.v1[i]:.3f}, P2={self.v2[j]:.3f}, Keithley={val:.2f} nA."
        )

    def apply_and_close(self):
        if self.param1 is None or self.param2 is None or self.sel_i is None or self.sel_j is None:
            self.close()
            return
        v1 = float(self.v1[self.sel_i])
        v2 = float(self.v2[self.sel_j])
        try:
            self._set_param_value(self.param2.channel, v2)
            self._set_param_value(self.param1.channel, v1)
            self.applied = (v1, v2)
        except Exception:
            pass
        self.close()

    def closeEvent(self, event):
        if self.running:
            self.running = False
            self.timer.stop()

        # restore if not applied
        if self.applied is None and self.param1 and self.param2 and self.orig1 is not None and self.orig2 is not None:
            try:
                self._set_param_value(self.param1.channel, float(self.orig1))
                self._set_param_value(self.param2.channel, float(self.orig2))
            except Exception:
                pass

        super().closeEvent(event)