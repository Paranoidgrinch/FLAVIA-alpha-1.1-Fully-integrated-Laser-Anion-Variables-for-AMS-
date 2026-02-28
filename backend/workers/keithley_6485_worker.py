# backend/workers/keithley_6485_worker.py
from __future__ import annotations

import math
import queue
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from ..model import DataModel


@dataclass
class AvgFilterSettings:
    enabled: bool = False
    count: int = 10
    tcon: str = "MOV"  # MOV or REP


@dataclass
class RangeSettings:
    auto: bool = True
    fixed_range_nA: float = 100.0


@dataclass
class TuneSettings:
    nplc: float = 0.05
    poll_hz: float = 15.0
    bucket_interval_s: float = 0.5
    autozero: bool = False
    range: RangeSettings = field(default_factory=RangeSettings)
    avg_filter: AvgFilterSettings = field(default_factory=AvgFilterSettings)


@dataclass
class MeasureSettings:
    nplc: float = 1.0
    interval_s: float = 2.0
    autozero: bool = True
    range: RangeSettings = field(default_factory=RangeSettings)
    avg_filter: AvgFilterSettings = field(default_factory=lambda: AvgFilterSettings(enabled=True, count=10, tcon="MOV"))


@dataclass
class KeithleySettings:
    host: str = "192.168.0.2"
    port: int = 100
    connect_timeout_s: float = 0.8
    io_timeout_s: float = 2.0
    mode: str = "TUNE"  # TUNE | MEASURE
    tune: TuneSettings = field(default_factory=TuneSettings)
    measure: MeasureSettings = field(default_factory=MeasureSettings)


class ScpiSocket:
    LINE_ENDING = b"\n"

    def __init__(self):
        self._sock: Optional[socket.socket] = None
        self._rx_buf = b""

    def open(self, host: str, port: int, connect_timeout_s: float, io_timeout_s: float) -> None:
        self.close()
        s = socket.create_connection((host, int(port)), timeout=float(connect_timeout_s))
        s.settimeout(float(io_timeout_s))
        self._sock = s
        self._rx_buf = b""

    def close(self) -> None:
        if self._sock is None:
            return
        try:
            self._sock.close()
        except Exception:
            pass
        self._sock = None
        self._rx_buf = b""

    def send(self, cmd: str) -> None:
        if self._sock is None:
            raise RuntimeError("Socket not open")
        data = cmd.encode("ascii", errors="ignore")
        if not data.endswith(self.LINE_ENDING):
            data += self.LINE_ENDING
        self._sock.sendall(data)

    def _recv_more(self) -> None:
        if self._sock is None:
            raise RuntimeError("Socket not open")
        chunk = self._sock.recv(4096)
        if not chunk:
            raise ConnectionError("Connection closed by peer")
        self._rx_buf += chunk

    def readline(self) -> str:
        while b"\n" not in self._rx_buf:
            self._recv_more()
        line, rest = self._rx_buf.split(b"\n", 1)
        self._rx_buf = rest
        return line.decode("ascii", errors="ignore").strip().strip("\r")

    def query(self, cmd: str) -> str:
        self.send(cmd)
        return self.readline()


