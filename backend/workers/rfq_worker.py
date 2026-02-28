# backend/workers/rfq_worker.py
from __future__ import annotations

import math
import socket
import time

import numpy as np
from PyQt5 import QtCore

try:
    import paramiko
except ImportError:
    paramiko = None


# =========================
# CONFIG
# =========================
FG_IP_DEFAULT = "192.168.0.11"
FG_PORT_DEFAULT = 100

SCOPE_IP_DEFAULT = "192.168.0.14"
SCOPE_PORT_DEFAULT = 1024
RECORD_LENGTH = 1000

PI_HOST_DEFAULT = "raspberrypi.local"
PI_USER_DEFAULT = "pi"
PI_PASSWORD_DEFAULT = "raspberry"

R0_MM = 5.232

u_to_kg = 1.66053906660e-27
e_charge = 1.602176634e-19


RESONANCE_PRESETS = [
    {"f_MHz": 0.5, "C_pF": 1100.0, "L_uH": 447.0},
    {"f_MHz": 0.6, "C_pF": 1100.0, "L_uH": 308.75},
    {"f_MHz": 0.7, "C_pF": 1100.0, "L_uH": 214.75},
    {"f_MHz": 0.8, "C_pF": 1300.0, "L_uH": 162.75},
    {"f_MHz": 0.9, "C_pF": 1300.0, "L_uH": 126.25},
    {"f_MHz": 1.0, "C_pF": 1300.0, "L_uH": 101.5},
    {"f_MHz": 1.1, "C_pF": 1300.0, "L_uH": 84.0},
    {"f_MHz": 1.2, "C_pF": 1300.0, "L_uH": 70.5},
    {"f_MHz": 1.3, "C_pF": 1300.0, "L_uH": 60.0},
    {"f_MHz": 1.4, "C_pF": 1300.0, "L_uH": 51.25},
    {"f_MHz": 1.5, "C_pF": 1300.0, "L_uH": 45.5},
    {"f_MHz": 1.6, "C_pF": 1300.0, "L_uH": 39.5},
    {"f_MHz": 1.7, "C_pF": 1300.0, "L_uH": 34.5},
    {"f_MHz": 1.8, "C_pF": 1300.0, "L_uH": 31.25},
    {"f_MHz": 1.9, "C_pF": 1300.0, "L_uH": 28.0},
    {"f_MHz": 2.0, "C_pF": 1300.0, "L_uH": 25.25},
    {"f_MHz": 2.1, "C_pF": 1300.0, "L_uH": 22.25},
    {"f_MHz": 2.2, "C_pF": 1300.0, "L_uH": 20.25},
    {"f_MHz": 2.3, "C_pF": 1300.0, "L_uH": 18.25},
    {"f_MHz": 2.4, "C_pF": 1300.0, "L_uH": 16.75},
    {"f_MHz": 2.5, "C_pF": 1500.0, "L_uH": 15.75},
    {"f_MHz": 2.6, "C_pF": 1700.0, "L_uH": 14.5},
    {"f_MHz": 2.7, "C_pF": 1700.0, "L_uH": 13.5},
    {"f_MHz": 2.8, "C_pF": 1700.0, "L_uH": 12.5},
    {"f_MHz": 2.9, "C_pF": 1700.0, "L_uH": 11.5},
    {"f_MHz": 3.0, "C_pF": 1500.0, "L_uH": 10.75},
]


# =========================
# DS345
# =========================
class DS345Client:
    def __init__(self, ip=FG_IP_DEFAULT, port=FG_PORT_DEFAULT):
        self.ip = ip
        self.port = port
        self.sock = None

    def set_target(self, ip, port):
        self.close()
        self.ip = ip
        self.port = port

    def ensure_connection(self):
        if self.sock is None:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1.0)
                s.connect((self.ip, self.port))
                self.sock = s
                return True
            except Exception:
                self.sock = None
                return False
        return True

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None

    def send_command(self, cmd):
        if not self.ensure_connection():
            return None
        try:
            self.sock.sendall((cmd + "\n").encode("ascii"))
            if "?" in cmd:
                response = self.sock.recv(1024)
                if len(response) == 4:
                    import struct
                    try:
                        return struct.unpack(">f", response)[0]
                    except struct.error:
                        pass
                try:
                    return response.decode("ascii", errors="ignore").strip()
                except UnicodeDecodeError:
                    return None
            return True
        except Exception:
            self.close()
            return None

    def get_frequency(self):
        resp = self.send_command("FREQ?")
        try:
            return float(resp)
        except Exception:
            return float("nan")

    def set_frequency(self, f_hz):
        return self.send_command(f"FREQ {f_hz}")

    def get_amplitude(self):
        resp = self.send_command("AMPL?")
        if resp is None:
            return float("nan")
        try:
            if isinstance(resp, (int, float)):
                return float(resp)
            return float(str(resp).replace("VP", "").strip())
        except Exception:
            return float("nan")

    def set_amplitude(self, vpp):
        vpp = max(0.0, min(10.0, vpp))
        return self.send_command(f"AMPL {vpp}VP")


