import sys
import os
import time
import socket
from dataclasses import dataclass
from typing import List, Optional, Tuple

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QLabel, QPushButton, QDoubleSpinBox, QGroupBox,
    QFormLayout, QMessageBox, QFileDialog, QHBoxLayout
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPalette

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None


@dataclass
class RampSegment:
    target_a: float
    rate_a_per_min: float


class IonizerCurrentControl(QMainWindow):
    """
    Ionizer current control (Safety Critical)

    Key points:
    - MQTT per provided spec: Host/Port, QoS0, ASCII payload. :contentReference[oaicite:3]{index=3}
    - Writes at most 1 value per second (1 Hz).
    - Persists the LAST SENT value to a failsafe text file.
    - Adds Start/Stop Ionizer sequences.
    - Avoids "connect/disconnect every second" by using a unique client id by default
      (ClientId collisions are a common MQTT disconnect cause when using a fixed ClientId).
    """

    # MQTT / Topic configuration (per provided command structure)
    MQTT_HOST = "192.168.0.20"
    MQTT_PORT = 1883
    MQTT_QOS = 0

    # Spec topics for ionizer current :contentReference[oaicite:4]{index=4}
    TOPIC_CMD_SET_I_A = "cs/ionizer/cmd/set_i_a"
    TOPIC_TLM_SET_I_A = "cs/ionizer/set_i_a"
    TOPIC_TLM_MEAS_I_A = "cs/ionizer/meas_i_a"

    # Spec base ClientId (document) :contentReference[oaicite:5]{index=5}
    SPEC_CLIENT_ID = "cx-cs-source"

    # UI / safety parameters
    MAX_CURRENT = 23.0
    MAX_RAMP_RATE = 1.0
    MIN_RAMP_RATE = 0.01

    # Predefined sequences
    START_STAGE1_TARGET = 15.0
    START_STAGE1_RATE = 1.0
    START_STAGE2_TARGET = 22.0
    START_STAGE2_RATE = 0.33

    STOP_TARGET = 0.0
    STOP_RATE = 0.33

    # Timing
    RAMP_TICK_MS = 1000        # 1 Hz writes
    UI_REFRESH_MS = 250

    # Telemetry staleness threshold (seconds)
    TLM_STALE_S = 5.0

    def __init__(self):
        super().__init__()

        if mqtt is None:
            QMessageBox.critical(
                self,
                "Missing dependency",
                "The 'paho-mqtt' package is required.\n\nInstall with:\n    pip install paho-mqtt"
            )
            raise ImportError("paho-mqtt is required")

        self.setWindowTitle("Ionizer Current Control")
        self.setGeometry(100, 100, 560, 520)

        # Control variables
        self.last_sent_current_a: float = 0.0
        self.target_current_a: float = 0.0

        # MQTT status / telemetry (updated by MQTT thread; read by UI thread)
        self._mqtt_connected: bool = False
        self._mqtt_last_connect_ts: Optional[float] = None
        self._mqtt_last_disconnect_ts: Optional[float] = None
        self._mqtt_last_connect_rc: Optional[int] = None
        self._mqtt_last_disconnect_rc: Optional[int] = None

        # When we want to publish from UI thread after a connect
        self._pending_publish_value: Optional[float] = None

        # Telemetry values
        self._plc_set_current_a: Optional[float] = None
        self._plc_meas_current_a: Optional[float] = None
        self._plc_set_rx_ts: Optional[float] = None
        self._plc_meas_rx_ts: Optional[float] = None

        # Ramp state
        self._ramp_active: bool = False
        self._ramp_segments: List[RampSegment] = []
        self._ramp_segment_index: int = -1
        self._control_current_a: float = 0.0
        self._ramp_done_popup: Optional[Tuple[str, str]] = None

        # ClientId collision detection (warning once)
        self._likely_clientid_conflict: bool = False
        self._clientid_warning_shown: bool = False

        # Failsafe file (stores LAST SENT setpoint)
        self.failsafe_file = os.path.join(os.path.expanduser("~"), "ionizer_current_failsafe.txt")

        # UI init
        self.init_ui()

        # Timers
        self.ramp_timer = QTimer(self)
        self.ramp_timer.setInterval(self.RAMP_TICK_MS)
        self.ramp_timer.timeout.connect(self._on_ramp_tick)

        self.ui_timer = QTimer(self)
        self.ui_timer.setInterval(self.UI_REFRESH_MS)
        self.ui_timer.timeout.connect(self._refresh_ui)
        self.ui_timer.start()

        # MQTT init
        self._init_mqtt()

        # Load failsafe (asks the user). Publish happens when connected (or queued).
        self.load_failsafe_with_confirmation()
        self._refresh_ui()

    # ----------------------------
    # UI
    # ----------------------------
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout()
        central_widget.setLayout(layout)

        # File Operations Group
        file_group = QGroupBox("File Operations")
        file_layout = QVBoxLayout()

        self.file_status = QLabel("No backup loaded")
        self.save_button = QPushButton("Save Current")
        self.save_button.clicked.connect(self.save_to_file)
        self.load_button = QPushButton("Load Backup")
        self.load_button.clicked.connect(self.load_from_file)

        file_layout.addWidget(self.file_status)
        file_layout.addWidget(self.save_button)
        file_layout.addWidget(self.load_button)
        file_group.setLayout(file_layout)
        layout.addWidget(file_group)

        # Current Display Group
        display_group = QGroupBox("Current Status")
        display_layout = QFormLayout()

        self.meas_current_label = QLabel("--")
        self.plc_set_label = QLabel("--")
        self.target_label = QLabel("--")

        self.status_indicator = QLabel()
        self.status_indicator.setFixedSize(20, 20)
        self._set_indicator_color(Qt.gray)

        display_layout.addRow("Measured Current [A]:", self.meas_current_label)
        display_layout.addRow("PLC Setpoint [A]:", self.plc_set_label)
        display_layout.addRow("Target Current [A]:", self.target_label)
        display_layout.addRow("Status:", self.status_indicator)

        display_group.setLayout(display_layout)
        layout.addWidget(display_group)

        # Control Group
        control_group = QGroupBox("Current Control")
        control_layout = QFormLayout()

        self.ramp_rate_input = QDoubleSpinBox()
        self.ramp_rate_input.setRange(self.MIN_RAMP_RATE, self.MAX_RAMP_RATE)
        self.ramp_rate_input.setValue(0.10)
        self.ramp_rate_input.setDecimals(2)

        self.target_input = QDoubleSpinBox()
        self.target_input.setRange(0.0, self.MAX_CURRENT)
        self.target_input.setValue(0.0)
        self.target_input.setDecimals(2)

        self.ramp_button = QPushButton("Start Ramp")
        self.ramp_button.clicked.connect(self.toggle_ramp)

        seq_row = QWidget()
        seq_row_layout = QHBoxLayout()
        seq_row_layout.setContentsMargins(0, 0, 0, 0)
        seq_row.setLayout(seq_row_layout)

        self.start_ionizer_button = QPushButton("Start Ionizer")
        self.start_ionizer_button.clicked.connect(self.start_ionizer_sequence)

        self.stop_ionizer_button = QPushButton("Stop Ionizer")
        self.stop_ionizer_button.clicked.connect(self.stop_ionizer_sequence)

        seq_row_layout.addWidget(self.start_ionizer_button)
        seq_row_layout.addWidget(self.stop_ionizer_button)

        self.emergency_button = QPushButton("Emergency Stop")
        self.emergency_button.setStyleSheet("background-color: red; color: white;")
        self.emergency_button.clicked.connect(self.emergency_stop)

        control_layout.addRow(f"Ramp Rate [A/min] (Max {self.MAX_RAMP_RATE}):", self.ramp_rate_input)
        control_layout.addRow(f"Target Current [A] (Max {self.MAX_CURRENT}):", self.target_input)
        control_layout.addRow(self.ramp_button)
        control_layout.addRow(seq_row)
        control_layout.addRow(self.emergency_button)

        control_group.setLayout(control_layout)
        layout.addWidget(control_group)

        self.status_label = QLabel("Status: Initializing…")
        layout.addWidget(self.status_label)

    def _set_indicator_color(self, color: Qt.GlobalColor):
        palette = self.status_indicator.palette()
        palette.setColor(QPalette.Window, color)
        self.status_indicator.setAutoFillBackground(True)
        self.status_indicator.setPalette(palette)
        self.status_indicator.update()

    # ----------------------------
    # MQTT
    # ----------------------------
    def _build_client_id(self) -> str:
        """
        If IONIZER_MQTT_CLIENT_ID is set, use it (e.g. "cx-cs-source").
        Otherwise use a unique id to prevent client-id collisions.
        """
        override = os.environ.get("IONIZER_MQTT_CLIENT_ID", "").strip()
        if override:
            return override

        host = socket.gethostname().replace(" ", "_")
        pid = os.getpid()
        return f"{self.SPEC_CLIENT_ID}-gui-{host}-{pid}"

    def _init_mqtt(self):
        self._client_id = self._build_client_id()

        # paho-mqtt 1.x vs 2.x compatibility:
        # - 2.x may require specifying callback API version.
        try:
            if hasattr(mqtt, "CallbackAPIVersion"):
                self.mqtt_client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION1,
                    client_id=self._client_id,
                    protocol=mqtt.MQTTv311,
                    transport="tcp",
                )
            else:
                self.mqtt_client = mqtt.Client(
                    client_id=self._client_id,
                    protocol=mqtt.MQTTv311,
                    transport="tcp",
                )
        except TypeError:
            # Fallback if signature differs
            self.mqtt_client = mqtt.Client(client_id=self._client_id)

        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
        self.mqtt_client.on_message = self._on_mqtt_message

        # Reduce reconnect thrash; still reconnects, but backs off sensibly.
        try:
            self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=10)
        except Exception:
            pass

        try:
            self.mqtt_client.connect_async(self.MQTT_HOST, self.MQTT_PORT, keepalive=30)
            self.mqtt_client.loop_start()
            self._set_status_text(f"Status: Connecting to MQTT broker… (ClientId: {self._client_id})")
        except Exception as e:
            self._set_status_text(f"Status: MQTT init failed - {str(e)}")
            QMessageBox.critical(self, "Error", f"MQTT connection initialization failed:\n\n{str(e)}")

    def _on_mqtt_connect(self, client, userdata, flags, rc):
        # MQTT network thread
        self._mqtt_last_connect_ts = time.monotonic()
        self._mqtt_last_connect_rc = rc
        self._likely_clientid_conflict = False  # reset on new connect attempt

        self._mqtt_connected = (rc == 0)
        if self._mqtt_connected:
            client.subscribe(self.TOPIC_TLM_SET_I_A, qos=self.MQTT_QOS)
            client.subscribe(self.TOPIC_TLM_MEAS_I_A, qos=self.MQTT_QOS)

            # Do not publish from network thread; schedule for UI thread.
            # (Small file writes are safer in UI thread.)
            # If we had a queued publish value, keep it. It will be sent in _refresh_ui.
        else:
            # rc != 0 -> connect refused
            # paho will keep retrying; we show rc in status bar.
            pass

    def _on_mqtt_disconnect(self, client, userdata, rc):
        # MQTT network thread
        self._mqtt_last_disconnect_ts = time.monotonic()
        self._mqtt_last_disconnect_rc = rc
        was_connected = self._mqtt_connected
        self._mqtt_connected = False

        # Heuristic: disconnect very shortly after a successful connect -> often client-id collision
        if was_connected and self._mqtt_last_connect_ts is not None:
            dt = self._mqtt_last_disconnect_ts - self._mqtt_last_connect_ts
            if dt < 2.0:
                self._likely_clientid_conflict = True

    def _on_mqtt_message(self, client, userdata, msg):
        # MQTT network thread
        try:
            payload = msg.payload.decode("ascii", errors="ignore").strip()
        except Exception:
            return

        now = time.monotonic()
        val = self._parse_float(payload)
        if val is None:
            return

        if msg.topic == self.TOPIC_TLM_SET_I_A:
            self._plc_set_current_a = val
            self._plc_set_rx_ts = now
        elif msg.topic == self.TOPIC_TLM_MEAS_I_A:
            self._plc_meas_current_a = val
            self._plc_meas_rx_ts = now

    @staticmethod
    def _parse_float(s: str) -> Optional[float]:
        try:
            return float(s)
        except Exception:
            return None

    def _publish_setpoint(self, value_a: float) -> bool:
        """Publish a new ionizer setpoint (ASCII string) and persist LAST SENT to failsafe."""
        value_a = float(value_a)
        if not (0.0 <= value_a <= self.MAX_CURRENT):
            self._set_status_text(f"Status: Error - setpoint {value_a:.4f}A out of range!")
            return False

        if not self._mqtt_connected:
            # queue for later; do NOT update failsafe (failsafe must reflect last actually SENT)
            self._pending_publish_value = value_a
            self._set_status_text("Status: Not connected - setpoint queued for reconnect")
            return False

        try:
            payload = f"{value_a:.4f}"
            self.mqtt_client.publish(self.TOPIC_CMD_SET_I_A, payload=payload, qos=self.MQTT_QOS, retain=False)

            # Update last-sent tracking
            self.last_sent_current_a = value_a
            self._autosave_failsafe()
            return True
        except Exception as e:
            self._set_status_text(f"Status: Publish failed - {str(e)}")
            return False

    # ----------------------------
    # Failsafe persistence
    # ----------------------------
    def _autosave_failsafe(self):
        try:
            with open(self.failsafe_file, "w", encoding="utf-8") as f:
                f.write(f"{self.last_sent_current_a:.4f}")
        except Exception as e:
            self._set_status_text(f"Status: Autosave failed - {str(e)}")

    def _create_default_failsafe(self):
        self.last_sent_current_a = 0.0
        try:
            with open(self.failsafe_file, "w", encoding="utf-8") as f:
                f.write("0.0000")
        except Exception:
            pass
        self.file_status.setText("Created new failsafe (0A)")
        self._set_status_text("Status: Created new failsafe file with 0A")

    def load_failsafe_with_confirmation(self):
        if not os.path.exists(self.failsafe_file):
            self._create_default_failsafe()
            return

        try:
            with open(self.failsafe_file, "r", encoding="utf-8") as f:
                value = float(f.read().strip())

            if not (0.0 <= value <= self.MAX_CURRENT):
                raise ValueError("Value out of range")

            reply = QMessageBox.question(
                self, "Confirm Load",
                f"Load previously saved LAST SENT setpoint: {value:.4f}A?\n\n"
                f"This will publish the value via MQTT.",
                QMessageBox.Yes | QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                # If offline, _publish_setpoint queues; failsafe stays unchanged until actually sent.
                self._publish_setpoint(value)
                self.file_status.setText(f"Loaded/Queued: {value:.4f}A")
                self._set_status_text(f"Status: Failsafe value requested: {value:.4f}A")
            else:
                self.file_status.setText("Load cancelled")
                self._set_status_text("Status: Using default 0A - load cancelled")
        except Exception as e:
            QMessageBox.warning(self, "Load Error", f"Could not load failsafe:\n\n{str(e)}")
            self._create_default_failsafe()

    def save_to_file(self):
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Current Value",
            self.failsafe_file,
            "Text Files (*.txt);;All Files (*)",
            options=options
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(f"{self.last_sent_current_a:.4f}")

            if file_path != self.failsafe_file:
                self.failsafe_file = file_path

            self.file_status.setText(f"Saved: {self.last_sent_current_a:.4f}A")
            self._set_status_text(f"Status: Current value saved to {file_path}")
            QMessageBox.information(self, "Success", f"Value {self.last_sent_current_a:.4f}A saved successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not save file:\n\n{str(e)}")

    def load_from_file(self):
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Backup File",
            os.path.dirname(self.failsafe_file) if self.failsafe_file else "",
            "Text Files (*.txt);;All Files (*)",
            options=options
        )
        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                value = float(f.read().strip())

            if not (0.0 <= value <= self.MAX_CURRENT):
                raise ValueError(f"Value {value}A out of range (0-{self.MAX_CURRENT}A)")

            reply = QMessageBox.question(
                self, "Confirm Load",
                f"Load setpoint {value:.4f}A from file?\n\nFile: {file_path}\n\n"
                f"This will publish the value via MQTT.",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

            self._publish_setpoint(value)
            self.failsafe_file = file_path
            self.file_status.setText(f"Loaded/Queued: {value:.4f}A")
            self._set_status_text(f"Status: Loaded value from {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not load file:\n\n{str(e)}")

    # ----------------------------
    # Helper: effective current from telemetry
    # ----------------------------
    def _is_fresh(self, ts: Optional[float]) -> bool:
        return ts is not None and (time.monotonic() - ts) <= self.TLM_STALE_S

    def _effective_plc_setpoint(self) -> Optional[float]:
        if self._plc_set_current_a is not None and self._is_fresh(self._plc_set_rx_ts):
            return self._plc_set_current_a
        return None

    def _effective_plc_measured(self) -> Optional[float]:
        if self._plc_meas_current_a is not None and self._is_fresh(self._plc_meas_rx_ts):
            return self._plc_meas_current_a
        return None

    def _best_start_setpoint(self) -> float:
        plc = self._effective_plc_setpoint()
        return float(plc) if plc is not None else float(self.last_sent_current_a)

    # ----------------------------
    # Ramping / sequences
    # ----------------------------
    def toggle_ramp(self):
        if self._ramp_active:
            self.stop_ramp(user_initiated=True)
        else:
            self.start_manual_ramp()

    def start_manual_ramp(self):
        if not self._mqtt_connected:
            QMessageBox.warning(self, "Not connected", "MQTT is not connected. Cannot start ramp.")
            return

        target = float(self.target_input.value())
        rate = float(self.ramp_rate_input.value())

        if not (0.0 <= target <= self.MAX_CURRENT):
            QMessageBox.warning(self, "Error", f"Target current must be between 0 and {self.MAX_CURRENT}A")
            return
        if not (self.MIN_RAMP_RATE <= rate <= self.MAX_RAMP_RATE):
            QMessageBox.warning(self, "Error", f"Ramp rate must be between {self.MIN_RAMP_RATE} and {self.MAX_RAMP_RATE} A/min")
            return

        start = self._best_start_setpoint()
        if abs(target - start) < 1e-9:
            QMessageBox.information(self, "Info", "Already at target current.")
            return

        self.target_current_a = target
        self._start_ramp_program(
            segments=[RampSegment(target_a=target, rate_a_per_min=rate)],
            done_popup=("Complete", "Current ramp completed successfully.")
        )
        self._set_status_text(f"Status: Ramping to {target:.2f}A at {rate:.2f} A/min")

    def start_ionizer_sequence(self):
        if not self._mqtt_connected:
            QMessageBox.warning(self, "Not connected", "MQTT is not connected. Cannot start ionizer.")
            return

        start = self._best_start_setpoint()

        segments: List[RampSegment] = []
        if start < self.START_STAGE1_TARGET - 1e-9:
            segments.append(RampSegment(target_a=self.START_STAGE1_TARGET, rate_a_per_min=self.START_STAGE1_RATE))
            segments.append(RampSegment(target_a=self.START_STAGE2_TARGET, rate_a_per_min=self.START_STAGE2_RATE))
        elif start < self.START_STAGE2_TARGET - 1e-9:
            segments.append(RampSegment(target_a=self.START_STAGE2_TARGET, rate_a_per_min=self.START_STAGE2_RATE))
        else:
            QMessageBox.information(self, "Info", f"Ionizer is already at or above {self.START_STAGE2_TARGET:.2f}A.")
            return

        self.target_current_a = segments[-1].target_a
        self._start_ramp_program(
            segments=segments,
            done_popup=("Ionizer", "Ionizer start sequence complete.")
        )
        self._set_status_text("Status: Running ionizer start sequence…")

    def stop_ionizer_sequence(self):
        if not self._mqtt_connected:
            QMessageBox.warning(self, "Not connected", "MQTT is not connected. Cannot stop ionizer.")
            return

        start = self._best_start_setpoint()
        if start <= 0.0 + 1e-9:
            QMessageBox.information(self, "Info", "Ionizer is already at 0A.")
            return

        self.target_current_a = 0.0
        self._start_ramp_program(
            segments=[RampSegment(target_a=self.STOP_TARGET, rate_a_per_min=self.STOP_RATE)],
            done_popup=("Ionizer", "Ionizer stop sequence complete.")
        )
        self._set_status_text("Status: Running ionizer stop sequence…")

    def _start_ramp_program(self, segments: List[RampSegment], done_popup: Tuple[str, str]):
        self.stop_ramp(user_initiated=False)

        cleaned: List[RampSegment] = []
        for seg in segments:
            if not (0.0 <= seg.target_a <= self.MAX_CURRENT):
                QMessageBox.critical(self, "Error", f"Segment target {seg.target_a}A out of range.")
                return
            if not (self.MIN_RAMP_RATE <= seg.rate_a_per_min <= self.MAX_RAMP_RATE):
                QMessageBox.critical(self, "Error", f"Segment ramp rate {seg.rate_a_per_min} A/min out of range.")
                return
            cleaned.append(seg)

        self._ramp_segments = cleaned
        self._ramp_segment_index = 0
        self._ramp_done_popup = done_popup

        self._control_current_a = self._best_start_setpoint()
        self._ramp_active = True

        self.ramp_button.setText("Stop Ramp")
        self._set_indicator_color(Qt.yellow)

        self.start_ionizer_button.setEnabled(False)
        self.stop_ionizer_button.setEnabled(False)

        self.ramp_timer.start()

    def stop_ramp(self, user_initiated: bool):
        if self._ramp_active:
            self._ramp_active = False
            self.ramp_timer.stop()

            self._ramp_segments = []
            self._ramp_segment_index = -1
            self._ramp_done_popup = None

            self.ramp_button.setText("Start Ramp")
            self._set_indicator_color(Qt.red if user_initiated else Qt.gray)

            self.start_ionizer_button.setEnabled(True)
            self.stop_ionizer_button.setEnabled(True)

            if user_initiated:
                self._set_status_text("Status: Ramp stopped by user")

    def _on_ramp_tick(self):
        if not self._ramp_active or not self._ramp_segments:
            return

        if self._ramp_segment_index < 0 or self._ramp_segment_index >= len(self._ramp_segments):
            self._finish_ramp_program()
            return

        seg = self._ramp_segments[self._ramp_segment_index]

        step = seg.rate_a_per_min / 60.0
        if step <= 0:
            self._fail_ramp("Invalid step size.")
            return

        current = float(self._control_current_a)
        target = float(seg.target_a)
        delta = target - current

        if abs(delta) < 1e-9:
            self._advance_or_finish()
            return

        direction = 1.0 if delta > 0 else -1.0
        next_value = current + direction * step

        if (direction > 0 and next_value >= target) or (direction < 0 and next_value <= target):
            next_value = target

        next_value = max(0.0, min(self.MAX_CURRENT, next_value))

        ok = self._publish_setpoint(next_value)
        if not ok:
            self._fail_ramp("Publish failed (not connected or error).")
            return

        self._control_current_a = next_value

        if abs(next_value - target) < 1e-9:
            self._advance_or_finish()

    def _advance_or_finish(self):
        self._ramp_segment_index += 1
        if self._ramp_segment_index >= len(self._ramp_segments):
            self._finish_ramp_program()

    def _finish_ramp_program(self):
        self._ramp_active = False
        self.ramp_timer.stop()

        self.ramp_button.setText("Start Ramp")
        self._set_indicator_color(Qt.green)
        self.start_ionizer_button.setEnabled(True)
        self.stop_ionizer_button.setEnabled(True)

        self._set_status_text(f"Status: Ramp complete! Target at {self.target_current_a:.2f}A")

        if self._ramp_done_popup:
            title, msg = self._ramp_done_popup
            QMessageBox.information(self, title, msg)

        self._ramp_segments = []
        self._ramp_segment_index = -1
        self._ramp_done_popup = None

    def _fail_ramp(self, reason: str):
        self.stop_ramp(user_initiated=False)
        self._set_indicator_color(Qt.red)
        self._set_status_text(f"Status: Ramp aborted - {reason}")
        QMessageBox.warning(self, "Ramp aborted", reason)

    def emergency_stop(self):
        reply = QMessageBox.question(
            self, "Confirm",
            "EMERGENCY STOP - Publish setpoint 0A immediately?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.stop_ramp(user_initiated=False)
        ok = self._publish_setpoint(0.0)
        if ok:
            self.target_current_a = 0.0
            self._set_indicator_color(Qt.red)
            self._set_status_text("Status: EMERGENCY STOP - Setpoint published: 0A")
        else:
            QMessageBox.critical(self, "Error", "Could not publish 0A (not connected).")

    # ----------------------------
    # UI refresh / status
    # ----------------------------
    def _set_status_text(self, text: str):
        self._latest_status_text = text

    def _refresh_ui(self):
        # If connected and something is queued, send it now from UI thread.
        if self._mqtt_connected and self._pending_publish_value is not None:
            value = self._pending_publish_value
            self._pending_publish_value = None
            self._publish_setpoint(value)

        # One-time warning for likely ClientId collision
        if self._likely_clientid_conflict and (not self._clientid_warning_shown):
            self._clientid_warning_shown = True
            QMessageBox.warning(
                self,
                "MQTT connection unstable",
                "The broker is disconnecting immediately after connect.\n\n"
                "This is very often caused by another client using the SAME ClientId.\n"
                f"Current ClientId: {self._client_id}\n\n"
                "Fix:\n"
                "- Stop the other client using that ClientId, OR\n"
                "- Set a unique ClientId (e.g. set env var IONIZER_MQTT_CLIENT_ID).\n\n"
                "If your broker ACL requires the exact ClientId from the document, only one client can run at a time."
            )

        # Connection status
        if self._mqtt_connected:
            conn_txt = f"MQTT: connected ({self.MQTT_HOST}:{self.MQTT_PORT})"
        else:
            extra = ""
            if self._mqtt_last_connect_rc is not None and self._mqtt_last_connect_rc != 0:
                extra = f" (connect rc={self._mqtt_last_connect_rc})"
            elif self._mqtt_last_disconnect_rc is not None and self._mqtt_last_disconnect_rc != 0:
                extra = f" (disconnect rc={self._mqtt_last_disconnect_rc})"
            conn_txt = f"MQTT: disconnected ({self.MQTT_HOST}:{self.MQTT_PORT}){extra}"

        # Telemetry values
        meas = self._effective_plc_measured()
        plc_set = self._effective_plc_setpoint()

        self.meas_current_label.setText("--" if meas is None else f"{meas:.4f}")
        self.plc_set_label.setText("--" if plc_set is None else f"{plc_set:.4f}")
        self.target_label.setText(f"{self.target_current_a:.4f}")

        base_status = getattr(self, "_latest_status_text", "Status: Ready")
        self.status_label.setText(f"{base_status}    |    {conn_txt}    |    ClientId: {self._client_id}")

        # Enable/disable controls based on connection
        can_control = self._mqtt_connected
        self.ramp_button.setEnabled(can_control or self._ramp_active)
        self.start_ionizer_button.setEnabled(can_control and (not self._ramp_active))
        self.stop_ionizer_button.setEnabled(can_control and (not self._ramp_active))
        self.emergency_button.setEnabled(can_control)

    # ----------------------------
    # Qt events
    # ----------------------------
    def closeEvent(self, event):
        if self._ramp_active:
            if QMessageBox.question(
                self, "Ramp Active",
                "A ramp is in progress. Really quit?",
                QMessageBox.Yes | QMessageBox.No
            ) == QMessageBox.No:
                event.ignore()
                return

        self._autosave_failsafe()

        try:
            if hasattr(self, "mqtt_client") and self.mqtt_client is not None:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
        except Exception:
            pass

        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = IonizerCurrentControl()
    window.show()
    sys.exit(app.exec_())
