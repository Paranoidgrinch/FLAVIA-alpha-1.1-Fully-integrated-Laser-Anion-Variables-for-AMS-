# gui/windows/keithley_plot.py
from __future__ import annotations

from PyQt5.QtWidgets import QDialog, QVBoxLayout, QCheckBox
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas


class KeithleyPlotWindow(QDialog):
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

        self.cb_show = QCheckBox("Show error bands")
        self.cb_show.setChecked(True)
        self.cb_show.toggled.connect(self.on_toggled)

        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        layout.addWidget(self.cb_show)
        self.setLayout(layout)

        self.xs: list[float] = []
        self.means: list[float] = []
        self.sigmas: list[float] = []
        self.max_points = 3000

    def on_toggled(self, on: bool) -> None:
        self.upper_line.set_visible(bool(on))
        self.lower_line.set_visible(bool(on))
        self.canvas.draw_idle()

    def add_point(self, t_s: float, mean: float, sigma: float) -> None:
        self.xs.append(float(t_s))
        self.means.append(float(mean))
        self.sigmas.append(float(sigma))
        if len(self.xs) > self.max_points:
            overflow = len(self.xs) - self.max_points
            self.xs = self.xs[overflow:]
            self.means = self.means[overflow:]
            self.sigmas = self.sigmas[overflow:]

        upper = [m + s for m, s in zip(self.means, self.sigmas)]
        lower = [m - s for m, s in zip(self.means, self.sigmas)]

        self.avg_line.set_data(self.xs, self.means)
        self.upper_line.set_data(self.xs, upper)
        self.lower_line.set_data(self.xs, lower)

        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw_idle()