# =========================
# Scope (GDS-1074B)
# =========================
class ScopeClient:
    def __init__(self, ip=SCOPE_IP_DEFAULT, port=SCOPE_PORT_DEFAULT, record_len=RECORD_LENGTH):
        self.ip = ip
        self.port = port
        self.record_len = record_len

    def set_target(self, ip, port):
        self.ip = ip
        self.port = port

    def test_connection(self, timeout=1.0) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect((self.ip, self.port))
            return True
        except Exception:
            return False

    def _send_cmd(self, sock, cmd: str):
        sock.sendall((cmd.strip() + "\n").encode("ascii"))

    def _recv_all(self, sock, timeout=2.0) -> bytes:
        sock.settimeout(timeout)
        chunks = []
        try:
            while True:
                data = sock.recv(4096)
                if not data:
                    break
                chunks.append(data)
        except socket.timeout:
            pass
        return b"".join(chunks)

    def _get_volts_for_channel_single_connection(self, ch: int):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((self.ip, self.port))
            self._send_cmd(s, f":ACQuire:RECOrdlength {self.record_len}")
            self._send_cmd(s, f":ACQuire{ch}:MEMory?")
            raw = self._recv_all(s, timeout=2.0)

        marker = b"Waveform Data;"
        idx = raw.find(marker)
        if idx == -1:
            raise RuntimeError(f"'Waveform Data;' not found (CH{ch})")

        header_str = raw[:idx].decode("ascii", errors="ignore")
        block = raw[idx + len(marker):].lstrip()

        header = {}
        for part in header_str.split(";"):
            part = part.strip()
            if not part:
                continue
            if "," in part:
                key, val = part.split(",", 1)
                header[key.strip()] = val.strip()

        vscale = float(header.get("Vertical Scale", "1.0"))  # V/div

        if not block.startswith(b"#"):
            raise RuntimeError(f"No SCPI block (CH{ch})")

        ndigits = int(chr(block[1]))
        nbytes = int(block[2:2 + ndigits].decode())
        data_bytes = block[2 + ndigits:2 + ndigits + nbytes]

        raw_vals = np.frombuffer(data_bytes, dtype=">i2")
        volts = (raw_vals / 25.0) * vscale
        return volts

    def measure_ch2_ch3(self):
        wave2 = self._get_volts_for_channel_single_connection(2)
        wave3 = self._get_volts_for_channel_single_connection(3)
        vpp2 = float(wave2.max() - wave2.min())
        vpp3 = float(wave3.max() - wave3.min())
        return vpp2, vpp3, wave2, wave3


# =========================
# LC via SSH
# =========================
class LCSSHClient:
    def __init__(self):
        self.client = None
        self.workdir = "/home/pi/Desktop/Python"
        self.script = "python3 rc_cmd_derin.py"

    def connect(self, host, username, password, port=22, timeout=5.0):
        if paramiko is None:
            raise RuntimeError("paramiko is not installed (pip install paramiko)")
        host = host.strip()
        if host.startswith("[") and host.endswith("]"):
            host = host[1:-1]

        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None

        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(host, port=port, username=username, password=password, timeout=timeout)

    def is_connected(self):
        return self.client is not None

    def close(self):
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
        self.client = None

    def _run_rc_cmd(self, args, timeout=5.0):
        if not self.client:
            raise RuntimeError("Not connected to Pi")
        cmd = f"cd {self.workdir} && {self.script} " + " ".join(args)
        stdin, stdout, stderr = self.client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="ignore").strip()
        err = stderr.read().decode("utf-8", errors="ignore").strip()
        return out, err

    def set_value(self, name, value):
        return self._run_rc_cmd(["set", name, str(value)])

    def get_value(self, name):
        out, err = self._run_rc_cmd(["get", name])
        if err:
            return float("nan"), err
        try:
            return float(out), ""
        except ValueError:
            return float("nan"), f"Parsing error: {out!r}"


