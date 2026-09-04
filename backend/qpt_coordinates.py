from __future__ import annotations

from typing import Tuple


QPT_MAX_VOLTAGE = 6000.0

QPT_FOCUS_SET = "qpt/focus/set_pct"
QPT_FOCUS_MEAS = "qpt/focus/meas_pct"
QPT_ASTIGMATISM_SET = "qpt/astigmatism/set_pct"
QPT_ASTIGMATISM_MEAS = "qpt/astigmatism/meas_pct"

QPT_VIRTUAL_SET_CHANNELS = (
    QPT_FOCUS_SET,
    QPT_ASTIGMATISM_SET,
)

QPT_HARDWARE_SET_CHANNELS = (
    "cs/qp1/set_u_v",
    "cs/qp2/set_u_v",
    "cs/qp3/set_u_v",
)

QPT_HARDWARE_MEAS_CHANNELS = (
    "cs/qp1/meas_u_v",
    "cs/qp2/meas_u_v",
    "cs/qp3/meas_u_v",
)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def focus_astigmatism_to_qpt(
    focus_pct: float,
    astigmatism_pct: float,
) -> Tuple[float, float, float]:
    """Convert virtual Focus/Astigmatism coordinates to QPT PSU setpoints.

    Focus is 0..100 %:
      0   -> QP1 = QP2 = QP3 = 0 V
      100 -> QP1 = QP2 = QP3 = 6000 V

    Astigmatism is 0..100 %, with 50 % neutral. It changes QP1 and
    QP3 symmetrically around the Focus voltage while QP2 remains at the
    Focus voltage. The available Astigmatism range shrinks automatically
    near 0 V and 6000 V so no PSU command can leave the valid range.
    """
    focus_pct = _clamp(focus_pct, 0.0, 100.0)
    astigmatism_pct = _clamp(astigmatism_pct, 0.0, 100.0)

    focus_voltage = QPT_MAX_VOLTAGE * focus_pct / 100.0
    astigmatism_norm = (astigmatism_pct - 50.0) / 50.0

    max_delta = min(focus_voltage, QPT_MAX_VOLTAGE - focus_voltage)
    delta = astigmatism_norm * max_delta

    qp1 = focus_voltage + delta
    qp2 = focus_voltage
    qp3 = focus_voltage - delta
    return qp1, qp2, qp3


def qpt_to_focus_astigmatism(
    qp1_v: float,
    qp2_v: float,
    qp3_v: float,
) -> Tuple[float, float]:
    """Convert QPT PSU values back to the virtual Focus/Astigmatism coordinates.

    The inverse is exact for points produced by focus_astigmatism_to_qpt().
    At Focus 0 % or 100 %, Astigmatism has no physical voltage headroom and is
    therefore reported as the neutral value 50 %.
    """
    qp1_v = _clamp(qp1_v, 0.0, QPT_MAX_VOLTAGE)
    qp2_v = _clamp(qp2_v, 0.0, QPT_MAX_VOLTAGE)
    qp3_v = _clamp(qp3_v, 0.0, QPT_MAX_VOLTAGE)

    focus_voltage = qp2_v
    focus_pct = 100.0 * focus_voltage / QPT_MAX_VOLTAGE

    max_delta = min(focus_voltage, QPT_MAX_VOLTAGE - focus_voltage)
    if max_delta <= 1e-12:
        return focus_pct, 50.0

    delta = 0.5 * (qp1_v - qp3_v)
    astigmatism_pct = 50.0 + 50.0 * delta / max_delta
    return focus_pct, _clamp(astigmatism_pct, 0.0, 100.0)
