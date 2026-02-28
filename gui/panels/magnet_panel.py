# gui/panels/magnet_panel.py
from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QWidget, QGroupBox, QGridLayout, QLabel,
    QDoubleSpinBox, QPushButton, QVBoxLayout
)

from gui.widgets.step_slider import StepSliderControl


class MagnetPanel(QWidget):
    """
    Magnet GUI with StepSliderControl (same behavior as other sliders):
      - Set value shown on the LEFT inside the slider control (bold)
      - Meas value shown on the RIGHT (bold)

    Rows:
      1) Current set via StepSliderControl, right side: Current meas (bold)
      2) Direct input 1 + send confirmation, right side: Voltage meas (bold)
      3) Direct input 2 + send confirmation, right side: Field meas (bold)
    """

    MAX_A = 120.0

    def __init__(self, backend, adapter, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.adapter = adapter

        self._sending = False
        self._pending_set: Optional[float] = None
        self._send_timer = QTimer(self)
        self._send_timer.setSingleShot(True)
        self._send_timer.timeout.connect(self._flush_pending_send)
        self._set_seen = False
        self._initialized_from_meas = True

        gb = QGroupBox("Magnet")
        gb.setStyleSheet("""
            QGroupBox { font-size: 14px; font-weight: 700; }
            QLabel { font-size: 12px; }
        """)

        grid = QGridLayout()
        grid.setContentsMargins(8, 6, 8, 6)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        # Status (top right)
        self.lbl_status = QLabel("Magnet: DISCONNECTED")
        self.lbl_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_status.setStyleSheet("color:#a00; font-weight:800;")
        grid.addWidget(self.lbl_status, 0, 0, 1, 6)

        # --- Row 1: main current control ---
        r = 1
        grid.addWidget(QLabel("Current:"), r, 0)

        # StepSliderControl: 0..120 A, 0.001 A ticks, user steps selectable
        decimals = 3
        multiplier = 10 ** decimals  # 1000
        self.ctrl = StepSliderControl(
            0.0, self.MAX_A, multiplier, "A",
            default_step=0.1,
            decimals=decimals,
        )
        self.ctrl.valueChangedFloat.connect(self._on_set_changed)
        grid.addWidget(self.ctrl, r, 1, 1, 3)

        grid.addWidget(QLabel("Meas:"), r, 4)
        self.lbl_meas_current = QLabel("— A")
        self.lbl_meas_current.setStyleSheet("font-weight:800;")
        self.lbl_meas_current.setMinimumWidth(95)
        grid.addWidget(self.lbl_meas_current, r, 5)

        # --- Row 2: direct input 1 + Voltage meas ---
        r += 1
        grid.addWidget(QLabel("Direct input 1:"), r, 0)

        self.in1 = QDoubleSpinBox()
        self.in1.setRange(0.0, self.MAX_A)
        self.in1.setDecimals(4)
        self.in1.setSingleStep(0.1)
        self.in1.setSuffix(" A")
        self.in1.setKeyboardTracking(False)
        grid.addWidget(self.in1, r, 1)

        self.btn_send1 = QPushButton("Send")
        self.btn_send1.clicked.connect(lambda: self._send_direct(self.in1.value(), which=1))
        grid.addWidget(self.btn_send1, r, 2)

        self.lbl_sent1 = QLabel("")
        self.lbl_sent1.setMinimumWidth(60)
        grid.addWidget(self.lbl_sent1, r, 3)

        lbl_v = QLabel("Voltage meas:")
        lbl_v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(lbl_v, r, 4)

        self.lbl_meas_voltage = QLabel("— V")
        self.lbl_meas_voltage.setStyleSheet("font-weight:800;")
        self.lbl_meas_voltage.setMinimumWidth(95)
        grid.addWidget(self.lbl_meas_voltage, r, 5)

        # --- Row 3: direct input 2 + Field meas ---
        r += 1
        grid.addWidget(QLabel("Direct input 2:"), r, 0)

        self.in2 = QDoubleSpinBox()
        self.in2.setRange(0.0, self.MAX_A)
        self.in2.setDecimals(4)
        self.in2.setSingleStep(0.1)
        self.in2.setSuffix(" A")
        self.in2.setKeyboardTracking(False)
        grid.addWidget(self.in2, r, 1)

        self.btn_send2 = QPushButton("Send")
        self.btn_send2.clicked.connect(lambda: self._send_direct(self.in2.value(), which=2))
        grid.addWidget(self.btn_send2, r, 2)

        self.lbl_sent2 = QLabel("")
        self.lbl_sent2.setMinimumWidth(60)
        grid.addWidget(self.lbl_sent2, r, 3)

        lbl_b = QLabel("Magnetic field meas:")
        lbl_b.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(lbl_b, r, 4)

        self.lbl_meas_field = QLabel("— kG")
        self.lbl_meas_field.setStyleSheet("font-weight:800;")
        self.lbl_meas_field.setMinimumWidth(95)
        grid.addWidget(self.lbl_meas_field, r, 5)

        gb.setLayout(grid)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(gb)

        # Subscribe channels
        self.adapter.channelUpdated.connect(self._on_update)
        for ch in [
            "magnet_connected",
            "gaussmeter_connected",
            "magnet_current_set",
            "magnet_current_meas",
            "magnet_voltage_meas",
            "magnet_field_meas",
        ]:
            self.adapter.register_channel(ch)

            QTimer.singleShot(0, self._refresh_status)


    def _refresh_status(self) -> None:
        m_ch = self.backend.model.get("magnet_connected")
        g_ch = self.backend.model.get("gaussmeter_connected")

        m_ok = bool(m_ch.value) if (m_ch and m_ch.value is not None) else False
        g_ok = bool(g_ch.value) if (g_ch and g_ch.value is not None) else False

        if m_ok and g_ok:
            self.lbl_status.setText("Magnet: CONNECTED | Gauss: CONNECTED")
            self.lbl_status.setStyleSheet("color:#060; font-weight:800;")
        elif m_ok and not g_ok:
            self.lbl_status.setText("Magnet: CONNECTED | Gauss: DISCONNECTED")
            self.lbl_status.setStyleSheet("color:#a60; font-weight:800;")
        else:
            self.lbl_status.setText("Magnet: DISCONNECTED")
            self.lbl_status.setStyleSheet("color:#a00; font-weight:800;")

    # ------------------------
    # Backend command helper
    # ------------------------
    def _set_current(self, value_A: float) -> None:
        v = float(value_A)
        if v < 0.0:
            v = 0.0
        if v > self.MAX_A:
            v = self.MAX_A

        if hasattr(self.backend, "set_magnet_current"):
            self.backend.set_magnet_current(v)
            return
        if hasattr(self.backend, "magnet") and hasattr(self.backend.magnet, "set_current"):
            self.backend.magnet.set_current(v)
            return

        raise AttributeError(
            "No magnet set-current API found in backend (expected set_magnet_current or backend.magnet.set_current)."
        )

    # ------------------------
    # UI events
    # ------------------------
    def _on_set_changed(self, value_A: float) -> None:
        """
        StepSliderControl emits very frequently while sliding.
        We debounce sends to avoid hammering the PSU.
        """
        self._pending_set = float(value_A)
        if not self._send_timer.isActive():
            self._send_timer.start(120)  # 120 ms debounce

    def _flush_pending_send(self) -> None:
        if self._pending_set is None:
            return
        v = self._pending_set
        self._pending_set = None
        try:
            self._set_current(v)
        except Exception:
            pass

    def _send_direct(self, value_A: float, *, which: int) -> None:
        try:
            self._set_current(float(value_A))
        except Exception:
            return

        lbl = self.lbl_sent1 if which == 1 else self.lbl_sent2
        lbl.setStyleSheet("color:#060; font-weight:800;")
        lbl.setText("Sent ✓")
        QTimer.singleShot(900, lambda: lbl.setText(""))


    def _refresh_status(self) -> None:
        m_ch = self.backend.model.get("magnet_connected")
        g_ch = self.backend.model.get("gaussmeter_connected")

        m_ok = bool(m_ch.value) if (m_ch and m_ch.value is not None) else False
        g_ok = bool(g_ch.value) if (g_ch and g_ch.value is not None) else False

        if m_ok and g_ok:
            self.lbl_status.setText("Magnet: CONNECTED | Gauss: CONNECTED")
            self.lbl_status.setStyleSheet("color:#060; font-weight:800;")
        elif m_ok and not g_ok:
            self.lbl_status.setText("Magnet: CONNECTED | Gauss: DISCONNECTED")
            self.lbl_status.setStyleSheet("color:#a60; font-weight:800;")
        else:
            self.lbl_status.setText("Magnet: DISCONNECTED")
            self.lbl_status.setStyleSheet("color:#a00; font-weight:800;")

    # ------------------------
    # Model updates
    # ------------------------
    def _on_update(self, name: str, value):

        # --- Status updates ---
        if name in ("magnet_connected", "gaussmeter_connected"):
            self._refresh_status()
            return

        # --- Set current (authoritative) ---
        if name == "magnet_current_set":
            try:
                v = float(value)
            except Exception:
                return

            self._set_seen = True  # ab jetzt gilt Set als “authoritative”
            try:
                self.ctrl.set_real_value(v, emit=False)
            except Exception:
                pass
            return

        # --- Measured current (used for startup init) ---
        if name == "magnet_current_meas":
            try:
                v = float(value)
                self.lbl_meas_current.setText(f"{v:.3f} A")
            except Exception:
                self.lbl_meas_current.setText("— A")
                return

            # beim Start Slider aus Meas initialisieren (nur einmal),
            # solange noch kein Set-Wert kam
            if (not self._set_seen) and (not self._initialized_from_meas):
                try:
                    self.ctrl.set_real_value(v, emit=False)
                except Exception:
                    pass
                self._initialized_from_meas = True

            return

        if name == "magnet_voltage_meas":
            try:
                v = float(value)
                self.lbl_meas_voltage.setText(f"{v:.3f} V")
            except Exception:
                self.lbl_meas_voltage.setText("— V")
            return

        if name == "magnet_field_meas":
            try:
                v = float(value)
                self.lbl_meas_field.setText(f"{v:.4f} kG")
            except Exception:
                self.lbl_meas_field.setText("— kG")
            return