class Keithley6485:
    def __init__(self, scpi: ScpiSocket, log_cb):
        self.scpi = scpi
        self.log = log_cb

    def try_send(self, cmd: str, pause_s: float = 0.0) -> None:
        try:
            self.log(f"SCPI >> {cmd}")
            self.scpi.send(cmd)
            if pause_s > 0:
                time.sleep(pause_s)
        except Exception as e:
            self.log(f"SCPI !! {cmd} ({e})")

    def read_current_A(self) -> float:
        resp = self.scpi.query("READ?")
        try:
            return abs(float(resp))
        except Exception:
            self.log(f"Parse error for READ?: {resp!r}")
            return 0.0

    def initialize_basic(self) -> None:
        cmds = [
            "*RST",
            ":SYST:ZCH ON",
            ":SYST:ZCOR ON",
            ":FORM:ELEM READ",
            ":SENS:FUNC 'CURR'",
            ":SENS:CURR:RANG:AUTO ON",
            ":SENS:CURR:NPLC 0.1",
            ":SYST:ZCH OFF",
        ]
        for c in cmds:
            self.try_send(c, pause_s=0.3)

    def apply_mode(self, settings: KeithleySettings) -> None:
        mode = (settings.mode or "TUNE").upper()
        s = settings.measure if mode == "MEASURE" else settings.tune

        if s.range.auto:
            self.try_send(":SENS:CURR:RANG:AUTO ON")
        else:
            self.try_send(":SENS:CURR:RANG:AUTO OFF")
            fixed_A = max(1e-15, float(s.range.fixed_range_nA) * 1e-9)
            self.try_send(f":SENS:CURR:RANG {fixed_A:.6e}")

        nplc = max(0.0001, float(s.nplc))
        self.try_send(f":SENS:CURR:NPLC {nplc}")
        self.try_send(f":SYST:AZER:STAT {'ON' if s.autozero else 'OFF'}")

        af = s.avg_filter
        tcon = (af.tcon or "MOV").upper()
        if tcon not in ("MOV", "REP"):
            tcon = "MOV"
        self.try_send(f":SENS:AVER:COUNT {int(max(1, af.count))}")
        self.try_send(f":SENS:AVER:TCON {tcon}")
        self.try_send(f":SENS:AVER:STAT {'ON' if af.enabled else 'OFF'}")

    def restart(self, settings: KeithleySettings) -> None:
        self.try_send("*RST", pause_s=0.2)
        self.initialize_basic()
        self.apply_mode(settings)

    def zero_cycle(self) -> None:
        self.try_send(":SYST:ZCH ON", pause_s=0.2)
        self.try_send(":SYST:ZCOR ON", pause_s=0.2)
        self.try_send(":SYST:ZCH OFF", pause_s=0.2)


