# backend/services/config_service.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Set, Optional

from ..channels import CHANNELS, GROUPS


EXTRA_KEYS = [
    "magnet_current_set",
    "rfq/fg_freq_hz",
    "rfq/fg_vpp",
]


@dataclass
class ConfigPayload:
    setpoints: Dict[str, Any]   # MQTT setpoints (cs/.../set_...)
    states: Dict[str, Any]      # MQTT states (cs/.../state)
    extras: Dict[str, Any]      # magnet/fg etc.


def _ui_channels() -> Set[str]:
    allowed: Set[str] = set()
    for _, names in GROUPS.items():
        for n in names:
            allowed.add(n)
    # include extras always
    for k in EXTRA_KEYS:
        allowed.add(k)
    return allowed


class ConfigService:
    def __init__(self, model):
        self.model = model
        self._allowed = _ui_channels()

    def _collect(self) -> ConfigPayload:
        setpoints: Dict[str, Any] = {}
        states: Dict[str, Any] = {}
        extras: Dict[str, Any] = {}

        # Normal MQTT channels from registry
        for name, c in CHANNELS.items():
            if name not in self._allowed:
                continue
            if not c.topic_cmd:
                continue

            ch = self.model.get(name)
            if ch is None:
                continue

            if c.kind == "set":
                setpoints[name] = ch.value
            elif c.kind == "state":
                states[name] = ch.value

        # Extras (magnet, FG) from model
        def mget(key: str) -> Optional[Any]:
            ch = self.model.get(key)
            return None if (ch is None) else ch.value

        # Magnet: prefer meas, fallback set
        m_meas = mget("magnet_current_meas")
        m_set = mget("magnet_current_set")
        extras["magnet_current_set"] = m_meas if m_meas is not None else m_set

        # RFQ FG: values are mirrored into model via Backend._on_rfq_fg_status
        extras["rfq/fg_freq_hz"] = mget("rfq/fg_freq_hz")
        extras["rfq/fg_vpp"] = mget("rfq/fg_vpp")

        return ConfigPayload(setpoints=setpoints, states=states, extras=extras)

    def save(self, filepath: str) -> None:
        payload = self._collect()
        data = {
            "version": 3,
            "setpoints": payload.setpoints,
            "states": payload.states,
            "extras": payload.extras,
        }
        p = Path(filepath)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def load(self, filepath: str) -> ConfigPayload:
        p = Path(filepath)
        data = json.loads(p.read_text(encoding="utf-8"))

        raw_setpoints = dict(data.get("setpoints", {}))
        raw_states = dict(data.get("states", {}))
        raw_extras = dict(data.get("extras", {}))

        setpoints = {k: v for k, v in raw_setpoints.items() if k in self._allowed}
        states = {k: v for k, v in raw_states.items() if k in self._allowed}
        extras = {k: v for k, v in raw_extras.items() if k in self._allowed}

        return ConfigPayload(setpoints=setpoints, states=states, extras=extras)