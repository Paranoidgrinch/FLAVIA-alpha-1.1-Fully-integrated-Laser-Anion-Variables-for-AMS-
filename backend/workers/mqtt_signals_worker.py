# backend/workers/mqtt_signals_worker.py
from __future__ import annotations

import threading
import time
from typing import Any, Optional, Tuple, List

import paho.mqtt.client as mqtt

from ..model import DataModel
from ..channels import (
    MQTT_DEFAULT_HOST,
    MQTT_DEFAULT_PORT,
    MQTT_DEFAULT_KEEPALIVE,
    SUBSCRIBE_ROOTS,
)


def _parse_float(s: str) -> Optional[float]:
    try:
        s = s.strip().replace(",", ".")
        return float(s)
    except Exception:
        return None


def _parse_bool01(s: str) -> Optional[bool]:
    s = (s or "").strip()
    if not s:
        return None
    if s == "1":
        return True
    if s == "0":
        return False
    return None


def parse_payload(payload: str) -> Any:
    """
    Best-effort parsing:
    - "0"/"1" -> bool
    - float numbers -> float
    - otherwise -> stripped string
    """
    p = (payload or "").strip()
    b = _parse_bool01(p)
    if b is not None:
        return b
    f = _parse_float(p)
    if f is not None:
        return f
    return p


class MqttSignalsWorker(threading.Thread):
    """
    MQTT-only replacement for OPC polling.

    WICHTIGE Entscheidung (für schnelle Migration):
    - Jede eingehende MQTT Topic wird *direkt* als Channel-Name im DataModel gespeichert.
      Beispiel: topic "cs/oven/temp_c" -> model channel "cs/oven/temp_c".
    """

    def __init__(
        self,
        model: DataModel,
        host: str = MQTT_DEFAULT_HOST,
        port: int = MQTT_DEFAULT_PORT,
        subscribe_roots: Optional[List[Tuple[str, int]]] = None,
    ):
        super().__init__(daemon=True)
        self.model = model
        self.host = host
        self.port = int(port)
        self.subscribe_roots = subscribe_roots or list(SUBSCRIBE_ROOTS)

        self._stop_event = threading.Event()
        self._client = mqtt.Client(protocol=mqtt.MQTTv311)

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        self._connected = False

    def run(self) -> None:
        try:
            self._client.connect(self.host, self.port, keepalive=MQTT_DEFAULT_KEEPALIVE)
            self._client.loop_start()
            while not self._stop_event.is_set():
                time.sleep(0.1)
        except Exception:
            self._set_connected(False, quality="bad")
        finally:
            try:
                self._client.loop_stop()
            except Exception:
                pass
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._set_connected(False, quality="bad")

    def stop(self) -> None:
        self._stop_event.set()
        self.join(timeout=5.0)

    def publish(self, topic: str, payload: str, *, qos: int = 0, retain: bool = False) -> None:
        try:
            self._client.publish(topic, payload=payload, qos=qos, retain=retain)
        except Exception:
            pass

    def publish_value(self, topic: str, value: Any, *, decimals: int = 6) -> None:
        if isinstance(value, bool):
            payload = "1" if value else "0"
        elif isinstance(value, (int, float)):
            payload = f"{float(value):.{int(decimals)}f}".replace(",", ".")
        else:
            payload = str(value)
        self.publish(topic, payload)

    def _set_connected(self, ok: bool, quality: str = "good") -> None:
        self._connected = ok
        self.model.update("mqtt_connected", bool(ok), source="mqtt", quality=quality)

    def _on_connect(self, client, userdata, flags, rc):
        ok = (rc == mqtt.CONNACK_ACCEPTED)
        self._set_connected(ok, quality="good" if ok else "bad")
        if not ok:
            return

        for topic, qos in self.subscribe_roots:
            try:
                client.subscribe(topic, qos=qos)
            except Exception:
                pass

    def _on_disconnect(self, client, userdata, rc):
        self._set_connected(False, quality="bad")

    def _on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode("utf-8", errors="ignore")
        except Exception:
            payload = ""
        value = parse_payload(payload)
        self.model.update(msg.topic, value, source="mqtt")

        # --- Derived display channel: Sputter current in mA ---
        if msg.topic == "cs/sputter/meas_i_a":
            # parse_payload kann bool/float/string liefern -> wir wollen nur float
            if isinstance(value, bool):
                a = None
            elif isinstance(value, (int, float)):
                a = float(value)
            else:
                a = _parse_float(payload)

            if a is not None:
                self.model.update("cs/sputter/meas_i_mA", a * 1000.0, source="mqtt")