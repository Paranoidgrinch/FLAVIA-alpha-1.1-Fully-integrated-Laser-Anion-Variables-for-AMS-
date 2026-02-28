# gui/panels/ion_source.py
from __future__ import annotations

from typing import Callable, List, Optional

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QGroupBox

from backend.channels import CHANNELS
from gui.qt_adapter import QtBackendAdapter
from .common import AnalogControl, AnalogBinding, ReadOnlyValue


def _pair_meas(set_ch: str) -> Optional[str]:
    if "/set_" in set_ch:
        return set_ch.replace("/set_", "/meas_", 1)
    if set_ch.endswith("/set_v"):
        return set_ch.replace("/set_v", "/meas_v", 1)
    if set_ch.endswith("/set_u"):
        return set_ch.replace("/set_u", "/meas_u", 1)
    return None


class IonSourcePanel(QWidget):
    """
    Compact single-column layout to reduce required width.
    Order (as requested):
      1) Sputter U Set (with Meas U)
      2) Oven I Set (with Meas I)
      3) Oven Temp
      4) Sputter I Meas
      5) Ionizer I Meas
    """
    def __init__(self, backend, adapter: QtBackendAdapter, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.adapter = adapter

        self._updaters: List[Callable[[str, object], None]] = []

        gb = QGroupBox("Ion Source")
        gb.setStyleSheet("""
            QGroupBox { font-size: 14px; font-weight: 700; }
            QLabel { font-size: 12px; }
        """)
        v = QVBoxLayout(gb)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        def add_set(ch_set: str):
            cdef = CHANNELS.get(ch_set)
            if not cdef:
                return
            meas = _pair_meas(ch_set)
            w = AnalogControl(self.backend, AnalogBinding(set_ch=ch_set, meas_ch=meas))
            v.addWidget(w)
            self._updaters.append(w.update_channel)
            self.adapter.register_channel(ch_set)
            if meas:
                self.adapter.register_channel(meas)

        def add_meas(ch_meas: str):
            cdef = CHANNELS.get(ch_meas)
            if not cdef:
                return
            w = ReadOnlyValue(ch_meas)
            v.addWidget(w)
            self._updaters.append(w.update_channel)
            self.adapter.register_channel(ch_meas)

        # 1) Sputter U set (+ meas)
        add_set("cs/sputter/set_u_v")

        # 2) Oven I set (+ meas)
        add_set("cs/oven/set_i_a")

        # 3) Oven temp
        add_meas("cs/oven/temp_c")

        # 4) Sputter I meas
        add_meas("cs/sputter/meas_i_mA")

        # 5) Ionizer I meas
        add_meas("cs/ionizer/meas_i_a")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(gb)

        self.adapter.channelUpdated.connect(self._on_update)

    def _on_update(self, name: str, value):
        for f in self._updaters:
            f(name, value)