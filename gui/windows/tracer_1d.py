from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple

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


def _pretty_label(ch: str) -> str:
    if ch == "magnet_current_set":
        return "Magnet current"
    return pretty_name(ch)


def _traceable_set_channels() -> list[str]:
    allowed_groups = ["Ion Source", "Ion Optics", "Ion Cooler"]
    s: list[str] = []
    for g in allowed_groups:
        for ch in GROUPS.get(g, []):
            c = CHANNELS.get(ch)
            if not c:
                continue
            # MQTT setpoints
            if c.kind == "set" and c.topic_cmd:
                s.append(ch)

    # ✅ add magnet setpoint (non-MQTT, but traceable)
    if "magnet_current_set" in CHANNELS:
        s.append("magnet_current_set")

    return sorted(set(s))


@dataclass
class ParamInfo:
    channel: str
    unit: str
    vmin: float
    vmax: float


class Tracer1DDialog(QDialog):
    """MQTT-only 1D tracer: traces one setpoint channel vs Keithley mean_nA."""

    def __init__(self, backend, adapter, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.adapter = adapter

        self.setWindowTitle("Parameter Tracer (1D)")
        self.setModal(False)
        self.resize(860, 520)

        self.param: Optional[ParamInfo] = None
        self.original_value: Optional[float] = None
        self.applied_value: Optional[float] = None

        self.step_values: List[float] = []
        self.current_step_index: int = -1
        self.step_elapsed: float = 0.0
        self.dwell_time: float = 2.0
        self.tracing_active: bool = False

        self.x_values: List[float] = []
        self.y_values: List[float] = []
        self.selected_index: Optional[int] = None

        self._build_ui()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_timer_tick)

        # subscribe keithley mean channel (for up-to-date values)
        self.adapter.register_channel("keithley/stats/mean_nA")

        # initial param
        if self.param_combo.count() > 0:
            self.param_combo.setCurrentIndex(0)
            self._update_param_fields()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        form = QGridLayout()
        row = 0

        form.addWidget(QLabel("Parameter (set channel):"), row, 0)
        self.param_combo = QComboBox()
        self._param_list = _traceable_set_channels()
        for ch in self._param_list:
            self.param_combo.addItem(_pretty_label(ch), userData=ch)
        self.param_combo.currentIndexChanged.connect(self._update_param_fields)
        form.addWidget(self.param_combo, row, 1, 1, 3)

        row += 1
        form.addWidget(QLabel("Start:"), row, 0)
        self.start_spin = QDoubleSpinBox()
        self.start_spin.setDecimals(3)
        self.start_spin.setSingleStep(0.1)
        form.addWidget(self.start_spin, row, 1)

        form.addWidget(QLabel("End:"), row, 2)
        self.end_spin = QDoubleSpinBox()
        self.end_spin.setDecimals(3)
        self.end_spin.setSingleStep(0.1)
        form.addWidget(self.end_spin, row, 3)

        row += 1
        form.addWidget(QLabel("Step size:"), row, 0)
        self.step_spin = QDoubleSpinBox()
        self.step_spin.setDecimals(3)
        self.step_spin.setSingleStep(0.1)
        self.step_spin.setMinimum(0.0001)
        form.addWidget(self.step_spin, row, 1)

        form.addWidget(QLabel("Dwell per step (s):"), row, 2)
        self.dwell_spin = QDoubleSpinBox()
        self.dwell_spin.setDecimals(1)
        self.dwell_spin.setSingleStep(0.5)
        self.dwell_spin.setRange(1.0, 600.0)
        self.dwell_spin.setValue(2.0)
        form.addWidget(self.dwell_spin, row, 3)

        row += 1
        self.status_label = QLabel("Ready.")
        form.addWidget(self.status_label, row, 0, 1, 4)

        layout.addLayout(form)

        # plot
        self.figure = Figure(figsize=(6.5, 3.2), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_xlabel("Setpoint")
        self.ax.set_ylabel("Keithley mean [nA]")

        (self.trace_line,) = self.ax.plot([], [], marker="o")
        self.vline = self.ax.axvline(0.0, color="red", visible=False)
        self.canvas.mpl_connect("button_press_event", self._on_plot_click)

        layout.addWidget(self.canvas, stretch=1)

        # buttons
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("Start Trace")
        self.start_btn.clicked.connect(self.start_trace)
        btn_row.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_trace)
        btn_row.addWidget(self.stop_btn)

        btn_row.addStretch()

        self.apply_btn = QPushButton("Apply & Close")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self.apply_and_close)
        btn_row.addWidget(self.apply_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.close)
        btn_row.addWidget(self.cancel_btn)

        layout.addLayout(btn_row)

    def _get_current_set_value(self, ch: str) -> float:
        c = self.backend.model.get(ch)
        try:
            return float(c.value) if c and c.value is not None else 0.0
        except Exception:
            return 0.0
        

    def _set_param_value(self, ch: str, value: float) -> None:
        if ch == "magnet_current_set":
            # magnet has a dedicated backend API
            self.backend.set_magnet_current(float(value))
        else:
            self.backend.set_channel(ch, float(value))

    

    def _get_keithley_mean_nA(self) -> Optional[float]:
        c = self.backend.model.get("keithley/stats/mean_nA")
        if not c or c.value is None:
            return None
        try:
            return float(c.value)
        except Exception:
            return None

    def _update_param_fields(self):
        ch = self.param_combo.currentData()
        if not ch:
            return
        cdef = CHANNELS.get(ch)
        unit = cdef.unit if cdef else unit_for(ch)

        r = range_for(ch)
        if r is None:
            # fallback: fixed polarity
            r = (0.0, 10000.0)
        vmin, vmax = r

        self.param = ParamInfo(channel=ch, unit=unit, vmin=vmin, vmax=vmax)

        current = self._get_current_set_value(ch)

        for spin in (self.start_spin, self.end_spin, self.step_spin):
            spin.blockSignals(True)
            spin.setRange(vmin, vmax)
            spin.blockSignals(False)

        self.start_spin.setValue(current)
        self.end_spin.setValue(current)

        st = step_for(ch)
        if st is None:
            span = max(1e-9, vmax - vmin)
            st = max(span / 20.0, 0.001)
        self.step_spin.setValue(float(st))

        self.status_label.setText(f"Ready for {ch} (current={current:.3f} {unit}).")

    def start_trace(self):
        if self.tracing_active:
            return
        if self.param is None:
            return

        start = self.start_spin.value()
        end = self.end_spin.value()
        step = self.step_spin.value()
        dwell = self.dwell_spin.value()

        if step <= 0:
            QMessageBox.warning(self, "Tracer", "Step size must be > 0.")
            return
        if start == end:
            QMessageBox.warning(self, "Tracer", "Start and End must differ.")
            return

        # generate step list
        values: List[float] = []
        if start < end:
            v = start
            while v < end - 1e-12:
                values.append(v)
                v += step
            values.append(end)
        else:
            v = start
            while v > end + 1e-12:
                values.append(v)
                v -= step
            values.append(end)

        if not values:
            QMessageBox.warning(self, "Tracer", "No steps generated.")
            return

        # remember original setpoint
        self.original_value = float(self._get_current_set_value(self.param.channel))

        self.step_values = values
        self.dwell_time = float(dwell)
        self.current_step_index = -1
        self.step_elapsed = 0.0

        self.x_values.clear()
        self.y_values.clear()
        self.selected_index = None
        self.applied_value = None
        self._update_plot()

        self.tracing_active = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.apply_btn.setEnabled(False)

        self.status_label.setText(f"Tracing {self.param.channel} over {len(values)} steps (dwell {self.dwell_time:.1f}s).")

        self.timer.start(1000)
        self._next_step()

    def _next_step(self):
        self.current_step_index += 1
        if self.current_step_index >= len(self.step_values):
            self._finish_trace()
            return

        value = float(self.step_values[self.current_step_index])
        try:
            self._set_param_value(self.param.channel, value)
        except Exception as e:
            self.status_label.setText(f"Set failed: {e}")

        self.step_elapsed = 0.0
        self.status_label.setText(
            f"Step {self.current_step_index+1}/{len(self.step_values)}: set={value:.3f}, waiting..."
        )

    def _on_timer_tick(self):
        if not self.tracing_active:
            return

        self.step_elapsed += 1.0
        remaining = max(0.0, self.dwell_time - self.step_elapsed)
        self.status_label.setText(
            f"Step {self.current_step_index+1}/{len(self.step_values)}: waiting... ({remaining:.0f}s left)"
        )
        if self.step_elapsed < self.dwell_time:
            return

        avg = self._get_keithley_mean_nA()
        if avg is None:
            avg = float("nan")

        setpoint = float(self.step_values[self.current_step_index])
        self.x_values.append(setpoint)
        self.y_values.append(avg)
        self._update_plot()

        self._next_step()

    def _finish_trace(self):
        self.tracing_active = False
        self.timer.stop()
        self.stop_btn.setEnabled(False)
        self.start_btn.setEnabled(True)

        if self.x_values:
            max_idx = max(range(len(self.x_values)), key=lambda i: self.y_values[i])
            self._select_index(max_idx)
            self.apply_btn.setEnabled(True)
            self.status_label.setText(
                f"Trace finished. Max at {self.x_values[max_idx]:.3f}, Keithley={self.y_values[max_idx]:.2f} nA."
            )
        else:
            self.status_label.setText("Trace finished (no data).")

    def stop_trace(self):
        if not self.tracing_active:
            return
        self.tracing_active = False
        self.timer.stop()
        self.stop_btn.setEnabled(False)
        self.start_btn.setEnabled(True)

        if self.x_values:
            max_idx = max(range(len(self.x_values)), key=lambda i: self.y_values[i])
            self._select_index(max_idx)
            self.apply_btn.setEnabled(True)
            self.status_label.setText(
                f"Trace stopped. Max at {self.x_values[max_idx]:.3f}, Keithley={self.y_values[max_idx]:.2f} nA."
            )
        else:
            self.status_label.setText("Trace stopped (no data yet).")

    def _update_plot(self):
        self.trace_line.set_data(self.x_values, self.y_values)

        if self.selected_index is not None and self.x_values:
            xsel = self.x_values[self.selected_index]
            self.vline.set_xdata([xsel, xsel])
            self.vline.set_visible(True)
        else:
            self.vline.set_visible(False)

        if self.x_values:
            xmin, xmax = min(self.x_values), max(self.x_values)
            if xmin == xmax:
                xmin -= 0.5
                xmax += 0.5
            pad = 0.05 * (xmax - xmin)
            self.ax.set_xlim(xmin - pad, xmax + pad)

            ymin, ymax = min(self.y_values), max(self.y_values)
            if ymin == ymax:
                ymin -= 0.5
                ymax += 0.5
            pad_y = 0.1 * (ymax - ymin)
            self.ax.set_ylim(ymin - pad_y, ymax + pad_y)

        self.canvas.draw_idle()

    def _on_plot_click(self, event):
        if event.inaxes != self.ax:
            return
        if not self.x_values or event.xdata is None:
            return
        x_click = float(event.xdata)
        idx = min(range(len(self.x_values)), key=lambda i: abs(self.x_values[i] - x_click))
        self._select_index(idx)

    def _select_index(self, idx: int):
        if not (0 <= idx < len(self.x_values)):
            return
        self.selected_index = idx
        self._update_plot()
        self.apply_btn.setEnabled(True)
        self.status_label.setText(
            f"Selected setpoint={self.x_values[idx]:.3f}, Keithley={self.y_values[idx]:.2f} nA."
        )

    def apply_and_close(self):
        if self.param is None or self.selected_index is None:
            self.close()
            return
        value = float(self.x_values[self.selected_index])
        try:
            self._set_param_value(self.param.channel, value)
            self.applied_value = value
        except Exception:
            pass
        self.close()

    def closeEvent(self, event):
        if self.tracing_active:
            self.tracing_active = False
            self.timer.stop()

        if self.applied_value is None and self.original_value is not None and self.param is not None:
            try:
                self._set_param_value(self.param.channel, float(self.original_value))
            except Exception:
                pass

        super().closeEvent(event)