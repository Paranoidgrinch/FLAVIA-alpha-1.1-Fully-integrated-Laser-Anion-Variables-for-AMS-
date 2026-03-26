from __future__ import annotations

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from backend.workers.keithley_6485_worker import (
    AvgFilterSettings,
    KeithleySettings,
    MeasureSettings,
    RangeSettings,
    TraceSettings,
    TuneSettings,
)


class _ModeBox(QGroupBox):
    def __init__(self, title: str, has_poll_hz: bool, settings_obj, parent=None):
        super().__init__(title, parent)
        self.has_poll_hz = has_poll_hz
        form = QFormLayout(self)

        self.sb_nplc = QDoubleSpinBox()
        self.sb_nplc.setRange(0.0001, 10.0)
        self.sb_nplc.setDecimals(4)
        self.sb_nplc.setValue(float(settings_obj.nplc))
        form.addRow("NPLC:", self.sb_nplc)

        if has_poll_hz:
            self.sb_poll = QDoubleSpinBox()
            self.sb_poll.setRange(1.0, 200.0)
            self.sb_poll.setDecimals(1)
            self.sb_poll.setValue(float(settings_obj.poll_hz))
            form.addRow("Poll rate [Hz]:", self.sb_poll)

            self.sb_bucket = QDoubleSpinBox()
            self.sb_bucket.setRange(0.05, 60.0)
            self.sb_bucket.setDecimals(2)
            self.sb_bucket.setValue(float(settings_obj.bucket_interval_s))
            form.addRow("Bucket interval [s]:", self.sb_bucket)
        else:
            self.sb_interval = QDoubleSpinBox()
            self.sb_interval.setRange(0.05, 60.0)
            self.sb_interval.setDecimals(2)
            self.sb_interval.setValue(float(settings_obj.interval_s))
            form.addRow("Interval [s]:", self.sb_interval)

        self.cb_autozero = QCheckBox("Autozero")
        self.cb_autozero.setChecked(bool(settings_obj.autozero))
        form.addRow("", self.cb_autozero)

        self.sb_display_tau = QDoubleSpinBox()
        self.sb_display_tau.setRange(0.01, 10.0)
        self.sb_display_tau.setDecimals(2)
        self.sb_display_tau.setValue(float(getattr(settings_obj, "display_tau_s", 0.3)))
        form.addRow("Gauge tau [s]:", self.sb_display_tau)

        self.cb_auto = QCheckBox("Auto range")
        self.cb_auto.setChecked(bool(settings_obj.range.auto))
        form.addRow("", self.cb_auto)

        self.sb_fixed = QDoubleSpinBox()
        self.sb_fixed.setRange(0.001, 1e9)
        self.sb_fixed.setDecimals(3)
        self.sb_fixed.setValue(float(settings_obj.range.fixed_range_nA))
        form.addRow("Fixed range [nA]:", self.sb_fixed)

        self.cb_avg = QCheckBox("Enable averaging filter")
        self.cb_avg.setChecked(bool(settings_obj.avg_filter.enabled))
        form.addRow("", self.cb_avg)

        self.sb_avg_cnt = QSpinBox()
        self.sb_avg_cnt.setRange(1, 10000)
        self.sb_avg_cnt.setValue(int(settings_obj.avg_filter.count))
        form.addRow("Avg count:", self.sb_avg_cnt)

        self.cb_avg_tcon = QComboBox()
        self.cb_avg_tcon.addItems(["MOV", "REP"])
        self.cb_avg_tcon.setCurrentText((settings_obj.avg_filter.tcon or "MOV").upper())
        form.addRow("Avg type:", self.cb_avg_tcon)

        self.cb_auto.toggled.connect(self.sb_fixed.setDisabled)
        self.sb_fixed.setEnabled(not self.cb_auto.isChecked())

    def build_range(self) -> RangeSettings:
        return RangeSettings(auto=bool(self.cb_auto.isChecked()), fixed_range_nA=float(self.sb_fixed.value()))

    def build_avg(self) -> AvgFilterSettings:
        return AvgFilterSettings(
            enabled=bool(self.cb_avg.isChecked()),
            count=int(self.sb_avg_cnt.value()),
            tcon=self.cb_avg_tcon.currentText().strip().upper(),
        )

    def build_mode_settings(self, cls):
        kwargs = {
            "nplc": float(self.sb_nplc.value()),
            "autozero": bool(self.cb_autozero.isChecked()),
            "display_tau_s": float(self.sb_display_tau.value()),
            "range": self.build_range(),
            "avg_filter": self.build_avg(),
        }
        if self.has_poll_hz:
            kwargs["poll_hz"] = float(self.sb_poll.value())
            kwargs["bucket_interval_s"] = float(self.sb_bucket.value())
        else:
            kwargs["interval_s"] = float(self.sb_interval.value())
        return cls(**kwargs)


class SettingsDialog(QDialog):
    def __init__(self, settings: KeithleySettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keithley Settings")
        self._s = settings

        layout = QVBoxLayout(self)

        g_conn = QGroupBox("Connection")
        f_conn = QFormLayout(g_conn)
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

        g_mode = QGroupBox("Active mode")
        h_mode = QHBoxLayout(g_mode)
        self.cb_mode = QComboBox()
        self.cb_mode.addItems(["TUNE", "TRACE", "MEASURE"])
        self.cb_mode.setCurrentText((settings.mode or "TUNE").upper())
        h_mode.addWidget(QLabel("Mode:"))
        h_mode.addWidget(self.cb_mode)
        h_mode.addStretch(1)

        self.box_tune = _ModeBox("Tune (fast/live)", has_poll_hz=True, settings_obj=settings.tune)
        self.box_trace = _ModeBox("Trace (scan)", has_poll_hz=True, settings_obj=getattr(settings, "trace", TraceSettings()))
        self.box_measure = _ModeBox("Measure (precision)", has_poll_hz=False, settings_obj=settings.measure)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.btn_ok = QPushButton("OK")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        btns.addWidget(self.btn_ok)
        btns.addWidget(self.btn_cancel)

        layout.addWidget(g_conn)
        layout.addWidget(g_mode)
        layout.addWidget(self.box_tune)
        layout.addWidget(self.box_trace)
        layout.addWidget(self.box_measure)
        layout.addLayout(btns)

    def get_settings(self) -> KeithleySettings:
        s = self._s
        s.host = self.ed_host.text().strip()
        s.port = int(self.sb_port.value())
        s.connect_timeout_s = float(self.sb_cto.value())
        s.io_timeout_s = float(self.sb_ito.value())
        s.mode = self.cb_mode.currentText().strip().upper()
        s.tune = self.box_tune.build_mode_settings(TuneSettings)
        s.trace = self.box_trace.build_mode_settings(TraceSettings)
        s.measure = self.box_measure.build_mode_settings(MeasureSettings)
        return s
