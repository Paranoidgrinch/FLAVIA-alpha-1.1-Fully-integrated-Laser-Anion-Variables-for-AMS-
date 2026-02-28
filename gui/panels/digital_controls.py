# gui/panels/digital_controls.py
from __future__ import annotations

from typing import Callable, List

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QGridLayout, QHBoxLayout,
    QLabel, QPushButton, QCheckBox, QDialog
)

from gui.qt_adapter import QtBackendAdapter


class HVDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("HV Bias Voltage")
        self.setModal(True)
        self._pending = None  # "on" / "off"

        title = QLabel("High Voltage (Bias) Control")
        f = QFont()
        f.setPointSize(12)
        f.setBold(True)
        title.setFont(f)

        self.info = QLabel("⚠️ HV switching requires confirmation.")
        self.info.setWordWrap(True)

        self.btn_on = QPushButton("Turn HV ON")
        self.btn_off = QPushButton("Turn HV OFF")
        self.btn_close = QPushButton("Close")

        self.btn_on.clicked.connect(lambda: self._arm("on"))
        self.btn_off.clicked.connect(lambda: self._arm("off"))
        self.btn_close.clicked.connect(self.reject)

        self.confirm = QLabel("")
        self.confirm.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addWidget(title)
        layout.addWidget(self.info)
        layout.addSpacing(8)
        layout.addWidget(self.btn_on)
        layout.addWidget(self.btn_off)
        layout.addSpacing(8)
        layout.addWidget(self.confirm)
        layout.addStretch(1)
        layout.addWidget(self.btn_close)
        self.setLayout(layout)

    def _arm(self, action: str):
        if self._pending == action:
            self.accept()
            return
        self._pending = action
        self.confirm.setText(
            "Confirm HV ON by pressing 'Turn HV ON' again." if action == "on"
            else "Confirm HV OFF by pressing 'Turn HV OFF' again."
        )

    def pending_action(self):
        return self._pending


class DigitalControlsPanel(QWidget):
    """
    Cup Switching + Attenuator + Quick Cool integrated (very compact).
    """
    def __init__(self, backend, adapter: QtBackendAdapter, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.adapter = adapter

        self._updaters: List[Callable[[str, object], None]] = []
        self._updating_from_status = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        cup_group = QGroupBox("Cup Switching")
        cup_group.setStyleSheet("""
            QGroupBox { font-size: 14px; font-weight: 700; }
            QLabel { font-size: 12px; }
            QCheckBox { margin: 0px; padding: 0px; spacing: 3px; }
            QCheckBox::indicator { width: 13px; height: 13px; }
        """)
        cup_v = QVBoxLayout(cup_group)
        cup_v.setContentsMargins(8, 8, 8, 8)
        cup_v.setSpacing(4)

        # top compact row: HV + All OFF + Attenuator + QuickCool + status
        top = QHBoxLayout()
        top.setSpacing(8)

        self.btn_hv = QPushButton("HV…")
        self.btn_hv.setFixedWidth(70)
        self.btn_hv.clicked.connect(self._open_hv_dialog)

        self.btn_all_off = QPushButton("All OFF")
        self.btn_all_off.setFixedWidth(90)
        self.btn_all_off.clicked.connect(lambda: self._set_cup(0))

        self.cb_att = QCheckBox("Attenuator")
        self.cb_qc = QCheckBox("Quick Cool")
        self.cb_att.toggled.connect(lambda on: self._publish_bool("cs/attenuator/state", on))
        self.cb_qc.toggled.connect(lambda on: self._publish_bool("cs/quick_cool/state", on))

        self.lbl_status = QLabel("Status: —")
        self.lbl_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        top.addWidget(self.btn_hv)
        top.addWidget(self.btn_all_off)
        top.addWidget(self.cb_att)
        top.addWidget(self.cb_qc)
        top.addStretch(1)
        top.addWidget(self.lbl_status)
        cup_v.addLayout(top)

        # cup checkboxes ultra-compact grid
        grid = QGridLayout()
        grid.setHorizontalSpacing(2)  # tighter
        grid.setVerticalSpacing(0)    # tighter
        grid.setContentsMargins(0, 0, 0, 0)

        self.cup_boxes: List[QCheckBox] = []
        for i in range(8):
            cb = QCheckBox(f"Cup {i+1}")
            cb.setStyleSheet("margin:0px; padding:0px; spacing:2px;")
            cb.stateChanged.connect(lambda state, idx=i: self._on_cup_checkbox(idx, state))
            self.cup_boxes.append(cb)
            grid.addWidget(cb, i // 4, i % 4)

        cup_v.addLayout(grid)
        lay.addWidget(cup_group)

        # subscribe
        self.adapter.channelUpdated.connect(self._on_update)
        for ch in ["cup/connected", "cup/selected", "cup/hv", "cs/attenuator/state", "cs/quick_cool/state"]:
            self.adapter.register_channel(ch)

    def _publish_bool(self, channel: str, on: bool):
        if self._updating_from_status:
            return
        try:
            self.backend.set_bool(channel, bool(on))
        except Exception:
            pass

    def _open_hv_dialog(self):
        dlg = HVDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            action = dlg.pending_action()
            if action == "on":
                self.backend.cup.hv_on()
            elif action == "off":
                self.backend.cup.hv_off()

    def _set_checkboxes_from_status(self, selected_cup: int):
        self._updating_from_status = True
        try:
            for i, cb in enumerate(self.cup_boxes, start=1):
                cb.blockSignals(True)
                cb.setChecked(selected_cup == i)
                cb.blockSignals(False)
        finally:
            self._updating_from_status = False

    def _on_cup_checkbox(self, idx0: int, state: int):
        if self._updating_from_status:
            return
        cup = idx0 + 1
        checked = (state == Qt.Checked)
        if checked:
            for j, cb in enumerate(self.cup_boxes):
                if j != idx0:
                    cb.blockSignals(True)
                    cb.setChecked(False)
                    cb.blockSignals(False)
            self._set_cup(cup)
        else:
            if not any(cb.isChecked() for cb in self.cup_boxes):
                self._set_cup(0)

    def _set_cup(self, cup: int):
        self.backend.cup.select_cup(int(cup))

    def _on_update(self, name: str, value):
        # update integrated user-digitals
        if name == "cs/attenuator/state":
            self._updating_from_status = True
            try:
                self.cb_att.blockSignals(True)
                self.cb_att.setChecked(bool(value))
            finally:
                self.cb_att.blockSignals(False)
                self._updating_from_status = False

        if name == "cs/quick_cool/state":
            self._updating_from_status = True
            try:
                self.cb_qc.blockSignals(True)
                self.cb_qc.setChecked(bool(value))
            finally:
                self.cb_qc.blockSignals(False)
                self._updating_from_status = False

        connected = self.backend.model.get("cup/connected")
        selected = self.backend.model.get("cup/selected")
        hv = self.backend.model.get("cup/hv")

        c_ok = bool(connected.value) if connected and connected.value is not None else False
        cup = int(selected.value) if selected and selected.value is not None else None
        hv_s = str(hv.value) if hv and hv.value is not None else None

        if name == "cup/selected" and cup is not None:
            self._set_checkboxes_from_status(cup)

        self.lbl_status.setText(
            f"{'OK' if c_ok else 'DISCONNECTED'}  "
            f"Cup={cup if cup is not None else '—'}  "
            f"HV={hv_s if hv_s else '—'}"
        )