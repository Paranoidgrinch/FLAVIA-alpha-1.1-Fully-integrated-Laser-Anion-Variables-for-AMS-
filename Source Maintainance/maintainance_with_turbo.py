# -*- coding: utf-8 -*-
"""
Source_Maintainance_MQTT.py

PyQt5 GUI for ion source maintenance control via MQTT
plus turbopump control via RS232-over-Ethernet (EX-6030).

Digital channels:
- Publish: cs/<channel>/cmd/set  payload "1" or "0" (first char is evaluated)
- Telemetry: cs/<channel>/state payload "1" or "0"

MQTT Broker:
- Host: 192.168.0.20
- Port: 1883
- QoS: 0

Turbopump gateway:
- Host: 192.168.0.21
- Port: 100

Notes:
- Uses a unique MQTT client id by default to avoid connect/disconnect loops caused by ClientId collisions.
  You can override via env var: MAINT_MQTT_CLIENT_ID
"""

import sys
import os
import time
import socket
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QGroupBox, QMessageBox, QDialog,
    QFormLayout, QScrollArea
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QPalette, QFont

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None


@dataclass(frozen=True)
class DigitalChannel:
    key: str
    cmd_set_topic: str
    state_topic: str


class StateIndicator(QLabel):
    """
    Small colored square:
    - Green / Red for bool states
    - Gray for unknown
    - Can also be set to arbitrary colors for multi-state indicators
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(20, 20)
        self.set_color(None)

    def set_color(self, color: Optional[QColor]):
        palette = self.palette()
        if color is None:
            color = QColor(160, 160, 160)
        palette.setColor(QPalette.Window, color)
        self.setAutoFillBackground(True)
        self.setPalette(palette)
        self.update()

    def set_state(self, state: Optional[bool]):
        if state is None:
            self.set_color(None)
        else:
            self.set_color(QColor(0, 255, 0) if state else QColor(255, 0, 0))


class MaintenanceGuide(QDialog):
    """
    Step-by-step guide dialog.

    Changes:
    - Starts large enough to read the full text without manual resizing.
    - Uses a scroll area for long steps.
    """
    def __init__(self, steps, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)

        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            w = int(min(1000, geo.width() * 0.70))
            h = int(min(700, geo.height() * 0.60))
        else:
            w, h = 900, 600

        self.resize(w, h)
        self.setMinimumSize(int(w * 0.85), int(h * 0.85))

        layout = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        content_layout = QVBoxLayout(content)

        self.step_label = QLabel()
        self.step_label.setWordWrap(True)
        self.step_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        font = QFont()
        font.setPointSize(11)
        self.step_label.setFont(font)
        content_layout.addWidget(self.step_label)

        self.current_step = 0
        self.steps = steps

        self.next_button = QPushButton("Next Step")
        self.next_button.clicked.connect(self.next_step)
        layout.addWidget(self.next_button)

        self.update_step()

    def update_step(self):
        if self.current_step < len(self.steps):
            step_text = self.steps[self.current_step]
            self.step_label.setText(f"Step {self.current_step + 1}: {step_text}")
            if self.current_step == len(self.steps) - 1:
                self.next_button.setText("Finish")
            else:
                self.next_button.setText("Next Step")

    def next_step(self):
        self.current_step += 1
        if self.current_step >= len(self.steps):
            self.accept()
        else:
            self.update_step()


class IonizerMaintenanceControl(QMainWindow):
    # ----------------------------
    # MQTT broker settings
    # ----------------------------
    MQTT_HOST = "192.168.0.20"
    MQTT_PORT = 1883
    MQTT_QOS = 0

    # Base client id from spec; we derive a unique id by default
    SPEC_CLIENT_ID = "cx-cs-source"

    # ----------------------------
    # Turbopump / EX-6030 settings
    # ----------------------------
    TURBO_HOST = "192.168.0.21"
    TURBO_PORT = 100
    TURBO_CONNECT_TIMEOUT_S = 2.0
    TURBO_SOCKET_TIMEOUT_S = 5.0
    TURBO_STATUS_POLL_S = .0

    # ----------------------------
    # General UI / telemetry
    # ----------------------------
    STATE_STALE_S = 5.0
    UI_REFRESH_MS = 250

    # If True: publish to cs/<ch>/cmd/set with payload "1"/"0"
    # If False: publish to cs/<ch>/cmd/set_1 or set_0 topics (payload can be empty)
    USE_SET_PAYLOAD_TOPIC = True

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ion Source Maintenance Control")
        self.setGeometry(100, 100, 800, 860)
        self.setMinimumWidth(800)
        self.setMinimumHeight(860)

        if mqtt is None:
            QMessageBox.critical(
                self,
                "Missing dependency",
                "The 'paho-mqtt' package is required.\n\nInstall with:\n    pip install paho-mqtt"
            )
            raise ImportError("paho-mqtt is required")

        # Digital channels
        self.channels: Dict[str, DigitalChannel] = {
            "source_valve": DigitalChannel(
                key="source_valve",
                cmd_set_topic="cs/source_valve/cmd/set",
                state_topic="cs/source_valve/state"
            ),
            "pump": DigitalChannel(
                key="pump",
                cmd_set_topic="cs/pump/cmd/set",
                state_topic="cs/pump/state"
            ),
            "wheel": DigitalChannel(
                key="wheel",
                cmd_set_topic="cs/wheel/cmd/set",
                state_topic="cs/wheel/state"
            ),
            "pump_valve": DigitalChannel(
                key="pump_valve",
                cmd_set_topic="cs/pump_valve/cmd/set",
                state_topic="cs/pump_valve/state"
            ),
            "vent": DigitalChannel(
                key="vent",
                cmd_set_topic="cs/vent/cmd/set",
                state_topic="cs/vent/state"
            ),
        }

        # MQTT / state caches
        self._mqtt_connected: bool = False
        self._mqtt_last_connect_ts: Optional[float] = None
        self._mqtt_last_disconnect_ts: Optional[float] = None
        self._mqtt_last_connect_rc: Optional[int] = None
        self._mqtt_last_disconnect_rc: Optional[int] = None

        self._likely_clientid_conflict: bool = False
        self._clientid_warning_shown: bool = False

        self._state_values: Dict[str, Optional[bool]] = {k: None for k in self.channels.keys()}
        self._state_rx_ts: Dict[str, Optional[float]] = {k: None for k in self.channels.keys()}

        # Turbopump / converter status caches
        self._turbo_converter_connected: bool = False
        self._turbo_status_code: Optional[int] = None
        self._turbo_last_status_ts: Optional[float] = None
        self._turbo_last_probe_ts: float = 0.0
        self._turbo_last_error: Optional[str] = None

        # UI
        self._latest_status_text = "Status: Initializing…"
        self.init_ui()

        # MQTT
        self._init_mqtt()

        # UI timer
        self.ui_timer = QTimer(self)
        self.ui_timer.setInterval(self.UI_REFRESH_MS)
        self.ui_timer.timeout.connect(self.update_states)
        self.ui_timer.start()

    # ----------------------------
    # UI
    # ----------------------------
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Maintenance Guides
        guide_group = QGroupBox("Maintenance Guides")
        guide_layout = QHBoxLayout()
        self.open_guide_btn = QPushButton("Open Source Guide")
        self.open_guide_btn.clicked.connect(self.show_open_guide)
        self.close_guide_btn = QPushButton("Close Source Guide")
        self.close_guide_btn.clicked.connect(self.show_close_guide)
        guide_layout.addWidget(self.open_guide_btn)
        guide_layout.addWidget(self.close_guide_btn)
        guide_group.setLayout(guide_layout)
        main_layout.addWidget(guide_group)

        # State indicators
        state_group = QGroupBox("Source States")
        state_layout = QFormLayout()

        self.wheel_indicator = StateIndicator()
        state_layout.addRow("Sample Wheel Retracted:", self.wheel_indicator)

        self.source_valve_indicator = StateIndicator()
        state_layout.addRow("Source Valve Closed:", self.source_valve_indicator)

        self.vent_indicator = StateIndicator()
        state_layout.addRow("Venting Active:", self.vent_indicator)

        self.pump_valve_indicator = StateIndicator()
        state_layout.addRow("Pump Valve Open:", self.pump_valve_indicator)

        self.pump_indicator = StateIndicator()
        state_layout.addRow("Pumping Active:", self.pump_indicator)

        state_group.setLayout(state_layout)
        main_layout.addWidget(state_group)

        # Manual controls
        control_group = QGroupBox("Manual Controls")
        control_layout = QVBoxLayout()

        # Sample wheel
        wheel_group = QGroupBox("Sample Wheel")
        wheel_layout = QHBoxLayout()
        self.retract_wheel_btn = QPushButton("Retract Sample Wheel")
        self.retract_wheel_btn.clicked.connect(lambda: self.set_digital_state("wheel", True))
        self.drive_in_wheel_btn = QPushButton("Drive In Sample Wheel")
        self.drive_in_wheel_btn.clicked.connect(lambda: self.set_digital_state("wheel", False))
        wheel_layout.addWidget(self.retract_wheel_btn)
        wheel_layout.addWidget(self.drive_in_wheel_btn)
        wheel_group.setLayout(wheel_layout)
        control_layout.addWidget(wheel_group)

        # Source valve
        valve_group = QGroupBox("Source Valve")
        valve_layout = QHBoxLayout()
        self.close_source_valve_btn = QPushButton("Close Source Valve")
        self.close_source_valve_btn.clicked.connect(lambda: self.set_digital_state("source_valve", True))
        self.open_source_valve_btn = QPushButton("Open Source Valve")
        self.open_source_valve_btn.clicked.connect(lambda: self.set_digital_state("source_valve", False))
        valve_layout.addWidget(self.close_source_valve_btn)
        valve_layout.addWidget(self.open_source_valve_btn)
        valve_group.setLayout(valve_layout)
        control_layout.addWidget(valve_group)

        # Vent
        vent_group = QGroupBox("Argon Venting")
        vent_layout = QHBoxLayout()
        self.start_vent_btn = QPushButton("Start Argon Venting")
        self.start_vent_btn.clicked.connect(self.confirm_start_venting)
        self.stop_vent_btn = QPushButton("Stop Argon Venting")
        self.stop_vent_btn.clicked.connect(lambda: self.set_digital_state("vent", False))
        vent_layout.addWidget(self.start_vent_btn)
        vent_layout.addWidget(self.stop_vent_btn)
        vent_group.setLayout(vent_layout)
        control_layout.addWidget(vent_group)

        # Pump valve
        pump_valve_group = QGroupBox("Pump Valve")
        pump_valve_layout = QHBoxLayout()
        self.open_pump_valve_btn = QPushButton("Open Pump Valve")
        self.open_pump_valve_btn.clicked.connect(self.confirm_open_pump_valve)
        self.close_pump_valve_btn = QPushButton("Close Pump Valve")
        self.close_pump_valve_btn.clicked.connect(lambda: self.set_digital_state("pump_valve", False))
        pump_valve_layout.addWidget(self.open_pump_valve_btn)
        pump_valve_layout.addWidget(self.close_pump_valve_btn)
        pump_valve_group.setLayout(pump_valve_layout)
        control_layout.addWidget(pump_valve_group)

        # Pump + Turbopump
        pump_group = QGroupBox("Pump")
        pump_outer_layout = QVBoxLayout()

        pump_layout = QHBoxLayout()
        self.start_pump_btn = QPushButton("Start Pumping")
        self.start_pump_btn.clicked.connect(lambda: self.set_digital_state("pump", True))
        self.stop_pump_btn = QPushButton("Stop Pumping")
        self.stop_pump_btn.clicked.connect(lambda: self.set_digital_state("pump", False))
        pump_layout.addWidget(self.start_pump_btn)
        pump_layout.addWidget(self.stop_pump_btn)
        pump_group_row = QWidget()
        pump_group_row.setLayout(pump_layout)
        pump_outer_layout.addWidget(pump_group_row)

        turbopump_group = QGroupBox("Turbopump")
        turbopump_layout = QHBoxLayout()

        self.turbo_start_btn = QPushButton("Start")
        self.turbo_start_btn.clicked.connect(lambda: self.confirm_turbopump_start(soft_start=False))

        self.turbo_soft_start_btn = QPushButton("Soft Start")
        self.turbo_soft_start_btn.clicked.connect(lambda: self.confirm_turbopump_start(soft_start=True))

        self.turbo_stop_btn = QPushButton("Stop")
        self.turbo_stop_btn.clicked.connect(self.confirm_turbopump_stop)

        self.turbo_status_indicator = StateIndicator()
        self.turbo_status_value = QLabel("Unknown")
        self.turbo_status_value.setMinimumWidth(120)

        turbopump_layout.addWidget(self.turbo_start_btn)
        turbopump_layout.addWidget(self.turbo_soft_start_btn)
        turbopump_layout.addWidget(self.turbo_stop_btn)
        turbopump_layout.addStretch(1)
        turbopump_layout.addWidget(QLabel("Current Status:"))
        turbopump_layout.addWidget(self.turbo_status_indicator)
        turbopump_layout.addWidget(self.turbo_status_value)

        turbopump_group.setLayout(turbopump_layout)
        pump_outer_layout.addWidget(turbopump_group)

        pump_group.setLayout(pump_outer_layout)
        control_layout.addWidget(pump_group)

        control_group.setLayout(control_layout)
        main_layout.addWidget(control_group)

        self.status_label = QLabel(self._latest_status_text)
        self.status_label.setWordWrap(True)
        main_layout.addWidget(self.status_label)

        self._update_turbopump_status_widgets()

    # ----------------------------
    # Guides
    # ----------------------------
    def show_open_guide(self):
        steps = [
            "Press Sample Wheel Retract",
            "Close the source valve (Optional: separate the system in front on the Ion Cooler)",
            "Open the Argon Valve, remove the 4 screws and vent",
            "Close the Argon Valve and stop venting after the wheel can be moved",
            "Remove the sample wheel",
            "Done!"
        ]
        guide = MaintenanceGuide(steps, "Opening Source Guide", self)
        guide.exec_()

    def show_close_guide(self):
        steps = [
            "Put the Wheel back in",
            "Turn on the pump in the program, open the Pump Valve, wait 5 minutes and start the turbopump in the Turbopump group",
            "Wait until the vacuum sensor at the source has a value of ~10mTorr",
            "Close the pump valve",
            "Open the source Valve and check vacuum conditions. Close in case of unexpected pressure changes",
            "Stop the turbopump in the Turbopump group",
            "Turn Off the Pump in the program",
            "Drive the Wheel back in",
            "Done!"
        ]
        guide = MaintenanceGuide(steps, "Closing Source Guide", self)
        guide.exec_()

    # ----------------------------
    # Confirmations
    # ----------------------------
    def confirm_start_venting(self):
        reply = QMessageBox.question(
            self, "Confirm Venting",
            "Are you sure you want to start argon venting?\n\n"
            "This will release gas into the system.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.set_digital_state("vent", True)

    def confirm_open_pump_valve(self):
        reply = QMessageBox.question(
            self, "Confirm Pump Valve",
            "Are you sure you want to open the pump valve?\n\n"
            "This will connect the pump to the system.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.set_digital_state("pump_valve", True)

    def confirm_turbopump_start(self, soft_start: bool):
        action_txt = "soft start" if soft_start else "start"
        reply = QMessageBox.question(
            self,
            "Confirm Turbopump Start",
            "Only continue if:\n"
            "- the backing/forepump is already running\n"
            "- the gate valve to the high-vacuum side remains closed\n"
            "- the foreline/turbo side has safe rough vacuum\n\n"
            f"Do you want to {action_txt} the turbopump now?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.turbopump_start(soft_start=soft_start)

    def confirm_turbopump_stop(self):
        reply = QMessageBox.question(
            self,
            "Confirm Turbopump Stop",
            "Do you want to stop the turbopump now?\n\n"
            "Make sure this matches your vacuum procedure.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.turbopump_stop()

    # ----------------------------
    # MQTT
    # ----------------------------
    def _build_client_id(self) -> str:
        override = os.environ.get("MAINT_MQTT_CLIENT_ID", "").strip()
        if override:
            return override
        host = socket.gethostname().replace(" ", "_")
        pid = os.getpid()
        return f"{self.SPEC_CLIENT_ID}-maint-{host}-{pid}"

    def _init_mqtt(self):
        self._client_id = self._build_client_id()

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
            self.mqtt_client = mqtt.Client(client_id=self._client_id)

        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
        self.mqtt_client.on_message = self._on_mqtt_message

        try:
            self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=10)
        except Exception:
            pass

        try:
            self.mqtt_client.connect_async(self.MQTT_HOST, self.MQTT_PORT, keepalive=30)
            self.mqtt_client.loop_start()
            self._set_status_text(f"Status: Connecting to MQTT broker… (ClientId: {self._client_id})")
        except Exception as e:
            self._set_status_text(f"Status: MQTT init failed - {e}")
            QMessageBox.critical(self, "Error", f"MQTT connection initialization failed:\n\n{e}")

    def _on_mqtt_connect(self, client, userdata, flags, rc):
        self._mqtt_last_connect_ts = time.monotonic()
        self._mqtt_last_connect_rc = rc

        self._mqtt_connected = (rc == 0)
        self._likely_clientid_conflict = False

        if self._mqtt_connected:
            for ch in self.channels.values():
                client.subscribe(ch.state_topic, qos=self.MQTT_QOS)

    def _on_mqtt_disconnect(self, client, userdata, rc):
        now = time.monotonic()
        was_connected = self._mqtt_connected
        self._mqtt_connected = False
        self._mqtt_last_disconnect_ts = now
        self._mqtt_last_disconnect_rc = rc

        if was_connected and self._mqtt_last_connect_ts is not None:
            if (now - self._mqtt_last_connect_ts) < 2.0:
                self._likely_clientid_conflict = True

    def _on_mqtt_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode("ascii", errors="ignore").strip()
        except Exception:
            return

        if not payload:
            return

        first = payload[0]
        if first == "1":
            state = True
        elif first == "0":
            state = False
        else:
            return

        now = time.monotonic()
        for key, ch in self.channels.items():
            if msg.topic == ch.state_topic:
                self._state_values[key] = state
                self._state_rx_ts[key] = now
                break

    # ----------------------------
    # Digital control
    # ----------------------------
    def set_digital_state(self, channel_key: str, state: bool) -> bool:
        if channel_key not in self.channels:
            QMessageBox.critical(self, "Error", f"Unknown channel: {channel_key}")
            return False

        if not self._mqtt_connected:
            QMessageBox.warning(self, "Not connected", "MQTT is not connected. Cannot send command.")
            return False

        ch = self.channels[channel_key]
        try:
            if self.USE_SET_PAYLOAD_TOPIC:
                payload = "1" if state else "0"
                self.mqtt_client.publish(ch.cmd_set_topic, payload=payload, qos=self.MQTT_QOS, retain=False)
            else:
                topic = f"{ch.cmd_set_topic}_{'1' if state else '0'}"
                self.mqtt_client.publish(topic, payload="", qos=self.MQTT_QOS, retain=False)

            self._set_status_text(f"Status: Command sent: {channel_key} -> {'ON' if state else 'OFF'}")
            return True
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to send MQTT command:\n\n{e}")
            return False

    # ----------------------------
    # Turbopump protocol helpers
    # ----------------------------
    def _turbopump_build_frame(self, window: int, write_value: Optional[str] = None) -> bytes:
        """
        TV Navigator protocol:
        <STX><ADDR><WIN><COM><DATA><ETX><CRC>
        RS232 ADDR = 0x80
        COM = '0' read, '1' write
        CRC = XOR over ADDR..ETX as 2 ASCII hex chars
        """
        addr = bytes([0x80])
        win = f"{window:03d}".encode("ascii")

        if write_value is None:
            com = b"0"
            payload = addr + win + com + b"\x03"
        else:
            com = b"1"
            data = str(write_value).encode("ascii")
            payload = addr + win + com + data + b"\x03"

        crc = 0
        for byte in payload:
            crc ^= byte

        return b"\x02" + payload + f"{crc:02X}".encode("ascii")

    def _turbopump_exchange(self, frame: bytes) -> bytes:
        try:
            with socket.create_connection(
                (self.TURBO_HOST, self.TURBO_PORT),
                timeout=self.TURBO_CONNECT_TIMEOUT_S
            ) as sock:
                sock.settimeout(self.TURBO_SOCKET_TIMEOUT_S)
                self._turbo_converter_connected = True
                sock.sendall(frame)
                reply = sock.recv(128)
                if not reply:
                    raise RuntimeError("No reply received from turbopump controller.")
                self._turbo_last_error = None
                return reply
        except Exception as e:
            self._turbo_converter_connected = False
            self._turbo_last_error = str(e)
            raise

    def _turbopump_ping_converter(self) -> bool:
        try:
            with socket.create_connection(
                (self.TURBO_HOST, self.TURBO_PORT),
                timeout=self.TURBO_CONNECT_TIMEOUT_S
            ):
                self._turbo_converter_connected = True
                return True
        except Exception as e:
            self._turbo_converter_connected = False
            self._turbo_last_error = str(e)
            return False

    @staticmethod
    def _turbopump_is_ack(reply: bytes) -> bool:
        return len(reply) >= 6 and reply[0] == 0x02 and reply[2] == 0x06

    @staticmethod
    def _turbopump_extract_read_data(reply: bytes) -> bytes:
        if len(reply) < 8 or reply[0] != 0x02:
            raise RuntimeError("Unexpected reply format from turbopump controller.")
        try:
            etx_index = reply.index(0x03)
        except ValueError:
            raise RuntimeError("ETX not found in turbopump reply.")
        if etx_index < 6:
            raise RuntimeError("Malformed turbopump reply.")
        return reply[6:etx_index]

    def _read_turbopump_logic(self, window: int) -> str:
        reply = self._turbopump_exchange(self._turbopump_build_frame(window))
        data = self._turbopump_extract_read_data(reply)
        return data.decode("ascii")

    def _read_turbopump_numeric(self, window: int) -> int:
        reply = self._turbopump_exchange(self._turbopump_build_frame(window))
        data = self._turbopump_extract_read_data(reply).decode("ascii")
        return int(data)

    def _write_turbopump_logic(self, window: int, value: int) -> None:
        reply = self._turbopump_exchange(self._turbopump_build_frame(window, str(value)))
        if not self._turbopump_is_ack(reply):
            raise RuntimeError(f"No ACK for turbopump write window {window:03d} = {value}")

    def _turbopump_status_description(self) -> Tuple[str, Optional[QColor]]:
        if self._turbo_status_code is None:
            if not self._turbo_converter_connected:
                return "No converter", QColor(160, 160, 160)
            if self._turbo_last_error:
                return "No pump reply", QColor(160, 160, 160)
            return "Unknown", QColor(160, 160, 160)

        mapping = {
            0: ("Stop", QColor(160, 160, 160)),
            1: ("Waiting intlk", QColor(255, 200, 0)),
            2: ("Starting", QColor(80, 170, 255)),
            3: ("Auto-tuning", QColor(80, 170, 255)),
            4: ("Braking", QColor(255, 150, 0)),
            5: ("Normal", QColor(0, 200, 0)),
            6: ("Fail", QColor(255, 0, 0)),
        }
        return mapping.get(self._turbo_status_code, (f"Code {self._turbo_status_code}", QColor(160, 160, 160)))

    def _update_turbopump_status_widgets(self):
        txt, color = self._turbopump_status_description()
        self.turbo_status_indicator.set_color(color)
        self.turbo_status_value.setText(txt)

    def _poll_turbopump_status(self, silent: bool = True) -> Optional[int]:
        self._turbo_last_probe_ts = time.monotonic()

        try:
            status = self._read_turbopump_numeric(205)
            self._turbo_status_code = status
            self._turbo_last_status_ts = time.monotonic()
            self._turbo_last_error = None
            return status
        except Exception as e:
            self._turbo_status_code = None
            self._turbo_last_error = str(e)

            # Distinguish between "converter unreachable" and "converter reachable, but no pump reply"
            self._turbopump_ping_converter()

            if not silent:
                QMessageBox.warning(
                    self,
                    "Turbopump status unavailable",
                    f"Could not read turbopump status:\n\n{e}"
                )
            return None
        finally:
            self._update_turbopump_status_widgets()

    def turbopump_start(self, soft_start: bool) -> bool:
        action_txt = "soft start" if soft_start else "start"

        try:
            status = self._poll_turbopump_status(silent=True)
            if status is None:
                raise RuntimeError("Could not read current turbopump status.")

            if status != 0:
                QMessageBox.warning(
                    self,
                    "Turbopump not in STOP",
                    f"The turbopump is not in STOP.\n\nCurrent status: {self._turbopump_status_description()[0]}\n\n"
                    "For safety, the start command was not sent."
                )
                return False

            # Ensure serial mode
            self._write_turbopump_logic(8, 0)

            # Configure soft start explicitly so button meaning stays predictable
            self._write_turbopump_logic(100, 1 if soft_start else 0)

            # Start
            self._write_turbopump_logic(0, 1)
            time.sleep(0.15)
            self._poll_turbopump_status(silent=True)

            self._set_status_text(f"Status: Turbopump {action_txt} command sent.")
            return True

        except Exception as e:
            self._set_status_text(f"Status: Turbopump {action_txt} failed - {e}")
            self._poll_turbopump_status(silent=True)
            QMessageBox.critical(
                self,
                "Turbopump Error",
                f"Failed to {action_txt} turbopump:\n\n{e}"
            )
            return False

    def turbopump_stop(self) -> bool:
        try:
            # Ensure serial mode
            self._write_turbopump_logic(8, 0)

            # Stop
            self._write_turbopump_logic(0, 0)
            time.sleep(0.15)
            self._poll_turbopump_status(silent=True)

            self._set_status_text("Status: Turbopump stop command sent.")
            return True

        except Exception as e:
            self._set_status_text(f"Status: Turbopump stop failed - {e}")
            self._poll_turbopump_status(silent=True)
            QMessageBox.critical(
                self,
                "Turbopump Error",
                f"Failed to stop turbopump:\n\n{e}"
            )
            return False

    # ----------------------------
    # UI update / staleness
    # ----------------------------
    def _set_status_text(self, text: str):
        self._latest_status_text = text

    def _is_fresh(self, ts: Optional[float]) -> bool:
        return ts is not None and (time.monotonic() - ts) <= self.STATE_STALE_S

    def update_states(self):
        # One-time warning for likely ClientId collision
        if self._likely_clientid_conflict and not self._clientid_warning_shown:
            self._clientid_warning_shown = True
            QMessageBox.warning(
                self,
                "MQTT connection unstable",
                "The broker disconnected shortly after connecting.\n\n"
                "This is very often caused by another client using the SAME ClientId.\n"
                f"Current ClientId: {self._client_id}\n\n"
                "Fix:\n"
                "- Stop the other client using that ClientId, OR\n"
                "- Set a unique ClientId via env var MAINT_MQTT_CLIENT_ID.\n\n"
                "If your broker ACL requires a fixed ClientId, only one client can run at a time."
            )

        # Periodic turbopump status poll
        now = time.monotonic()
        if (now - self._turbo_last_probe_ts) >= self.TURBO_STATUS_POLL_S:
            self._poll_turbopump_status(silent=True)

        # Apply MQTT telemetry (gray if stale/unknown)
        wheel = self._state_values["wheel"] if self._is_fresh(self._state_rx_ts["wheel"]) else None
        source_valve = self._state_values["source_valve"] if self._is_fresh(self._state_rx_ts["source_valve"]) else None
        vent = self._state_values["vent"] if self._is_fresh(self._state_rx_ts["vent"]) else None
        pump_valve = self._state_values["pump_valve"] if self._is_fresh(self._state_rx_ts["pump_valve"]) else None
        pump = self._state_values["pump"] if self._is_fresh(self._state_rx_ts["pump"]) else None

        self.wheel_indicator.set_state(wheel)
        self.source_valve_indicator.set_state(source_valve)
        self.vent_indicator.set_state(vent)
        self.pump_valve_indicator.set_state(pump_valve)
        self.pump_indicator.set_state(pump)
        self._update_turbopump_status_widgets()

        mqtt_txt = "connected" if self._mqtt_connected else "disconnected"
        rs232_txt = "connected" if self._turbo_converter_connected else "disconnected"

        base_status = self._latest_status_text
        self.status_label.setText(
            f"{base_status}"
            f"    |    MQTT: {mqtt_txt} ({self.MQTT_HOST}:{self.MQTT_PORT})"
            f"    |    RS232: {rs232_txt} ({self.TURBO_HOST}:{self.TURBO_PORT})"
            f"    |    ClientId: {self._client_id}"
        )

        # Enable/disable MQTT-based controls
        can_mqtt_control = self._mqtt_connected
        for btn in [
            self.retract_wheel_btn, self.drive_in_wheel_btn,
            self.close_source_valve_btn, self.open_source_valve_btn,
            self.start_vent_btn, self.stop_vent_btn,
            self.open_pump_valve_btn, self.close_pump_valve_btn,
            self.start_pump_btn, self.stop_pump_btn
        ]:
            btn.setEnabled(can_mqtt_control)

        # Enable/disable turbopump controls based on converter reachability
        can_turbo_control = self._turbo_converter_connected
        for btn in [
            self.turbo_start_btn,
            self.turbo_soft_start_btn,
            self.turbo_stop_btn
        ]:
            btn.setEnabled(can_turbo_control)

    # ----------------------------
    # Close
    # ----------------------------
    def closeEvent(self, event):
        try:
            if hasattr(self, "mqtt_client") and self.mqtt_client is not None:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
        except Exception:
            pass
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = IonizerMaintenanceControl()
    window.show()
    sys.exit(app.exec_())