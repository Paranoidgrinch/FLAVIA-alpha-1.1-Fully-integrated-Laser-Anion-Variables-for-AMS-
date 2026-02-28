# backend/workers/stepper_worker.py
import threading
import socket
import time
from typing import Optional
import queue

from backend.model import DataModel

STEPPER_DEFAULT_HOST = "192.168.0.6"
STEPPER_DEFAULT_PORT = 102


class StepperWorker(threading.Thread):
    def __init__(self, model: DataModel, host: str = STEPPER_DEFAULT_HOST, port: int = STEPPER_DEFAULT_PORT, poll_interval: float = 0.5):
        super().__init__(daemon=True)
        self.model = model
        self.host = host
        self.port = port
        self.poll_interval = poll_interval

        self._stop_event = threading.Event()
        self._cmd_queue: "queue.Queue[tuple[str, Optional[int]]]" = queue.Queue()
        self._sock: Optional[socket.socket] = None

        self._moving = False
        self._pending_target: Optional[int] = None
        self._last_pos: Optional[int] = None
        self._stable_count = 0

    def run(self):
        time.sleep(0.1)
        while not self._stop_event.is_set():
            if self._sock is None:
                self._connect()

            try:
                cmd, param = self._cmd_queue.get(timeout=self.poll_interval)
                if cmd == "move" and param is not None:
                    self._handle_move(param)
                elif cmd == "stop":
                    self._handle_stop()
                elif cmd == "home":
                    self._handle_home()
                elif cmd == "shutdown":
                    break
            except queue.Empty:
                pass
            except Exception:
                self._disconnect()

            try:
                self._poll_position()
            except Exception:
                self._disconnect()

        self._disconnect()

    def _connect(self):
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(2.0)
            self._sock.connect((self.host, self.port))
            self._update_connected(True)
        except Exception:
            self._sock = None
            self._update_connected(False)

    def _disconnect(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        self._sock = None
        self._update_connected(False)
        self._set_moving(False)

    def _update_connected(self, connected: bool):
        self.model.update("stepper_connected", bool(connected), source="stepper", quality="good" if connected else "bad")

    def _set_moving(self, moving: bool):
        if self._moving != moving:
            self._moving = moving
            self.model.update("stepper_moving", bool(moving), source="stepper", quality="good")

    def _send_command(self, command: str) -> Optional[str]:
        if self._sock is None:
            self._connect()
            if self._sock is None:
                return None
        try:
            self._sock.sendall((command + "\n").encode("ascii"))
            resp = self._sock.recv(1024).decode("ascii").strip()
            return resp
        except Exception:
            self._disconnect()
            return None

    def _handle_move(self, target_position: int):
        self.model.update("stepper_target_position_set", target_position, source="stepper")
        resp = self._send_command(f"s r0xca {target_position}")
        if resp != "ok":
            return
        resp = self._send_command("t 1")
        if resp == "ok":
            self._pending_target = target_position
            self._stable_count = 0
            self._set_moving(True)

    def _handle_home(self):
        resp = self._send_command("t 2")
        if resp == "ok":
            self._pending_target = None
            self._stable_count = 0
            self._set_moving(True)

    def _handle_stop(self):
        self._send_command("t 0")
        self._pending_target = None
        self._set_moving(False)

    def _poll_position(self):
        resp = self._send_command("g r0x30")
        if not resp or not resp.startswith("v "):
            return
        try:
            pos = int(resp[2:])
        except ValueError:
            return

        self.model.update("stepper_position_meas", pos, source="stepper")

        if self._last_pos is not None and pos == self._last_pos:
            self._stable_count += 1
        else:
            self._stable_count = 0
        self._last_pos = pos

        if self._moving:
            if self._pending_target is not None:
                if pos == self._pending_target and self._stable_count >= 1:
                    self._set_moving(False)
            else:
                if self._stable_count >= 3:
                    self._set_moving(False)

    def move_to(self, target_position: int):
        try:
            self._cmd_queue.put_nowait(("move", int(target_position)))
        except queue.Full:
            pass

    def stop_motion(self):
        try:
            self._cmd_queue.put_nowait(("stop", None))
        except queue.Full:
            pass

    def go_home(self):
        try:
            self._cmd_queue.put_nowait(("home", None))
        except queue.Full:
            pass

    def shutdown(self):
        self._stop_event.set()
        try:
            self._cmd_queue.put_nowait(("shutdown", None))
        except queue.Full:
            pass