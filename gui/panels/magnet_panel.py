# gui/panels/magnet_panel.py
from __future__ import annotations

import math
from typing import Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QWidget,
    QGroupBox,
    QGridLayout,
    QLabel,
    QDoubleSpinBox,
    QPushButton,
    QVBoxLayout,
    QDialog,
)

from gui.widgets.step_slider import StepSliderControl


class MagnetCalculatorDialog(QDialog):
    """
    Popup dialog for calculating the required magnet current from:
      - ion mass [u]
      - extraction voltage [V]
      - sputter voltage [V]

    Uses the same formula that existed in the old mainwindow magnet calculator.
    """

    MAX_A = 120.0

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self._last_current_a = 0.0

        self.setWindowTitle("Magnet Calculator")
        self.setModal(False)
        self.setMinimumWidth(460)

        layout = QGridLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(8)

        # Inputs
        self.mass_input = QDoubleSpinBox()
        self.mass_input.setRange(1.0, 500.0)
        self.mass_input.setDecimals(3)
        self.mass_input.setSingleStep(1.0)
        self.mass_input.setSuffix(" u")
        self.mass_input.setValue(1.0)
        self.mass_input.setKeyboardTracking(False)
        self.mass_input.valueChanged.connect(self.update_calculations)

        self.extraction_input = QDoubleSpinBox()
        self.extraction_input.setRange(0.0, 100000.0)
        self.extraction_input.setDecimals(1)
        self.extraction_input.setSingleStep(100.0)
        self.extraction_input.setSuffix(" V")
        self.extraction_input.setValue(1000.0)
        self.extraction_input.setKeyboardTracking(False)
        self.extraction_input.valueChanged.connect(self.update_calculations)

        self.sputter_input = QDoubleSpinBox()
        self.sputter_input.setRange(0.0, 100000.0)
        self.sputter_input.setDecimals(1)
        self.sputter_input.setSingleStep(100.0)
        self.sputter_input.setSuffix(" V")
        self.sputter_input.setValue(1000.0)
        self.sputter_input.setKeyboardTracking(False)
        self.sputter_input.valueChanged.connect(self.update_calculations)

        # Outputs
        self.b_field_label = QLabel("0.00 kG")
        self.b_field_label.setStyleSheet("font-weight:800; color:#2E86C1;")

        self.current_label = QLabel("0.0000 A")
        self.current_label.setStyleSheet("font-weight:800; color:#1E8449;")

        self.info_label = QLabel("")
        self.info_label.setStyleSheet("color:#666;")

        self.set_btn = QPushButton("Set Magnet Current")
        self.set_btn.clicked.connect(self.apply_current)

        row = 0
        layout.addWidget(QLabel("Mass:"), row, 0)
        layout.addWidget(self.mass_input, row, 1)
        layout.addWidget(QLabel("Calculated B field:"), row, 2)
        layout.addWidget(self.b_field_label, row, 3)

        row += 1
        layout.addWidget(QLabel("Extraction voltage:"), row, 0)
        layout.addWidget(self.extraction_input, row, 1)
        layout.addWidget(QLabel("Required current:"), row, 2)
        layout.addWidget(self.current_label, row, 3)

        row += 1
        layout.addWidget(QLabel("Sputter voltage:"), row, 0)
        layout.addWidget(self.sputter_input, row, 1)
        layout.addWidget(self.set_btn, row, 2, 1, 2)

        row += 1
        layout.addWidget(self.info_label, row, 0, 1, 4)

        self.update_calculations()

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
            "No magnet set-current API found in backend "
            "(expected set_magnet_current or backend.magnet.set_current)."
        )

    def update_calculations(self) -> None:
        try:
            mass_u = float(self.mass_input.value())
            extraction_v = float(self.extraction_input.value())
            sputter_v = float(self.sputter_input.value())

            mass_kg = mass_u * 1.66054e-27
            total_energy_ev = extraction_v + sputter_v

            q = 1.60218e-19
            radius_m = 0.5  # same radius as used in the old code

            if total_energy_ev <= 0.0:
                b_field_tesla = 0.0
            else:
                b_field_tesla = math.sqrt(2.0 * total_energy_ev * q * mass_kg) / (q * radius_m)

            b_field_kG = b_field_tesla * 10.0  # 1 T = 10 kG
            current_a = (b_field_kG - 0.0937) / 0.1055

            self._last_current_a = current_a
            self.b_field_label.setText(f"{b_field_kG:.2f} kG")
            self.current_label.setText(f"{current_a:.4f} A")

            if current_a < 0.0:
                self.info_label.setText("Calculated current is below 0 A and will be clamped to 0 A.")
            elif current_a > self.MAX_A:
                self.info_label.setText(
                    f"Calculated current is above {self.MAX_A:.1f} A and will be clamped."
                )
            else:
                self.info_label.setText("")

        except Exception:
            self._last_current_a = 0.0
            self.b_field_label.setText("ERR")
            self.current_label.setText("ERR")
            self.info_label.setText("Calculation error.")

    def apply_current(self) -> None:
        try:
            self._set_current(self._last_current_a)
            shown = min(max(self._last_current_a, 0.0), self.MAX_A)
            self.info_label.setText(f"Magnet current sent: {shown:.4f} A")
        except Exception as exc:
            self.info_label.setText(f"Send error: {exc}")


