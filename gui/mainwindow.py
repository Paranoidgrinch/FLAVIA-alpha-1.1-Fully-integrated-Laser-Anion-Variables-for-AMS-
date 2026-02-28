# gui/mainwindow.py
from __future__ import annotations

from typing import Optional
from datetime import datetime

from PyQt5.QtCore import Qt
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
)

from backend.backend import Backend
from backend.services.config_service import ConfigPayload
from .qt_adapter import QtBackendAdapter

from .windows.keithley_gauge import KeithleyGaugeWindow
from .windows.keithley_plot import KeithleyPlotWindow
from .windows.pressure_monitor import PressureMonitorWindow
from .windows.tracer_1d import Tracer1DDialog
from .windows.tracer_2d import Tracer2DDialog
from .windows.pressure_monitor import PressureMonitorWindow

from .panels.ion_source import IonSourcePanel
from .panels.digital_controls import DigitalControlsPanel
from .panels.ion_optics import IonOpticsPanel
from .panels.ion_cooler import IonCoolerPanel
from .windows.rfq_mathieu_lc import RFQMathieuLCWindow
from .panels.keithley_panel import KeithleyPanel
from .panels.sample_selection import SampleSelectionPanel
from .panels.magnet_panel import MagnetPanel

from gui.dialogs.config_apply_dialog import ConfigApplyDialog


