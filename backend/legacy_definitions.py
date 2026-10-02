from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class LegacyAnalogDefinition:
    key: str
    label: str
    legacy_id: int
    set_channel: str
    meas_channel: str
    unit: str
    min_val: float
    max_val: float
    default_step: float
    decimals: int
    board_in: int
    channel_in: int
    input_full_scale_v: float
    readback_min_val: float
    readback_max_val: float
    virtual: bool = False


@dataclass(frozen=True)
class LegacyDigitalDefinition:
    key: str
    label: str
    state_channel: str
    board: int
    channel: int
    io_list_id: Optional[int] = None
    exclusive_cup: bool = False
    confirm_retract: bool = False
    active_low_inserted: bool = True


@dataclass(frozen=True)
class LegacyCurrentDeviceDefinition:
    key: str
    label: str
    percent_channel: str
    current_channel: str
    range_channel: str
    overload_channel: str
    range_labels: Tuple[str, ...]
    range_full_scale_A: Tuple[float, ...]
    autorange_channel: Optional[str] = None
    negative_channel: Optional[str] = None
    target_channel: Optional[str] = None
    board_in: Optional[int] = None
    channel_in: Optional[int] = None
    status_data_index: Optional[int] = None
    range_select_bits: Tuple[Tuple[int, int], ...] = ()
    overload_input: Optional[Tuple[int, int]] = None


