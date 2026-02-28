from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, List

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QLabel, QToolButton, QHBoxLayout, QVBoxLayout, QGroupBox

from backend.channels import decimals_for, unit_for
from gui.widgets import StepSliderControl
from backend.channels import decimals_for, unit_for, range_for, step_for

def pretty_name(channel: str) -> str:
    parts = channel.split("/")
    if len(parts) < 2:
        return channel

    root = parts[0]
    block = parts[1].replace("_", " ").title()
    tail = "/".join(parts[2:]).replace("_", " ")

    tail = tail.replace("set u v", "U set").replace("meas u v", "U meas")
    tail = tail.replace("set i a", "I set").replace("meas i a", "I meas")
    tail = tail.replace("set v", "V set").replace("meas v", "V meas")
    tail = tail.replace("temp c", "Temp")
    tail = tail.replace("meas i ma", "I meas")
    tail = tail.replace("set u", "U set").replace("meas u", "U meas")

    if root == "cs":
        prefix = ""
    elif root == "hv":
        prefix = "HV "
    elif root == "psu":
        prefix = "PSU "
    elif root == "pressure":
        prefix = "Pressure "
    elif root == "steerer":
        prefix = "Steerer "
        if parts[1] in ("1x", "1y", "2x", "2y", "3x", "3y"):
            axis = "X" if parts[1].endswith("x") else "Y"
            idx = parts[1][0]
            block = f"{axis}{idx}"
        elif parts[1] == "bias":
            block = "Bias"
    else:
        prefix = root.upper() + " "

    return f"{prefix}{block}: {tail.title()}" if tail else f"{prefix}{block}"


def default_range_for(channel: str) -> Tuple[float, float]:
    r = range_for(channel)
    if r is not None:
        return r

    # fallback: fixed polarity => 0..x
    u = unit_for(channel)
    if u == "V":
        return (0.0, 10000.0)
    if u == "A":
        return (0.0, 5.0)
    if u == "mA":
        return (0.0, 50.0)
    if u == "°C":
        return (0.0, 2000.0)
    return (0.0, 1000.0)


def default_step_for(channel: str) -> float:
    s = step_for(channel)
    if s is not None:
        return s

    # fallback
    u = unit_for(channel)
    if u == "V":
        return 10.0
    if u in ("A", "mA"):
        return 0.1
    if u == "°C":
        return 1.0
    d = decimals_for(channel, default=2)
    return 10 ** (-d)


@dataclass
class AnalogBinding:
    set_ch: str
    meas_ch: Optional[str]


class AnalogControl(QWidget):
    """
    Compact row:
      [Label] [SET value+unit (bold)] ◀ [slider] ▶ [step]   [Meas: value+unit (bold)]
    """
    def __init__(self, backend, binding: AnalogBinding, label: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.binding = binding

        self.lbl = QLabel(label or pretty_name(binding.set_ch))
        self.lbl.setMinimumWidth(170)

        d_set = decimals_for(binding.set_ch, default=1)
        mult = 10 ** int(max(0, d_set))
        unit_set = unit_for(binding.set_ch)
        vmin, vmax = default_range_for(binding.set_ch)
        default_step = default_step_for(binding.set_ch)

        self.slider = StepSliderControl(vmin, vmax, mult, unit_set, default_step=default_step, decimals=d_set)

        self.meas_prefix = QLabel("Meas:")
        self.meas_prefix.setStyleSheet("font-weight:800;")
        self.meas_val = QLabel("—")
        self.meas_val.setStyleSheet("font-weight:800;")
        self.meas_val.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.meas_val.setMinimumWidth(140)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(self.lbl, 0)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.meas_prefix, 0)
        lay.addWidget(self.meas_val, 0)

        self.slider.valueChangedFloat.connect(self._on_user_send)

    def _on_user_send(self, value: float) -> None:
        try:
            self.backend.set_channel(self.binding.set_ch, float(value))
        except Exception:
            pass

    def update_channel(self, name: str, value) -> None:
        if name == self.binding.set_ch:
            try:
                self.slider.set_real_value(float(value), emit=False)
            except Exception:
                pass
        elif self.binding.meas_ch and name == self.binding.meas_ch:
            self.meas_val.setText(self._format_value(self.binding.meas_ch, value))

    def _format_value(self, ch: str, value) -> str:
        if value is None or value == "":
            return "—"
        d = decimals_for(ch, default=2)
        u = unit_for(ch)
        try:
            v = float(value)
            return f"{v:.{d}f} {u}".strip()
        except Exception:
            return f"{value} {u}".strip()