# =========================
# Physics helpers
# =========================
def compute_q(m_u, z, r0_mm, f_hz, Vpp_FG, gain):
    if f_hz <= 0 or m_u <= 0 or gain <= 0:
        return float("nan")
    m = m_u * u_to_kg
    Q = abs(z) * e_charge
    r0 = r0_mm / 1000.0
    Vpp_RFQ = gain * Vpp_FG
    V0 = Vpp_RFQ / 2.0
    omega = 2.0 * math.pi * f_hz
    return 4.0 * Q * V0 / (m * (r0 ** 2) * (omega ** 2))


def compute_freq_for_q(m_u, z, r0_mm, q_target, Vpp_FG, gain):
    if q_target <= 0 or m_u <= 0 or Vpp_FG <= 0 or gain <= 0:
        return float("nan")
    m = m_u * u_to_kg
    Q = abs(z) * e_charge
    r0 = r0_mm / 1000.0
    Vpp_RFQ = gain * Vpp_FG
    omega2 = 2.0 * Q * Vpp_RFQ / (m * r0**2 * q_target)
    if omega2 <= 0:
        return float("nan")
    return math.sqrt(omega2) / (2.0 * math.pi)


def L_from_f_C(f_hz, C_F):
    if f_hz <= 0 or C_F <= 0:
        return float("nan")
    return 1.0 / ((2.0 * math.pi * f_hz) ** 2 * C_F)


def C_from_f_L(f_hz, L_H):
    if f_hz <= 0 or L_H <= 0:
        return float("nan")
    return 1.0 / ((2.0 * math.pi * f_hz) ** 2 * L_H)


