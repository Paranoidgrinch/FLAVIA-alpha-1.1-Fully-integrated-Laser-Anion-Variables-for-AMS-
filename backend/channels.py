# backend/channels.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple


# --- MQTT defaults ---
MQTT_DEFAULT_HOST = "192.168.0.20"
MQTT_DEFAULT_PORT = 1883
MQTT_DEFAULT_KEEPALIVE = 30

# Subscribe roots (aus Topic-Liste)
SUBSCRIBE_ROOTS: List[Tuple[str, int]] = [
    ("cs/#", 0),
    ("psu/#", 0),
    ("hv/#", 0),
    ("pressure/#", 0),
    ("steerer/#", 0),
]


@dataclass(frozen=True)
class ChannelDef:
    name: str
    unit: str = ""
    decimals: int = 3

    # incoming topic (optional) — hier identisch zum Channel-Namen
    topic_state: Optional[str] = None

    # outgoing command topic (optional)
    topic_cmd: Optional[str] = None

    # "meas" | "set" | "state" | "derived"
    kind: str = "meas"

    #max min
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    default_step: Optional[float] = None


# --- UI setpoint limits (from old GUI create_slider_control calls) ---
SETPOINT_LIMITS: Dict[str, Tuple[float, float, float]] = {
    # Ion Source
    "cs/oven/set_i_a": (0.0, 2.0, 0.01),
    "cs/sputter/set_u_v": (0.0, 10000.0, 10.0),

    #magnet
    "magnet_current_set": (0.0, 120.0, 0.1),

    #rfq zeuug
    "rfq/fg_frq_hz": (0.0, 5_000_000.0, 100.0),
    "rfq/fg_vpp_v": (0.0, 10.0, 0.01),

    # Ion Optics
    "cs/extraction/set_u_v": (0.0, 30000.0, 10.0),
    "cs/einzellens/set_u_v": (0.0, 30000.0, 10.0),
    "cs/lens2/set_u_v": (0.0, 12500.0, 10.0),
    "cs/qp1/set_u_v": (0.0, 6000.0, 10.0),
    "cs/qp2/set_u_v": (0.0, 6000.0, 10.0),
    "cs/qp3/set_u_v": (0.0, 6000.0, 10.0),
    "cs/esa/set_u_v": (0.0, 3000.0, 10.0),
    "cs/lens4/set_u_v": (0.0, 10000.0, 10.0),

    # Ion Cooler
    "cs/ion_cooler/set_u_v": (0.0, 40000.0, 10.0),

    # PSU/HV
    "psu/1/set_v": (0.0, 30.0, 0.1),
    "psu/2/set_v": (0.0, 75.0, 0.1),
    "hv/1/set_v": (0.0, 6500.0, 10.0),
    "hv/4/set_v": (0.0, 6500.0, 10.0),

    # Pressure AO (0–10 V)
    "pressure/set_v": (0.0, 10.0, 0.01),

    # Steerers (noch kein altes Limit vorhanden → konservativ, später easy ändern)
    "steerer/bias/set_u": (0.0, 500.0, 1.0),
    "steerer/1x/set_u": (0.0, 500.0, 1.0),
    "steerer/1y/set_u": (0.0, 500.0, 1.0),
    "steerer/2x/set_u": (0.0, 500.0, 1.0),
    "steerer/2y/set_u": (0.0, 500.0, 1.0),
    "steerer/3x/set_u": (0.0, 500.0, 1.0),
    "steerer/3y/set_u": (0.0, 500.0, 1.0),
}


CHANNELS: Dict[str, ChannelDef] = {}


def _add(
    name: str,
    *,
    unit: str = "",
    decimals: int = 3,
    kind: str = "meas",
    topic_state: Optional[str] = None,
    topic_cmd: Optional[str] = None,
    min_val: Optional[float] = None,
    max_val: Optional[float] = None,
    default_step: Optional[float] = None,
) -> None:
    # Auto-apply limits for setpoint channels (from old GUI)
    if kind == "set" and name in SETPOINT_LIMITS:
        mn, mx, st = SETPOINT_LIMITS[name]
        if min_val is None:
            min_val = mn
        if max_val is None:
            max_val = mx
        if default_step is None:
            default_step = st

    CHANNELS[name] = ChannelDef(
        name=name,
        unit=unit,
        decimals=decimals,
        kind=kind,
        topic_state=topic_state or name,
        topic_cmd=topic_cmd,
        min_val=min_val,
        max_val=max_val,
        default_step=default_step,
    )


# --- Core state channels ---
_add("mqtt_connected", kind="state")

# --- Cup switch worker (HTTP device, not MQTT topics) ---
_add("cup/connected", kind="state")
_add("cup/selected", kind="meas", decimals=0)
_add("cup/hv", kind="meas")

