# backend/backend.py
from __future__ import annotations
import threading
import time

from typing import Optional, Any
from copy import deepcopy

from .channels import MQTT_DEFAULT_HOST, MQTT_DEFAULT_PORT, CHANNELS, decimals_for, unit_for
from .model import DataModel
from .qpt_coordinates import (
    QPT_ASTIGMATISM_MEAS,
    QPT_ASTIGMATISM_SET,
    QPT_FOCUS_MEAS,
    QPT_FOCUS_SET,
    QPT_HARDWARE_MEAS_CHANNELS,
    QPT_HARDWARE_SET_CHANNELS,
    QPT_VIRTUAL_SET_CHANNELS,
    focus_astigmatism_to_qpt,
    qpt_to_focus_astigmatism,
)

from .workers.mqtt_signals_worker import MqttSignalsWorker
from .workers.cup_switch_worker import CupSwitchWorker, CupSwitchConfig
from .workers.keithley_6485_worker import Keithley6485Worker, KeithleySettings
from .workers.magnet_worker import MagnetWorker
from .workers.gaussmeter_worker import GaussmeterWorker
from .services.logging_service import LoggingService, LoggingConfig
from .services.config_service import ConfigService, ConfigPayload
from .services.rfq_service import RFQService
from .services.sample_exposure_counter import SampleExposureCounterService

SOURCE_HV_CHANNELS = (
    "cs/sputter/set_u_v",
    "cs/extraction/set_u_v",
    "cs/einzellens/set_u_v",
)

