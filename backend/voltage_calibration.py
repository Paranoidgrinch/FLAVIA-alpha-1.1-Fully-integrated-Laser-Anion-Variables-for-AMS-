from __future__ import annotations

from bisect import bisect_right
from typing import Dict, Tuple


# Calibration data from Spannungsverlauf.ipynb.
# x = voltage set in FLAVIA/PLC [V]
# y = externally measured actual voltage (*_m_mV arrays) [V]

EXTRACTION_SET_V = tuple(range(0, 1001, 100)) + tuple(range(2000, 12001, 1000)) + tuple(range(12500, 15001, 500)) + tuple(range(15100, 25001, 100))
EXTRACTION_MEASURED_V = (
    8, 101.2, 201.2, 303.6, 403.9, 506.6, 609.3, 709.4, 810.7, 913.1, 1013, 2009, 3015, 4019, 5023,
    6027, 7032, 8041, 9048, 10054, 11040, 12050, 12550, 13050, 13550, 14060, 14560, 15060, 15160,
    15260, 15360, 15460, 15560, 15660, 15760, 15860, 15960, 16060, 16160, 16260, 16360, 16460,
    16560, 16660, 16770, 16870, 16970, 17070, 17170, 17270, 17370, 17470, 17570, 17670, 17770,
    17870, 17970, 18070, 18170, 18270, 18370, 18470, 18570, 18670, 18770, 18870, 18970, 19080,
    19180, 19280, 19380, 19480, 19580, 19680, 19780, 19880, 19980, 20080, 20180, 20280, 20380,
    20480, 20580, 20680, 20780, 20880, 20990, 21090, 21190, 21290, 21390, 21490, 21590, 21690,
    21790, 21890, 21990, 22090, 22190, 22290, 22390, 22490, 22590, 22690, 22790, 22890, 22990,
    23100, 23200, 23300, 23400, 23500, 23600, 23700, 23800, 23900, 24000, 24100, 24200, 24300,
    24400, 24500, 24600, 24700, 24800, 24900, 25000, 25100,
)

ION_COOLER_SET_V = tuple(range(0, 1001, 100)) + tuple(range(2000, 16001, 1000)) + tuple(range(16100, 30001, 100))
ION_COOLER_MEASURED_V = (
    5.3, 58.6, 147.6, 243.8, 329.9, 437.2, 540.6, 636.8, 729.3, 840.5, 943.2, 1937, 2923, 3940,
    4978, 5981, 6986, 7970, 8962, 9963, 10968, 11970, 12980, 13980, 14980, 15980, 16090, 16170,
    16260, 16360, 16470, 16570, 16670, 16800, 16870, 17000, 17090, 17190, 17280, 17390, 17500,
    17600, 17700, 17800, 17900, 18000, 18100, 18200, 18300, 18400, 18480, 18600, 18700, 18800,
    18900, 19000, 19100, 19200, 19300, 19400, 19500, 19600, 19690, 19790, 19900, 20000, 20100,
    20200, 20300, 20390, 20490, 20590, 20690, 20790, 20890, 20990, 21060, 21170, 21280, 21340,
    21490, 21570, 21670, 21770, 21870, 21970, 22080, 22180, 22270, 22390, 22490, 22590, 22700,
    22800, 22900, 23000, 23100, 23200, 23300, 23390, 23500, 23600, 23700, 23800, 23900, 24000,
    24100, 24200, 24300, 24400, 24490, 24590, 24690, 24790, 24890, 25000, 25090, 25190, 25290,
    25390, 25490, 25590, 25690, 25790, 25890, 25990, 26090, 26190, 26290, 26390, 26490, 26590,
    26690, 26790, 26890, 26990, 27090, 27190, 27290, 27390, 27490, 27590, 27690, 27790, 27890,
    27990, 28090, 28190, 28290, 28390, 28490, 28590, 28690, 28790, 28890, 28990, 29090, 29190,
    29290, 29390, 29490, 29580, 29690, 29780, 29880, 29980,
)

SPUTTER_SET_V = tuple(range(0, 9001, 100))
SPUTTER_MEASURED_V = (
    0, 100.8, 200.9, 301, 401.1, 501.3, 601.3, 701.2, 801, 901.3, 1001.2, 1090, 1190, 1289, 1388,
    1487, 1587, 1685, 1785, 1884, 1982, 2082, 2181, 2280, 2380, 2479, 2579, 2678, 2777, 2876, 2975,
    3074, 3174, 3273, 3372, 3471, 3571, 3670, 3769, 3868, 3968, 4067, 4166, 4266, 4365, 4464, 4563,
    4662, 4761, 4861, 4960, 5059, 5159, 5258, 5357, 5457, 5556, 5655, 5754, 5853, 5952, 6052, 6151,
    6250, 6350, 6449, 6548, 6648, 6747, 6846, 6945, 7044, 7143, 7243, 7342, 7441, 7540, 7639, 7738,
    7837, 7937, 8036, 8135, 8235, 8334, 8433, 8532, 8631, 8730, 8830, 8929,
)

CALIBRATION_CURVES: Dict[str, Tuple[Tuple[float, ...], Tuple[float, ...]]] = {
    "cs/extraction/set_u_v": (tuple(map(float, EXTRACTION_SET_V)), tuple(map(float, EXTRACTION_MEASURED_V))),
    "cs/ion_cooler/set_u_v": (tuple(map(float, ION_COOLER_SET_V)), tuple(map(float, ION_COOLER_MEASURED_V))),
    "cs/sputter/set_u_v": (tuple(map(float, SPUTTER_SET_V)), tuple(map(float, SPUTTER_MEASURED_V))),
}


def _interpolate_or_extrapolate(x: float, xs: Tuple[float, ...], ys: Tuple[float, ...]) -> float:
    """Piecewise-linear calibration with endpoint extrapolation outside the measured range."""
    if len(xs) != len(ys) or len(xs) < 2:
        raise ValueError("Calibration curve needs at least two paired points.")

    x = float(x)
    if x <= xs[0]:
        i0, i1 = 0, 1
    elif x >= xs[-1]:
        i0, i1 = len(xs) - 2, len(xs) - 1
    else:
        i1 = bisect_right(xs, x)
        i0 = i1 - 1

    x0, x1 = xs[i0], xs[i1]
    y0, y1 = ys[i0], ys[i1]
    if x1 == x0:
        return float(y0)
    return float(y0 + (x - x0) * (y1 - y0) / (x1 - x0))


def calibrated_voltage(set_channel: str, set_voltage_v: float) -> float:
    """Return expected actual voltage [V] for a calibrated FLAVIA set channel."""
    try:
        xs, ys = CALIBRATION_CURVES[set_channel]
    except KeyError as exc:
        raise KeyError(f"No voltage calibration for {set_channel!r}") from exc
    return _interpolate_or_extrapolate(float(set_voltage_v), xs, ys)


def expected_entry_energy_ev(extraction_set_v: float, sputter_set_v: float, ion_cooler_set_v: float) -> float:
    """Expected ion-cooler entry energy for singly charged ions, numerically in eV."""
    extraction_v = calibrated_voltage("cs/extraction/set_u_v", extraction_set_v)
    sputter_v = calibrated_voltage("cs/sputter/set_u_v", sputter_set_v)
    cooler_v = calibrated_voltage("cs/ion_cooler/set_u_v", ion_cooler_set_v)
    return extraction_v + sputter_v - cooler_v