# --- Keithley worker channels ---
_add("keithley/connected", kind="state")
_add("keithley/current_A", unit="A", kind="meas", decimals=9)
_add("keithley/stats/mean_nA", unit="nA", kind="derived", decimals=6)
_add("keithley/stats/sigma_nA", unit="nA", kind="derived", decimals=6)
_add("keithley/stats/n", unit="", kind="derived", decimals=0)
_add("keithley/stats/t_s", unit="s", kind="derived", decimals=3)
_add("keithley/log", kind="state")

#sample und stepper channels

_add("stepper_connected", kind="meas")
_add("stepper_position_meas", kind="meas", unit="steps", decimals=0)
_add("stepper_moving", kind="meas")
_add("stepper_target_position_set", kind="meas", unit="steps", decimals=0)

_add("sample/last_timestamp", kind="meas")
_add("sample/last_command", kind="meas")
_add("sample/last_pos_idx", kind="meas", decimals=0)
_add("sample/last_target_steps", kind="meas", unit="steps", decimals=0)
_add("sample/last_sample_name", kind="meas")


#magnet channels
_add("magnet_connected", kind="state")
_add("magnet_current_set", unit="A", kind="set", decimals=3)   # set-channel im Model (kein MQTT)
_add("magnet_current_meas", unit="A", kind="meas", decimals=3)
_add("magnet_voltage_meas", unit="V", kind="meas", decimals=3)

_add("gaussmeter_connected", kind="state")
_add("magnet_field_meas", unit="kG", kind="meas", decimals=4)


# RFQ channels
_add("rfq/fg_freq_hz", kind="meas", unit="Hz", decimals=1)
_add("rfq/fg_vpp", kind="meas", unit="Vpp", decimals=3)


# =========================
# Topic list registry
# =========================
# Quelle der Struktur: topic list :contentReference[oaicite:2]{index=2}


# --- 1) cs-source (Root cs/) ---
# Analog OUT
_add("cs/sputter/set_u_v", unit="V", kind="set", decimals=2, topic_cmd="cs/sputter/cmd/set_u_v")
_add("cs/sputter/meas_u_v", unit="V", kind="meas", decimals=2)
_add("cs/sputter/meas_i_a", unit="A", kind="meas", decimals=6)
_add("cs/sputter/dbg/ao_counts", unit="cts", kind="meas", decimals=0)
_add("cs/sputter/meas_i_mA", kind="meas", unit="mA", decimals=3)

_add("cs/ionizer/set_i_a", unit="A", kind="set", decimals=6, topic_cmd="cs/ionizer/cmd/set_i_a")
_add("cs/ionizer/meas_i_a", unit="A", kind="meas", decimals=6)
_add("cs/ionizer/dbg/ao_counts", unit="cts", kind="meas", decimals=0)

_add("cs/oven/set_i_a", unit="A", kind="set", decimals=6, topic_cmd="cs/oven/cmd/set_i_a")
_add("cs/oven/meas_i_a", unit="A", kind="meas", decimals=6)
_add("cs/oven/temp_c", unit="°C", kind="meas", decimals=1)
_add("cs/oven/dbg/ao_counts", unit="cts", kind="meas", decimals=0)

# Digital OUT (state) + command IN
for name in ["vent", "wheel", "pump_valve", "pump", "source_valve"]:
    _add(f"cs/{name}/state", unit="", kind="state", decimals=0, topic_cmd=f"cs/{name}/cmd/set")


# --- 2) psu / hv / pressure ---
# Commands IN -> map to OUT "set_*" channels
_add("psu/1/set_v", unit="V", kind="set", decimals=2, topic_cmd="psu/1/cmd/set_v")
_add("psu/1/meas_v", unit="V", kind="meas", decimals=2)
_add("psu/dbg/ao1_counts", unit="cts", kind="meas", decimals=0)

_add("psu/2/set_v", unit="V", kind="set", decimals=2, topic_cmd="psu/2/cmd/set_v")
_add("psu/2/meas_v", unit="V", kind="meas", decimals=2)
_add("psu/dbg/ao2_counts", unit="cts", kind="meas", decimals=0)

_add("hv/1/set_v", unit="V", kind="set", decimals=1, topic_cmd="hv/1/cmd/set_v")
_add("hv/1/meas_v", unit="V", kind="meas", decimals=1)
_add("hv/1/meas_i_mA", unit="mA", kind="meas", decimals=4)
_add("hv/dbg/ao3_counts", unit="cts", kind="meas", decimals=0)

_add("hv/4/set_v", unit="V", kind="set", decimals=1, topic_cmd="hv/4/cmd/set_v")
_add("hv/4/meas_v", unit="V", kind="meas", decimals=1)
_add("hv/4/meas_i_mA", unit="mA", kind="meas", decimals=4)
_add("hv/dbg/ao4_counts", unit="cts", kind="meas", decimals=0)