class Keithley6485Worker(threading.Thread):
    def __init__(self, model: DataModel, settings: Optional[KeithleySettings] = None):
        super().__init__(daemon=True)
        self.model = model
        self.settings = settings or KeithleySettings()

        self._cmdq: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.scpi = ScpiSocket()
        self.dev: Optional[Keithley6485] = None
        self.connected = False

        self._bucket_start: Optional[float] = None
        self._bucket_vals: list[float] = []
        self._t0: Optional[float] = None

        self.model.update("keithley/connected", False, source="keithley", quality="bad")

    def _log(self, msg: str) -> None:
        self.model.update("keithley/log", msg, source="keithley")

    def stop(self) -> None:
        self._cmdq.put(("stop", None))
        self.join(timeout=3.0)

    def cmd_connect(self) -> None:
        self._cmdq.put(("connect", None))

    def cmd_disconnect(self) -> None:
        self._cmdq.put(("disconnect", None))

    def cmd_apply_settings(self, s: KeithleySettings) -> None:
        self._cmdq.put(("apply", s))

    def cmd_restart(self) -> None:
        self._cmdq.put(("restart", None))

    def cmd_zero(self) -> None:
        self._cmdq.put(("zero", None))

    def _set_connected(self, ok: bool) -> None:
        self.connected = ok
        self.model.update("keithley/connected", bool(ok), source="keithley", quality="good" if ok else "bad")

    def _do_connect(self) -> None:
        if self.connected:
            return
        try:
            s = self.settings
            self.scpi.open(s.host, s.port, s.connect_timeout_s, s.io_timeout_s)
            self.dev = Keithley6485(self.scpi, self._log)
            self._set_connected(True)
            self._log(f"TCP connected to {s.host}:{s.port}")
            self.dev.initialize_basic()
            self.dev.apply_mode(self.settings)
            self._bucket_start = None
            self._bucket_vals = []
            self._t0 = None
        except Exception as e:
            self._log(f"Connect failed: {e}")
            self.scpi.close()
            self.dev = None
            self._set_connected(False)

    def _do_disconnect(self) -> None:
        self.scpi.close()
        self.dev = None
        self._set_connected(False)
        self._log("Disconnected.")

    def _bucket_update(self, current_nA: float, interval_s: float) -> None:
        now = time.perf_counter()
        if self._bucket_start is None:
            self._bucket_start = now
            self._bucket_vals = [current_nA]
            return
        self._bucket_vals.append(current_nA)
        if now - self._bucket_start >= interval_s:
            vals = self._bucket_vals
            n = len(vals)
            mean = sum(vals) / n if n else 0.0
            var = sum((v - mean) ** 2 for v in vals) / n if n > 1 else 0.0
            sigma = math.sqrt(max(var, 0.0))
            if self._t0 is None:
                self._t0 = self._bucket_start
            t_point = (self._bucket_start + interval_s / 2.0) - self._t0

            self.model.update("keithley/stats/mean_nA", mean, source="keithley")
            self.model.update("keithley/stats/sigma_nA", sigma, source="keithley")
            self.model.update("keithley/stats/n", n, source="keithley")
            self.model.update("keithley/stats/t_s", float(t_point), source="keithley")

            self._bucket_start = now
            self._bucket_vals = [current_nA]

    def run(self) -> None:
        while True:
            try:
                while True:
                    cmd, payload = self._cmdq.get_nowait()
                    if cmd == "stop":
                        self._do_disconnect()
                        return
                    if cmd == "connect":
                        self._do_connect()
                    elif cmd == "disconnect":
                        self._do_disconnect()
                    elif cmd == "apply":
                        self.settings = payload  # type: ignore
                        self._log(f"Settings applied (mode={self.settings.mode})")
                        self._bucket_start = None
                        self._bucket_vals = []
                        self._t0 = None
                        if self.connected and self.dev:
                            self.dev.apply_mode(self.settings)
                    elif cmd == "restart":
                        if self.connected and self.dev:
                            self._log("Restarting (*RST) ...")
                            self.dev.restart(self.settings)
                            self._log("Restart done.")
                    elif cmd == "zero":
                        if self.connected and self.dev:
                            self._log("Zero cycle ...")
                            self.dev.zero_cycle()
                            self._log("Zero cycle done.")
            except queue.Empty:
                pass

            if not self.connected or not self.dev:
                time.sleep(0.05)
                continue

            mode = (self.settings.mode or "TUNE").upper()
            try:
                if mode == "MEASURE":
                    current_A = self.dev.read_current_A()
                    self.model.update("keithley/current_A", float(current_A), source="keithley")
                    current_nA = current_A * 1e9
                    if self._t0 is None:
                        self._t0 = time.perf_counter()
                    t_s = time.perf_counter() - self._t0
                    self.model.update("keithley/stats/mean_nA", float(current_nA), source="keithley")
                    self.model.update("keithley/stats/sigma_nA", 0.0, source="keithley")
                    self.model.update("keithley/stats/n", 1, source="keithley")
                    self.model.update("keithley/stats/t_s", float(t_s), source="keithley")
                    time.sleep(max(0.05, float(self.settings.measure.interval_s)))
                else:
                    poll_hz = max(1.0, float(self.settings.tune.poll_hz))
                    dt = 1.0 / poll_hz
                    current_A = self.dev.read_current_A()
                    self.model.update("keithley/current_A", float(current_A), source="keithley")
                    current_nA = current_A * 1e9
                    self._bucket_update(current_nA, max(0.05, float(self.settings.tune.bucket_interval_s)))
                    time.sleep(max(0.001, dt))
            except Exception as e:
                self._log(f"I/O error: {e}")
                self._do_disconnect()
                time.sleep(0.2)