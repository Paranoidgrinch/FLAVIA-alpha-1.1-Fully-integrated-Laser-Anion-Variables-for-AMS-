from __future__ import annotations

from typing import Callable, List, Optional

from PyQt5.QtWidgets import QWidget, QVBoxLayout

from backend.channels import CHANNELS
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


class _BaseIonOpticsPanel(QWidget):
    GROUP_TITLE = "Ion Optics"
    ENTRIES: list[tuple[str, str]] = []

    def __init__(self, backend, adapter: QtBackendAdapter, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.adapter = adapter

        self.group = TwoColumnGroup(self.GROUP_TITLE, fill_mode="left_only")
        self._updaters: List[Callable[[str, object], None]] = []

        for ch, label in self.ENTRIES:
            cdef = CHANNELS.get(ch)
            if not cdef:
                continue

            if cdef.kind == "set":
                meas = _pair_meas(ch)
                w = AnalogControl(backend, AnalogBinding(set_ch=ch, meas_ch=meas), label=label)
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

        self.group.add_stretch()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.group)

        self.adapter.channelUpdated.connect(self._on_update)

    def _on_update(self, name: str, value):
        for f in self._updaters:
            f(name, value)


class PreCoolerIonOpticsPanel(_BaseIonOpticsPanel):
    GROUP_TITLE = "Pre-Cooler Ion Optics"
    ENTRIES = [
        ("cs/extraction/set_u_v", "Extraction"),
        ("cs/einzellens/set_u_v", "Einzellens"),
        ("cs/lens2/set_u_v", "Lens 2"),
        ("steerer/1x/set_u", "Steerer X1"),
        ("steerer/1y/set_u", "Steerer Y1"),
    ]


class PostCoolerIonOpticsPanel(_BaseIonOpticsPanel):
    GROUP_TITLE = "Post-Cooler Ion Optics"
    ENTRIES = [
        ("cs/qp1/set_u_v", "Quadrupole Triplet 1"),
        ("cs/qp2/set_u_v", "Quadrupole Triplet 2"),
        ("cs/qp3/set_u_v", "Quadrupole Triplet 3"),
        ("steerer/2x/set_u", "Steerer X2"),
        ("steerer/2y/set_u", "Steerer Y2"),
    ]


class ESAIonOpticsPanel(_BaseIonOpticsPanel):
    GROUP_TITLE = "ESA Ion Optics"
    ENTRIES = [
        ("cs/esa/set_u_v", "ESA"),
        ("steerer/3x/set_u", "Steerer X3"),
        ("steerer/3y/set_u", "Steerer Y3"),
        ("cs/lens4/set_u_v", "Lens 4"),
    ]