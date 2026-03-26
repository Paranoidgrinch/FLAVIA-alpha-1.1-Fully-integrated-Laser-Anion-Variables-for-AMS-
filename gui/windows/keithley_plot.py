from __future__ import annotations

# unchanged versus current keithley_plot.py on purpose;
# only ownership moves from MainWindow to KeithleyPanel.

import csv
import os
from datetime import datetime

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QCheckBox, QPushButton, QFileDialog, QMessageBox

from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas


class KeithleyPlotWindow(QDialog):
    clearRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keithley Plot (mean ± σ)")

        self.figure = Figure(figsize=(7, 4), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_xlabel("Time [s]")
        self.ax.set_ylabel("Current [nA]")

        (self.avg_line,) = self.ax.plot([], [], label="Avg(interval)")
        (self.upper_line,) = self.ax.plot([], [], linestyle="--", label="+σ")
        (self.lower_line,) = self.ax.plot([], [], linestyle="--", label="-σ")
        self.ax.legend(loc="best")

        self.cb_show_error = QCheckBox("Show error bands")
        self.cb_show_error.setChecked(True)
        self.cb_show_error.toggled.connect(self.on_error_band_toggled)

        self.btn_export = QPushButton("Export CSV…")
        self.btn_export.clicked.connect(self.export_csv)

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.clicked.connect(self.clear_data)

        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        bottom = QHBoxLayout()
        bottom.addWidget(self.btn_export)
        bottom.addWidget(self.btn_clear)
        bottom.addStretch(1)
        bottom.addWidget(self.cb_show_error)
        layout.addLayout(bottom)
        self.setLayout(layout)

        self.xs: list[float] = []
        self.avg_vals: list[float] = []
        self.sigma_vals: list[float] = []
        self.max_points = 3000
        self._last_dir = ""

    def add_point(self, t: float, mean: float, sigma: float):
        self.xs.append(float(t))
        self.avg_vals.append(float(mean))
        self.sigma_vals.append(float(sigma))

        if len(self.xs) > self.max_points:
            overflow = len(self.xs) - self.max_points
            self.xs = self.xs[overflow:]
            self.avg_vals = self.avg_vals[overflow:]
            self.sigma_vals = self.sigma_vals[overflow:]

        lower = [a - s for a, s in zip(self.avg_vals, self.sigma_vals)]
        upper = [a + s for a, s in zip(self.avg_vals, self.sigma_vals)]
        self.avg_line.set_data(self.xs, self.avg_vals)
        self.upper_line.set_data(self.xs, upper)
        self.lower_line.set_data(self.xs, lower)
        show = self.cb_show_error.isChecked()
        self.upper_line.set_visible(show)
        self.lower_line.set_visible(show)
        self.ax.set_autoscale_on(True)
        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw_idle()

    def on_error_band_toggled(self, checked: bool):
        self.upper_line.set_visible(checked)
        self.lower_line.set_visible(checked)
        self.canvas.draw_idle()

    def clear_data(self) -> None:
        self.xs.clear()
        self.avg_vals.clear()
        self.sigma_vals.clear()
        self.avg_line.set_data([], [])
        self.upper_line.set_data([], [])
        self.lower_line.set_data([], [])
        self.ax.set_autoscale_on(True)
        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw_idle()
        self.clearRequested.emit()

    def export_csv(self) -> None:
        if not self.xs:
            QMessageBox.information(self, "Export CSV", "No data to export.")
            return

        default_name = datetime.now().strftime("keithley_plot_%Y%m%d_%H%M%S.csv")
        default_path = os.path.join(self._last_dir, default_name) if self._last_dir else default_name
        path, _ = QFileDialog.getSaveFileName(self, "Export Keithley Plot as CSV", default_path, "CSV files (*.csv);;All files (*.*)")
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        d = os.path.dirname(path)
        if d:
            self._last_dir = d
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["t_s", "mean_nA", "sigma_nA", "upper_nA", "lower_nA"])
                for t, m, s in zip(self.xs, self.avg_vals, self.sigma_vals):
                    w.writerow([t, m, s, m + s, m - s])
        except Exception as e:
            QMessageBox.critical(self, "Export CSV", f"Failed to write file:\n{e}")
            return
        QMessageBox.information(self, "Export CSV", f"Saved:\n{path}")
