from __future__ import annotations

from typing import Optional
from datetime import datetime

from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QMessageBox,
    QFileDialog,
    QScrollArea,
    QDialog,
    QDoubleSpinBox,
)

from backend.backend import Backend
from backend.services.config_service import ConfigPayload
from .qt_adapter import QtBackendAdapter
from .windows.pressure_monitor import PressureMonitorWindow
from .windows.tracer_1d import Tracer1DDialog
from .windows.tracer_2d import Tracer2DDialog
from .windows.rfq_mathieu_lc import RFQMathieuLCWindow
from .panels.ion_source import IonSourcePanel
from .panels.digital_controls import DigitalControlsPanel
from .panels.ion_optics import (
    PreCoolerIonOpticsPanel,
    PostCoolerIonOpticsPanel,
    ESAIonOpticsPanel,
)
from .panels.ion_cooler import IonCoolerPanel
from .panels.keithley_panel import KeithleyPanel
from .panels.sample_selection import SampleSelectionPanel
from .panels.magnet_panel import MagnetPanel
from gui.dialogs.config_apply_dialog import ConfigApplyDialog


class MainWindow(QMainWindow):
    def __init__(self, backend: Backend):
        super().__init__()
        self.backend = backend
        self.adapter = QtBackendAdapter(backend)

        self.setWindowTitle("FLAVIA2")
        self.resize(1400, 820)

        self.pressure_win: Optional[PressureMonitorWindow] = None
        self.tracer_win: Optional[Tracer1DDialog] = None
        self.tracer2d_win: Optional[Tracer2DDialog] = None
        self.rfq_win: Optional[RFQMathieuLCWindow] = None

        self._logging = False
        self._last_dir = ""

        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(10, 10, 10, 10)
        main.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)

        self.btn_log = QPushButton("Start Logging")
        self.btn_save = QPushButton("Save Config")
        self.btn_load = QPushButton("Load Config")

        self.btn_kill_source_hv = QPushButton("Kill Source HV")
        self.btn_restore_source_hv = QPushButton("Restore Source HV")
        self.btn_restore_source_hv.setEnabled(False)

        self.btn_steerer_bias = QPushButton("Steerer Bias")

        self.btn_pressure = QPushButton("Pressure Monitor")
        self.btn_tracer1d = QPushButton("Tracer 1D")
        self.btn_tracer2d = QPushButton("Tracer 2D")
        self.btn_mathieu = QPushButton("Mathieu + LC")

        for b in [
            self.btn_log,
            self.btn_save,
            self.btn_load,
            self.btn_kill_source_hv,
            self.btn_restore_source_hv,
            self.btn_steerer_bias,
            self.btn_pressure,
            self.btn_tracer1d,
            self.btn_tracer2d,
            self.btn_mathieu,
        ]:
            b.setStyleSheet("font-size: 12px; padding: 6px 10px;")
            top.addWidget(b)

        top.addStretch(1)

        f = QFont()
        f.setBold(True)

        self.lbl_mqtt = QLabel("MQTT: —")
        self.lbl_mqtt.setFont(f)
        top.addWidget(self.lbl_mqtt)

        self.lbl_log = QLabel("LOG: OFF")
        self.lbl_log.setFont(f)
        self.lbl_log.setStyleSheet("color:#a00;")
        top.addWidget(self.lbl_log)

        main.addLayout(top)

        content = QHBoxLayout()
        content.setSpacing(12)

        left_wrap = QWidget()
        left_lay = QVBoxLayout(left_wrap)
        left_lay.setContentsMargins(8, 8, 8, 8)
        left_lay.setSpacing(10)

        self.panel_ion_source = IonSourcePanel(self.backend, self.adapter)
        self.panel_digital = DigitalControlsPanel(self.backend, self.adapter)
        self.panel_keithley = KeithleyPanel(self.backend, self.adapter)
        self.panel_sample = SampleSelectionPanel(self.backend, self.adapter)
        self.panel_magnet = MagnetPanel(self.backend, self.adapter)

        left_lay.addWidget(self.panel_ion_source)
        left_lay.addWidget(self.panel_digital)
        left_lay.addWidget(self.panel_keithley)
        left_lay.addWidget(self.panel_sample)
        left_lay.addWidget(self.panel_magnet)
        left_lay.addStretch(1)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(left_wrap)

        right_wrap = QWidget()
        right_lay = QVBoxLayout(right_wrap)
        right_lay.setContentsMargins(8, 8, 8, 8)
        right_lay.setSpacing(10)

        self.panel_ion_optics_pre = PreCoolerIonOpticsPanel(self.backend, self.adapter)
        self.panel_ion_cooler = IonCoolerPanel(self.backend, self.adapter)
        self.panel_ion_optics_post = PostCoolerIonOpticsPanel(self.backend, self.adapter)
        self.panel_ion_optics_esa = ESAIonOpticsPanel(self.backend, self.adapter)

        right_lay.addWidget(self.panel_ion_optics_pre)
        right_lay.addWidget(self.panel_ion_cooler)
        right_lay.addWidget(self.panel_ion_optics_post)
        right_lay.addWidget(self.panel_ion_optics_esa)
        right_lay.addStretch(1)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setWidget(right_wrap)

        content.addWidget(left_scroll, 3)
        content.addWidget(right_scroll, 5)
        main.addLayout(content, 1)

        self.btn_log.clicked.connect(self.toggle_logging)
        self.btn_save.clicked.connect(self.save_config)
        self.btn_load.clicked.connect(self.load_config)

        self.btn_kill_source_hv.clicked.connect(self.kill_source_hv)
        self.btn_restore_source_hv.clicked.connect(self.restore_source_hv)
        self.btn_steerer_bias.clicked.connect(self.open_steerer_bias_dialog)

        self.btn_pressure.clicked.connect(self.open_pressure_monitor)
        self.btn_tracer1d.clicked.connect(self.open_tracer_1d)
        self.btn_tracer2d.clicked.connect(self.open_tracer_2d)
        self.btn_mathieu.clicked.connect(self.open_rfq_mathieu)

        self.adapter.channelUpdated.connect(self.on_channel_updated)
        self.adapter.register_channel("mqtt_connected")

    def open_rfq_mathieu(self) -> None:
        if self.rfq_win is None:
            self.rfq_win = RFQMathieuLCWindow(self.backend, self)
            self.rfq_win.destroyed.connect(lambda *_: setattr(self, "rfq_win", None))
        self.rfq_win.show()
        self.rfq_win.raise_()
        self.rfq_win.activateWindow()

    def open_pressure_monitor(self) -> None:
        if self.pressure_win is None:
            self.pressure_win = PressureMonitorWindow(self.backend, self.adapter, self)
        self.pressure_win.show()
        self.pressure_win.raise_()
        self.pressure_win.activateWindow()

    def open_tracer_1d(self) -> None:
        if self.tracer_win is None:
            self.tracer_win = Tracer1DDialog(self.backend, self.adapter, self)
            self.tracer_win.destroyed.connect(lambda *_: setattr(self, "tracer_win", None))
        self.tracer_win.show()
        self.tracer_win.raise_()
        self.tracer_win.activateWindow()

    def open_tracer_2d(self) -> None:
        if self.tracer2d_win is None:
            self.tracer2d_win = Tracer2DDialog(self.backend, self.adapter, self)
            self.tracer2d_win.destroyed.connect(lambda *_: setattr(self, "tracer2d_win", None))
        self.tracer2d_win.show()
        self.tracer2d_win.raise_()
        self.tracer2d_win.activateWindow()

    def open_steerer_bias_dialog(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Steerer Bias")
        dlg.resize(280, 120)

        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("Steerer bias voltage (V)"))

        spin = QDoubleSpinBox()
        spin.setDecimals(2)
        spin.setRange(0.0, 500.0)
        spin.setSingleStep(1.0)

        ch = self.backend.model.get("steerer/bias/set_u")
        try:
            if ch is not None and ch.value is not None:
                spin.setValue(float(ch.value))
            else:
                spin.setValue(250.0)
        except Exception:
            spin.setValue(250.0)

        layout.addWidget(spin)

        row = QHBoxLayout()
        btn_set = QPushButton("Set")
        btn_close = QPushButton("Close")
        row.addWidget(btn_set)
        row.addWidget(btn_close)
        layout.addLayout(row)

        def _apply():
            self.backend.set_channel("steerer/bias/set_u", float(spin.value()))

        btn_set.clicked.connect(_apply)
        btn_close.clicked.connect(dlg.close)

        dlg.exec_()

    def kill_source_hv(self) -> None:
        try:
            ok = self.backend.kill_source_hv()
        except Exception as e:
            QMessageBox.critical(self, "Kill Source HV", str(e))
            return

        if ok:
            self.btn_restore_source_hv.setEnabled(True)

    def restore_source_hv(self) -> None:
        try:
            ok = self.backend.restore_source_hv(ramp_s=10.0)
        except Exception as e:
            QMessageBox.critical(self, "Restore Source HV", str(e))
            return

        if not ok:
            QMessageBox.information(
                self,
                "Restore Source HV",
                "No stored source HV values available from the last kill.",
            )

    def on_channel_updated(self, name: str, value) -> None:
        if name == "mqtt_connected":
            ok = bool(value)
            self.lbl_mqtt.setText("MQTT: Connected" if ok else "MQTT: Disconnected")
            self.lbl_mqtt.setStyleSheet("color:#0a0;" if ok else "color:#a00;")
            return

    def toggle_logging(self) -> None:
        if not self._logging:
            self.backend.start_logging()
            self._logging = True
            self.btn_log.setText("Stop Logging")
            self.lbl_log.setText("LOG: ON")
            self.lbl_log.setStyleSheet("color:#0a0;")
        else:
            self.backend.stop_logging()
            self._logging = False
            self.btn_log.setText("Start Logging")
            self.lbl_log.setText("LOG: OFF")
            self.lbl_log.setStyleSheet("color:#a00;")

    def save_config(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save Config", self._last_dir or "", "JSON (*.json)")
        if not path:
            return
        try:
            self.backend.save_config(path)
            self._last_dir = path
            QMessageBox.information(self, "Config", f"Saved:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Save Config", str(e))

    def load_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load Config", self._last_dir or "", "JSON (*.json)")
        if not path:
            return
        try:
            payload = ConfigPayload.from_file(path)
        except Exception as e:
            QMessageBox.critical(self, "Load Config", f"Could not read config:\n{e}")
            return

        dlg = ConfigApplyDialog(payload, self)
        if dlg.exec_() != dlg.Accepted:
            return

        try:
            self.backend.apply_config(payload, ramp_s=dlg.ramp_seconds())
            self._last_dir = path
            QMessageBox.information(
                self,
                "Config",
                f"Loaded and ramp started:\n{path}\nRamp: {dlg.ramp_seconds():.1f} s",
            )
        except Exception as e:
            QMessageBox.critical(self, "Apply Config", str(e))