_add("pressure/set_v", unit="V", kind="set", decimals=3, topic_cmd="pressure/cmd/set_v")
_add("pressure/meas_v", unit="V", kind="meas", decimals=3)
_add("pressure/dbg/ao_counts", unit="cts", kind="meas", decimals=0)


# --- 3) gnd-plc (Root cs/) ---
# Analog lenses + ion cooler
for base in [
    "extraction",
    "einzellens",
    "lens2",
    "ion_cooler",
    "qp1",
    "qp2",
    "qp3",
    "esa",
    "lens4",
]:
    _add(f"cs/{base}/set_u_v", unit="V", kind="set", decimals=2, topic_cmd=f"cs/{base}/cmd/set_u_v")
    _add(f"cs/{base}/meas_u_v", unit="V", kind="meas", decimals=2)
    _add(f"cs/{base}/dbg/ao_counts", unit="cts", kind="meas", decimals=0)

# Vacuum (OUT only)
_add("cs/vac1/meas_v", unit="V", kind="meas", decimals=3)
_add("cs/vac1/dbg/ai_counts", unit="cts", kind="meas", decimals=0)
_add("cs/vac2/meas_v", unit="V", kind="meas", decimals=3)
_add("cs/vac2/dbg/ai_counts", unit="cts", kind="meas", decimals=0)

# Digital (cup1..5, attenuator, quick_cool)
for name in ["cup1", "cup2", "cup3", "cup4", "cup5", "attenuator", "quick_cool"]:
    _add(f"cs/{name}/state", unit="", kind="state", decimals=0, topic_cmd=f"cs/{name}/cmd/set")


# --- 4) steerer-sps (Root steerer/) ---
for ch in ["bias", "1x", "1y", "2x", "2y", "3x", "3y"]:
    _add(f"steerer/{ch}/set_u", unit="V", kind="set", decimals=2, topic_cmd=f"steerer/{ch}/cmd/set_u")
    _add(f"steerer/{ch}/meas_u", unit="V", kind="meas", decimals=2)
    _add(f"steerer/{ch}/dbg/ao_counts", unit="cts", kind="meas", decimals=0)


# =========================
# Groups (für GUI Panels als nächster Schritt)
# =========================
GROUPS: Dict[str, List[str]] = {
    "Ion Source": [
        # Sputter: control includes meas_u, so we only list set + extra meas channels
        "cs/sputter/set_u_v",
        "cs/sputter/meas_i_a",

        # Ionizer: ONLY meas (set removed from UI/config)
        "cs/ionizer/meas_i_a",

        # Oven: control includes meas_i, temp below
        "cs/oven/set_i_a",
        "cs/oven/temp_c",
    ],

    # Still exists for config save/load, but not shown as separate group box anymore
    "Digital Controls": [
        "cs/attenuator/state",
        "cs/quick_cool/state",
    ],

    "Ion Optics": [
        # lens setpoints (control includes meas)
        "cs/extraction/set_u_v",
        "cs/einzellens/set_u_v",
        "cs/lens2/set_u_v",
        "cs/qp1/set_u_v",
        "cs/qp2/set_u_v",
        "cs/qp3/set_u_v",
        "cs/esa/set_u_v",
        "cs/lens4/set_u_v",

        # ✅ steerers belong here
        "steerer/bias/set_u",
        "steerer/1x/set_u",
        "steerer/1y/set_u",
        "steerer/2x/set_u",
        "steerer/2y/set_u",
        "steerer/3x/set_u",
        "steerer/3y/set_u",
    ],

    "Ion Cooler": [
        "cs/ion_cooler/set_u_v",

        "hv/1/set_v",
        "hv/4/set_v",
        "psu/1/set_v",
        "psu/2/set_v",

        # meas-only channels that we want visible
       
    ],

    "Pressure": [
        "pressure/set_v",
        "pressure/meas_v",
        "cs/vac1/meas_v",
        "cs/vac2/meas_v",
    ],
}


def unit_for(name: str) -> str:
    c = CHANNELS.get(name)
    return c.unit if c else ""


def decimals_for(name: str, default: int = 3) -> int:
    c = CHANNELS.get(name)
    return c.decimals if c else default


def range_for(name: str) -> Optional[Tuple[float, float]]:
    c = CHANNELS.get(name)
    if c and c.min_val is not None and c.max_val is not None:
        return (float(c.min_val), float(c.max_val))
    return None


def step_for(name: str) -> Optional[float]:
    c = CHANNELS.get(name)
    if c and c.default_step is not None:
        return float(c.default_step)
    return None