# FLAVIA — Fully integrated Laser-Anion Variables for AMS

**FLAVIA is the control system of the laser-assisted AMS beamline at CologneAMS.** One PyQt5 application
brings every device of the experiment — ion source, ion optics, analyzing magnet, RFQ ion cooler, Faraday
cups, current measurement, vacuum and the legacy Tandetron controls — into one interface, one data model and
one set of saved machine configurations.

The beamline is built to study selective laser photodetachment of molecular isobars (e.g. suppressing MgO⁻
while transmitting AlO⁻ for ²⁶Al AMS) in a helium-filled RFQ ion cooler with a 532 nm CW laser. FLAVIA is
also the hardware backend for the automated beam-tuning projects [SIRIUS](https://github.com/Paranoidgrinch/SIRIUS)
and [mcsirius](https://github.com/Paranoidgrinch/mcsirius).

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![GUI](https://img.shields.io/badge/GUI-PyQt5-41CD52?style=flat-square&logo=qt&logoColor=white)
![Status](https://img.shields.io/badge/status-in_use_at_the_beamline-3FB950?style=flat-square)
[![License](https://img.shields.io/badge/license-GPL--3.0-394B59?style=flat-square)](LICENSE)

## What it controls

| Area | Devices and functions |
| --- | --- |
| **Ion source** | sputter, extraction and einzel-lens high voltage, ionizer, sample wheel selection, sputter/exposure time per sample, *Kill / Restore Source HV* |
| **Ion optics** | lenses, steerers (X/Y), quadrupole triplet with focus/astigmatism coordinates, ESA, calibrated HV readbacks and expected entry energy |
| **Analyzing magnet** | Delta SM 60-100 power supply, Hall probe (EX-6030 / LakeShore 421), magnet-current calculator from ion mass and energy |
| **RFQ ion cooler** | function generator and oscilloscope, Mathieu-parameter and LC-circuit calculator, LC matching via the Raspberry Pi, L sweeps, ion-cooler high voltages, helium pressure control |
| **Beam diagnostics** | Keithley 6485 picoammeter (tune and trace modes, gauge view, plots), current converters, Faraday-cup switching, attenuator |
| **Vacuum** | Thyracont gauges on the ion cooler and ESA (Graphix), PLC vacuum signals |
| **Legacy Tandetron** | cups, apertures, BI magnet and current measurement of the existing accelerator over its TCP line protocol |

Device communication runs over **MQTT** (Beckhoff CX7080 PLC, see
[Beckhoff-CX7080-MQTT](https://github.com/Paranoidgrinch/Beckhoff-CX7080-MQTT)), **TCP/IP**,
**RS-232-over-Ethernet** and **SSH** (Raspberry Pi, see
[LC-Circuit-flashing](https://github.com/Paranoidgrinch/LC-Circuit-flashing)).

## Features

- **One data model** — every setpoint and readback is a named channel (`backend/channels.py`); workers write
  into the model, the GUI only reads and requests.
- **Machine configurations** — save the whole machine state to JSON and restore it later, with a dialog to
  choose which parts to apply. `data/Configs/` holds the configurations from past beam times.
- **Beam scans** — 1D and 2D tracers scan any setpoint (or pair of setpoints) against the Keithley current,
  with separate settling and measurement windows, setpoint restore after the scan, and CSV export.
- **Safe ramps** — high-voltage changes are ramped, can be cancelled at any time, and workers shut down cleanly
  without delayed writes.
- **Logging** — continuous logging of the selected channels to a file of your choice.

## Getting started

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip install -r requirements.txt
.venv/bin/python main.py
```

Requires Python 3.11+ with PyQt5, paho-mqtt, NumPy, Matplotlib and Paramiko.

**Network configuration:** the device addresses are the defaults of the CologneAMS lab network
(`192.168.0.x`) and must be adapted to your setup. They are defined at the top of the respective worker:

| Device | Where |
| --- | --- |
| MQTT broker (PLC) | `backend/channels.py` (`MQTT_DEFAULT_HOST`) |
| Magnet PSU, Hall probe, stepper, Keithley, cup switch | `backend/workers/*_worker.py` |
| RFQ function generator, oscilloscope, Raspberry Pi | `backend/workers/rfq_worker.py` |
| Legacy Tandetron server | `backend/workers/legacy_tcp_worker.py` |
| Vacuum gauges | `gui/windows/pressure_monitor.py` |

**Windows executable:** `FLAVIA.spec` builds a standalone executable with PyInstaller
(`pyinstaller FLAVIA.spec`).

## Standalone tools

| Folder | Tool |
| --- | --- |
| `Ionizer/` | Ramps the ionizer current in programmed segments over MQTT. A prebuilt `Ionizer.exe` is in `dist/`. |
| `Source Maintainance/` | Ion-source maintenance panel (digital channels over MQTT), optionally with turbopump control. Prebuilt executables are in `dist/`. |

## Repository layout

```text
main.py            entry point: starts the backend and the main window
backend/           data model, channel definitions, calibrations, legacy protocol
  workers/         one thread per device (MQTT, magnet, Keithley, RFQ, stepper, legacy TCP, …)
  services/        configurations, logging, RFQ service, sample selection and exposure counter
gui/               main window, panels per beamline section, tracer/plot/pressure windows
data/Configs/      saved machine configurations from beam times
tests/             unit tests (pytest)
```

Tests: `.venv/bin/pip install pytest && .venv/bin/pytest`

## History

FLAVIA alpha 1.1 replaces the first two prototypes in
[FLAVIA (pre-alpha)](https://github.com/Paranoidgrinch/FLAVIA-Fully-integrated-Laser-Anion-Variables-for-AMS)
and the older single-purpose scripts in [ALIS-Control-Software](https://github.com/Paranoidgrinch/ALIS-Control-Software).

## License

GPL-3.0 — see [LICENSE](LICENSE).
