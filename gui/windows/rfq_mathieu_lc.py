# gui/windows/rfq_mathieu_lc.py
from __future__ import annotations

import math
import numpy as np

from PyQt5 import QtWidgets, QtCore
from PyQt5.QtGui import QTextCursor

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from backend.workers.rfq_worker import (
    compute_q,
    compute_freq_for_q,
    L_from_f_C,
    C_from_f_L,
    RESONANCE_PRESETS,
    R0_MM,
    u_to_kg,
    e_charge,
    PI_HOST_DEFAULT,
    paramiko,
)


class RFQMathieuLCWindow(QtWidgets.QMainWindow):
    """
    GUI uses backend.rfq (RFQService).
    No local QThread/worker here anymore.
    """

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.rfq = backend.rfq

        self.setWindowTitle("RFQ – Mathieu, FG, LC (SSH), Scope + L-sweep")
        self.resize(1250, 800)

        self.resonance_presets = RESONANCE_PRESETS
        self._build_ui()

        # connect backend service signals to GUI slots
        self.rfq.fgStatus.connect(self._on_fg_status)
        self.rfq.fgError.connect(self._on_fg_error)

        self.rfq.piStatus.connect(self._on_pi_status)
        self.rfq.lcReadResult.connect(self._on_lc_read_result)
        self.rfq.lcSendResult.connect(self._on_lc_send_result)
        self.rfq.lcError.connect(self._on_lc_error)

        self.rfq.scopeStatus.connect(self._on_scope_status)
        self.rfq.scopeMeasurement.connect(self._on_scope_measurement)
        self.rfq.scopeError.connect(self._on_scope_error)

        self.rfq.sweepLog.connect(self.append_log)
        self.rfq.sweepProgress.connect(self._on_sweep_progress)
        self.rfq.sweepResult.connect(self._on_sweep_result)
        self.rfq.sweepError.connect(self._on_sweep_error)

        # FG status timer
        self.timer_fg = QtCore.QTimer(self)
        self.timer_fg.timeout.connect(self.update_fg_display)
        self.timer_fg.start(2000)

        # initial actions
        self._connect_pi()
        self.update_scope_status()
        self.update_fg_display()

    # =========================
    # UI BUILD
    # =========================
    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)

        middle_layout = QtWidgets.QHBoxLayout()
        main_layout.addLayout(middle_layout)

        left_col = QtWidgets.QVBoxLayout()
        middle_layout.addLayout(left_col, stretch=3)

        left_top_row = QtWidgets.QHBoxLayout()
        left_col.addLayout(left_top_row)

        left_top_row.addWidget(self._build_mathieu_group(), stretch=1)
        left_top_row.addWidget(self._build_fg_group(), stretch=1)

        left_col.addWidget(self._build_plot_group(), stretch=2)

        right_col = QtWidgets.QVBoxLayout()
        middle_layout.addLayout(right_col, stretch=2)

        right_col.addWidget(self._build_lc_group())
        right_col.addWidget(self._build_scope_group())

        self.log = QtWidgets.QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(160)
        main_layout.addWidget(self.log)

    # =========================
    # MATHIEU GROUP
    # =========================
    def _build_mathieu_group(self):
        group = QtWidgets.QGroupBox("Mathieu Parameter Calculator")
        layout = QtWidgets.QFormLayout(group)

        self.edit_mass = QtWidgets.QLineEdit("40.0")
        self.edit_charge = QtWidgets.QLineEdit("1")
        self.label_r0 = QtWidgets.QLabel(f"{R0_MM:.3f} mm (fixed)")
        self.edit_q_target = QtWidgets.QLineEdit("0.3")

        self.spin_amp = QtWidgets.QDoubleSpinBox()
        self.spin_amp.setRange(0.0, 10.0)
        self.spin_amp.setSingleStep(0.1)
        self.spin_amp.setDecimals(2)
        self.spin_amp.setValue(5.0)
        self.spin_amp.setSuffix(" Vpp")

        self.combo_gain = QtWidgets.QComboBox()
        self.combo_gain.addItems(["1 (HF amp off)", "10 (HF amp on)"])
        self.combo_gain.setCurrentIndex(1)

        self.edit_freq = QtWidgets.QLineEdit("200000.0")  # Hz

        btn_q_from_f = QtWidgets.QPushButton("Compute Mathieu Parameter for given Frequency")
        btn_q_from_f.clicked.connect(self.on_q_from_f)

        btn_f_from_q = QtWidgets.QPushButton("Compute Frequency for given Mathieu Parameter")
        btn_f_from_q.clicked.connect(self.on_f_from_q)

        self.lbl_q_result = QtWidgets.QLabel("q = ---")

        layout.addRow("Mass m (u):", self.edit_mass)
        layout.addRow("Charge z:", self.edit_charge)
        layout.addRow("r0:", self.label_r0)
        layout.addRow("Target q:", self.edit_q_target)
        layout.addRow("FG amplitude:", self.spin_amp)
        layout.addRow("HF amp gain:", self.combo_gain)
        layout.addRow("Frequency f (Hz):", self.edit_freq)

        hl = QtWidgets.QHBoxLayout()
        hl.addWidget(btn_q_from_f)
        hl.addWidget(btn_f_from_q)
        layout.addRow(hl)
        layout.addRow("Result:", self.lbl_q_result)

        return group

    def _read_mathieu_params(self):
        try:
            m_u = float(self.edit_mass.text())
            z = int(self.edit_charge.text())
            q_target = float(self.edit_q_target.text())
            Vpp_FG = float(self.spin_amp.value())
            gain = 1 if self.combo_gain.currentIndex() == 0 else 10
        except ValueError:
            return None
        return m_u, z, q_target, Vpp_FG, gain

    def on_q_from_f(self):
        params = self._read_mathieu_params()
        if params is None:
            self.append_log("Error: invalid Mathieu parameters.")
            return
        m_u, z, q_target, Vpp_FG, gain = params

        try:
            f_hz = float(self.edit_freq.text())
        except ValueError:
            self.append_log("Error: frequency f is invalid.")
            return

        q_val = compute_q(m_u, z, R0_MM, f_hz, Vpp_FG, gain)
        if math.isnan(q_val):
            self.lbl_q_result.setText("q = NaN")
            self.append_log("Failed to compute q.")
        else:
            self.lbl_q_result.setText(f"q = {q_val:.3f}")
            self.append_log(f"q from f -> q={q_val:.3f}")

    def on_f_from_q(self):
        params = self._read_mathieu_params()
        if params is None:
            self.append_log("Error: invalid Mathieu parameters.")
            return
        m_u, z, q_target, Vpp_FG, gain = params

        f_hz = compute_freq_for_q(m_u, z, R0_MM, q_target, Vpp_FG, gain)
        if math.isnan(f_hz):
            self.append_log("Failed to compute frequency from q.")
            return
        self.edit_freq.setText(f"{f_hz:.3f}")
        self.lbl_q_result.setText("q = ---")
        self.append_log(f"f from q -> f={f_hz:.1f} Hz")

    # =========================
    # FG GROUP
    # =========================
    def _build_fg_group(self):
        group = QtWidgets.QGroupBox("Function Generator")
        layout = QtWidgets.QFormLayout(group)

        self.lbl_fg_status = QtWidgets.QLabel("Status: unknown")
        self.lbl_fg_status.setStyleSheet("color: red;")

        self.lbl_fg_freq = QtWidgets.QLabel("f = --- Hz")
        self.lbl_fg_ampl = QtWidgets.QLabel("Vpp = --- V")

        btn_fg_read = QtWidgets.QPushButton("Readout Function Generator")
        btn_fg_read.clicked.connect(self.update_fg_display)

        btn_fg_send = QtWidgets.QPushButton("Set calculated Frequency and Amplitude")
        btn_fg_send.clicked.connect(self.on_fg_send)

        layout.addRow(self.lbl_fg_status)
        layout.addRow("FG frequency:", self.lbl_fg_freq)
        layout.addRow("FG amplitude:", self.lbl_fg_ampl)
        layout.addRow(btn_fg_read)
        layout.addRow(btn_fg_send)

        return group

    def update_fg_display(self):
        self.rfq.request_fg_status()

    def _on_fg_status(self, f, a):
        if math.isnan(f) or math.isnan(a):
            self.lbl_fg_status.setText("Status: not connected")
            self.lbl_fg_status.setStyleSheet("color: red;")
            self.lbl_fg_freq.setText("f = --- Hz")
            self.lbl_fg_ampl.setText("Vpp = --- V")
        else:
            self.lbl_fg_status.setText("Status: connected")
            self.lbl_fg_status.setStyleSheet("color: green;")
            self.lbl_fg_freq.setText(f"f = {f:.1f} Hz")
            self.lbl_fg_ampl.setText(f"Vpp = {a:.3f} V")

    def _on_fg_error(self, msg: str):
        self.append_log(f"FG error: {msg}")
        self.lbl_fg_status.setText("Status: not connected")
        self.lbl_fg_status.setStyleSheet("color: red;")

    def on_fg_send(self):
        try:
            f = float(self.edit_freq.text())
        except ValueError:
            self.append_log("FG send: frequency f is invalid.")
            return
        Vpp_FG = float(self.spin_amp.value())
        self.append_log(f"Sent to FG: f={f:.1f} Hz, Vpp={Vpp_FG:.2f} V")
        self.rfq.set_fg(f, Vpp_FG)

    # =========================
    # LC GROUP
    # =========================
    def _build_lc_group(self):
        group = QtWidgets.QGroupBox("LC Circuit")
        vlayout = QtWidgets.QVBoxLayout(group)
        form = QtWidgets.QFormLayout()
        vlayout.addLayout(form)

        self.lbl_pi_status = QtWidgets.QLabel("Status: not connected")
        self.lbl_pi_status.setStyleSheet("color: red;")

        btn_pi_connect = QtWidgets.QPushButton("Reconnect to Pi")
        btn_pi_connect.clicked.connect(self.on_pi_connect)

        self.edit_C_pF = QtWidgets.QLineEdit("1300.0")
        self.edit_L_uH = QtWidgets.QLineEdit("31.0")

        btn_L_from_C = QtWidgets.QPushButton("Compute L from Frequency and C")
        btn_L_from_C.clicked.connect(self.on_L_from_C)

        btn_C_from_L = QtWidgets.QPushButton("Compute C from Frequency and L")
        btn_C_from_L.clicked.connect(self.on_C_from_L)

        btn_lc_send = QtWidgets.QPushButton("Send LC values to Pi")
        btn_lc_send.clicked.connect(self.on_lc_send)

        btn_lc_read = QtWidgets.QPushButton("Read LC values from Pi")
        btn_lc_read.clicked.connect(self.on_lc_read)

        self.combo_resonance = QtWidgets.QComboBox()
        if not self.resonance_presets:
            self.combo_resonance.addItem("No resonance data")
            self.combo_resonance.setEnabled(False)
        else:
            for row in self.resonance_presets:
                f_mhz = row["f_MHz"]
                c_pf = row["C_pF"]
                l_uh = row["L_uH"]
                text = f"{f_mhz:.3f} MHz  (C={c_pf:.0f} pF, L={l_uh:.3f} µH)"
                self.combo_resonance.addItem(text, row)
            self.combo_resonance.currentIndexChanged.connect(self.on_resonance_selected)

        form.addRow(btn_pi_connect)
        form.addRow(self.lbl_pi_status)
        form.addRow("Resonance preset:", self.combo_resonance)
        form.addRow("C (pF):", self.edit_C_pF)
        form.addRow("L (µH):", self.edit_L_uH)

        hl = QtWidgets.QHBoxLayout()
        hl.addWidget(btn_L_from_C)
        hl.addWidget(btn_C_from_L)
        form.addRow(hl)
        form.addRow(btn_lc_send)
        form.addRow(btn_lc_read)

        sweep_group = QtWidgets.QGroupBox("L sweep (around current L)")
        sweep_layout = QtWidgets.QFormLayout(sweep_group)

        self.edit_sweep_span_uH = QtWidgets.QLineEdit("5.0")
        self.edit_sweep_step_uH = QtWidgets.QLineEdit("0.25")
        self.edit_sweep_dwell_ms = QtWidgets.QLineEdit("1000")

        self.check_sweep_scope = QtWidgets.QCheckBox("Measure Vpp from scope at each step")
        self.check_sweep_scope.setChecked(True)

        btn_sweep = QtWidgets.QPushButton("Start L sweep")
        btn_sweep.clicked.connect(self.on_sweep_L)

        sweep_layout.addRow("± span around L (µH):", self.edit_sweep_span_uH)
        sweep_layout.addRow("Step size (µH):", self.edit_sweep_step_uH)
        sweep_layout.addRow("Time per step (ms):", self.edit_sweep_dwell_ms)
        sweep_layout.addRow(self.check_sweep_scope)
        sweep_layout.addRow(btn_sweep)

        vlayout.addWidget(sweep_group)
        return group

    def _connect_pi(self):
        if paramiko is None:
            self.lbl_pi_status.setText("Status: paramiko not installed")
            self.lbl_pi_status.setStyleSheet("color: red;")
            self.append_log("SSH error: paramiko not installed (pip install paramiko).")
            return
        self.lbl_pi_status.setText("Status: connecting...")
        self.lbl_pi_status.setStyleSheet("color: orange;")
        self.rfq.connect_pi()

    def on_pi_connect(self):
        self._connect_pi()

    def _on_pi_status(self, ok: bool, msg: str):
        if ok:
            self.lbl_pi_status.setText(f"Status: connected to {PI_HOST_DEFAULT}")
            self.lbl_pi_status.setStyleSheet("color: green;")
        else:
            self.lbl_pi_status.setText("Status: connection error")
            self.lbl_pi_status.setStyleSheet("color: red;")
        if msg:
            self.append_log(msg)

    def _read_freq(self):
        try:
            return float(self.edit_freq.text())
        except ValueError:
            return float("nan")

    def on_resonance_selected(self, idx):
        data = self.combo_resonance.itemData(idx)
        if not isinstance(data, dict):
            return
        f_hz = data["f_MHz"] * 1e6
        self.edit_freq.setText(f"{f_hz:.3f}")
        self.edit_C_pF.setText(f"{data['C_pF']:.3f}")
        self.edit_L_uH.setText(f"{data['L_uH']:.3f}")

    def on_L_from_C(self):
        f = self._read_freq()
        if math.isnan(f):
            self.append_log("LC: frequency invalid.")
            return
        try:
            C_pF = float(self.edit_C_pF.text())
        except ValueError:
            self.append_log("LC: C invalid.")
            return
        L_H = L_from_f_C(f, C_pF * 1e-12)
        if math.isnan(L_H):
            self.append_log("LC: compute L failed.")
            return
        self.edit_L_uH.setText(f"{L_H * 1e6:.3f}")

    def on_C_from_L(self):
        f = self._read_freq()
        if math.isnan(f):
            self.append_log("LC: frequency invalid.")
            return
        try:
            L_uH = float(self.edit_L_uH.text())
        except ValueError:
            self.append_log("LC: L invalid.")
            return
        C_F = C_from_f_L(f, L_uH * 1e-6)
        if math.isnan(C_F):
            self.append_log("LC: compute C failed.")
            return
        self.edit_C_pF.setText(f"{C_F * 1e12:.3f}")

    def on_lc_send(self):
        try:
            C_pF = float(self.edit_C_pF.text())
            L_uH = float(self.edit_L_uH.text())
        except ValueError:
            self.append_log("LC: invalid numbers.")
            return
        self.rfq.set_lc(C_pF, L_uH)

    def on_lc_read(self):
        self.rfq.read_lc()

    def _on_lc_read_result(self, c_val, c_err, l_val, l_err):
        if not math.isnan(c_val):
            self.edit_C_pF.setText(f"{c_val:.3f}")
        if not math.isnan(l_val):
            self.edit_L_uH.setText(f"{l_val:.3f}")
        self.append_log(f"LC from Pi: C={c_val} (err={c_err}), L={l_val} (err={l_err})")

    def _on_lc_send_result(self, C_pF, L_uH, errC, errL):
        self.append_log(f"LC sent: C={C_pF:.3f} pF, L={L_uH:.3f} µH | C-err={errC!r} L-err={errL!r}")

    def _on_lc_error(self, msg: str):
        self.append_log(f"LC error: {msg}")

    def on_sweep_L(self):
        try:
            center_L = float(self.edit_L_uH.text())
            span = float(self.edit_sweep_span_uH.text())
            step = float(self.edit_sweep_step_uH.text())
            dwell_ms = float(self.edit_sweep_dwell_ms.text())
        except ValueError:
            QtWidgets.QMessageBox.warning(self, "Error", "Sweep parameters invalid.")
            return
        self.rfq.run_sweep_L(center_L, span, step, dwell_ms, self.check_sweep_scope.isChecked())

    def _on_sweep_progress(self, step_idx: int, total: int, L_uH: float):
        self.edit_L_uH.setText(f"{L_uH:.3f}")

    def _on_sweep_result(self, L_meas, Vpp2_list, Vpp3_list, best_wave2, best_wave3, best_L, max_vpp2, msg_txt):
        if L_meas and best_wave2 is not None and best_wave3 is not None:
            dialog = QtWidgets.QDialog(self)
            dialog.setWindowTitle("L sweep result")
            dlg_layout = QtWidgets.QVBoxLayout(dialog)

            fig = Figure(figsize=(7, 6))
            canvas = FigureCanvas(fig)
            dlg_layout.addWidget(canvas)

            ax1 = fig.add_subplot(211)
            ax1.plot(L_meas, Vpp2_list, label="CH2 Vpp")
            ax1.plot(L_meas, Vpp3_list, label="CH3 Vpp")
            ax1.set_xlabel("L (µH)")
            ax1.set_ylabel("Vpp (V)")
            ax1.legend(loc="best")
            ax1.grid(True)

            ax2 = fig.add_subplot(212)
            ax2.plot(np.arange(len(best_wave2)), best_wave2, label="CH2 best")
            ax2.plot(np.arange(len(best_wave3)), best_wave3, label="CH3 best")
            ax2.legend(loc="best")
            ax2.grid(True)

            canvas.draw()
            dlg_layout.addWidget(QtWidgets.QLabel(msg_txt))
            btn_close = QtWidgets.QPushButton("Close")
            btn_close.clicked.connect(dialog.accept)
            dlg_layout.addWidget(btn_close)

            dialog.exec_()
        else:
            QtWidgets.QMessageBox.information(self, "Sweep result", msg_txt)

    def _on_sweep_error(self, msg: str):
        QtWidgets.QMessageBox.warning(self, "Sweep error", msg)
        self.append_log(f"Sweep error: {msg}")

    # =========================
    # SCOPE + PLOT
    # =========================
    def _build_scope_group(self):
        group = QtWidgets.QGroupBox("Oscilloscope")
        layout = QtWidgets.QFormLayout(group)

        self.lbl_scope_status = QtWidgets.QLabel("Status: unknown")
        self.lbl_scope_status.setStyleSheet("color: red;")

        self.lbl_vpp2 = QtWidgets.QLabel("CH2 Vpp = --- V")
        self.lbl_vpp3 = QtWidgets.QLabel("CH3 Vpp = --- V")
        self.lbl_q_meas = QtWidgets.QLabel("q_meas (from CH2) = ---")

        btn_measure = QtWidgets.QPushButton("Measure CH2 & CH3 + plot")
        btn_measure.clicked.connect(self.on_measure_scope)

        layout.addRow(self.lbl_scope_status)
        layout.addRow(btn_measure)
        layout.addRow(self.lbl_vpp2)
        layout.addRow(self.lbl_vpp3)
        layout.addRow(self.lbl_q_meas)

        return group

    def update_scope_status(self):
        self.rfq.test_scope()

    def _on_scope_status(self, ok: bool):
        self.lbl_scope_status.setText("Status: connected" if ok else "Status: not connected")
        self.lbl_scope_status.setStyleSheet("color: green;" if ok else "color: red;")

    def _build_plot_group(self):
        group = QtWidgets.QGroupBox("Waveform plot (CH2 & CH3)")
        layout = QtWidgets.QVBoxLayout(group)
        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)
        return group

    def on_measure_scope(self):
        self.rfq.measure_scope()

    def _on_scope_measurement(self, vpp2, vpp3, wave2, wave3):
        self.lbl_vpp2.setText(f"CH2 Vpp = {vpp2:.3f} V")
        self.lbl_vpp3.setText(f"CH3 Vpp = {vpp3:.3f} V")

        params = self._read_mathieu_params()
        try:
            f = float(self.edit_freq.text())
        except ValueError:
            f = float("nan")

        if params is None or math.isnan(f):
            self.lbl_q_meas.setText("q_meas (from CH2) = NaN")
        else:
            m_u, z, _, _, _ = params
            m = m_u * u_to_kg
            Q = abs(z) * e_charge
            r0 = R0_MM / 1000.0
            V0 = vpp2 / 2.0
            omega = 2.0 * math.pi * f
            q_meas = 4.0 * Q * V0 / (m * (r0 ** 2) * (omega ** 2))
            self.lbl_q_meas.setText(f"q_meas (from CH2) = {q_meas:.3f}")

        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.plot(np.arange(len(wave2)), wave2, label="CH2")
        ax.plot(np.arange(len(wave3)), wave3, label="CH3")
        ax.legend(loc="best")
        ax.grid(True)
        self.canvas.draw_idle()

    def _on_scope_error(self, msg: str):
        self.append_log(f"Scope error: {msg}")
        self._on_scope_status(False)

    # =========================
    # LOG / CLOSE
    # =========================
    def append_log(self, text: str):
        self.log.append(text)
        self.log.moveCursor(QTextCursor.End)

    def closeEvent(self, event):
        try:
            self.timer_fg.stop()
        except Exception:
            pass
        # do NOT stop backend service here (backend owns it)
        event.accept()