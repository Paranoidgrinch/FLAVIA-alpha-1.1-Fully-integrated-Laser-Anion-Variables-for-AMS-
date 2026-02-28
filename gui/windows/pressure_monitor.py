# gui/windows/pressure_monitor.py
from __future__ import annotations

import socket
import re
import math
import datetime
from functools import partial
from collections import deque
from typing import Optional, Dict

from PyQt5 import QtCore, QtWidgets, QtGui

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.dates as mdates


# === GRAPHIX Connection defaults (wie vorher) ===
DEVICE_A_IP = "192.168.0.15"   # Ion Cooler Graphix
DEVICE_A_PORT = 100

DEVICE_B_IP = "192.168.0.16"   # ESA Graphix
DEVICE_B_PORT = 100

POLL_MS = 1000

SO = bytes([0x0E])
SI = bytes([0x0F])
EOT = bytes([0x04])


# === Thyracont Kennlinie (wie vorher) ===
V_MIN, V_MAX = 1.8, 8.6
def voltage_to_mbar(u: float) -> float:
    """Thyracont VSM72MV: V = 0.6*log10(p) + 6.8 -> p [mbar]."""
    if u is None or (isinstance(u, float) and math.isnan(u)):
        return float("nan")
    if u < V_MIN:
        u = V_MIN
    elif u > V_MAX:
        u = V_MAX
    return 10 ** ((u - 6.8) / 0.6)

# Offset nur für Vac2 (wie vorher)
CH2_OFFSET = 0.245


# === Kanal-Namen ===
GRAPHIX_KEYS = ["A1", "A2", "A3", "B1"]
MQTT_VAC_KEYS = ["OP1", "OP2"]
ALL_KEYS = GRAPHIX_KEYS + MQTT_VAC_KEYS

LEFT_Y_KEYS = ["A1", "A2"]
RIGHT_Y_KEYS = ["A3", "B1", "OP1", "OP2"]

DISPLAY_NAMES = {
    "A1": "INJ",
    "A2": "RFQ",
    "A3": "INJ Ref",
    "B1": "ESA",
    "OP1": "Vac 1",
    "OP2": "Vac 2",
}

COLOR_MAP = {
    "A1": "#1f77b4",
    "A2": "#ff7f0e",
    "A3": "#2ca02c",
    "B1": "#d62728",
    "OP1": "#9467bd",
    "OP2": "#000000",
}


def leybold_crc(payload: bytes) -> bytes:
    s = sum(payload) % 256
    c = 255 - s
    if c < 32:
        c += 32
    return bytes([c])

def build_read(group: int, param: int) -> bytes:
    body = f"{group};{param}".encode("ascii")
    payload = SI + body
    return payload + leybold_crc(payload) + EOT

def parse_ack_value(resp: bytes) -> str:
    if not resp:
        return ""
    if resp.endswith(EOT):
        resp = resp[:-1]
    if len(resp) >= 1:
        resp = resp[:-1]
    try:
        idx = resp.index(b"\x06") + 1
        val = resp[idx:]
    except ValueError:
        val = resp
    return val.decode("ascii", errors="ignore").strip()

def to_mbar(value_with_unit: str):
    m = re.search(r"([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)(?:\s*([A-Za-z]+))?", value_with_unit)
    if not m:
        return None, None
    val = float(m.group(1))
    unit = (m.group(2) or "").lower()
    if unit in ("mbar", "mbar."):
        return val, "mbar"
    if unit in ("pa", "pa."):
        return val / 100.0, "mbar"
    if unit in ("torr", "tor", "mmhg"):
        return val * 1.33322, "mbar"
    return val, "mbar"

def format_sci(val: float):
    if val is None or (isinstance(val, float) and (math.isnan(val) or val == 0)):
        return "0 mbar"
    exp = int(math.floor(math.log10(abs(val))))
    if -2 <= exp <= 2:
        return f"{val:.6g} mbar"
    a = val / (10 ** exp)
    return f"{a:.3g} × 10^{exp} mbar"

def html_sci(text: str) -> str:
    s = text.replace("10^", "10<sup>")
    s = s.replace(" mbar", "</sup> mbar") if "<sup>" in s else s
    return s