class MagnetPanel(QWidget):
    """
    Magnet GUI with StepSliderControl (same behavior as other sliders):
      - Set value shown on the LEFT inside the slider control (bold)
      - Meas value shown on the RIGHT (bold)

    Rows:
      1) Current set via StepSliderControl, right side: Current meas (bold)
      2) Direct input 1 + send confirmation, right side: Voltage meas (bold)
      3) Direct input 2 + send confirmation, right side: Field meas (bold)

    Extra:
      - Magnet Calculator popup button integrated into the panel header
    """

    MAX_A = 120.0

    def __init__(self, backend, adapter, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.adapter = adapter

        self._pending_set: Optional[float] = None
        self._send_timer = QTimer(self)
        self._send_timer.setSingleShot(True)
        self._send_timer.timeout.connect(self._flush_pending_send)

        self._set_seen = False
        self._initialized_from_meas = False
        self._calc_dialog: Optional[MagnetCalculatorDialog] = None

        gb = QGroupBox("Magnet")
        gb.setStyleSheet("""
            QGroupBox { font-size: 14px; font-weight: 700; }
            QLabel { font-size: 12px; }
        """)

        grid = QGridLayout()
        grid.setContentsMargins(8, 6, 8, 6)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        # Header row
        self.lbl_status = QLabel("Magnet: DISCONNECTED")
        self.lbl_status.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.lbl_status.setStyleSheet("color:#a00; font-weight:800;")
        grid.addWidget(self.lbl_status, 0, 0, 1, 4)

        self.btn_calc = QPushButton("Calculator")
        self.btn_calc.clicked.connect(self._open_calculator)
        grid.addWidget(self.btn_calc, 0, 4, 1, 2)

        # --- Row 1: main current control ---
        r = 1
        grid.addWidget(QLabel("Current:"), r, 0)

        decimals = 3
        multiplier = 10 ** decimals
        self.ctrl = StepSliderControl(
            0.0,
            self.MAX_A,
            multiplier,
            "A",
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
        for ch in (
            "magnet_connected",
            "gaussmeter_connected",
            "magnet_current_set",
            "magnet_current_meas",
            "magnet_voltage_meas",
            "magnet_field_meas",
        ):
            self.adapter.register_channel(ch)

        QTimer.singleShot(0, self._refresh_status)

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
            "No magnet set-current API found in backend "
            "(expected set_magnet_current or backend.magnet.set_current)."
        )

    # ------------------------
    # UI events
    # ------------------------
    def _open_calculator(self) -> None:
        if self._calc_dialog is None:
            self._calc_dialog = MagnetCalculatorDialog(self.backend, self)
            self._calc_dialog.destroyed.connect(
                lambda *_: setattr(self, "_calc_dialog", None)
            )

        self._calc_dialog.show()
        self._calc_dialog.raise_()
        self._calc_dialog.activateWindow()

    def _on_set_changed(self, value_A: float) -> None:
        """
        StepSliderControl emits very frequently while sliding.
        Debounce sends to avoid hammering the PSU.
        """
        self._pending_set = float(value_A)
        self._send_timer.start(120)

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
        if name in ("magnet_connected", "gaussmeter_connected"):
            self._refresh_status()
            return

        if name == "magnet_current_set":
            try:
                v = float(value)
            except Exception:
                return

            self._set_seen = True
            try:
                self.ctrl.set_real_value(v, emit=False)
            except Exception:
                pass
            return

        if name == "magnet_current_meas":
            try:
                v = float(value)
                self.lbl_meas_current.setText(f"{v:.3f} A")
            except Exception:
                self.lbl_meas_current.setText("— A")
                return

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