class Backend:
    """Orchestrator for all background workers + services."""

    def __init__(
        self,
        mqtt_host: str = MQTT_DEFAULT_HOST,
        mqtt_port: int = MQTT_DEFAULT_PORT,
        *,
        cup_cfg: CupSwitchConfig = CupSwitchConfig(),
        keithley_settings: Optional[KeithleySettings] = None,
    ):
        self.model = DataModel(unit_resolver=unit_for)

        # Virtual QPT coordinates. Hardware readbacks/setpoints refresh these
        # as soon as a complete, fresh QP1/QP2/QP3 triplet is available.
        self.model.update(QPT_FOCUS_SET, 0.0, source="qpt_virtual")
        self.model.update(QPT_ASTIGMATISM_SET, 50.0, source="qpt_virtual")
        self.model.update(QPT_FOCUS_MEAS, 0.0, source="qpt_virtual")
        self.model.update(QPT_ASTIGMATISM_MEAS, 50.0, source="qpt_virtual")
        for name in QPT_HARDWARE_SET_CHANNELS:
            self.model.subscribe(name, self._on_qpt_setpoint_update)
        for name in QPT_HARDWARE_MEAS_CHANNELS:
            self.model.subscribe(name, self._on_qpt_measurement_update)

        #ramp für config laden
        self._ramp_cancel = threading.Event()
        self._ramp_thread = None
        self._last_killed_source_hv: Optional[dict[str, float]] = None


        #magnet
        self.magnet = MagnetWorker(self.model)
        self.gaussmeter = GaussmeterWorker(self.model)

        #stepper
        from backend.workers.stepper_worker import StepperWorker
        from backend.services.sample_selection_state import SampleSelectionStateService

        self.stepper = StepperWorker(self.model)
        self.sample_state = SampleSelectionStateService(self.model)
        self.sample_exposure = SampleExposureCounterService(self.model)

        # Workers
        self.mqtt = MqttSignalsWorker(self.model, host=mqtt_host, port=mqtt_port)
        self.cup = CupSwitchWorker(self.model, cfg=cup_cfg)
        self.keithley = Keithley6485Worker(self.model, settings=keithley_settings)

        # Services
        self.logging = LoggingService(self.model)
        self.config = ConfigService(self.model)
        self.rfq = RFQService()
        self.rfq.fgStatus.connect(self._on_rfq_fg_status)

        self._default_steerer_channels = [
            "steerer/bias/set_u",
            "steerer/1x/set_u",
            "steerer/1y/set_u",
            "steerer/2x/set_u",
            "steerer/2y/set_u",
            "steerer/3x/set_u",
            "steerer/3y/set_u",
        ]

        self._started = False



    def _on_rfq_fg_status(self, f_hz: float, vpp: float) -> None:
        try:
            self.model.update("rfq/fg_freq_hz", float(f_hz), source="rfq", quality="good")
            self.model.update("rfq/fg_vpp", float(vpp), source="rfq", quality="good")
        except Exception:
            pass

    

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self.mqtt.start()
        self.cup.start()
        self.keithley.start()
        self.keithley.cmd_connect()
        self.rfq.start()
        self.stepper.start()
        self.magnet.start()
        self.gaussmeter.start()
        self.sample_exposure.start()



        def _delayed_steerer_defaults():
            time.sleep(2)  # wait for initial MQTT values to arrive
            self.apply_default_steerer_values_if_empty()

        threading.Thread(target=_delayed_steerer_defaults, daemon=True).start()
        # logging thread starts lazily on first start_logging()

    def apply_default_steerer_values_if_empty(self) -> None:
        for key in self._default_steerer_channels:
            ch = self.model.get(key)
            if ch is None:
                continue

            if ch.value is None:
                try:
                    self.set_channel(key, 250.0)
                except Exception:
                    pass

    def stop(self) -> None:
        if not self._started:
            return
        self._started = False

        try:
            self.sample_exposure.stop()
        except Exception:
            pass

        try:
            self.stepper.stop()
        except Exception:
            pass

        try:
            self.magnet.stop()
        except Exception:
            pass

        try:
            self.gaussmeter.stop()
        except Exception:
            pass

        try:
            self.logging.shutdown()
        except Exception:
            pass

        try:
            self.rfq.stop()
        except Exception:
            pass

        for w in (self.mqtt, self.cup, self.keithley):
            try:
                w.stop()
            except Exception:
                pass

    #magnet funktion
    def set_magnet_current(self, current_A: float):
        self.magnet.set_current(current_A)
        
    #stepper funktionen
    def move_sample_to_position(self, steps: int):
        self.stepper.move_to(int(steps))

    def stop_stepper(self):
        self.stepper.stop_motion()

    def home_stepper(self):
        self.stepper.go_home()

    # ----------------------
    # MQTT publish helpers
    # ----------------------
    def mqtt_publish(self, topic: str, payload: str) -> None:
        self.mqtt.publish(topic, payload)

    def mqtt_publish_value(self, topic: str, value: Any, *, decimals: int = 6) -> None:
        self.mqtt.publish_value(topic, value, decimals=decimals)


    #keithley zeug neu
    def get_keithley_settings_copy(self):
        return deepcopy(self.keithley.get_settings_copy())


    def apply_keithley_settings(self, settings):
        self.keithley.cmd_apply_settings(deepcopy(settings))


    def reset_keithley_trace(self):
        self.keithley.cmd_reset_trace()
    # ----------------------
    # Virtual QPT coordinates
    # ----------------------
    def _fresh_qpt_triplet(self, names, max_skew_s: float = 0.5):
        channels = [self.model.get(name) for name in names]
        if any(ch is None or ch.value is None for ch in channels):
            return None
        timestamps = [float(ch.timestamp) for ch in channels]
        if max(timestamps) - min(timestamps) > float(max_skew_s):
            return None
        try:
            return tuple(float(ch.value) for ch in channels)
        except Exception:
            return None

    def _update_virtual_qpt_from_hardware(self, names, focus_channel: str, astigmatism_channel: str) -> None:
        values = self._fresh_qpt_triplet(names)
        if values is None:
            return
        focus, astigmatism = qpt_to_focus_astigmatism(*values)
        self.model.update(focus_channel, focus, source="qpt_derived")
        self.model.update(astigmatism_channel, astigmatism, source="qpt_derived")

    def _on_qpt_setpoint_update(self, _channel) -> None:
        self._update_virtual_qpt_from_hardware(
            QPT_HARDWARE_SET_CHANNELS,
            QPT_FOCUS_SET,
            QPT_ASTIGMATISM_SET,
        )

    def _on_qpt_measurement_update(self, _channel) -> None:
        self._update_virtual_qpt_from_hardware(
            QPT_HARDWARE_MEAS_CHANNELS,
            QPT_FOCUS_MEAS,
            QPT_ASTIGMATISM_MEAS,
        )

    def _virtual_qpt_value(self, channel_name: str, default: float) -> float:
        ch = self.model.get(channel_name)
        try:
            return float(ch.value) if ch is not None and ch.value is not None else float(default)
        except Exception:
            return float(default)

    def set_qpt_focus_astigmatism(self, focus_pct: float, astigmatism_pct: float) -> None:
        qp1, qp2, qp3 = focus_astigmatism_to_qpt(focus_pct, astigmatism_pct)

        # Keep virtual set values immediately in sync for GUI/tracers.
        self.model.update(QPT_FOCUS_SET, float(focus_pct), source="qpt_virtual")
        self.model.update(QPT_ASTIGMATISM_SET, float(astigmatism_pct), source="qpt_virtual")

        for channel_name, voltage in zip(QPT_HARDWARE_SET_CHANNELS, (qp1, qp2, qp3)):
            c = CHANNELS[channel_name]
            d = decimals_for(channel_name, default=6)
            self.mqtt_publish_value(c.topic_cmd, voltage, decimals=d)

    # ----------------------
    # Channel-based set API
    # ----------------------
    def set_channel(self, channel_name: str, value: Any) -> None:
        if channel_name in QPT_VIRTUAL_SET_CHANNELS:
            focus = self._virtual_qpt_value(QPT_FOCUS_SET, 0.0)
            astigmatism = self._virtual_qpt_value(QPT_ASTIGMATISM_SET, 50.0)
            if channel_name == QPT_FOCUS_SET:
                focus = float(value)
            else:
                astigmatism = float(value)
            self.set_qpt_focus_astigmatism(focus, astigmatism)
            return

        c = CHANNELS.get(channel_name)
        if c is None or not c.topic_cmd:
            raise KeyError(f"Channel {channel_name!r} has no topic_cmd mapping.")
        d = decimals_for(channel_name, default=6)
        self.mqtt_publish_value(c.topic_cmd, value, decimals=d)

    def set_bool(self, channel_name: str, on: bool) -> None:
        self.set_channel(channel_name, bool(on))

    def _cancel_active_ramp(self) -> None:
        try:
            self._ramp_cancel.set()
        except Exception:
            pass

    def _channel_numeric_value(self, channel_name: str, fallback: float = 0.0) -> float:
        ch = self.model.get(channel_name)

        if ch is None or ch.value is None:
            if "/set_" in channel_name:
                ch2 = self.model.get(channel_name.replace("/set_", "/meas_", 1))
                if ch2 and ch2.value is not None:
                    ch = ch2
            elif channel_name.endswith("/set_v"):
                ch2 = self.model.get(channel_name.replace("/set_v", "/meas_v", 1))
                if ch2 and ch2.value is not None:
                    ch = ch2
            elif channel_name.endswith("/set_u"):
                ch2 = self.model.get(channel_name.replace("/set_u", "/meas_u", 1))
                if ch2 and ch2.value is not None:
                    ch = ch2
            elif channel_name.endswith("/set_u_v"):
                ch2 = self.model.get(channel_name.replace("/set_u_v", "/meas_u_v", 1))
                if ch2 and ch2.value is not None:
                    ch = ch2

        try:
            return float(ch.value) if (ch and ch.value is not None) else float(fallback)
        except Exception:
            return float(fallback)

    def _ramp_targets(self, targets: dict[str, float], ramp_s: float = 10.0) -> None:
        if not targets:
            return

        self._cancel_active_ramp()
        self._ramp_cancel = threading.Event()

        starts = {k: self._channel_numeric_value(k, fallback=float(v)) for k, v in targets.items()}

        steps = max(50, int(float(ramp_s) * 10))
        dt = float(ramp_s) / steps if steps > 0 else 0.1

        def ramp_thread():
            for i in range(steps + 1):
                if self._ramp_cancel.is_set():
                    return

                frac = i / steps
                for k, tgt in targets.items():
                    s0 = starts[k]
                    v = s0 + (float(tgt) - s0) * frac
                    try:
                        self.set_channel(k, v)
                    except Exception:
                        pass

                time.sleep(dt)

        self._ramp_thread = threading.Thread(target=ramp_thread, daemon=True)
        self._ramp_thread.start()

    def kill_source_hv(self, ramp_s: float = 15.0) -> bool:
        snapshot = {
            ch: self._channel_numeric_value(ch, fallback=0.0)
            for ch in SOURCE_HV_CHANNELS
        }
        self._last_killed_source_hv = dict(snapshot)

        targets = {ch: 0.0 for ch in SOURCE_HV_CHANNELS}
        self._ramp_targets(targets, ramp_s=float(ramp_s))
        return True

    def restore_source_hv(self, ramp_s: float = 10.0) -> bool:
        if not self._last_killed_source_hv:
            return False

        self._ramp_targets(dict(self._last_killed_source_hv), ramp_s=float(ramp_s))
        return True

    # ----------------------
    # Logging
    # ----------------------
    def start_logging(self, filepath: str, interval_s: float = 1.0) -> None:
        cfg = LoggingConfig(interval_s=float(interval_s), channels=None)
        self.logging.start_logging(filepath, cfg=cfg)

    def stop_logging(self) -> None:
        self.logging.stop_logging()

    # ----------------------
    # Config
    # ----------------------
    def save_config(self, filepath: str) -> None:
        self.config.save(filepath)

    def load_config(self, filepath: str) -> ConfigPayload:
        return self.config.load(filepath)

    def apply_config(self, payload, selected_keys=None, ramp_s: float = 30.0) -> None:
        """
        Apply config with selection.
        - states are applied immediately
        - setpoints + extras are ramped over ramp_s seconds
        """
        selected = set(selected_keys) if selected_keys is not None else set()
        if not selected:
            # default: apply everything present
            selected = set(payload.setpoints.keys()) | set(payload.states.keys()) | set(payload.extras.keys())

        # --- apply states immediately ---
        for k, v in payload.states.items():
            if k not in selected:
                continue
            try:
                self.set_bool(k, bool(v))
            except Exception:
                pass

        # --- build ramp targets ---
        targets = {}

        # normal mqtt setpoints
        for k, v in payload.setpoints.items():
            if k in selected and v is not None:
                try:
                    targets[k] = float(v)
                except Exception:
                    pass

        # extras
        for k, v in payload.extras.items():
            if k in selected and v is not None:
                try:
                    targets[k] = float(v)
                except Exception:
                    pass

        if not targets:
            return

        # cancel previous ramp
        try:
            self._ramp_cancel.set()
        except Exception:
            pass

        self._ramp_cancel = threading.Event()

        # snapshot start values
        def current_value(key: str) -> float:
            # magnet: prefer meas
            if key == "magnet_current_set":
                ch = self.model.get("magnet_current_meas") or self.model.get("magnet_current_set")
            else:
                ch = self.model.get(key)

            # fallback: try meas partner for cs/.../set_
            if ch is None or ch.value is None:
                if "/set_" in key:
                    ch2 = self.model.get(key.replace("/set_", "/meas_", 1))
                    if ch2 and ch2.value is not None:
                        ch = ch2
                elif key.endswith("/set_v"):
                    ch2 = self.model.get(key.replace("/set_v", "/meas_v", 1))
                    if ch2 and ch2.value is not None:
                        ch = ch2
                elif key.endswith("/set_u"):
                    ch2 = self.model.get(key.replace("/set_u", "/meas_u", 1))
                    if ch2 and ch2.value is not None:
                        ch = ch2

            try:
                return float(ch.value) if (ch and ch.value is not None) else float(targets[key])
            except Exception:
                return float(targets[key])

        starts = {k: current_value(k) for k in targets.keys()}

        # FG combined ramp
        fg_target_f = targets.get("rfq/fg_freq_hz", None)
        fg_target_v = targets.get("rfq/fg_vpp", None)
        fg_start_f = starts.get("rfq/fg_freq_hz", None)
        fg_start_v = starts.get("rfq/fg_vpp", None)

        # remove individual fg keys from generic loop, we handle combined
        for k in ("rfq/fg_freq_hz", "rfq/fg_vpp"):
            if k in targets:
                targets.pop(k, None)
                starts.pop(k, None)

        steps = max(50, int(ramp_s * 10))  # ~10 Hz updates
        dt = ramp_s / steps

        def ramp_thread():
            for i in range(steps + 1):
                if self._ramp_cancel.is_set():
                    return
                frac = i / steps

                # generic ramp (mqtt setpoints + magnet)
                for k, tgt in targets.items():
                    s0 = starts[k]
                    v = s0 + (tgt - s0) * frac
                    try:
                        if k == "magnet_current_set":
                            self.set_magnet_current(v)
                        else:
                            self.set_channel(k, v)
                    except Exception:
                        pass

                # fg ramp (freq+vpp together)
                if fg_target_f is not None or fg_target_v is not None:
                    # if only one selected, keep the other at its start value
                    f0 = fg_start_f if fg_start_f is not None else (fg_target_f or 0.0)
                    v0 = fg_start_v if fg_start_v is not None else (fg_target_v or 0.0)
                    f1 = fg_target_f if fg_target_f is not None else f0
                    v1 = fg_target_v if fg_target_v is not None else v0

                    f = f0 + (f1 - f0) * frac
                    vpp = v0 + (v1 - v0) * frac
                    try:
                        self.rfq.set_fg(f, vpp)
                    except Exception:
                        pass

                time.sleep(dt)

        self._ramp_thread = threading.Thread(target=ramp_thread, daemon=True)
        self._ramp_thread.start()