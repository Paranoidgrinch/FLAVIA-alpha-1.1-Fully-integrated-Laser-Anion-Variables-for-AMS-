from __future__ import annotations

from typing import Iterable, Sequence

from .legacy_definitions import (
    CC_RANGE_FULL_SCALE_A,
    GCPD_RANGE_FULL_SCALE_A,
    HEE_ESA_INPUT_FULL_SCALE_V,
    HEE_ESA_READBACKS,
    LEGACY_ANALOG_CONTROLS,
    LEGACY_DIGITAL_CONTROLS,
)

DATA_WORD_COUNT = 807
MAX_RESPONSE_BYTES = 131072


class LegacyProtocolError(ValueError):
    pass


def parse_get_all_data_response(response: str | bytes) -> tuple[int, ...]:
    if isinstance(response, bytes):
        try:
            response = response.decode("ascii")
        except UnicodeDecodeError as exc:
            raise LegacyProtocolError("Legacy response is not ASCII") from exc

    line = response.rstrip("\r\n")
    prefix = f"DATA {DATA_WORD_COUNT} "
    if not line.startswith(prefix):
        raise LegacyProtocolError("Invalid getAllData prefix")

    payload = line[len(prefix):]
    parts = payload.split(",")
    if len(parts) != DATA_WORD_COUNT:
        raise LegacyProtocolError(
            f"Expected {DATA_WORD_COUNT} data words, got {len(parts)}"
        )

    values = []
    for index, text in enumerate(parts):
        try:
            value = int(text)
        except ValueError as exc:
            raise LegacyProtocolError(f"Data word {index} is not an integer") from exc
        if value < 0 or value > 0xFFFF:
            raise LegacyProtocolError(f"Data word {index} outside ushort range")
        values.append(value)
    return tuple(values)


def analog_input_raw(data: Sequence[int], board: int, channel: int) -> int:
    return int(data[128 + int(board) * 8 + int(channel)])


def digital_input(data: Sequence[int], board: int, channel: int) -> bool:
    word = int(data[384 + int(board) * 4])
    return bool(word & (1 << int(channel)))


def digital_output(data: Sequence[int], board: int, channel: int) -> bool:
    word = int(data[385 + int(board) * 4])
    return bool(word & (1 << int(channel)))


def decode_linear_input(
    raw_counts: int,
    *,
    input_full_scale_v: float,
    min_value: float,
    max_value: float,
    min_input_v: float = 0.0,
) -> float:
    """Mirror anaData.MakeInActual() for normal Analog/Bipolar inputs."""
    max_input_v = float(input_full_scale_v)
    if max_input_v <= float(min_input_v):
        raise LegacyProtocolError("Invalid analog input scaling")
    input_v = float(raw_counts) / 409.5
    relative = (input_v - float(min_input_v)) / (max_input_v - float(min_input_v))
    return relative * (float(max_value) - float(min_value)) + float(min_value)


def _cc_status(data: Sequence[int], converter: int) -> int:
    return int(data[768 if int(converter) == 0 else 803])


def decode_snapshot(data: Sequence[int]) -> dict[str, object]:
    if len(data) != DATA_WORD_COUNT:
        raise LegacyProtocolError(f"Snapshot length is {len(data)}, expected {DATA_WORD_COUNT}")

    out: dict[str, object] = {}

    # Normal legacy analog readbacks. Virtual controls have no meaningful
    # direct MakeInActual() readback in the old code and are intentionally
    # omitted here until their individual plate mapping is fully verified.
    for definition in LEGACY_ANALOG_CONTROLS:
        if definition.virtual:
            continue
        raw = analog_input_raw(data, definition.board_in, definition.channel_in)
        out[definition.meas_channel] = decode_linear_input(
            raw,
            input_full_scale_v=definition.input_full_scale_v,
            min_value=definition.readback_min_val,
            max_value=definition.readback_max_val,
        )

    # The three additional HEE ESA monitor channels are plain 0..100 kV
    # readbacks. ESA1+ is already covered by ID 47 above.
    for _label, channel, board, input_channel in HEE_ESA_READBACKS:
        input_fs_v = HEE_ESA_INPUT_FULL_SCALE_V[channel]
        raw = analog_input_raw(data, board, input_channel)
        out[channel] = decode_linear_input(
            raw,
            input_full_scale_v=input_fs_v,
            min_value=0.0,
            max_value=100.0,
        )

    # Cups/apertures are active-low in io.lst: output bit 0 means inserted.
    for definition in LEGACY_DIGITAL_CONTROLS:
        raw_state = digital_output(data, definition.board, definition.channel)
        inserted = (not raw_state) if definition.active_low_inserted else raw_state
        out[definition.state_channel] = inserted

    # Current Converter 1/2.
    for converter, key, board in ((0, "cc1", 4), (1, "cc2", 8)):
        status = _cc_status(data, converter)
        raw = analog_input_raw(data, board, 5)
        fraction_fs = float(raw) / 4095.0
        range_code = (status >> 8) & 0x7
        overload = bool(status & 0x4000)
        negative = bool(status & 0x8000)
        autorange = bool(status & 0x0800)
        target = status & 0xF

        out[f"legacy/{key}/percent_fs"] = fraction_fs * 100.0
        out[f"legacy/{key}/range_index"] = range_code
        out[f"legacy/{key}/overload"] = overload
        out[f"legacy/{key}/negative"] = negative
        out[f"legacy/{key}/autorange"] = autorange
        out[f"legacy/{key}/target_index"] = target

        if 0 <= range_code < len(CC_RANGE_FULL_SCALE_A):
            current = fraction_fs * CC_RANGE_FULL_SCALE_A[range_code]
            out[f"legacy/{key}/current_A"] = -current if negative else current
        else:
            out[f"legacy/{key}/current_A"] = None

    # GCPD/OFC1 and OFC2.  Select0 is the LSB, Select1 the MSB.
    gcpd = (
        ("gcpd1", 10, 3, 5, 3, 4, 5, 0),
        ("gcpd2", 10, 4, 6, 6, 7, 6, 0),
    )
    for key, board, channel, sel_board, sel0, sel1, ol_board, ol_channel in gcpd:
        raw = analog_input_raw(data, board, channel)
        fraction_fs = float(raw) / 4095.0
        range_code = (1 if digital_output(data, sel_board, sel0) else 0)
        range_code |= (2 if digital_output(data, sel_board, sel1) else 0)
        # io.lst overload input semantics: off = Active => active low.
        overload = not digital_input(data, ol_board, ol_channel)

        out[f"legacy/{key}/percent_fs"] = fraction_fs * 100.0
        out[f"legacy/{key}/range_index"] = range_code
        out[f"legacy/{key}/overload"] = overload
        out[f"legacy/{key}/current_A"] = fraction_fs * GCPD_RANGE_FULL_SCALE_A[range_code]

    return out