class MainWindow(QMainWindow):
    def __init__(self, backend: Backend):
        super().__init__()
        self.backend = backend
        self.adapter = QtBackendAdapter(backend)

        self.setWindowTitle("FLAVIA2 (MQTT-only) — Phase C Panels")
        self.resize(1400, 820)

        self.gauge_win: Optional[KeithleyGaugeWindow] = None
        self.plot_win: Optional[KeithleyPlotWindow] = None
        self.pressure_win: Optional[PressureMonitorWindow] = None
        self.tracer_win: Optional[Tracer1DDialog] = None
        self.tracer2d_win: Optional[Tracer2DDialog] = None
        self.rfq_win: Optional[RFQMathieuLCWindow] = None

        self._k_mean_nA: Optional[float] = None
        self._k_sigma_nA: Optional[float] = None
        self._k_t_s: Optional[float] = None

        self._logging = False
        self._last_dir = ""

        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(10, 10, 10, 10)
        main.setSpacing(10)

        # ---------------- Topbar ----------------
        top = QHBoxLayout()
        top.setSpacing(8)

        self.btn_log = QPushButton("Start Logging")
        self.btn_save = QPushButton("Save Config")
        self.btn_load = QPushButton("Load Config")

        self.btn_keithley_connect = QPushButton("Keithley Connect")
        self.btn_keithley_disconnect = QPushButton("Keithley Disconnect")
        self.btn_keithley_gauge = QPushButton("Keithley Gauge")
        self.btn_keithley_plot = QPushButton("Keithley Plot")

        # placeholders for next steps (windows)
        self.btn_pressure = QPushButton("Pressure Monitor")
        self.btn_tracer1d = QPushButton("Tracer 1D")
        self.btn_tracer2d = QPushButton("Tracer 2D")
        self.btn_mathieu = QPushButton("Mathieu + LC")

        for b in [
            self.btn_log,
            self.btn_save,
            self.btn_load,
            self.btn_keithley_connect,
            self.btn_keithley_disconnect,
            self.btn_keithley_gauge,
            self.btn_keithley_plot,
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

        # ---------------- Main panels layout ----------------
        content = QHBoxLayout()
        content.setSpacing(12)

        # Left column (scroll)
        left_wrap = QWidget()
        left_lay = QVBoxLayout(left_wrap)
        left_lay.setContentsMargins(8, 8, 8, 8)
        left_lay.setSpacing(10)

        self.panel_ion_source = IonSourcePanel(self.backend, self.adapter)
        self.panel_digital = DigitalControlsPanel(self.backend, self.adapter)   # Cup switching
        self.panel_keithley = KeithleyPanel(self.backend, self.adapter)
        self.panel_sample = SampleSelectionPanel(self.backend, self.adapter)
        self.panel_magnet = MagnetPanel(self.backend, self.adapter)

        left_lay.addWidget(self.panel_ion_source)
        left_lay.addWidget(self.panel_digital)
        left_lay.addWidget(self.panel_keithley)   # ✅ direkt unter Cup Switching
        left_lay.addWidget(self.panel_sample)     # ✅ direkt unter Keithley
        left_lay.addWidget(self.panel_magnet)     # ✅ direkt unter Sample Selection
        left_lay.addStretch(1)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(left_wrap)

        # Right column (scroll)
        right_wrap = QWidget()
        right_lay = QVBoxLayout(right_wrap)
        right_lay.setContentsMargins(8, 8, 8, 8)
        right_lay.setSpacing(10)

        self.panel_ion_optics = IonOpticsPanel(self.backend, self.adapter)
        self.panel_ion_cooler = IonCoolerPanel(self.backend, self.adapter)
        right_lay.addWidget(self.panel_ion_optics)
        right_lay.addWidget(self.panel_ion_cooler)
        right_lay.addStretch(1)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setWidget(right_wrap)

        content.addWidget(left_scroll, 3)
        content.addWidget(right_scroll, 5)

        main.addLayout(content, 1)

        # ---------------- Wiring ----------------
        self.btn_log.clicked.connect(self.toggle_logging)
        self.btn_save.clicked.connect(self.save_config)
        self.btn_load.clicked.connect(self.load_config)

        self.btn_keithley_connect.clicked.connect(self.backend.keithley.cmd_connect)
        self.btn_keithley_disconnect.clicked.connect(self.backend.keithley.cmd_disconnect)
        self.btn_keithley_gauge.clicked.connect(self.open_gauge)
        self.btn_keithley_plot.clicked.connect(self.open_plot)

        self.btn_pressure.clicked.connect(self.open_pressure_monitor)
        self.btn_tracer1d.clicked.connect(self.open_tracer_1d)
        self.btn_tracer2d.clicked.connect(self.open_tracer_2d)
        self.btn_mathieu.clicked.connect(self.open_rfq_mathieu)

        # Subscribe for status + keithley plot/gauge
        self.adapter.channelUpdated.connect(self.on_channel_updated)
        for ch in [
            "mqtt_connected",
            "keithley/current_A",
            "keithley/stats/mean_nA",
            "keithley/stats/sigma_nA",
            "keithley/stats/t_s",
        ]:
            self.adapter.register_channel(ch)

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

    def open_pressure_monitor(self) -> None:
        if self.pressure_win is None:
            self.pressure_win = PressureMonitorWindow(self.backend, self.adapter, self)
        self.pressure_win.show()
        self.pressure_win.raise_()
        self.pressure_win.activateWindow()

    def _todo(self):
        QMessageBox.information(self, "TODO", "Wiring folgt als nächster Schritt (Fenster/Worker).")

    # -------- Logging --------
    def toggle_logging(self) -> None:
        if not self._logging:
            default_name = datetime.now().strftime("flavia2_log_%Y%m%d_%H%M%S.tsv")
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Select log file",
                (self._last_dir + "/" + default_name) if self._last_dir else default_name,
                "TSV files (*.tsv);;All files (*.*)",
            )
            if not path:
                return
            self._last_dir = str(path).rsplit("/", 1)[0] if "/" in path else self._last_dir

            try:
                self.backend.start_logging(path, interval_s=1.0)
            except Exception as e:
                QMessageBox.critical(self, "Logging error", str(e))
                return

            self._logging = True
            self.btn_log.setText("Stop Logging")
            self.lbl_log.setText("LOG: ON")
            self.lbl_log.setStyleSheet("color:#060;")
        else:
            try:
                self.backend.stop_logging()
            except Exception:
                pass
            self._logging = False
            self.btn_log.setText("Start Logging")
            self.lbl_log.setText("LOG: OFF")
            self.lbl_log.setStyleSheet("color:#a00;")

    # -------- Config --------
    def save_config(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save config",
            (self._last_dir + "/flavia2_config.json") if self._last_dir else "flavia2_config.json",
            "JSON files (*.json);;All files (*.*)",
        )
        if not path:
            return
        self._last_dir = str(path).rsplit("/", 1)[0] if "/" in path else self._last_dir
        try:
            self.backend.save_config(path)
        except Exception as e:
            QMessageBox.critical(self, "Save config error", str(e))
            return
        QMessageBox.information(self, "Config saved", f"Saved to:\n{path}")

    def load_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load config",
            self._last_dir or "",
            "JSON files (*.json);;All files (*.*)",
        )
        if not path:
            return
        self._last_dir = str(path).rsplit("/", 1)[0] if "/" in path else self._last_dir
        try:
            payload: ConfigPayload = self.backend.load_config(path)
            dlg = ConfigApplyDialog(payload.setpoints, payload.states, payload.extras, self)
            if dlg.exec_() != dlg.Accepted:
                return

            selected = dlg.selected_keys()

            # Apply selected with 30s ramp
            self.backend.apply_config(payload, selected_keys=selected, ramp_s=30.0)
        except Exception as e:
            QMessageBox.critical(self, "Load config error", str(e))
            return
        QMessageBox.information(self, "Config loaded", f"Applied config from:\n{path}")

    # -------- Keithley windows --------
    def open_gauge(self) -> None:
        if self.gauge_win is None:
            self.gauge_win = KeithleyGaugeWindow(self)
        self.gauge_win.show()
        self.gauge_win.raise_()
        self.gauge_win.activateWindow()

    def open_plot(self) -> None:
        if self.plot_win is None:
            self.plot_win = KeithleyPlotWindow(self)
        self.plot_win.show()
        self.plot_win.raise_()
        self.plot_win.activateWindow()

    # -------- Model updates --------
    def on_channel_updated(self, name: str, value):
        if name == "mqtt_connected":
            ok = bool(value)
            self.lbl_mqtt.setText("MQTT: CONNECTED" if ok else "MQTT: DISCONNECTED")
            self.lbl_mqtt.setStyleSheet("color:#060;" if ok else "color:#a00;")
            return

        if name == "keithley/current_A":
            if self.gauge_win is not None and value is not None:
                try:
                    self.gauge_win.update_current_A(float(value))
                except Exception:
                    pass
            return

        if name == "keithley/stats/mean_nA":
            try:
                self._k_mean_nA = float(value)
            except Exception:
                self._k_mean_nA = None
            return

        if name == "keithley/stats/sigma_nA":
            try:
                self._k_sigma_nA = float(value)
            except Exception:
                self._k_sigma_nA = None
            return

        if name == "keithley/stats/t_s":
            try:
                self._k_t_s = float(value)
            except Exception:
                self._k_t_s = None

            if (
                self.plot_win is not None
                and self._k_t_s is not None
                and self._k_mean_nA is not None
                and self._k_sigma_nA is not None
            ):
                self.plot_win.add_point(self._k_t_s, self._k_mean_nA, self._k_sigma_nA)

    def closeEvent(self, ev):
        try:
            if self._logging:
                self.backend.stop_logging()
        except Exception:
            pass
        try:
            self.backend.stop()
        except Exception:
            pass
        super().closeEvent(ev)