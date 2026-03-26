# -*- coding: utf-8 -*-
"""
Source_Maintainance_MQTT.py

PyQt5 GUI for ion source maintenance control via MQTT.

Digital channels:
- Publish: cs/<channel>/cmd/set  payload "1" or "0" (first char is evaluated)
- Telemetry: cs/<channel>/state payload "1" or "0"

Broker:
- Host: 192.168.0.20
- Port: 1883
- QoS: 0

Notes:
- Uses a unique client id by default to avoid connect/disconnect loops caused by ClientId collisions.
  You can override via env var: MAINT_MQTT_CLIENT_ID
"""

import sys
import os
import time
import socket
from dataclasses import dataclass
from typing import Dict, Optional

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
    - Green: True
    - Red: False
    - Gray: Unknown / stale
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(20, 20)
        self.set_state(None)

    def set_state(self, state: Optional[bool]):
        palette = self.palette()
        if state is None:
            color = QColor(160, 160, 160)
        else:
            color = QColor(0, 255, 0) if state else QColor(255, 0, 0)
        palette.setColor(QPalette.Window, color)
        self.setAutoFillBackground(True)
        self.setPalette(palette)
        self.update()


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

        # Size: choose a comfortable default based on screen
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            w = int(min(1000, geo.width() * 0.70))
            h = int(min(700,  geo.height() * 0.60))
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
    # MQTT broker settings
    MQTT_HOST = "192.168.0.20"
    MQTT_PORT = 1883
    MQTT_QOS = 0

    # Base client id from spec; we derive a unique id by default
    SPEC_CLIENT_ID = "cx-cs-source"

    # Staleness threshold for telemetry (seconds)
    STATE_STALE_S = 5.0

    # UI refresh
    UI_REFRESH_MS = 250

    # If True: publish to cs/<ch>/cmd/set with payload "1"/"0"
    # If False: publish to cs/<ch>/cmd/set_1 or set_0 topics (payload can be empty)
    USE_SET_PAYLOAD_TOPIC = True

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ion Source Maintenance Control")
        self.setGeometry(100, 100, 800, 600)

        if mqtt is None:
            QMessageBox.critical(
                self,
                "Missing dependency",
                "The 'paho-mqtt' package is required.\n\nInstall with:\n    pip install paho-mqtt"
            )
            raise ImportError("paho-mqtt is required")

        # Digital channels (per command structure)
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

        # MQTT / state caches (updated by MQTT thread)
        self._mqtt_connected: bool = False
        self._mqtt_last_connect_ts: Optional[float] = None
        self._mqtt_last_disconnect_ts: Optional[float] = None
        self._mqtt_last_connect_rc: Optional[int] = None
        self._mqtt_last_disconnect_rc: Optional[int] = None

        self._likely_clientid_conflict: bool = False
        self._clientid_warning_shown: bool = False

        self._state_values: Dict[str, Optional[bool]] = {k: None for k in self.channels.keys()}
        self._state_rx_ts: Dict[str, Optional[float]] = {k: None for k in self.channels.keys()}

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

        # Pump
        pump_group = QGroupBox("Pump")
        pump_layout = QHBoxLayout()
        self.start_pump_btn = QPushButton("Start Pumping")
        self.start_pump_btn.clicked.connect(lambda: self.set_digital_state("pump", True))
        self.stop_pump_btn = QPushButton("Stop Pumping")
        self.stop_pump_btn.clicked.connect(lambda: self.set_digital_state("pump", False))
        pump_layout.addWidget(self.start_pump_btn)
        pump_layout.addWidget(self.stop_pump_btn)
        pump_group.setLayout(pump_layout)
        control_layout.addWidget(pump_group)

        control_group.setLayout(control_layout)
        main_layout.addWidget(control_group)

        self.status_label = QLabel(self._latest_status_text)
        main_layout.addWidget(self.status_label)

    # ----------------------------
    # Guides (now using the original full step lists)
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
            "Turn on the pump in the program, open the Pump Valve wait 5 Minutes and manually turn on the turbo pump, by plugging it in",
            "Wait until the vacuum sensor at the source has a value of ~10mTorr",
            "Close the pump valve",
            "Open the source Valve and check vacuum conditions. Close in case of unexpected pressure changes",
            "Turn Off the turbo pump manually",
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

        # paho-mqtt 1.x / 2.x compatibility
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

        # Heuristic: disconnect very shortly after a successful connect -> often ClientId collision
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

        # Apply telemetry (gray if stale/unknown)
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

        conn_txt = "connected" if self._mqtt_connected else "disconnected"
        base_status = self._latest_status_text
        self.status_label.setText(
            f"{base_status}    |    MQTT: {conn_txt} ({self.MQTT_HOST}:{self.MQTT_PORT})"
            f"    |    ClientId: {self._client_id}"
        )

        # Enable/disable controls based on connection
        can_control = self._mqtt_connected
        for btn in [
            self.retract_wheel_btn, self.drive_in_wheel_btn,
            self.close_source_valve_btn, self.open_source_valve_btn,
            self.start_vent_btn, self.stop_vent_btn,
            self.open_pump_valve_btn, self.close_pump_valve_btn,
            self.start_pump_btn, self.stop_pump_btn
        ]:
            btn.setEnabled(can_control)

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