# =========================
# Qt Worker (to be used by GUI in a QThread)
# =========================
class RFQWorker(QtCore.QObject):
    fgStatus = QtCore.pyqtSignal(float, float)  # freq, ampl
    fgError = QtCore.pyqtSignal(str)

    piStatus = QtCore.pyqtSignal(bool, str)
    lcReadResult = QtCore.pyqtSignal(float, str, float, str)  # C, C_err, L, L_err
    lcSendResult = QtCore.pyqtSignal(float, float, str, str)  # C, L, errC, errL
    lcError = QtCore.pyqtSignal(str)

    scopeStatus = QtCore.pyqtSignal(bool)
    scopeMeasurement = QtCore.pyqtSignal(float, float, object, object)  # vpp2, vpp3, wave2, wave3
    scopeError = QtCore.pyqtSignal(str)

    sweepProgress = QtCore.pyqtSignal(int, int, float)
    sweepLog = QtCore.pyqtSignal(str)
    sweepResult = QtCore.pyqtSignal(object, object, object, object, object, float, float, str)
    sweepError = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fg = DS345Client()
        self.scope = ScopeClient()
        self.lc = LCSSHClient()
        self._sweep_cancelled = False

    @QtCore.pyqtSlot()
    def request_fg_status(self):
        try:
            self.fgStatus.emit(self.fg.get_frequency(), self.fg.get_amplitude())
        except Exception as e:
            self.fgError.emit(str(e))

    @QtCore.pyqtSlot(float, float)
    def set_fg(self, freq, vpp):
        try:
            self.fg.set_frequency(freq)
            self.fg.set_amplitude(vpp)
        except Exception as e:
            self.fgError.emit(str(e))

    @QtCore.pyqtSlot()
    def connect_pi(self):
        if paramiko is None:
            self.piStatus.emit(False, "paramiko not installed")
            return
        try:
            self.lc.connect(PI_HOST_DEFAULT, PI_USER_DEFAULT, PI_PASSWORD_DEFAULT)
            self.piStatus.emit(True, f"SSH to {PI_HOST_DEFAULT} established.")
        except Exception as e:
            self.piStatus.emit(False, f"SSH error: {e}")

    @QtCore.pyqtSlot(float, float)
    def set_lc(self, C_pF, L_uH):
        if not self.lc.is_connected():
            self.lcError.emit("Not connected to Pi.")
            return
        try:
            _, errC = self.lc.set_value("C", C_pF)
            _, errL = self.lc.set_value("L", L_uH)
            self.lcSendResult.emit(C_pF, L_uH, errC, errL)
        except Exception as e:
            self.lcError.emit(str(e))

    @QtCore.pyqtSlot()
    def read_lc(self):
        if not self.lc.is_connected():
            self.lcError.emit("Not connected to Pi.")
            return
        try:
            c_val, c_err = self.lc.get_value("C")
            l_val, l_err = self.lc.get_value("L")
            self.lcReadResult.emit(c_val, c_err, l_val, l_err)
        except Exception as e:
            self.lcError.emit(str(e))

    @QtCore.pyqtSlot()
    def test_scope(self):
        try:
            ok = self.scope.test_connection()
        except Exception:
            ok = False
        self.scopeStatus.emit(ok)

    @QtCore.pyqtSlot()
    def measure_scope(self):
        try:
            vpp2, vpp3, wave2, wave3 = self.scope.measure_ch2_ch3()
            self.scopeMeasurement.emit(vpp2, vpp3, wave2, wave3)
        except Exception as e:
            self.scopeError.emit(str(e))

    @QtCore.pyqtSlot(float, float, float, float, bool)
    def run_sweep_L(self, center_L, span, step, dwell_ms, measure_scope):
        if not self.lc.is_connected():
            self.sweepError.emit("Not connected to Pi (SSH).")
            return
        if span <= 0 or step <= 0 or dwell_ms <= 0:
            self.sweepError.emit("Span, step and dwell time must be > 0.")
            return

        dwell_s = dwell_ms / 1000.0
        start = center_L - span
        stop = center_L + span

        values = []
        v = start
        while v <= stop + 1e-9:
            values.append(v)
            v += step

        self.sweepLog.emit(
            f"Starting L sweep around {center_L:.3f} µH: from {start:.3f} to {stop:.3f} in steps of {step:.3f} µH."
        )

        L_meas, Vpp2_list, Vpp3_list = [], [], []
        max_vpp2 = -1.0
        best_L, best_wave2, best_wave3 = None, None, None

        L_max_uH = 512.0
        L_step_hw = 0.25
        self._sweep_cancelled = False

        for idx, val in enumerate(values):
            if self._sweep_cancelled:
                self.sweepLog.emit("Sweep cancelled by user.")
                break
            if val < 0.0 or val >= L_max_uH:
                continue

            index = round(val / L_step_hw)
            L_uH = index * L_step_hw
            if L_uH >= L_max_uH:
                L_uH = L_max_uH - L_step_hw

            try:
                self.lc.set_value("L", L_uH)
            except Exception as e:
                self.sweepLog.emit(f"Sweep: error setting L: {e}")
                continue

            self.sweepProgress.emit(idx + 1, len(values), L_uH)
            time.sleep(dwell_s)

            if measure_scope:
                try:
                    vpp2, vpp3, wave2, wave3 = self.scope.measure_ch2_ch3()
                    L_meas.append(L_uH)
                    Vpp2_list.append(vpp2)
                    Vpp3_list.append(vpp3)
                    if vpp2 > max_vpp2:
                        max_vpp2 = vpp2
                        best_L = L_uH
                        best_wave2 = wave2
                        best_wave3 = wave3
                except Exception as e:
                    self.sweepLog.emit(f"Sweep: scope error: {e}")

        if measure_scope and L_meas and best_L is not None:
            msg_txt = f"Max CH2 Vpp during sweep: {max_vpp2:.3f} V at L = {best_L:.3f} µH"
            self.sweepResult.emit(L_meas, Vpp2_list, Vpp3_list, best_wave2, best_wave3, best_L, max_vpp2, msg_txt)
        elif measure_scope:
            self.sweepResult.emit([], [], [], None, None, float("nan"), float("nan"), "Sweep finished, no valid scope data.")
        else:
            self.sweepResult.emit([], [], [], None, None, float("nan"), float("nan"), "Sweep finished (scope disabled).")

    @QtCore.pyqtSlot()
    def cancel_sweep(self):
        self._sweep_cancelled = True

    @QtCore.pyqtSlot()
    def shutdown(self):
        try:
            self.fg.close()
        except Exception:
            pass
        try:
            self.lc.close()
        except Exception:
            pass