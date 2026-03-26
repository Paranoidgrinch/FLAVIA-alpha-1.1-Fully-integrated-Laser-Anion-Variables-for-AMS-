from __future__ import annotations

import copy
import csv
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Tuple

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QGridLayout, QLabel, QComboBox, QDoubleSpinBox, QHBoxLayout, QPushButton, QMessageBox, QFileDialog

from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

from backend.channels import range_for, step_for, GROUPS, CHANNELS, unit_for
from gui.panels.common import pretty_name


def _pretty_label(ch: str) -> str:
    if ch == "magnet_current_set":
        return "Magnet current"
    return pretty_name(ch)


def _traceable_set_channels() -> List[str]:
    allowed_groups = ["Ion Source", "Ion Optics", "Ion Cooler"]
    out: List[str] = []
    for g in allowed_groups:
        for ch in GROUPS.get(g, []):
            c = CHANNELS.get(ch)
            if not c:
                continue
            if c.kind == "set" and c.topic_cmd:
                out.append(ch)
    if "magnet_current_set" in CHANNELS:
        out.append("magnet_current_set")
    return sorted(set(out))


@dataclass
class ParamInfo:
    channel: str
    unit: str
    vmin: float
    vmax: float


class Tracer2DDialog(QDialog):
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
        self._saved_keithley_settings = None

        self.v1: List[float] = []
        self.v2: List[float] = []
        self.grid: List[List[float]] = []
        self.i = -1
        self.j = -1
        self.dwell_s = 2.0
        self.elapsed_s = 0.0
        self.running = False
        self.sel_i: Optional[int] = None
        self.sel_j: Optional[int] = None
        self._last_dir = ""
        self._tick_dt_s = 0.2

        self._build_ui()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.adapter.register_channel("keithley/trace/mean_nA")
        self.adapter.register_channel("keithley/trace/n")
        if self.param1_combo.count() > 0:
            self.param1_combo.setCurrentIndex(0)
            self.param2_combo.setCurrentIndex(min(1, self.param2_combo.count() - 1))
            self._update_params()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QGridLayout()
        row = 0
        params = _traceable_set_channels()
        form.addWidget(QLabel("Parameter 1:"), row, 0)
        self.param1_combo = QComboBox(); form.addWidget(self.param1_combo, row, 1)
        form.addWidget(QLabel("Parameter 2:"), row, 2)
        self.param2_combo = QComboBox(); form.addWidget(self.param2_combo, row, 3)
        for ch in params:
            self.param1_combo.addItem(_pretty_label(ch), userData=ch)
            self.param2_combo.addItem(_pretty_label(ch), userData=ch)
        self.param1_combo.currentIndexChanged.connect(self._update_params)
        self.param2_combo.currentIndexChanged.connect(self._update_params)

        row += 1
        form.addWidget(QLabel("P1 start/end/step:"), row, 0)
        self.p1_start = QDoubleSpinBox(); self.p1_end = QDoubleSpinBox(); self.p1_step = QDoubleSpinBox()
        for sp in (self.p1_start, self.p1_end, self.p1_step): sp.setDecimals(3); sp.setSingleStep(0.1)
        self.p1_step.setMinimum(0.0001)
        form.addWidget(self.p1_start, row, 1); form.addWidget(self.p1_end, row, 2); form.addWidget(self.p1_step, row, 3)

        row += 1
        form.addWidget(QLabel("P2 start/end/step:"), row, 0)
        self.p2_start = QDoubleSpinBox(); self.p2_end = QDoubleSpinBox(); self.p2_step = QDoubleSpinBox()
        for sp in (self.p2_start, self.p2_end, self.p2_step): sp.setDecimals(3); sp.setSingleStep(0.1)
        self.p2_step.setMinimum(0.0001)
        form.addWidget(self.p2_start, row, 1); form.addWidget(self.p2_end, row, 2); form.addWidget(self.p2_step, row, 3)

        row += 1
        form.addWidget(QLabel("Dwell per point (s):"), row, 0)
        self.dwell_spin = QDoubleSpinBox(); self.dwell_spin.setDecimals(1); self.dwell_spin.setRange(0.5, 600.0); self.dwell_spin.setSingleStep(0.5); self.dwell_spin.setValue(2.0)
        form.addWidget(self.dwell_spin, row, 1)
        self.status = QLabel("Ready.")
        form.addWidget(self.status, row, 2, 1, 2)
        layout.addLayout(form)

        self.fig = Figure(figsize=(7, 4), dpi=100)
        self.canvas = FigureCanvas(self.fig)
        self.ax = self.fig.add_subplot(111)
        self.im = None
        self.cbar = None
        self.marker = self.ax.plot([], [], marker="o", markersize=10, color="red", linestyle="")[0]
        self.canvas.mpl_connect("button_press_event", self._on_click)
        layout.addWidget(self.canvas, 1)

        rowb = QHBoxLayout()
        self.btn_start = QPushButton("Start 2D Trace")
        self.btn_stop = QPushButton("Stop")
        self.btn_export = QPushButton("Export CSV…")
        self.btn_apply = QPushButton("Apply & Close")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_stop.setEnabled(False); self.btn_apply.setEnabled(False); self.btn_export.setEnabled(False)
        self.btn_start.clicked.connect(self.start_trace)
        self.btn_stop.clicked.connect(self.stop_trace)
        self.btn_export.clicked.connect(self.export_csv)
        self.btn_apply.clicked.connect(self.apply_and_close)
        self.btn_cancel.clicked.connect(self.close)
        rowb.addWidget(self.btn_start); rowb.addWidget(self.btn_stop); rowb.addWidget(self.btn_export); rowb.addStretch(); rowb.addWidget(self.btn_apply); rowb.addWidget(self.btn_cancel)
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

    def _get_trace_mean(self) -> Optional[float]:
        n_ch = self.backend.model.get("keithley/trace/n")
        try:
            n = int(n_ch.value) if n_ch and n_ch.value is not None else 0
        except Exception:
            n = 0
        if n <= 0:
            return None
        c = self.backend.model.get("keithley/trace/mean_nA")
        try:
            return float(c.value) if c and c.value is not None else None
        except Exception:
            return None

    def _gen_steps(self, start: float, end: float, step: float) -> List[float]:
        vals: List[float] = []
        if start < end:
            v = start
            while v < end - 1e-12:
                vals.append(v)
                v += step
            vals.append(end)
        else:
            v = start
            while v > end + 1e-12:
                vals.append(v)
                v -= step
            vals.append(end)
        return vals

    def _update_params(self):
        ch1 = self.param1_combo.currentData(); ch2 = self.param2_combo.currentData()
        if not ch1 or not ch2:
            return
        u1 = (CHANNELS.get(ch1).unit if CHANNELS.get(ch1) else unit_for(ch1))
        u2 = (CHANNELS.get(ch2).unit if CHANNELS.get(ch2) else unit_for(ch2))
        r1 = range_for(ch1) or (0.0, 10000.0)
        r2 = range_for(ch2) or (0.0, 10000.0)
        self.param1 = ParamInfo(ch1, u1, float(r1[0]), float(r1[1]))
        self.param2 = ParamInfo(ch2, u2, float(r2[0]), float(r2[1]))
        cur1 = self._get_set_value(ch1); cur2 = self._get_set_value(ch2)
        for sp in (self.p1_start, self.p1_end, self.p1_step): sp.blockSignals(True); sp.setRange(float(r1[0]), float(r1[1])); sp.blockSignals(False)
        for sp in (self.p2_start, self.p2_end, self.p2_step): sp.blockSignals(True); sp.setRange(float(r2[0]), float(r2[1])); sp.blockSignals(False)
        st1 = step_for(ch1); st2 = step_for(ch2)
        if st1 is None: st1 = max((float(r1[1]) - float(r1[0])) / 10.0, 0.001)
        if st2 is None: st2 = max((float(r2[1]) - float(r2[0])) / 10.0, 0.001)
        self.p1_start.setValue(cur1); self.p1_end.setValue(cur1); self.p1_step.setValue(float(st1))
        self.p2_start.setValue(cur2); self.p2_end.setValue(cur2); self.p2_step.setValue(float(st2))
        self.status.setText("Ready.")
        self._update_axes_labels()

    def _update_axes_labels(self):
        if self.param1 is None or self.param2 is None:
            return
        xlab = f"{_pretty_label(self.param1.channel)} [{self.param1.unit}]" if self.param1.unit else _pretty_label(self.param1.channel)
        ylab = f"{_pretty_label(self.param2.channel)} [{self.param2.unit}]" if self.param2.unit else _pretty_label(self.param2.channel)
        self.ax.set_xlabel(xlab); self.ax.set_ylabel(ylab); self.canvas.draw_idle()

    def _has_any_data(self) -> bool:
        return any(v == v for row in self.grid for v in row)

    def _best_cell(self) -> Tuple[Optional[int], Optional[int], Optional[float]]:
        best_val = None; best_i = None; best_j = None
        for j in range(len(self.v2)):
            for i in range(len(self.v1)):
                val = self.grid[j][i]
                if val != val:
                    continue
                if best_val is None or val > best_val:
                    best_val = val; best_i = i; best_j = j
        return best_i, best_j, best_val

    def _reset_ui_after_run(self):
        self.running = False; self.timer.stop(); self.btn_start.setEnabled(True); self.btn_stop.setEnabled(False)
        self.btn_apply.setEnabled(self.sel_i is not None and self.sel_j is not None)
        self.btn_export.setEnabled((not self.running) and self._has_any_data())

    def _restore_keithley_settings(self) -> None:
        if self._saved_keithley_settings is None:
            return
        try:
            self.backend.apply_keithley_settings(self._saved_keithley_settings)
        except Exception:
            pass
        self._saved_keithley_settings = None

    def start_trace(self):
        if self.running or self.param1 is None or self.param2 is None:
            return
        s1, e1, st1 = self.p1_start.value(), self.p1_end.value(), self.p1_step.value()
        s2, e2, st2 = self.p2_start.value(), self.p2_end.value(), self.p2_step.value()
        if st1 <= 0 or st2 <= 0:
            QMessageBox.warning(self, "2D Tracer", "Step sizes must be > 0."); return
        if s1 == e1 or s2 == e2:
            QMessageBox.warning(self, "2D Tracer", "Start and End must differ for both parameters."); return
        v1 = self._gen_steps(float(s1), float(e1), float(st1))
        v2 = self._gen_steps(float(s2), float(e2), float(st2))
        if not v1 or not v2:
            QMessageBox.warning(self, "2D Tracer", "No steps generated."); return

        k_settings = self.backend.get_keithley_settings_copy()
        dwell_s = float(self.dwell_spin.value())
        if dwell_s < float(k_settings.trace.bucket_interval_s):
            QMessageBox.warning(self, "2D Tracer", f"Dwell must be at least {k_settings.trace.bucket_interval_s:.2f} s for TRACE mode.")
            return
        self._saved_keithley_settings = copy.deepcopy(k_settings)
        k_settings.mode = "TRACE"
        self.backend.apply_keithley_settings(k_settings)

        self.v1 = v1; self.v2 = v2
        self.orig1 = self._get_set_value(self.param1.channel); self.orig2 = self._get_set_value(self.param2.channel)
        self.applied = None
        self.grid = [[float("nan") for _ in self.v1] for __ in self.v2]
        self.i = -1; self.j = -1; self.sel_i = None; self.sel_j = None
        self.dwell_s = dwell_s; self.elapsed_s = 0.0; self.running = True
        self.btn_start.setEnabled(False); self.btn_stop.setEnabled(True); self.btn_apply.setEnabled(False); self.btn_export.setEnabled(False)
        self._update_axes_labels(); self._draw_heatmap()
        self.timer.start(int(self._tick_dt_s * 1000))
        self._next_point()

    def _next_point(self):
        self.i += 1
        if self.i >= len(self.v1):
            self.i = 0; self.j += 1
        if self.j >= len(self.v2):
            self._finish(); return
        try:
            self._set_param_value(self.param2.channel, float(self.v2[self.j]))
            self._set_param_value(self.param1.channel, float(self.v1[self.i]))
            self.backend.reset_keithley_trace()
        except Exception:
            pass
        self.elapsed_s = 0.0
        self.status.setText(f"Point ({self.j + 1}/{len(self.v2)}, {self.i + 1}/{len(self.v1)}): waiting...")

    def _tick(self):
        if not self.running:
            return
        self.elapsed_s += self._tick_dt_s
        rem = max(0.0, self.dwell_s - self.elapsed_s)
        self.status.setText(f"Point ({self.j + 1}/{len(self.v2)}, {self.i + 1}/{len(self.v1)}): waiting... ({rem:.1f}s)")
        if self.elapsed_s < self.dwell_s:
            return
        y = self._get_trace_mean()
        if y is None:
            y = float("nan")
        self.grid[self.j][self.i] = float(y)
        self._draw_heatmap()
        self._next_point()

    def _finish(self):
        self.running = False; self.timer.stop(); self._restore_keithley_settings()
        self.btn_stop.setEnabled(False); self.btn_start.setEnabled(True); self.btn_export.setEnabled(self._has_any_data())
        best_i, best_j, best_val = self._best_cell()
        if best_i is not None and best_j is not None and best_val is not None:
            self._select(best_i, best_j); self.btn_apply.setEnabled(True)
            self.status.setText(f"Finished. Max at P1={self.v1[best_i]:.3f}, P2={self.v2[best_j]:.3f}, Keithley={best_val:.2f} nA.")
        else:
            self.btn_apply.setEnabled(False); self.status.setText("Finished (no valid data).")

    def stop_trace(self):
        if not self.running:
            return
        self.running = False; self.timer.stop(); self._restore_keithley_settings()
        self.btn_stop.setEnabled(False); self.btn_start.setEnabled(True); self.btn_export.setEnabled(self._has_any_data())
        best_i, best_j, best_val = self._best_cell()
        if best_i is not None and best_j is not None and best_val is not None:
            self._select(best_i, best_j); self.btn_apply.setEnabled(True)
            self.status.setText(f"Stopped. Current max at P1={self.v1[best_i]:.3f}, P2={self.v2[best_j]:.3f}, Keithley={best_val:.2f} nA.")
        else:
            self.btn_apply.setEnabled(False); self.status.setText("Stopped (no valid data yet).")

    def _draw_heatmap(self):
        import numpy as np
        if not self.v1 or not self.v2:
            return
        Z = np.array(self.grid, dtype=float)
        self._update_axes_labels()
        extent = [self.v1[0], self.v1[-1], self.v2[0], self.v2[-1]]
        if self.im is None:
            self.im = self.ax.imshow(Z, origin="lower", aspect="auto", interpolation="nearest", extent=extent)
            self.cbar = self.fig.colorbar(self.im, ax=self.ax, label="Keithley mean [nA]")
        else:
            self.im.set_data(Z); self.im.set_extent(extent)
            finite = np.isfinite(Z)
            if np.any(finite):
                vmin = float(np.nanmin(Z)); vmax = float(np.nanmax(Z))
                if vmin == vmax:
                    vmax = vmin + 1e-12
                self.im.set_clim(vmin, vmax)
            if self.cbar is not None:
                self.cbar.update_normal(self.im)
        if self.sel_i is not None and self.sel_j is not None:
            self.marker.set_data([self.v1[self.sel_i]], [self.v2[self.sel_j]])
        else:
            self.marker.set_data([], [])
        self.canvas.draw_idle()

    def _on_click(self, event):
        if event.inaxes != self.ax or self.im is None or event.xdata is None or event.ydata is None or not self.v1 or not self.v2:
            return
        i = min(range(len(self.v1)), key=lambda k: abs(self.v1[k] - float(event.xdata)))
        j = min(range(len(self.v2)), key=lambda k: abs(self.v2[k] - float(event.ydata)))
        if 0 <= i < len(self.v1) and 0 <= j < len(self.v2):
            self._select(i, j); self.btn_apply.setEnabled(True)

    def _select(self, i: int, j: int):
        self.sel_i, self.sel_j = i, j
        self._draw_heatmap()
        val = self.grid[j][i]
        self.status.setText(f"Selected: P1={self.v1[i]:.3f}, P2={self.v2[j]:.3f}, Keithley={val:.2f} nA.")

    def export_csv(self) -> None:
        if self.running:
            QMessageBox.information(self, "Export CSV", "Stop/finish the trace before exporting."); return
        if not self._has_any_data():
            QMessageBox.information(self, "Export CSV", "No data to export yet."); return
        if self.param1 is None or self.param2 is None:
            QMessageBox.information(self, "Export CSV", "No parameters selected."); return
        ch1 = self.param1.channel; ch2 = self.param2.channel
        safe_ch1 = "".join(c if (c.isalnum() or c in ("-", "_")) else "_" for c in ch1)
        safe_ch2 = "".join(c if (c.isalnum() or c in ("-", "_")) else "_" for c in ch2)
        default_name = datetime.now().strftime(f"trace2d_{safe_ch1}__{safe_ch2}_%Y%m%d_%H%M%S.csv")
        default_path = os.path.join(self._last_dir, default_name) if self._last_dir else default_name
        path, _ = QFileDialog.getSaveFileName(self, "Export 2D trace data as CSV", default_path, "CSV files (*.csv);;All files (*.*)")
        if not path:
            return
        path = str(path)
        if not path.lower().endswith(".csv"):
            path += ".csv"
        d = os.path.dirname(path)
        if d:
            self._last_dir = d
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["j_index", "i_index", "param2_value", "param1_value", "keithley_mean_nA", "selected"])
                for j in range(len(self.v2)):
                    for i in range(len(self.v1)):
                        val = self.grid[j][i]
                        if val != val:
                            continue
                        w.writerow([j, i, float(self.v2[j]), float(self.v1[i]), float(val), 1 if (self.sel_i == i and self.sel_j == j) else 0])
        except Exception as e:
            QMessageBox.critical(self, "Export CSV", f"Failed to write file:\n{e}")
            return
        QMessageBox.information(self, "Export CSV", f"Saved:\n{path}")

    def apply_and_close(self):
        if self.param1 is None or self.param2 is None or self.sel_i is None or self.sel_j is None:
            self.close(); return
        v1 = float(self.v1[self.sel_i]); v2 = float(self.v2[self.sel_j])
        try:
            self._set_param_value(self.param2.channel, v2)
            self._set_param_value(self.param1.channel, v1)
            self.applied = (v1, v2)
        except Exception:
            pass
        self.close()

    def closeEvent(self, event):
        if self.running:
            self.running = False; self.timer.stop()
        self._restore_keithley_settings()
        if self.applied is None and self.param1 is not None and self.param2 is not None and self.orig1 is not None and self.orig2 is not None:
            try:
                self._set_param_value(self.param1.channel, float(self.orig1))
                self._set_param_value(self.param2.channel, float(self.orig2))
            except Exception:
                pass
        self._reset_ui_after_run()
        super().closeEvent(event)
