from __future__ import annotations

from typing import Callable, Dict, List

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QDoubleSpinBox,
)

from backend.legacy_definitions import (
    HEE_ESA_READBACKS,
    LEGACY_ANALOG_BY_GROUP,
    LEGACY_ANALOG_BY_SET,
)
from gui.legacy_safety import ACC_TERMINAL_CHANNEL, confirm_terminal_voltage_change
from gui.qt_adapter import QtBackendAdapter
from gui.widgets import StepSliderControl
from .common import AnalogBinding, AnalogControl, TwoColumnGroup


class _TerminalVoltageControl(AnalogControl):
    def _on_user_send(self, value: float) -> None:
        self._update_calibration(value)
        if not confirm_terminal_voltage_change(self, self.backend, float(value)):
            current = self.backend.model.get(self.binding.set_ch)
            try:
                if current is not None and current.value is not None:
                    self.slider.set_real_value(float(current.value), emit=False)
            except Exception:
                pass
            return
        try:
            self.backend.set_channel(self.binding.set_ch, float(value))
        except Exception:
            pass


class _BIMagnetControl(QWidget):
    """BI magnet standard slider plus two persistent direct-send values."""
    def __init__(self, backend, set_ch: str, meas_ch: str, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.set_ch = set_ch
        self.meas_ch = meas_ch
        definition = LEGACY_ANALOG_BY_SET[set_ch]

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        self.analog = AnalogControl(
            backend,
            AnalogBinding(set_ch=set_ch, meas_ch=meas_ch),
            label="BI Magnet",
        )
        outer.addWidget(self.analog)

        direct = QHBoxLayout()
        direct.setContentsMargins(170, 0, 0, 0)
        direct.setSpacing(6)
        self.inputs: List[QDoubleSpinBox] = []
        for idx in range(2):
            spin = QDoubleSpinBox()
            spin.setRange(definition.min_val, definition.max_val)
            spin.setDecimals(3)
            spin.setSingleStep(0.1)
            spin.setSuffix(" A")
            spin.setKeyboardTracking(False)
            btn = QPushButton(f"Send {idx + 1}")
            btn.clicked.connect(lambda _checked=False, s=spin: self._send_direct(s.value()))
            self.inputs.append(spin)
            direct.addWidget(spin)
            direct.addWidget(btn)
        direct.addStretch(1)
        outer.addLayout(direct)

    def _send_direct(self, value: float) -> None:
        try:
            self.backend.set_channel(self.set_ch, float(value))
        except Exception:
            pass

    def update_channel(self, name: str, value) -> None:
        self.analog.update_channel(name, value)


class _HEEESAControl(QWidget):
    """One common 0..100 % control with four plate-voltage readbacks."""
    def __init__(self, backend, set_ch: str, parent=None):
        super().__init__(parent)
        self.backend = backend
        definition = LEGACY_ANALOG_BY_SET[set_ch]

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(3)

        label = QLabel(definition.label)
        label.setMinimumWidth(170)
        layout.addWidget(label, 0, 0)

        multiplier = 10 ** max(0, definition.decimals)
        self.slider = StepSliderControl(
            definition.min_val,
            definition.max_val,
            multiplier,
            definition.unit,
            default_step=definition.default_step,
            decimals=definition.decimals,
        )
        self.slider.valueChangedFloat.connect(self._send)
        layout.addWidget(self.slider, 0, 1, 1, 3)

        self.readback_labels: Dict[str, QLabel] = {}
        for i, (plate_label, channel, _board, _input) in enumerate(HEE_ESA_READBACKS):
            prefix = QLabel(f"{plate_label}:")
            prefix.setStyleSheet("font-weight:800;")
            value = QLabel("—")
            value.setStyleSheet("font-weight:800;")
            value.setMinimumWidth(80)
            row = 1 + (i // 2)
            col = 1 + (i % 2) * 2
            layout.addWidget(prefix, row, col)
            layout.addWidget(value, row, col + 1)
            self.readback_labels[channel] = value

    def _send(self, value: float) -> None:
        try:
            self.backend.set_channel("legacy/hee/esa_common/set_pct", float(value))
        except Exception:
            pass

    def update_channel(self, name: str, value) -> None:
        if name == "legacy/hee/esa_common/set_pct":
            try:
                self.slider.set_real_value(float(value), emit=False)
            except Exception:
                pass
            return
        label = self.readback_labels.get(name)
        if label is None:
            return
        if value is None or value == "":
            label.setText("—")
            return
        try:
            label.setText(f"{float(value):.2f} kV")
        except Exception:
            label.setText(str(value))


class LegacyBeamlineControlsPanel(QWidget):
    """The six legacy analog-control groups using the normal FLAVIA style."""
    GROUP_ORDER = (
        "BI Controls", "ACC Controls", "HES Controls",
        "HEM Controls", "HEE Controls", "DSW Controls",
    )

    def __init__(self, backend, adapter: QtBackendAdapter, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.adapter = adapter
        self._updaters: List[Callable[[str, object], None]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        for group_name in self.GROUP_ORDER:
            group = TwoColumnGroup(group_name, fill_mode="left_only")
            for definition in LEGACY_ANALOG_BY_GROUP[group_name]:
                if definition.key == "bi_magnet":
                    widget = _BIMagnetControl(backend, definition.set_channel, definition.meas_channel)
                elif definition.set_channel == ACC_TERMINAL_CHANNEL:
                    widget = _TerminalVoltageControl(
                        backend,
                        AnalogBinding(definition.set_channel, definition.meas_channel),
                        label=definition.label,
                    )
                elif definition.key == "hee_esa_common":
                    widget = _HEEESAControl(backend, definition.set_channel)
                else:
                    widget = AnalogControl(
                        backend,
                        AnalogBinding(definition.set_channel, definition.meas_channel),
                        label=definition.label,
                    )

                group.add_widget(widget)
                self._updaters.append(widget.update_channel)
                self.adapter.register_channel(definition.set_channel)
                self.adapter.register_channel(definition.meas_channel)

                if definition.key == "hee_esa_common":
                    for _plate, channel, _board, _input in HEE_ESA_READBACKS:
                        self.adapter.register_channel(channel)

            group.add_stretch()
            root.addWidget(group)

        self.adapter.channelUpdated.connect(self._on_update)

    def _on_update(self, name: str, value) -> None:
        for updater in self._updaters:
            updater(name, value)
