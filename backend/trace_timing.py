from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TracePointTiming:
    dwell_s: float
    settle_s: float
    measure_s: float
    timeout_s: float


def build_trace_point_timing(
    dwell_s: float,
    bucket_interval_s: float,
    poll_hz: float,
) -> TracePointTiming:
    dwell_s = float(dwell_s)
    bucket_interval_s = float(bucket_interval_s)
    poll_hz = float(poll_hz)

    if bucket_interval_s <= 0.0:
        raise ValueError('bucket_interval_s must be > 0')

    if poll_hz <= 0.0:
        raise ValueError('poll_hz must be > 0')

    if dwell_s < bucket_interval_s:
        raise ValueError('dwell_s must be at least one TRACE bucket')

    settle_s = max(0.0, dwell_s - bucket_interval_s)
    poll_period_s = 1.0 / poll_hz
    timeout_s = bucket_interval_s + max(0.5, 3.0 * poll_period_s)

    return TracePointTiming(
        dwell_s=dwell_s,
        settle_s=settle_s,
        measure_s=bucket_interval_s,
        timeout_s=timeout_s,
    )
