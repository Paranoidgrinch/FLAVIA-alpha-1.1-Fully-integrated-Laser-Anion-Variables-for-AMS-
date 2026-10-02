from __future__ import annotations

from typing import Dict

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QGridLayout, QLabel, QComboBox, QCheckBox,
)

from backend.legacy_definitions import LEGACY_CURRENT_DEVICES
from gui.qt_adapter import QtBackendAdapter
from .keithley_panel import format_current_auto


class LegacyCurrentMeasurementsPanel(QWidget):
    """Current Converter 1/2 and GCPD 1/2 controls below the Keithley."""
    def __init__(self, backend, adapter: QtBackendAdapter, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.adapter = adapter
        self._ui: Dict[str, dict] = {}
        self._updating = False

        gb = QGroupBox("Additional Current Measurements")
        gb.setStyleSheet("QGroupBox { font-size: 14px; font-weight: 700; } QLabel { font-size: 12px; }")
        grid = QGridLayout(gb)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(5)

        grid.addWidget(QLabel("Device"), 0, 0)
        grid.addWidget(QLabel("Current"), 0, 1)
        grid.addWidget(QLabel("Range"), 0, 2)
        grid.addWidget(QLabel("Auto"), 0, 3)
        grid.addWidget(QLabel("Status"), 0, 4)

        for row, dev in enumerate(LEGACY_CURRENT_DEVICES, start=1):
            lbl_name = QLabel(dev.label)
            lbl_current = QLabel("—")
            lbl_current.setStyleSheet("font-weight:800;")
            cb_range = QComboBox()
            for idx, text in enumerate(dev.range_labels):
                cb_range.addItem(text, idx)
            cb_range.setCurrentIndex(-1)
            cb_auto = QCheckBox()
            cb_auto.setVisible(dev.autorange_channel is not None)
            lbl_status = QLabel("—")

            grid.addWidget(lbl_name, row, 0)
            grid.addWidget(lbl_current, row, 1)
            grid.addWidget(cb_range, row, 2)
            grid.addWidget(cb_auto, row, 3)
            grid.addWidget(lbl_status, row, 4)

            self._ui[dev.key] = {
                "current": lbl_current, "range": cb_range,
                "auto": cb_auto, "status": lbl_status,
            }
            cb_range.currentIndexChanged.connect(
                lambda idx, key=dev.key: self._range_changed(key, idx)
            )
            if dev.autorange_channel:
                cb_auto.toggled.connect(
                    lambda on, key=dev.key: self._autorange_changed(key, on)
                )

            for ch in (dev.current_channel, dev.range_channel, dev.overload_channel):
                self.adapter.register_channel(ch)
            if dev.autorange_channel:
                self.adapter.register_channel(dev.autorange_channel)
            if dev.negative_channel:
                self.adapter.register_channel(dev.negative_channel)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(gb)
        self.adapter.channelUpdated.connect(self._on_update)

    def _device(self, key):
        for dev in LEGACY_CURRENT_DEVICES:
            if dev.key == key:
                return dev
        return None

    def _range_changed(self, key: str, idx: int) -> None:
        if self._updating or idx < 0:
            return
        try:
            if key.startswith("cc"):
                self.backend.set_legacy_current_converter_range(int(key[-1]) - 1, int(idx))
            else:
                self.backend.set_legacy_gcpd_range(int(key[-1]) - 1, int(idx))
        except NotImplementedError:
            pass
        except Exception:
            pass

    def _autorange_changed(self, key: str, on: bool) -> None:
        if self._updating:
            return
        try:
            self.backend.set_legacy_current_converter_autorange(int(key[-1]) - 1, bool(on))
        except NotImplementedError:
            pass
        except Exception:
            pass

    def _on_update(self, name: str, value) -> None:
        for dev in LEGACY_CURRENT_DEVICES:
            ui = self._ui[dev.key]
            if name == dev.current_channel:
                if value is None or value == "":
                    ui["current"].setText("—")
                else:
                    try:
                        text, unit = format_current_auto(float(value), decimals=3)
                        ui["current"].setText(f"{text} {unit}")
                    except Exception:
                        ui["current"].setText("—")
                return
            if name == dev.range_channel:
                try:
                    idx = int(value)
                except Exception:
                    return
                if 0 <= idx < ui["range"].count():
                    self._updating = True
                    try:
                        ui["range"].setCurrentIndex(idx)
                    finally:
                        self._updating = False
                return
            if dev.autorange_channel and name == dev.autorange_channel:
                self._updating = True
                try:
                    ui["auto"].setChecked(bool(value))
                    ui["range"].setEnabled(not bool(value))
                finally:
                    self._updating = False
                return
            if name == dev.overload_channel:
                overload = bool(value)
                ui["status"].setText("OVERLOAD" if overload else "OK")
                ui["status"].setStyleSheet(
                    "color:#a00; font-weight:800;" if overload else "color:#060; font-weight:800;"
                )
                return