class ReadOnlyValue(QWidget):
    """Compact row: [Label]  Meas: [value bold]"""
    def __init__(self, channel: str, label: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.channel = channel

        self.lbl = QLabel(label or pretty_name(channel))
        self.lbl.setMinimumWidth(170)

        self.meas_prefix = QLabel("Meas:")
        self.meas_prefix.setStyleSheet("font-weight:800;")
        self.val = QLabel("—")
        self.val.setStyleSheet("font-weight:800;")
        self.val.setMinimumWidth(140)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(self.lbl, 0)
        lay.addStretch(1)
        lay.addWidget(self.meas_prefix, 0)
        lay.addWidget(self.val, 0)

    def update_channel(self, name: str, value) -> None:
        if name != self.channel:
            return
        d = decimals_for(self.channel, default=2)
        u = unit_for(self.channel)
        if value is None or value == "":
            self.val.setText("—")
            return
        try:
            v = float(value)
            self.val.setText(f"{v:.{d}f} {u}".strip())
        except Exception:
            self.val.setText(f"{value} {u}".strip())


class DigitalToggle(QWidget):
    def __init__(self, backend, state_channel: str, label: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.state_channel = state_channel

        self.lbl = QLabel(label or pretty_name(state_channel))
        self.lbl.setMinimumWidth(170)

        self.btn = QToolButton()
        self.btn.setCheckable(True)
        self.btn.setText("OFF")
        self.btn.setMinimumWidth(80)
        self.btn.toggled.connect(self._on_user_toggle)
        self._set_style(False)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(self.lbl, 0)
        lay.addStretch(1)
        lay.addWidget(self.btn, 0)

    def _on_user_toggle(self, on: bool) -> None:
        self.btn.setText("ON" if on else "OFF")
        self._set_style(on)
        try:
            self.backend.set_bool(self.state_channel, bool(on))
        except Exception:
            pass

    def _set_style(self, on: bool) -> None:
        self.btn.setStyleSheet("font-weight:bold; color:#060;" if on else "font-weight:bold; color:#a00;")

    def update_channel(self, name: str, value) -> None:
        if name != self.state_channel:
            return
        on = bool(value) if value is not None else False
        self.btn.blockSignals(True)
        try:
            self.btn.setChecked(on)
            self.btn.setText("ON" if on else "OFF")
            self._set_style(on)
        finally:
            self.btn.blockSignals(False)


class TwoColumnGroup(QGroupBox):
    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        self._left = QVBoxLayout()
        self._right = QVBoxLayout()
        self._left.setSpacing(6)
        self._right.setSpacing(6)

        outer = QHBoxLayout()
        outer.setSpacing(10)  # tighter than before
        outer.addLayout(self._left, 1)
        outer.addLayout(self._right, 1)
        self.setLayout(outer)

        self.setStyleSheet("""
            QGroupBox { font-size: 14px; font-weight: 700; }
            QLabel { font-size: 12px; }
        """)

        self._count = 0

    def add_widget(self, w: QWidget, column: Optional[int] = None) -> None:
        if column is None:
            column = 0 if (self._count % 2 == 0) else 1
        (self._left if column == 0 else self._right).addWidget(w)
        self._count += 1

    def add_stretch(self) -> None:
        self._left.addStretch(1)
        self._right.addStretch(1)