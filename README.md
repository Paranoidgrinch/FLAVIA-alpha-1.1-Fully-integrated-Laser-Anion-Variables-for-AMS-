# FLAVIA

FLAVIA (Fully integrated Laser-Anion Variables for AMS) is the control system of the laser-assisted AMS
beamline at CologneAMS. A single PyQt5 application controls the ion source, ion optics, analyzing magnet, RFQ
ion cooler, Faraday cups, current measurement, vacuum and the legacy Tandetron controls, with one data model
and one format for saved machine configurations.

The beamline is used to study selective laser photodetachment of molecular isobars in a helium-filled RFQ ion
cooler with a 532 nm CW laser, for example suppressing MgO⁻ while transmitting AlO⁻ for ²⁶Al AMS. FLAVIA also
serves as the hardware backend for the beam-tuning projects [SIRIUS](https://github.com/Paranoidgrinch/SIRIUS)
and [mcsirius](https://github.com/Paranoidgrinch/mcsirius).

## Controlled hardware

| Section | Devices and functions |
| --- | --- |
| Ion source | sputter, extraction and Einzel-lens high voltage, ionizer, sample-wheel selection, sputter time per sample, source HV kill and restore |
| Ion optics | lenses, X/Y steerers, quadrupole triplets with focus and astigmatism coordinates, ESA, calibrated HV readbacks, expected entry energy |
| Analyzing magnet | Delta SM 60-100 power supply, Hall probe (EX-6030 / LakeShore 421), magnet-current calculator from ion mass and energy |
| RFQ ion cooler | function generator and oscilloscope, Mathieu-parameter and LC calculator, LC matching via Raspberry Pi, L sweeps, cooler high voltages, gas pressure control |
| Beam diagnostics | Keithley 6485 picoammeter (tune and trace modes, gauge, plots), current converters, Faraday-cup switching, attenuator |
| Vacuum | Thyracont gauges at the ion cooler and the ESA, PLC vacuum signals |
| Legacy Tandetron | cups, apertures, BI magnet and current measurement of the existing accelerator via its TCP line protocol |

Devices are reached over MQTT (Beckhoff CX7080 PLC, see
[Beckhoff-CX7080-MQTT](https://github.com/Paranoidgrinch/Beckhoff-CX7080-MQTT)), TCP/IP, RS-232 over
Ethernet and SSH (Raspberry Pi, see [LC-Circuit-flashing](https://github.com/Paranoidgrinch/LC-Circuit-flashing)).

## Features

- Every setpoint and readback is a named channel (`backend/channels.py`). Device workers write into the data
  model; the GUI reads from it and sends requests.
- The full machine state can be saved to JSON and restored later; a dialog selects which parts are applied.
  `data/Configs/` contains the configurations from previous beam times.
- 1D and 2D tracers scan one or two setpoints against the Keithley current, with separate settling and
  measurement windows, restore the setpoints afterwards and export CSV.
- High-voltage changes are ramped and can be cancelled at any time; workers shut down without delayed writes.
- Selected channels can be logged continuously to a file.

## Installation

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py
```

On Windows use `.venv\Scripts\pip` and `.venv\Scripts\python`. Python 3.11 or newer with PyQt5, paho-mqtt,
NumPy, Matplotlib and Paramiko.

The device addresses are the defaults of the CologneAMS lab network (`192.168.0.x`) and have to be adapted to
other setups:

| Device | Defined in |
| --- | --- |
| MQTT broker (PLC) | `backend/channels.py` (`MQTT_DEFAULT_HOST`) |
| magnet supply, Hall probe, stepper, Keithley, cup switch | `backend/workers/*_worker.py` |
| RFQ function generator, oscilloscope, Raspberry Pi | `backend/workers/rfq_worker.py` |
| legacy Tandetron server | `backend/workers/legacy_tcp_worker.py` |
| vacuum gauges | `gui/windows/pressure_monitor.py` |

A Windows executable is built with PyInstaller: `pyinstaller FLAVIA.spec`.

## Standalone tools

| Folder | Tool |
| --- | --- |
| `Ionizer/` | ramps the ionizer current in programmed segments over MQTT; prebuilt `Ionizer.exe` in `dist/` |
| `Source Maintainance/` | ion-source maintenance panel (digital channels over MQTT), optionally with turbopump control; prebuilt executables in `dist/` |

## Repository layout

```text
main.py            starts the backend and the main window
backend/           data model, channel definitions, calibrations, legacy protocol
  workers/         one thread per device (MQTT, magnet, Keithley, RFQ, stepper, legacy TCP, ...)
  services/        configurations, logging, RFQ service, sample selection, exposure counter
gui/               main window, panels per beamline section, tracer, plot and pressure windows
data/Configs/      saved machine configurations
tests/             unit tests
```

Tests: `.venv/bin/pip install pytest`, then `.venv/bin/pytest`.

## History

FLAVIA alpha 1.1 replaces the two prototypes in
[FLAVIA (pre-alpha)](https://github.com/Paranoidgrinch/FLAVIA-Fully-integrated-Laser-Anion-Variables-for-AMS)
and the older single-purpose programs in [ALIS-Control-Software](https://github.com/Paranoidgrinch/ALIS-Control-Software).

## License

GPL-3.0, see [LICENSE](LICENSE).
