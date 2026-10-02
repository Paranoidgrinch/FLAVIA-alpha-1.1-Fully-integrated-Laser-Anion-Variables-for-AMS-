from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Dict, Optional, Tuple

from .legacy_definitions import LEGACY_CURRENT_BY_KEY


@dataclass(frozen=True)
class TraceMeasurementSource:
    key: str
    label: str
    value_channel: str
    scale_to_nA: float
    count_channel: Optional[str] = None
    range_channel: Optional[str] = None
    overload_channel: Optional[str] = None
    uses_keithley_trace: bool = False
    nominal_poll_hz: float = 1.0


TRACE_MEASUREMENT_SOURCES: Dict[str, TraceMeasurementSource] = {
    "keithley": TraceMeasurementSource(
        key="keithley",
        label="Keithley",
        value_channel="keithley/trace/mean_nA",
        count_channel="keithley/trace/n",
        scale_to_nA=1.0,
        uses_keithley_trace=True,
        nominal_poll_hz=10.0,
    ),
}

for _key in ("cc1", "cc2", "gcpd1", "gcpd2"):
    _dev = LEGACY_CURRENT_BY_KEY[_key]
    TRACE_MEASUREMENT_SOURCES[_key] = TraceMeasurementSource(
        key=_key,
        label=_dev.label,
        value_channel=_dev.current_channel,
        scale_to_nA=1e9,
        range_channel=_dev.range_channel,
        overload_channel=_dev.overload_channel,
        uses_keithley_trace=False,
        nominal_poll_hz=1.0,
    )


TRACE_MEASUREMENT_ORDER: Tuple[str, ...] = ("keithley", "cc1", "cc2", "gcpd1", "gcpd2")


def source_for(key: str) -> TraceMeasurementSource:
    return TRACE_MEASUREMENT_SOURCES.get(str(key), TRACE_MEASUREMENT_SOURCES["keithley"])


def read_measurement_nA(
    model,
    source_key: str,
    *,
    min_timestamp: Optional[float] = None,
    max_age_s: Optional[float] = None,
) -> Optional[float]:
    src = source_for(source_key)

    if src.count_channel:
        count = model.get(src.count_channel)
        try:
            if count is None or count.value is None or int(count.value) <= 0:
                return None
        except Exception:
            return None

    if src.overload_channel:
        overload = model.get(src.overload_channel)
        if overload is not None and bool(overload.value):
            return None

    ch = model.get(src.value_channel)
    if ch is None or ch.value is None:
        return None

    if getattr(ch, "quality", "good") not in ("good", ""):
        return None

    ts = float(getattr(ch, "timestamp", 0.0) or 0.0)
    if min_timestamp is not None and ts < float(min_timestamp):
        return None
    if max_age_s is not None and ts > 0.0 and (time.time() - ts) > float(max_age_s):
        return None

    try:
        return float(ch.value) * float(src.scale_to_nA)
    except Exception:
        return None


def read_range_label(model, source_key: str) -> str:
    src = source_for(source_key)
    if not src.range_channel:
        return ""

    ch = model.get(src.range_channel)
    if ch is None or ch.value is None:
        return ""

    try:
        idx = int(ch.value)
    except Exception:
        return ""

    dev = LEGACY_CURRENT_BY_KEY.get(source_key)
    if dev is None or idx < 0 or idx >= len(dev.range_labels):
        return str(idx)
    return dev.range_labels[idx]