class TcpClient:
    def __init__(self, host, port, timeout=2.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None

    def connect(self):
        self.close()
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        finally:
            self.sock = None

    def xfer(self, frame: bytes) -> bytes:
        if not self.sock:
            self.connect()
        self.sock.sendall(frame)
        chunks = []
        while True:
            chunk = self.sock.recv(1024)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\x04" in chunk:
                break
        return b"".join(chunks)


class GraphixWorker(QtCore.QObject):
    resultsReady = QtCore.pyqtSignal(dict, dict)  # (values_mbar, raw_map)
    error = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self.clients = {}
        self._poll_items = []
        self._poll_index = 0
        self._latest_values = {key: None for key in GRAPHIX_KEYS}
        self._latest_raw = {key: "" for key in GRAPHIX_KEYS}
        self._timer = None

    @QtCore.pyqtSlot()
    def start(self):
        self._running = True
        self.clients = {}
        self._poll_items = []
        self._poll_index = 0
        self._latest_values = {key: None for key in GRAPHIX_KEYS}
        self._latest_raw = {key: "" for key in GRAPHIX_KEYS}

        config = {
            "A": (DEVICE_A_IP, DEVICE_A_PORT),
            "B": (DEVICE_B_IP, DEVICE_B_PORT),
        }

        for dev in ("A", "B"):
            host, port = config[dev]
            try:
                client = TcpClient(host, port, timeout=2.0)
                client.connect()
                self.clients[dev] = client

                channels = (1, 2, 3) if dev == "A" else (1,)
                for ch in channels:
                    frame = build_read(ch, 29)
                    key = f"{dev}{ch}"
                    if key in GRAPHIX_KEYS:
                        self._poll_items.append((dev, ch, frame))
            except Exception as e:
                name = "Ion Cooler Graphix" if dev == "A" else "ESA Graphix"
                self.error.emit(f"Connection failed ({name}): {e}")

        if not self._poll_items:
            self.error.emit("No GRAPHIX device configured/connected.")
            return

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll_step)
        self._timer.start()

    @QtCore.pyqtSlot()
    def stop(self):
        self._running = False
        if self._timer is not None:
            self._timer.stop()
        for c in self.clients.values():
            try:
                c.close()
            except Exception:
                pass
        self.clients = {}
        self._poll_items = []

    @QtCore.pyqtSlot()
    def _poll_step(self):
        if not self._running or not self._poll_items:
            return

        dev, ch, frame = self._poll_items[self._poll_index]
        client = self.clients.get(dev)
        if not client:
            self._poll_index = (self._poll_index + 1) % len(self._poll_items)
            return

        key = f"{dev}{ch}"  # A1/A2/A3/B1
        try:
            resp = client.xfer(frame)
            raw = parse_ack_value(resp)
            val_mbar, _ = to_mbar(raw)
            self._latest_values[key] = val_mbar
            self._latest_raw[key] = raw
        except Exception as e:
            self._latest_values[key] = None
            self._latest_raw[key] = f"ERROR {e}"
            try:
                client.connect()
            except Exception:
                pass

        if self._poll_index == len(self._poll_items) - 1:
            self.resultsReady.emit(dict(self._latest_values), dict(self._latest_raw))

        self._poll_index = (self._poll_index + 1) % len(self._poll_items)


