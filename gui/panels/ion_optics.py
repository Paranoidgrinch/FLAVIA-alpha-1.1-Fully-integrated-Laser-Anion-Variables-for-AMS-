from __future__ import annotations

from typing import Callable, List, Optional

from PyQt5.QtWidgets import QWidget, QVBoxLayout

from backend.channels import GROUPS, CHANNELS
from gui.qt_adapter import QtBackendAdapter
from .common import TwoColumnGroup, AnalogControl, AnalogBinding, ReadOnlyValue


def _pair_meas(set_ch: str) -> Optional[str]:
    if "/set_" in set_ch:
        return set_ch.replace("/set_", "/meas_", 1)
    if set_ch.endswith("/set_v"):
        return set_ch.replace("/set_v", "/meas_v", 1)
    if set_ch.endswith("/set_u"):
        return set_ch.replace("/set_u", "/meas_u", 1)
    return None


class IonOpticsPanel(QWidget):
    def __init__(self, backend, adapter: QtBackendAdapter, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.adapter = adapter

        self.group = TwoColumnGroup("Ion Optics")
        self._updaters: List[Callable[[str, object], None]] = []

        names = GROUPS.get("Ion Optics", [])
        for ch in names:
            cdef = CHANNELS.get(ch)
            if not cdef:
                continue

            if cdef.kind == "set":
                meas = _pair_meas(ch)
                w = AnalogControl(backend, AnalogBinding(set_ch=ch, meas_ch=meas))
                self.group.add_widget(w)
                self._updaters.append(w.update_channel)
                self.adapter.register_channel(ch)
                if meas:
                    self.adapter.register_channel(meas)

            elif cdef.kind == "meas":
                w = ReadOnlyValue(ch)
                self.group.add_widget(w)
                self._updaters.append(w.update_channel)
                self.adapter.register_channel(ch)

        self.group.add_stretch()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.group)

        self.adapter.channelUpdated.connect(self._on_update)

    def _on_update(self, name: str, value):
        for f in self._updaters:
            f(name, value)