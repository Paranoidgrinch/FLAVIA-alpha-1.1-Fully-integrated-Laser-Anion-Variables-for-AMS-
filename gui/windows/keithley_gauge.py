from __future__ import annotations

import math
import time
from typing import Optional

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QPainter, QPen, QFont, QColor
from PyQt5.QtWidgets import QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox


AUTO_SCALE_UP_FRACTION = 0.90
AUTO_SCALE_DOWN_FRACTION = 0.20
AUTO_SCALE_DOWN_HOLD_S = 0.50
AUTO_SCALE_TARGET_FRACTION = 0.80


def _range_max_nA(range_spec) -> float:
    _mn, mx, unit = range_spec
    if unit == "pA":
        return float(mx) / 1000.0
    if unit == "nA":
        return float(mx)
    return float(mx) * 1000.0


def _best_auto_range_index(current_nA: float, ranges) -> int:
    value_nA = abs(float(current_nA))
    for idx, spec in enumerate(ranges):
        if value_nA <= AUTO_SCALE_TARGET_FRACTION * _range_max_nA(spec):
            return idx
    return len(ranges) - 1


def _auto_scale_step(current_nA: float, ranges, current_idx: int, down_since, now: float):
    """Return (range_idx, down_since) for display-only autoscaling.

    Upscaling is immediate near full scale. Downscaling requires the signal to
    stay well below full scale for a short hold time, preventing visible range
    chatter while tuning.
    """
    if not ranges:
        return 0, None

    idx = max(0, min(int(current_idx), len(ranges) - 1))
    value_nA = abs(float(current_nA))
    max_nA = _range_max_nA(ranges[idx])

    if value_nA > AUTO_SCALE_UP_FRACTION * max_nA and idx < len(ranges) - 1:
        target = _best_auto_range_index(value_nA, ranges)
        return max(idx + 1, target), None

    if value_nA < AUTO_SCALE_DOWN_FRACTION * max_nA and idx > 0:
        if down_since is None:
            return idx, float(now)
        if float(now) - float(down_since) >= AUTO_SCALE_DOWN_HOLD_S:
            return min(idx, _best_auto_range_index(value_nA, ranges)), None
        return idx, down_since

    return idx, None


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

        cx = w / 2
        cy = h * 0.85
        radius = min(w, h) * 0.42

        painter.setPen(QPen(Qt.black, 2))
        painter.drawArc(int(cx - radius), int(cy - radius), int(2 * radius), int(2 * radius), 180 * 16, -180 * 16)

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
                painter.setFont(QFont("Sans", 8))
                painter.drawText(int(cx + (radius - 30) * math.cos(ang) - 12), int(cy - (radius - 30) * math.sin(ang) + 4), 40, 16, Qt.AlignLeft, f"{val:g}")

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
    """Display-only gauge. Data ownership stays outside this window."""

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
        self.auto_scale = False
        self._auto_down_since: Optional[float] = None
        self.last_nA: Optional[float] = None

        layout = QVBoxLayout()
        top = QHBoxLayout()
        top.addWidget(QLabel("Scale:"))
        self.cb_range = QComboBox()
        self.cb_range.addItem("Auto", userData="auto")
        for i, (_, max_val, unit) in enumerate(self.ranges):
            self.cb_range.addItem(f"0–{max_val} {unit}", userData=i)
        # Preserve the previous 100 nA manual default. Auto is an explicit option.
        self.cb_range.setCurrentIndex(self.range_idx + 1)
        self.cb_range.currentIndexChanged.connect(self.on_range_changed)
        top.addWidget(self.cb_range)
        top.addStretch()
        layout.addLayout(top)

        self.gauge = GaugeWidget()
        mn, mx, unit = self.ranges[self.range_idx]
        self.gauge.set_range(mn, mx, unit)
        layout.addWidget(self.gauge)
        self.setLayout(layout)

    def _apply_range(self) -> None:
        mn, mx, unit = self.ranges[self.range_idx]
        self.gauge.set_range(mn, mx, unit)

    def on_range_changed(self, combo_idx: int) -> None:
        data = self.cb_range.itemData(combo_idx)
        self._auto_down_since = None
        if data == "auto":
            self.auto_scale = True
            if self.last_nA is not None:
                self.range_idx = _best_auto_range_index(self.last_nA, self.ranges)
        else:
            self.auto_scale = False
            try:
                self.range_idx = int(data)
            except (TypeError, ValueError):
                return
        self._apply_range()
        if self.last_nA is not None:
            self.update_current(self.last_nA)

    def update_current_A(self, current_A: float) -> None:
        try:
            current_nA = float(current_A) * 1e9
        except Exception:
            current_nA = 0.0
        self.update_current(current_nA)

    def update_current(self, current_nA: float) -> None:
        self.last_nA = float(current_nA)
        if self.auto_scale:
            new_idx, self._auto_down_since = _auto_scale_step(
                self.last_nA,
                self.ranges,
                self.range_idx,
                self._auto_down_since,
                time.monotonic(),
            )
            if new_idx != self.range_idx:
                self.range_idx = new_idx
                self._apply_range()

        mn, mx, unit = self.ranges[self.range_idx]
        if unit == "pA":
            val = current_nA * 1000.0
        elif unit == "nA":
            val = current_nA
        else:
            val = current_nA / 1000.0
        self.gauge.set_value(max(mn, min(mx, val)))
