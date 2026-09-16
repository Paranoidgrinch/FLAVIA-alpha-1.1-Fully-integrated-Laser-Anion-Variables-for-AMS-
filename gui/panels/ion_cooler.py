from __future__ import annotations

from typing import Callable, List, Optional

from PyQt5.QtWidgets import QWidget, QVBoxLayout

from backend.channels import CHANNELS
from gui.qt_adapter import QtBackendAdapter
from .common import TwoColumnGroup, AnalogControl, AnalogBinding, ReadOnlyValue
from backend.voltage_calibration import expected_entry_energy_ev


def _pair_meas(set_ch: str) -> Optional[str]:
    if "/set_" in set_ch:
        return set_ch.replace("/set_", "/meas_", 1)
    if set_ch.endswith("/set_v"):
        return set_ch.replace("/set_v", "/meas_v", 1)
    if set_ch.endswith("/set_u"):
        return set_ch.replace("/set_u", "/meas_u", 1)
    return None


class IonCoolerPanel(QWidget):
    def __init__(self, backend, adapter: QtBackendAdapter, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.adapter = adapter

        self.group = TwoColumnGroup("Ion Cooler", fill_mode="left_only")
        self._updaters: List[Callable[[str, object], None]] = []
        self._entry_channels = (
            "cs/extraction/set_u_v",
            "cs/sputter/set_u_v",
            "cs/ion_cooler/set_u_v",
        )
        self._entry_values = {name: None for name in self._entry_channels}
        self._ion_cooler_control = None

        entries = [
            ("cs/ion_cooler/set_u_v", "Ion Cooler"),
            ("hv/1/set_v", "Deceleration Electrode (HV1)"),
            ("hv/4/set_v", "Acceleration Electrode (HV4)"),
            ("hv/2/set_v", "Entry Focus Electrode (HV2)"),
            ("hv/3/set_v", "Exit Focus Electrode (HV3)"),
            ("psu/1/set_v", "Guidefield1 (PSU1)"),
            ("psu/2/set_v", "Guidefield2 (PSU2)"),
        ]

        for ch, label in entries:
            cdef = CHANNELS.get(ch)
            if not cdef:
                continue

            if cdef.kind == "set":
                meas = _pair_meas(ch)
                is_ion_cooler = ch == "cs/ion_cooler/set_u_v"
                w = AnalogControl(
                    backend,
                    AnalogBinding(set_ch=ch, meas_ch=meas),
                    label=label,
                    show_calibration=is_ion_cooler,
                    aux_label=("Expected Entry Energy: — eV" if is_ion_cooler else None),
                )
                if is_ion_cooler:
                    self._ion_cooler_control = w
                    w.slider.valueChangedFloat.connect(
                        lambda value, name=ch: self._on_entry_setpoint(name, value)
                    )
                self.group.add_widget(w)
                self._updaters.append(w.update_channel)
                self.adapter.register_channel(ch)
                if meas:
                    self.adapter.register_channel(meas)

            elif cdef.kind == "meas":
                w = ReadOnlyValue(ch, label=label)
                self.group.add_widget(w)
                self._updaters.append(w.update_channel)
                self.adapter.register_channel(ch)

        for name in self._entry_channels:
            self.adapter.register_channel(name)
            ch = self.backend.model.get(name)
            if ch is not None and ch.value is not None:
                try:
                    self._entry_values[name] = float(ch.value)
                except Exception:
                    pass

        self._refresh_entry_energy()
        self.group.add_stretch()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.group)

        self.adapter.channelUpdated.connect(self._on_update)

    def _on_entry_setpoint(self, name: str, value) -> None:
        try:
            self._entry_values[name] = float(value)
        except Exception:
            self._entry_values[name] = None
        self._refresh_entry_energy()

    def _refresh_entry_energy(self) -> None:
        if self._ion_cooler_control is None:
            return
        if any(self._entry_values[name] is None for name in self._entry_channels):
            self._ion_cooler_control.set_aux_text("Expected Entry Energy: — eV")
            return
        try:
            energy_ev = expected_entry_energy_ev(
                self._entry_values["cs/extraction/set_u_v"],
                self._entry_values["cs/sputter/set_u_v"],
                self._entry_values["cs/ion_cooler/set_u_v"],
            )
            self._ion_cooler_control.set_aux_text(
                f"Expected Entry Energy: {energy_ev:.1f} eV"
            )
        except Exception:
            self._ion_cooler_control.set_aux_text("Expected Entry Energy: — eV")

    def _on_update(self, name: str, value):
        if name in self._entry_values:
            self._on_entry_setpoint(name, value)
        for f in self._updaters:
            f(name, value)