# GUI limits are kept separate from the legacy readback scaling.  In a few
# places FLAVIA intentionally restricts the operator range more tightly than
# the old io.lst hardware range.
LEGACY_ANALOG_CONTROLS: Tuple[LegacyAnalogDefinition, ...] = (
    LegacyAnalogDefinition("bi_magnet", "BI Magnet", 41,
        "legacy/bi/magnet/set_a", "legacy/bi/magnet/meas_a", "A",
        0.0, 260.0, 0.1, 2, 2, 5, 5.0, 0.0, 280.0),
    LegacyAnalogDefinition("bi_x1", "BI X Steerer 1", 430,
        "legacy/bi/x_steerer_1/set_v", "legacy/bi/x_steerer_1/meas_v", "V",
        -500.0, 500.0, 1.0, 1, 2, 0, 10.0, -500.0, 500.0),
    LegacyAnalogDefinition("bi_x2", "BI X Steerer 2", 433,
        "legacy/bi/x_steerer_2/set_v", "legacy/bi/x_steerer_2/meas_v", "V",
        -500.0, 500.0, 1.0, 1, 3, 2, 10.0, -500.0, 500.0),
    LegacyAnalogDefinition("bi_y1", "BI Y Steerer 1", 431,
        "legacy/bi/y_steerer_1/set_v", "legacy/bi/y_steerer_1/meas_v", "V",
        -425.0, 425.0, 1.0, 1, 2, 3, 10.0, -425.0, 425.0),
    LegacyAnalogDefinition("bi_y2", "BI Y Steerer 2", 432,
        "legacy/bi/y_steerer_2/set_v", "legacy/bi/y_steerer_2/meas_v", "V",
        -500.0, 500.0, 1.0, 1, 2, 4, 10.0, -500.0, 500.0),
    LegacyAnalogDefinition("bi_einzellens", "BI Einzellens", 42,
        "legacy/bi/einzellens/set_kv", "legacy/bi/einzellens/meas_kv", "kV",
        0.0, 30.0, 0.1, 2, 3, 3, 10.0, 0.0, 30.0),

    LegacyAnalogDefinition("acc_terminal", "ACC Terminal Voltage", 45,
        "legacy/acc/terminal_voltage/set_kv", "legacy/acc/terminal_voltage/meas_kv", "kV",
        0.0, 6000.0, 0.1, 1, 6, 5, 9.983, 0.0, 6600.0),
    LegacyAnalogDefinition("acc_q_snout", "ACC Q Snout Lens", 44,
        "legacy/acc/q_snout_lens/set_kv", "legacy/acc/q_snout_lens/meas_kv", "kV",
        0.0, 30.0, 0.1, 2, 4, 0, 10.0, 0.0, 60.0),
    LegacyAnalogDefinition("acc_q_focus", "ACC QPole Focus", 440,
        "legacy/acc/qpole_focus/set_pct", "legacy/acc/qpole_focus/meas_pct", "%",
        0.0, 100.0, 0.1, 1, 6, 0, 0.0, 0.0, 100.0, virtual=True),
    LegacyAnalogDefinition("acc_q_astig", "ACC QPole Astigmatism", 441,
        "legacy/acc/qpole_astigmatism/set_pct", "legacy/acc/qpole_astigmatism/meas_pct", "%",
        -30.0, 30.0, 0.1, 1, 6, 3, 0.0, -30.0, 30.0, virtual=True),

    # io.lst labels these HES steerer engineering values as kV with +/-10000;
    # the old unit convention is still ambiguous.  Keep the already agreed
    # FLAVIA UI range here, but do not use the raw snapshot for their readback
    # until that engineering scaling has been validated live.
    LegacyAnalogDefinition("hes_x1", "HES X Steerer 1", 450,
        "legacy/hes/x_steerer_1/set_kv", "legacy/hes/x_steerer_1/meas_kv", "kV",
        -10.0, 10.0, 0.01, 2, 8, 0, 10.0, -10000.0, 10000.0),
    LegacyAnalogDefinition("hes_x2", "HES X Steerer 2", 451,
        "legacy/hes/x_steerer_2/set_kv", "legacy/hes/x_steerer_2/meas_kv", "kV",
        -10.0, 10.0, 0.01, 2, 8, 3, 10.0, -10000.0, 10000.0),
    LegacyAnalogDefinition("hes_y1", "HES Y Steerer 1", 452,
        "legacy/hes/y_steerer_1/set_kv", "legacy/hes/y_steerer_1/meas_kv", "kV",
        -10.0, 10.0, 0.01, 2, 8, 2, 10.0, -10000.0, 10000.0),
    LegacyAnalogDefinition("hes_y2", "HES Y Steerer 2", 453,
        "legacy/hes/y_steerer_2/set_kv", "legacy/hes/y_steerer_2/meas_kv", "kV",
        -10.0, 10.0, 0.01, 2, 8, 4, 10.0, -10000.0, 10000.0),
    LegacyAnalogDefinition("hes_q_focus", "HES QPole Focus", 442,
        "legacy/hes/qpole_focus/set_pct", "legacy/hes/qpole_focus/meas_pct", "%",
        0.0, 100.0, 0.1, 1, 9, 2, 0.0, 0.0, 100.0, virtual=True),
    LegacyAnalogDefinition("hes_q_astig", "HES QPole Astigmatism", 443,
        "legacy/hes/qpole_astigmatism/set_pct", "legacy/hes/qpole_astigmatism/meas_pct", "%",
        -30.0, 30.0, 0.1, 1, 9, 4, 0.0, -30.0, 30.0, virtual=True),

    LegacyAnalogDefinition("hem_magnet", "HEM Magnet", 46,
        "legacy/hem/magnet/set_a", "legacy/hem/magnet/meas_a", "A",
        0.0, 260.0, 0.1, 2, 10, 5, 5.0, 0.0, 270.0),

    LegacyAnalogDefinition("hee_q_focus", "HEE QPole Focus", 460,
        "legacy/hee/qpole_focus/set_pct", "legacy/hee/qpole_focus/meas_pct", "%",
        0.0, 100.0, 0.1, 1, 11, 0, 0.0, 0.0, 100.0, virtual=True),
    LegacyAnalogDefinition("hee_q_astig", "HEE QPole Astigmatism", 461,
        "legacy/hee/qpole_astigmatism/set_pct", "legacy/hee/qpole_astigmatism/meas_pct", "%",
        -30.0, 30.0, 0.1, 1, 11, 3, 0.0, -30.0, 30.0, virtual=True),
    LegacyAnalogDefinition("hee_esa_common", "HEE ESA 1 + 2", 47,
        "legacy/hee/esa_common/set_pct", "legacy/hee/esa1_pos/meas_kv", "kV",
        0.0, 100.0, 0.1, 1, 11, 5, 5.0, 0.0, 100.0),
    LegacyAnalogDefinition("hee_y", "HEE Y Steerer", 462,
        "legacy/hee/y_steerer/set_kv", "legacy/hee/y_steerer/meas_kv", "V",
        -10000.0, 10000.0, 10.0, 1, 12, 2, 10.0, -10000.0, 10000.0),

    LegacyAnalogDefinition("dsw_q_focus", "DSW QPole Focus", 470,
        "legacy/dsw/qpole_focus/set_pct", "legacy/dsw/qpole_focus/meas_pct", "%",
        0.0, 100.0, 0.1, 1, 13, 0, 0.0, 0.0, 100.0, virtual=True),
    LegacyAnalogDefinition("dsw_q_astig", "DSW QPole Astigmatism", 471,
        "legacy/dsw/qpole_astigmatism/set_pct", "legacy/dsw/qpole_astigmatism/meas_pct", "%",
        -30.0, 30.0, 0.1, 1, 13, 3, 0.0, -30.0, 30.0, virtual=True),
    LegacyAnalogDefinition("dsw_magnet", "DSW Magnet", 48,
        "legacy/dsw/magnet/set_a", "legacy/dsw/magnet/meas_a", "A",
        0.0, 185.5, 0.1, 2, 13, 5, 5.0, 0.0, 200.0),
)

