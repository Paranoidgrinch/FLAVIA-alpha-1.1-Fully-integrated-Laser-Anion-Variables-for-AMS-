from __future__ import annotations

from typing import List

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QPushButton, QComboBox, QLabel, QSlider, QSizePolicy


class ScrollableSlider(QSlider):
    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.control = None  # {'step_selector': QComboBox, 'multiplier': int}

    def wheelEvent(self, event):
        if not self.control:
            return
        delta = event.angleDelta().y()
        step_selector: QComboBox = self.control["step_selector"]
        multiplier: int = int(self.control["multiplier"])

        step_val = step_selector.currentData()
        if step_val is None:
            step_text = step_selector.currentText().replace(",", ".")
            step_val = float(step_text)

        ticks = max(1, round(float(step_val) * multiplier))
        new_val = self.value() + (ticks if delta > 0 else -ticks)
        self.setValue(min(self.maximum(), max(self.minimum(), new_val)))
        event.accept()


class StepSliderControl(QWidget):
    """
    Old behavior, compact layout:
      [value_label] ◀ [slider] ▶ [step]
    value_label is the SET value (bold) and is now on the LEFT to save width.
    """
    valueChangedFloat = pyqtSignal(float)

    allowed_steps: List[float] = [0.001,0.01, 0.1, 1.0, 10.0, 100.0, 1000.0]

    def __init__(
        self,
        min_val: float,
        max_val: float,
        multiplier: int,
        unit: str,
        *,
        default_step: float = 1.0,
        decimals: int = 1,
        parent=None,
    ):
        super().__init__(parent)
        self._min_val = float(min_val)
        self._max_val = float(max_val)
        self._multiplier = int(max(1, multiplier))
        self._unit = str(unit)
        self._decimals = int(max(0, decimals))

        layout = QHBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(0, 0, 0, 0)

        # SET value label (left)
        self.value_label = QLabel("—")
        self.value_label.setStyleSheet("font-weight: 800;")
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.value_label.setMinimumWidth(95)

        self.decrease_btn = QPushButton("◀")
        self.decrease_btn.setFixedWidth(22)

        self.slider = ScrollableSlider()
        self.slider.setMinimum(round(self._min_val * self._multiplier))
        self.slider.setMaximum(round(self._max_val * self._multiplier))
        self.slider.setSingleStep(1)
        self.slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.slider.setMinimumWidth(90)

        self.increase_btn = QPushButton("▶")
        self.increase_btn.setFixedWidth(22)

        self.step_selector = QComboBox()
        self.step_selector.setMinimumWidth(55)
        self.step_selector.setMaximumWidth(70)
        for step in self.allowed_steps:
            self.step_selector.addItem(format(step, "g"), step)
        default_index = self.allowed_steps.index(default_step) if default_step in self.allowed_steps else 1
        self.step_selector.setCurrentIndex(default_index)

        self.slider.control = {"step_selector": self.step_selector, "multiplier": self._multiplier}

        layout.addWidget(self.value_label)
        layout.addWidget(self.decrease_btn)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.increase_btn)
        layout.addWidget(self.step_selector)

        self.slider.valueChanged.connect(self._update_value_label_and_emit)
        self.decrease_btn.clicked.connect(self._decrease_value)
        self.increase_btn.clicked.connect(self._increase_value)

        self.set_real_value(self._min_val, emit=False)

    def real_value(self) -> float:
        return float(self.slider.value()) / float(self._multiplier)

    def set_real_value(self, v: float, *, emit: bool = False) -> None:
        v = float(v)
        v = max(self._min_val, min(self._max_val, v))
        ticks = int(round(v * self._multiplier))

        self.slider.blockSignals(True)
        try:
            self.slider.setValue(ticks)
        finally:
            self.slider.blockSignals(False)

        self._update_value_label(ticks)
        if emit:
            self.valueChangedFloat.emit(self.real_value())

    def _step_ticks(self) -> int:
        val = self.step_selector.currentData()
        if val is None:
            val = float(self.step_selector.currentText().replace(",", "."))
        return max(1, round(float(val) * self._multiplier))

    def _decrease_value(self) -> None:
        self.slider.setValue(max(self.slider.minimum(), self.slider.value() - self._step_ticks()))

    def _increase_value(self) -> None:
        self.slider.setValue(min(self.slider.maximum(), self.slider.value() + self._step_ticks()))

    def _update_value_label(self, ticks: int) -> None:
        real_value = float(ticks) / float(self._multiplier)
        self.value_label.setText(f"{real_value:.{self._decimals}f} {self._unit}".strip())

    def _update_value_label_and_emit(self, ticks: int) -> None:
        self._update_value_label(int(ticks))
        self.valueChangedFloat.emit(self.real_value())