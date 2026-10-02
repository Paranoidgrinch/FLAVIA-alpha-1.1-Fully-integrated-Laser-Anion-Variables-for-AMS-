from backend.legacy_protocol import (
    DATA_WORD_COUNT,
    LegacyProtocolError,
    analog_input_raw,
    decode_linear_input,
    decode_snapshot,
    parse_get_all_data_response,
)


def test_parse_get_all_data_exact_807_words():
    values = list(range(DATA_WORD_COUNT))
    line = "DATA 807 " + ",".join(str(v) for v in values) + "\r\n"
    assert parse_get_all_data_response(line) == tuple(values)


def test_parse_rejects_wrong_count():
    try:
        parse_get_all_data_response("DATA 807 1,2,3\r\n")
    except LegacyProtocolError:
        pass
    else:
        raise AssertionError("wrong getAllData length was accepted")


def test_linear_decoder_matches_legacy_0_to_10v_scaling():
    assert decode_linear_input(0, input_full_scale_v=10.0, min_value=-500, max_value=500) == -500
    assert abs(decode_linear_input(4095, input_full_scale_v=10.0, min_value=-500, max_value=500) - 500) < 1e-9


def test_snapshot_decodes_cc1_range_sign_target_and_current():
    data = [0] * DATA_WORD_COUNT
    # CC1 analog input board 4 channel 5 -> index 165. 50% full scale.
    data[128 + 4 * 8 + 5] = 2048
    # target=3, range=5 (100 nA), autorange=1, negative=1, overload=0
    data[768] = 3 | (5 << 8) | 0x0800 | 0x8000
    decoded = decode_snapshot(data)
    assert decoded["legacy/cc1/target_index"] == 3
    assert decoded["legacy/cc1/range_index"] == 5
    assert decoded["legacy/cc1/autorange"] is True
    assert decoded["legacy/cc1/negative"] is True
    assert decoded["legacy/cc1/overload"] is False
    expected = -(2048 / 4095.0) * 100e-9
    assert abs(decoded["legacy/cc1/current_A"] - expected) < 1e-18


def test_snapshot_decodes_gcpd_range_bits_binary():
    data = [0] * DATA_WORD_COUNT
    # GCPD1 input 100% FS
    data[128 + 10 * 8 + 3] = 4095
    # board 5 digital output index 405: sel0 bit3=0, sel1 bit4=1 => range 2 = 10 uA
    data[385 + 5 * 4] = 1 << 4
    # board 5 digital input index 404: overload bit0 high => NOT overloaded (active-low)
    data[384 + 5 * 4] = 1 << 0
    decoded = decode_snapshot(data)
    assert decoded["legacy/gcpd1/range_index"] == 2
    assert decoded["legacy/gcpd1/overload"] is False
    assert abs(decoded["legacy/gcpd1/current_A"] - 10e-6) < 1e-15