LEGACY_ANALOG_BY_SET: Dict[str, LegacyAnalogDefinition] = {
    d.set_channel: d for d in LEGACY_ANALOG_CONTROLS
}

_GROUP_PREFIXES = {
    "BI Controls": "bi_",
    "ACC Controls": "acc_",
    "HES Controls": "hes_",
    "HEM Controls": "hem_",
    "HEE Controls": "hee_",
    "DSW Controls": "dsw_",
}
LEGACY_ANALOG_BY_GROUP: Dict[str, Tuple[LegacyAnalogDefinition, ...]] = {
    group: tuple(d for d in LEGACY_ANALOG_CONTROLS if d.key.startswith(prefix))
    for group, prefix in _GROUP_PREFIXES.items()
}


LEGACY_DIGITAL_CONTROLS: Tuple[LegacyDigitalDefinition, ...] = (
    LegacyDigitalDefinition("bi_cup", "BI Cup", "legacy/bi/cup/inserted", 1, 13, 632, exclusive_cup=True),
    LegacyDigitalDefinition("bi_app", "BI App", "legacy/bi/aperture/inserted", 1, 12, 633),
    LegacyDigitalDefinition("acc_cup", "ACC Cup", "legacy/acc/cup/inserted", 2, 12, 243, exclusive_cup=True),
    LegacyDigitalDefinition("acc_app", "ACC App", "legacy/acc/aperture/inserted", 2, 11, 634),
    LegacyDigitalDefinition("hes_cup", "HES Cup", "legacy/hes/cup/inserted", 4, 15, 636, exclusive_cup=True),
    LegacyDigitalDefinition("hes_app", "HES App", "legacy/hes/aperture/inserted", 4, 14, 635),
    LegacyDigitalDefinition("hem_cup", "HEM FC", "legacy/hem/cup/inserted", 5, 8, None, exclusive_cup=True),
    LegacyDigitalDefinition("hem_app1", "HEM App1", "legacy/hem/aperture_1/inserted", 5, 9, 637),
    LegacyDigitalDefinition("hem_app2", "HEM App2", "legacy/hem/aperture_2/inserted", 5, 10, 638),
    LegacyDigitalDefinition("esa_cup", "ESA FC", "legacy/hee/cup/inserted", 6, 10, 639, exclusive_cup=True),
    LegacyDigitalDefinition("gic_cup", "GIC Cup", "legacy/gic/cup/inserted", 7, 12, 640, confirm_retract=True),
)

