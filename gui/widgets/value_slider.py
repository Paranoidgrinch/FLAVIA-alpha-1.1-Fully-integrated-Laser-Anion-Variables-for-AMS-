# gui/widgets/value_slider.py
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QSlider, QDoubleSpinBox


class ValueSlider(QWidget):
    """
    Composite widget: QSlider + QDoubleSpinBox, float value, editable.
    API so designed that we can later replace it with your existing CustomSlider.

    Signals:
      - editingFinished(value: float): emitted when user finishes edit (spinbox) or releases slider
    """
    editingFinished = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._min = 0.0
        self._max = 1.0
        self._decimals = 3
        self._scale = 1000  # slider integer steps

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(self._scale)

        self.spin = QDoubleSpinBox()
        self.spin.setDecimals(self._decimals)
        self.spin.setMinimum(self._min)
        self.spin.setMaximum(self._max)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(self.slider, 2)
        lay.addWidget(self.spin, 1)

        self.slider.valueChanged.connect(self._on_slider)
        self.slider.sliderReleased.connect(self._emit_finished)
        self.spin.valueChanged.connect(self._on_spin)
        self.spin.editingFinished.connect(self._emit_finished)

        self._block = False
        self.set_value(0.0)

    def set_decimals(self, d: int) -> None:
        self._decimals = int(max(0, d))
        self.spin.setDecimals(self._decimals)

    def set_range(self, vmin: float, vmax: float) -> None:
        self._min = float(vmin)
        self._max = float(vmax)
        if self._max <= self._min:
            self._max = self._min + 1.0
        self.spin.setMinimum(self._min)
        self.spin.setMaximum(self._max)
        self.set_value(self.value())  # clamp + sync

    def set_single_step(self, step: float) -> None:
        self.spin.setSingleStep(float(step))

    def value(self) -> float:
        return float(self.spin.value())

    def set_value(self, v: float) -> None:
        v = float(v)
        if v < self._min:
            v = self._min
        if v > self._max:
            v = self._max

        self._block = True
        try:
            self.spin.setValue(v)
            self.slider.setValue(self._to_slider(v))
        finally:
            self._block = False

    def _to_slider(self, v: float) -> int:
        frac = (v - self._min) / (self._max - self._min) if self._max > self._min else 0.0
        x = int(round(frac * self._scale))
        return max(0, min(self._scale, x))

    def _from_slider(self, x: int) -> float:
        frac = float(x) / float(self._scale)
        return self._min + frac * (self._max - self._min)

    def _on_slider(self, x: int) -> None:
        if self._block:
            return
        v = self._from_slider(int(x))
        self._block = True
        try:
            self.spin.setValue(v)
        finally:
            self._block = False

    def _on_spin(self, v: float) -> None:
        if self._block:
            return
        self._block = True
        try:
            self.slider.setValue(self._to_slider(float(v)))
        finally:
            self._block = False

    def _emit_finished(self) -> None:
        self.editingFinished.emit(self.value())