class PlotCanvas(FigureCanvas):
    def __init__(self, parent=None, max_points=600):
        self.fig = Figure(figsize=(5, 4), tight_layout=True)
        super().__init__(self.fig)
        self.setParent(parent)

        self.ax_left = self.fig.add_subplot(111)
        self.ax_right = self.ax_left.twinx()

        self.max_points = max_points
        self.t = deque(maxlen=max_points)
        self.y = {key: deque(maxlen=max_points) for key in ALL_KEYS}

        self.lines = {}

        for key in LEFT_Y_KEYS:
            color = COLOR_MAP.get(key, None)
            label = DISPLAY_NAMES.get(key, key)
            (ln,) = self.ax_left.plot([], [], label=label, color=color)
            self.lines[key] = ln

        for key in RIGHT_Y_KEYS:
            color = COLOR_MAP.get(key, None)
            label = DISPLAY_NAMES.get(key, key)
            (ln,) = self.ax_right.plot([], [], label=label, color=color)
            self.lines[key] = ln

        self.plot_enabled = {key: False for key in ALL_KEYS}

        self.ax_left.set_xlabel("Time")
        self.ax_left.set_ylabel("INJ / RFQ (mbar)")
        self.ax_right.set_ylabel("INJ Ref / ESA / Vac 1 / Vac 2 (mbar)")
        self.ax_left.grid(True, which="both", linestyle="--", alpha=0.3)

        self.ax_left.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        self.ax_left.xaxis.set_major_locator(mdates.AutoDateLocator())

        all_lines = list(self.lines.values())
        labels = [ln.get_label() for ln in all_lines]
        self.ax_left.legend(all_lines, labels, loc="upper right")

    def set_plot_enabled(self, key: str, enabled: bool):
        self.plot_enabled[key] = enabled
        self.redraw()

    def append_point(self, when: datetime.datetime, values: dict):
        self.t.append(when)
        for key in ALL_KEYS:
            self.y[key].append(values.get(key, float("nan")))

    def redraw(self):
        if not self.t:
            return
        x = mdates.date2num(list(self.t))

        for key, ln in self.lines.items():
            if not self.plot_enabled.get(key, False):
                ln.set_data([], [])
            else:
                ln.set_data(x, list(self.y[key]))

        self.ax_left.relim()
        self.ax_left.autoscale_view()

        self.ax_right.relim()
        self.ax_right.autoscale_view()

        self.ax_left.set_xlim(x[0], x[-1] if len(x) > 1 else x[0] + 1 / 86400.0)
        self.draw_idle()


