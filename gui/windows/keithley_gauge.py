# gui/windows/keithley_gauge.py
from __future__ import annotations

import math
from typing import Optional

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QPainter, QPen, QFont, QColor
from PyQt5.QtWidgets import QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox


class GaugeWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._min = 0.0
        self._max = 100.0
        self._unit = "nA"
        self._value = 0.0
        self.setMinimumSize(QSize(260, 180))

    def set_range(self, min_val: float, max_val: float, unit: str) -> None:
        self._min = float(min_val)
        self._max = float(max_val)
        self._unit = str(unit)
        self.update()

    def set_value(self, v: float) -> None:
        self._value = float(v)
        self.update()

    def paintEvent(self, ev):
        w = self.width()
        h = self.height()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        margin = 14
        cx = w / 2
        cy = h * 0.85
        radius = min(w, h) * 0.42

        painter.setPen(QPen(Qt.black, 2))
        painter.drawArc(int(cx - radius), int(cy - radius), int(2 * radius), int(2 * radius),
                        180 * 16, -180 * 16)

        painter.setPen(QPen(Qt.black, 1))
        tick_count = 10
        for i in range(tick_count + 1):
            frac = i / tick_count
            ang = math.pi * (1.0 - frac)
            x1 = cx + (radius - 4) * math.cos(ang)
            y1 = cy - (radius - 4) * math.sin(ang)
            x2 = cx + (radius - 14) * math.cos(ang)
            y2 = cy - (radius - 14) * math.sin(ang)
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

            if i % 2 == 0:
                val = self._min + frac * (self._max - self._min)
                label = f"{val:g}"
                lx = cx + (radius - 30) * math.cos(ang)
                ly = cy - (radius - 30) * math.sin(ang)
                painter.setFont(QFont("Sans", 8))
                painter.drawText(int(lx - 12), int(ly + 4), 40, 16, Qt.AlignLeft, label)

        painter.setPen(QPen(Qt.red, 3))
        v = max(self._min, min(self._max, self._value))
        frac = 0.0 if self._max <= self._min else (v - self._min) / (self._max - self._min)
        ang = math.pi * (1.0 - frac)
        nx = cx + (radius - 22) * math.cos(ang)
        ny = cy - (radius - 22) * math.sin(ang)
        painter.drawLine(int(cx), int(cy), int(nx), int(ny))

        painter.setBrush(QColor(0, 0, 0))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(int(cx - 5), int(cy - 5), 10, 10)

        painter.setPen(QPen(Qt.black, 1))
        painter.setFont(QFont("Sans", 10, QFont.Bold))
        painter.drawText(0, 0, w, int(h * 0.25), Qt.AlignCenter, f"{v:.3g} {self._unit}")
        painter.end()


class KeithleyGaugeWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keithley Gauge")

        self.ranges = [
            (0, 100, "pA"),
            (0, 300, "pA"),
            (0, 1, "nA"),
            (0, 3, "nA"),
            (0, 10, "nA"),
            (0, 30, "nA"),
            (0, 100, "nA"),
            (0, 300, "nA"),
            (0, 1, "µA"),
            (0, 3, "µA"),
            (0, 10, "µA"),
            (0, 30, "µA"),
        ]
        self.range_idx = 6
        self.last_nA: Optional[float] = None

        layout = QVBoxLayout()
        top = QHBoxLayout()
        top.addWidget(QLabel("Scale:"))
        self.cb_range = QComboBox()
        for i, (_, max_val, unit) in enumerate(self.ranges):
            self.cb_range.addItem(f"0–{max_val} {unit}", userData=i)
        self.cb_range.setCurrentIndex(self.range_idx)
        self.cb_range.currentIndexChanged.connect(self.on_range_changed)
        top.addWidget(self.cb_range)
        top.addStretch()
        layout.addLayout(top)

        self.gauge = GaugeWidget()
        mn, mx, unit = self.ranges[self.range_idx]
        self.gauge.set_range(mn, mx, unit)
        layout.addWidget(self.gauge)
        self.setLayout(layout)

    def on_range_changed(self, idx: int) -> None:
        self.range_idx = idx
        mn, mx, unit = self.ranges[idx]
        self.gauge.set_range(mn, mx, unit)
        if self.last_nA is not None:
            self.update_current(self.last_nA)

    def update_current(self, current_nA: float) -> None:
        self.last_nA = float(current_nA)
        mn, mx, unit = self.ranges[self.range_idx]
        if unit == "pA":
            val = current_nA * 1000.0
        elif unit == "nA":
            val = current_nA
        else:
            val = current_nA / 1000.0
        val = max(mn, min(mx, val))
        self.gauge.set_value(val)