LEGACY_DIGITAL_BY_CHANNEL: Dict[str, LegacyDigitalDefinition] = {
    d.state_channel: d for d in LEGACY_DIGITAL_CONTROLS
}
LEGACY_EXCLUSIVE_CUP_CHANNELS: Tuple[str, ...] = tuple(
    d.state_channel for d in LEGACY_DIGITAL_CONTROLS if d.exclusive_cup
)


# HEE ESA has one common setpoint and four independent voltage readbacks.
HEE_ESA_READBACKS: Tuple[Tuple[str, str, int, int], ...] = (
    ("ESA 1+", "legacy/hee/esa1_pos/meas_kv", 11, 5),
    ("ESA 1-", "legacy/hee/esa1_neg/meas_kv", 11, 4),
    ("ESA 2+", "legacy/hee/esa2_pos/meas_kv", 12, 5),
    ("ESA 2-", "legacy/hee/esa2_neg/meas_kv", 12, 4),
)
HEE_ESA_INPUT_FULL_SCALE_V: Dict[str, float] = {
    "legacy/hee/esa1_pos/meas_kv": 5.0,
    "legacy/hee/esa1_neg/meas_kv": 10.0,
    "legacy/hee/esa2_pos/meas_kv": 10.0,
    "legacy/hee/esa2_neg/meas_kv": 10.0,
}


# Hardware range codes verified from procIo.cs: large -> small.
CC_RANGE_LABELS = ("10 mA", "1 mA", "100 uA", "10 uA", "1 uA", "100 nA", "10 nA")
CC_RANGE_FULL_SCALE_A = (10e-3, 1e-3, 100e-6, 10e-6, 1e-6, 100e-9, 10e-9)
GCPD_RANGE_LABELS = ("100 nA", "1 uA", "10 uA", "100 uA")
GCPD_RANGE_FULL_SCALE_A = (100e-9, 1e-6, 10e-6, 100e-6)

LEGACY_CURRENT_DEVICES: Tuple[LegacyCurrentDeviceDefinition, ...] = (
    LegacyCurrentDeviceDefinition(
        "cc1", "Current Converter 1",
        "legacy/cc1/percent_fs", "legacy/cc1/current_A", "legacy/cc1/range_index",
        "legacy/cc1/overload", CC_RANGE_LABELS, CC_RANGE_FULL_SCALE_A,
        autorange_channel="legacy/cc1/autorange",
        negative_channel="legacy/cc1/negative",
        target_channel="legacy/cc1/target_index",
        board_in=4, channel_in=5, status_data_index=768,
    ),
    LegacyCurrentDeviceDefinition(
        "cc2", "Current Converter 2",
        "legacy/cc2/percent_fs", "legacy/cc2/current_A", "legacy/cc2/range_index",
        "legacy/cc2/overload", CC_RANGE_LABELS, CC_RANGE_FULL_SCALE_A,
        autorange_channel="legacy/cc2/autorange",
        negative_channel="legacy/cc2/negative",
        target_channel="legacy/cc2/target_index",
        board_in=8, channel_in=5, status_data_index=803,
    ),
    LegacyCurrentDeviceDefinition(
        "gcpd1", "GCPD 1",
        "legacy/gcpd1/percent_fs", "legacy/gcpd1/current_A", "legacy/gcpd1/range_index",
        "legacy/gcpd1/overload", GCPD_RANGE_LABELS, GCPD_RANGE_FULL_SCALE_A,
        board_in=10, channel_in=3, range_select_bits=((5, 3), (5, 4)), overload_input=(5, 0),
    ),
    LegacyCurrentDeviceDefinition(
        "gcpd2", "GCPD 2",
        "legacy/gcpd2/percent_fs", "legacy/gcpd2/current_A", "legacy/gcpd2/range_index",
        "legacy/gcpd2/overload", GCPD_RANGE_LABELS, GCPD_RANGE_FULL_SCALE_A,
        board_in=10, channel_in=4, range_select_bits=((6, 6), (6, 7)), overload_input=(6, 0),
    ),
)
LEGACY_CURRENT_BY_KEY: Dict[str, LegacyCurrentDeviceDefinition] = {
    d.key: d for d in LEGACY_CURRENT_DEVICES
}