class PressureMonitorWindow(QtWidgets.QDialog):
    """
    Integrated Pressure Monitor:
      - GRAPHIX pressures via TCP polling (A1,A2,A3,B1)
      - Vac1/Vac2 via MQTT channels in DataModel: cs/vac1/meas_v, cs/vac2/meas_v
      - Pressure control via Backend: pressure/set_v (+ show pressure/meas_v)
    """
    def __init__(self, backend, adapter, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.adapter = adapter

        self.setWindowTitle("Ion Cooler / ESA Graphix Monitor")
        self.resize(1100, 750)

        # Top row: Start/Stop + logging
        self.startBtn = QtWidgets.QPushButton("Start")
        self.stopBtn = QtWidgets.QPushButton("Stop")
        self.stopBtn.setEnabled(False)

        self.logEnable = QtWidgets.QCheckBox("Enable logging (TXT)")
        self.logPathBtn = QtWidgets.QPushButton("Choose file…")
        self.logPathBtn.setEnabled(False)
        self.logPathLbl = QtWidgets.QLabel("—")

        topRow = QtWidgets.QHBoxLayout()
        topRow.addWidget(self.startBtn)
        topRow.addWidget(self.stopBtn)
        topRow.addSpacing(20)
        topRow.addWidget(self.logEnable)
        topRow.addWidget(self.logPathBtn)
        topRow.addWidget(self.logPathLbl, 1)

        # Plot + channel labels
        self.channel_labels: Dict[str, QtWidgets.QLabel] = {}
        self.channel_plot_checks: Dict[str, QtWidgets.QCheckBox] = {}
        self.canvas = PlotCanvas(self, max_points=600)

        # PLC Vac (now MQTT) left
        plcGB = QtWidgets.QGroupBox("PLC Vac (MQTT)")
        plcLayout = QtWidgets.QGridLayout(plcGB)

        lbl_v1 = QtWidgets.QLabel("Vac 1: —")
        f = lbl_v1.font()
        f.setPointSize(18)
        lbl_v1.setFont(f)
        chk_v1 = QtWidgets.QCheckBox("Plot")
        self.channel_labels["OP1"] = lbl_v1
        self.channel_plot_checks["OP1"] = chk_v1
        chk_v1.toggled.connect(lambda state, k="OP1": self.canvas.set_plot_enabled(k, state))
        plcLayout.addWidget(lbl_v1, 0, 0)
        plcLayout.addWidget(chk_v1, 0, 1)

        lbl_v2 = QtWidgets.QLabel("Vac 2: —")
        f = lbl_v2.font()
        f.setPointSize(18)
        lbl_v2.setFont(f)
        chk_v2 = QtWidgets.QCheckBox("Plot")
        self.channel_labels["OP2"] = lbl_v2
        self.channel_plot_checks["OP2"] = chk_v2
        chk_v2.toggled.connect(lambda state, k="OP2": self.canvas.set_plot_enabled(k, state))
        plcLayout.addWidget(lbl_v2, 1, 0)
        plcLayout.addWidget(chk_v2, 1, 1)

        # ESA Graphix
        esaGB = QtWidgets.QGroupBox("ESA Graphix")
        esaLayout = QtWidgets.QGridLayout(esaGB)
        lbl_esa = QtWidgets.QLabel("ESA: —")
        f = lbl_esa.font()
        f.setPointSize(18)
        lbl_esa.setFont(f)
        chk_esa = QtWidgets.QCheckBox("Plot")
        self.channel_labels["B1"] = lbl_esa
        self.channel_plot_checks["B1"] = chk_esa
        chk_esa.toggled.connect(lambda state, k="B1": self.canvas.set_plot_enabled(k, state))
        esaLayout.addWidget(lbl_esa, 0, 0)
        esaLayout.addWidget(chk_esa, 0, 1)

        # Ion Cooler Graphix
        ionGB = QtWidgets.QGroupBox("Ion Cooler Graphix")
        ionLayout = QtWidgets.QGridLayout(ionGB)
        ion_channels = [("A1", "INJ"), ("A2", "RFQ"), ("A3", "INJ Ref")]
        for row, (key, label_text) in enumerate(ion_channels):
            lbl = QtWidgets.QLabel(f"{label_text}: —")
            f = lbl.font()
            f.setPointSize(18)
            lbl.setFont(f)
            chk = QtWidgets.QCheckBox("Plot")
            self.channel_labels[key] = lbl
            self.channel_plot_checks[key] = chk
            chk.toggled.connect(lambda state, k=key: self.canvas.set_plot_enabled(k, state))
            ionLayout.addWidget(lbl, row, 0)
            ionLayout.addWidget(chk, row, 1)

        leftColWidget = QtWidgets.QWidget()
        leftColLayout = QtWidgets.QVBoxLayout(leftColWidget)
        leftColLayout.setContentsMargins(0, 0, 0, 0)
        leftColLayout.addWidget(plcGB)
        leftColLayout.addWidget(esaGB)

        deviceRow = QtWidgets.QHBoxLayout()
        deviceRow.addWidget(leftColWidget, 1)
        deviceRow.addWidget(ionGB, 1)

        # Pressure control (MQTT via backend)
        mqttGB = QtWidgets.QGroupBox("Pressure Control (MQTT, 0–10 V)")
        mqttLayout = QtWidgets.QHBoxLayout(mqttGB)

        self.mqttConnLabel = QtWidgets.QLabel("MQTT: —")
        self.mqttConnLabel.setStyleSheet("color:#888")

        self.pSet = QtWidgets.QDoubleSpinBox()
        self.pSet.setDecimals(2)
        self.pSet.setRange(0, 10)
        self.pSet.setSingleStep(0.01)
        self.pSet.setKeyboardTracking(False)
        self.pSet.setAccelerated(True)

        self.pSetBtn = QtWidgets.QPushButton("Set Pressure (V)")
        self.pMeasV = QtWidgets.QLabel("-")

        # NEW: derived pressure labels (mbar)
        self.pSetMbar = QtWidgets.QLabel("—")
        self.pMeasMbar = QtWidgets.QLabel("—")
        f = self.pSetMbar.font()
        f.setPointSize(14)
        f.setBold(True)
        self.pSetMbar.setFont(f)
        self.pMeasMbar.setFont(f)

        mqttLayout.addWidget(self.mqttConnLabel)
        mqttLayout.addStretch(1)
        mqttLayout.addWidget(QtWidgets.QLabel("Pressure (0–10 V)"))
        mqttLayout.addWidget(self.pSet)
        mqttLayout.addWidget(self.pSetBtn)

        mqttLayout.addWidget(QtWidgets.QLabel("set → mbar"))
        mqttLayout.addWidget(self.pSetMbar)

        mqttLayout.addWidget(QtWidgets.QLabel("meas_v"))
        mqttLayout.addWidget(self.pMeasV)

        mqttLayout.addWidget(QtWidgets.QLabel("meas → mbar"))
        mqttLayout.addWidget(self.pMeasMbar)

        # Main layout
        v = QtWidgets.QVBoxLayout(self)
        v.addLayout(topRow)
        v.addLayout(deviceRow)
        v.addWidget(mqttGB)
        v.addWidget(self.canvas, 1)

        # timers
        self.timer_plot = QtCore.QTimer(self)
        self.timer_plot.setInterval(1000)
        self.timer_plot.timeout.connect(self.canvas.redraw)

        self.timer_log = QtCore.QTimer(self)
        self.timer_log.setInterval(1000)
        self.timer_log.timeout.connect(self.write_log_line)

        # worker thread for graphix
        self.graphix_thread = None
        self.graphix_worker = None

        self.latest = {key: None for key in ALL_KEYS}
        self.latest_raw = {key: "" for key in ALL_KEYS}

        self._log_file = None
        self._log_path = None
        self._log_active = False

        # wiring
        self.startBtn.clicked.connect(self.on_start)
        self.stopBtn.clicked.connect(self.on_stop)

        self.logEnable.toggled.connect(self.on_toggle_logging)
        self.logPathBtn.clicked.connect(self.choose_log_path)

        self.pSetBtn.clicked.connect(self._publish_pressure_set)
        self.pSet.editingFinished.connect(self.pSetBtn.click)

        # subscribe to model channels
        self.adapter.channelUpdated.connect(self._on_channel_update)
        for ch in [
            "mqtt_connected",
            "pressure/set_v",
            "pressure/meas_v",
            "cs/vac1/meas_v",
            "cs/vac2/meas_v",
        ]:
            self.adapter.register_channel(ch)

        # initialize mqtt label
        self._update_mqtt_label()

    def _set_pressure_labels_from_v(self, *, set_v: float | None = None, meas_v: float | None = None) -> None:
        if set_v is not None:
            p = voltage_to_mbar(float(set_v))
            self.pSetMbar.setText(html_sci(format_sci(p)) if p == p else "—")
        if meas_v is not None:
            p = voltage_to_mbar(float(meas_v))
            self.pMeasMbar.setText(html_sci(format_sci(p)) if p == p else "—")

    # --- logging ---
    def choose_log_path(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Choose log file (TXT)", filter="Text file (*.txt)")
        if path:
            if not path.lower().endswith(".txt"):
                path += ".txt"
            self._log_path = path
            self.logPathLbl.setText(path)

    def on_toggle_logging(self, checked: bool):
        if checked:
            self.logPathBtn.setEnabled(True)
            if not self._log_path:
                self.choose_log_path()
                if not self._log_path:
                    self.logEnable.setChecked(False)
                    return
            ok = QtWidgets.QMessageBox.question(
                self, "Enable logging",
                f"Write measurements to\n\n{self._log_path}\n\nevery second?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.Yes,
            )
            if ok == QtWidgets.QMessageBox.Yes:
                try:
                    self._log_file = open(self._log_path, "a", encoding="utf-8")
                    self._log_file.write("# time (ISO8601Z); channel; value_mbar; pretty; raw\n")
                    self._log_file.flush()
                    self._log_active = True
                    self.timer_log.start()
                except Exception as e:
                    QtWidgets.QMessageBox.critical(self, "Logging failed", str(e))
                    self.logEnable.setChecked(False)
            else:
                self.logEnable.setChecked(False)
        else:
            self.logPathBtn.setEnabled(False)
            self.stop_logging()

    def stop_logging(self):
        self.timer_log.stop()
        self._log_active = False
        try:
            if self._log_file:
                self._log_file.flush()
                self._log_file.close()
        finally:
            self._log_file = None

    def write_log_line(self):
        if not self._log_active or not self._log_file:
            return
        now = datetime.datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
        for key in ALL_KEYS:
            val = self.latest.get(key, None)
            raw = self.latest_raw.get(key, "")
            if val is None:
                continue
            pretty = format_sci(val)
            self._log_file.write(f"{now}; {key}; {val:.9g}; {pretty}; raw: {raw}\n")
        self._log_file.flush()

    # --- graphix start/stop ---
    def _stop_graphix_thread(self):
        if self.graphix_worker is not None:
            QtCore.QMetaObject.invokeMethod(self.graphix_worker, "stop", QtCore.Qt.QueuedConnection)
        if self.graphix_thread is not None:
            self.graphix_thread.quit()
            self.graphix_thread.wait(2000)
        self.graphix_worker = None
        self.graphix_thread = None

    def on_start(self):
        self._stop_graphix_thread()

        self.graphix_thread = QtCore.QThread(self)
        self.graphix_worker = GraphixWorker()
        self.graphix_worker.moveToThread(self.graphix_thread)

        self.graphix_thread.started.connect(self.graphix_worker.start)
        self.graphix_worker.resultsReady.connect(self.on_graphix_results)
        self.graphix_worker.error.connect(self.on_graphix_error)
        self.graphix_thread.start()

        self.timer_plot.start()
        self.startBtn.setEnabled(False)
        self.stopBtn.setEnabled(True)

    def on_stop(self):
        self.timer_plot.stop()
        self.stop_logging()
        self._stop_graphix_thread()

        self.startBtn.setEnabled(True)
        self.stopBtn.setEnabled(False)

    def on_graphix_results(self, values: dict, raw_map: dict):
        for key, val in values.items():
            if key in GRAPHIX_KEYS:
                self.latest[key] = val
        for key, raw in raw_map.items():
            if key in GRAPHIX_KEYS:
                self.latest_raw[key] = raw

        for key in GRAPHIX_KEYS:
            lbl = self.channel_labels.get(key)
            if lbl is None:
                continue
            name = DISPLAY_NAMES.get(key, key)
            val = self.latest.get(key, None)
            if val is None or (isinstance(val, float) and math.isnan(val)):
                lbl.setText(f"{name}: —")
            else:
                lbl.setText(f"{name}: " + html_sci(format_sci(val)))

        # Plot point (graphix + latest vac)
        now = datetime.datetime.utcnow()
        values_for_plot = {k: self.latest.get(k, float("nan")) for k in ALL_KEYS}
        self.canvas.append_point(now, values_for_plot)

    def on_graphix_error(self, msg: str):
        QtWidgets.QMessageBox.warning(self, "GRAPHIX error", msg)

    # --- pressure control ---
    def _publish_pressure_set(self):
        try:
            self.backend.set_channel("pressure/set_v", float(self.pSet.value()))
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Publish failed", str(e))

    # --- model updates (MQTT via DataModel) ---
    def _update_mqtt_label(self):
        ch = self.backend.model.get("mqtt_connected")
        ok = bool(ch.value) if ch and ch.value is not None else False
        self.mqttConnLabel.setText("MQTT: CONNECTED" if ok else "MQTT: DISCONNECTED")
        self.mqttConnLabel.setStyleSheet("color:#060" if ok else "color:#a00")

    def _update_vac(self, key: str, voltage_v: float, raw: str):
        p = voltage_to_mbar(voltage_v)
        self.latest[key] = p
        self.latest_raw[key] = raw

        lbl = self.channel_labels.get(key)
        if lbl is None:
            return
        name = DISPLAY_NAMES.get(key, key)
        if p is None or (isinstance(p, float) and math.isnan(p)):
            lbl.setText(f"{name}: —")
        else:
            lbl.setText(f"{name}: " + html_sci(format_sci(p)))

    def _on_channel_update(self, name: str, value):
        if name == "mqtt_connected":
            self._update_mqtt_label()
            return

        if name == "pressure/set_v":
            try:
                self.pSet.blockSignals(True)
                self.pSet.setValue(float(value))
            except Exception:
                pass
            finally:
                self.pSet.blockSignals(False)
            return
        

        if name == "pressure/meas_v":
            try:
                self.pMeasV.setText(f"{float(value):.3f}")
            except Exception:
                self.pMeasV.setText(str(value))
            return  

        

        if name == "cs/vac1/meas_v":
            try:
                u1 = float(value)
            except Exception:
                u1 = float("nan")
            self._update_vac("OP1", u1, raw=f"U1={u1}")
            return

        if name == "cs/vac2/meas_v":
            try:
                u2 = float(value)
            except Exception:
                u2 = float("nan")
            if not math.isnan(u2):
                u2 = u2 + CH2_OFFSET
            self._update_vac("OP2", u2, raw=f"U2corr={u2}")
            return

    def closeEvent(self, ev):
        try:
            self.on_stop()
        except Exception:
            pass
        super().closeEvent(ev)