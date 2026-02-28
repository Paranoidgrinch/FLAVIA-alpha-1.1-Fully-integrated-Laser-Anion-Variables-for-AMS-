# gui/windows/keithley_settings.py
from __future__ import annotations

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QGroupBox, QFormLayout, QLineEdit, QSpinBox, QDoubleSpinBox,
    QCheckBox, QComboBox, QLabel, QPushButton, QHBoxLayout
)

# expected to exist in your "new keithley worker"
from backend.workers.keithley_6485_worker import KeithleySettings, AvgFilterSettings


class SettingsDialog(QDialog):
    def __init__(self, settings: KeithleySettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keithley Settings")
        self._s = settings

        layout = QVBoxLayout()

        g_conn = QGroupBox("Connection")
        f_conn = QFormLayout()
        self.ed_host = QLineEdit(settings.host)
        self.sb_port = QSpinBox()
        self.sb_port.setRange(1, 65535)
        self.sb_port.setValue(int(settings.port))
        self.sb_cto = QDoubleSpinBox()
        self.sb_cto.setRange(0.1, 10.0)
        self.sb_cto.setDecimals(2)
        self.sb_cto.setValue(float(settings.connect_timeout_s))
        self.sb_ito = QDoubleSpinBox()
        self.sb_ito.setRange(0.1, 30.0)
        self.sb_ito.setDecimals(1)
        self.sb_ito.setValue(float(settings.io_timeout_s))
        f_conn.addRow("Host:", self.ed_host)
        f_conn.addRow("Port:", self.sb_port)
        f_conn.addRow("Connect timeout [s]:", self.sb_cto)
        f_conn.addRow("I/O timeout [s]:", self.sb_ito)
        g_conn.setLayout(f_conn)

        g_mode = QGroupBox("Mode")
        h_mode = QHBoxLayout()
        self.cb_mode = QComboBox()
        self.cb_mode.addItems(["TUNE", "MEASURE"])
        self.cb_mode.setCurrentText(settings.mode.upper())
        h_mode.addWidget(QLabel("Mode:"))
        h_mode.addWidget(self.cb_mode)
        h_mode.addStretch()
        g_mode.setLayout(h_mode)

        g_tune = QGroupBox("Tune (fast)")
        f_tune = QFormLayout()
        self.sb_t_nplc = QDoubleSpinBox()
        self.sb_t_nplc.setRange(0.0001, 10.0)
        self.sb_t_nplc.setDecimals(4)
        self.sb_t_nplc.setValue(float(settings.tune.nplc))
        self.sb_t_poll = QDoubleSpinBox()
        self.sb_t_poll.setRange(1.0, 200.0)
        self.sb_t_poll.setDecimals(1)
        self.sb_t_poll.setValue(float(settings.tune.poll_hz))
        self.sb_t_bucket = QDoubleSpinBox()
        self.sb_t_bucket.setRange(0.05, 10.0)
        self.sb_t_bucket.setDecimals(2)
        self.sb_t_bucket.setValue(float(settings.tune.bucket_interval_s))
        self.cb_t_az = QCheckBox("Autozero")
        self.cb_t_az.setChecked(bool(settings.tune.autozero))
        f_tune.addRow("NPLC:", self.sb_t_nplc)
        f_tune.addRow("Poll rate [Hz]:", self.sb_t_poll)
        f_tune.addRow("Bucket interval [s]:", self.sb_t_bucket)
        f_tune.addRow("", self.cb_t_az)
        g_tune.setLayout(f_tune)

        g_meas = QGroupBox("Measure (precision)")
        f_meas = QFormLayout()
        self.sb_m_nplc = QDoubleSpinBox()
        self.sb_m_nplc.setRange(0.0001, 10.0)
        self.sb_m_nplc.setDecimals(4)
        self.sb_m_nplc.setValue(float(settings.measure.nplc))
        self.sb_m_int = QDoubleSpinBox()
        self.sb_m_int.setRange(0.2, 60.0)
        self.sb_m_int.setDecimals(2)
        self.sb_m_int.setValue(float(settings.measure.interval_s))
        self.cb_m_az = QCheckBox("Autozero")
        self.cb_m_az.setChecked(bool(settings.measure.autozero))
        f_meas.addRow("NPLC:", self.sb_m_nplc)
        f_meas.addRow("Interval [s]:", self.sb_m_int)
        f_meas.addRow("", self.cb_m_az)
        g_meas.setLayout(f_meas)

        g_rng = QGroupBox("Range")
        f_rng = QFormLayout()
        self.cb_auto = QCheckBox("Auto range")
        self.cb_auto.setChecked(bool(settings.tune.range.auto))
        self.sb_fixed = QDoubleSpinBox()
        self.sb_fixed.setRange(0.001, 1e9)
        self.sb_fixed.setDecimals(3)
        self.sb_fixed.setValue(float(settings.tune.range.fixed_range_nA))
        f_rng.addRow("", self.cb_auto)
        f_rng.addRow("Fixed range [nA] (auto off):", self.sb_fixed)
        g_rng.setLayout(f_rng)

        g_filt = QGroupBox("Averaging filter (best effort)")
        f_filt = QFormLayout()
        self.cb_avg = QCheckBox("Enable averaging filter")
        self.cb_avg.setChecked(bool(settings.measure.avg_filter.enabled))
        self.sb_avg_cnt = QSpinBox()
        self.sb_avg_cnt.setRange(1, 10000)
        self.sb_avg_cnt.setValue(int(settings.measure.avg_filter.count))
        self.cb_avg_tcon = QComboBox()
        self.cb_avg_tcon.addItems(["MOV", "REP"])
        self.cb_avg_tcon.setCurrentText(settings.measure.avg_filter.tcon.upper())
        f_filt.addRow("", self.cb_avg)
        f_filt.addRow("Count:", self.sb_avg_cnt)
        f_filt.addRow("Type:", self.cb_avg_tcon)
        g_filt.setLayout(f_filt)

        btns = QHBoxLayout()
        self.btn_ok = QPushButton("OK")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(self.btn_ok)
        btns.addWidget(self.btn_cancel)

        layout.addWidget(g_conn)
        layout.addWidget(g_mode)
        layout.addWidget(g_tune)
        layout.addWidget(g_meas)
        layout.addWidget(g_rng)
        layout.addWidget(g_filt)
        layout.addLayout(btns)
        self.setLayout(layout)

    def get_settings(self) -> KeithleySettings:
        s = self._s
        s.host = self.ed_host.text().strip()
        s.port = int(self.sb_port.value())
        s.connect_timeout_s = float(self.sb_cto.value())
        s.io_timeout_s = float(self.sb_ito.value())
        s.mode = self.cb_mode.currentText().strip().upper()

        s.tune.nplc = float(self.sb_t_nplc.value())
        s.tune.poll_hz = float(self.sb_t_poll.value())
        s.tune.bucket_interval_s = float(self.sb_t_bucket.value())
        s.tune.autozero = bool(self.cb_t_az.isChecked())

        s.measure.nplc = float(self.sb_m_nplc.value())
        s.measure.interval_s = float(self.sb_m_int.value())
        s.measure.autozero = bool(self.cb_m_az.isChecked())

        auto = bool(self.cb_auto.isChecked())
        fixed = float(self.sb_fixed.value())
        s.tune.range.auto = auto
        s.tune.range.fixed_range_nA = fixed
        s.measure.range.auto = auto
        s.measure.range.fixed_range_nA = fixed

        af = AvgFilterSettings(
            enabled=bool(self.cb_avg.isChecked()),
            count=int(self.sb_avg_cnt.value()),
            tcon=self.cb_avg_tcon.currentText().strip().upper(),
        )
        s.tune.avg_filter = af
        s.measure.avg_filter = af
        return s