from __future__ import annotations

import queue
import socket
import threading
import time
from dataclasses import dataclass
from typing import Optional

from backend.legacy_protocol import (
    LegacyProtocolError,
    MAX_RESPONSE_BYTES,
    decode_snapshot,
    parse_get_all_data_response,
)


@dataclass(frozen=True)
class LegacyTcpConfig:
    host: str = "192.168.0.1"
    port: int = 50001
    poll_interval_s: float = 1.0
    connect_timeout_s: float = 1.5
    io_timeout_s: float = 2.0
    reconnect_interval_s: float = 2.0


class LegacyTcpWorker:
    """Persistent request/response client for the old CServer line protocol."""

    def __init__(self, model, cfg: LegacyTcpConfig = LegacyTcpConfig()):
        self.model = model
        self.cfg = cfg
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._sock: Optional[socket.socket] = None
        self._rx = bytearray()
        self._commands: queue.Queue[str] = queue.Queue()
        self._connected = False
        self.model.update("legacy/connected", False, source="legacy", quality="bad")

    @property
    def connected(self) -> bool:
        return bool(self._connected)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="LegacyTcpWorker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._close_socket()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)
        self._thread = None
        self._set_connected(False)
        self._drop_pending_commands()

    def send_command(self, command: str) -> None:
        """Queue one hardware command only for the currently validated connection."""
        if not self.connected:
            raise ConnectionError("Legacy TCP server is not connected")
        command = str(command).strip()
        if not command or "\r" in command or "\n" in command:
            raise ValueError("Invalid legacy command")
        self._commands.put_nowait(command)

    def _set_connected(self, ok: bool) -> None:
        ok = bool(ok)
        if self._connected == ok:
            return
        self._connected = ok
        self.model.update(
            "legacy/connected",
            ok,
            source="legacy",
            quality="good" if ok else "bad",
        )

    def _connect(self) -> None:
        s = socket.create_connection(
            (self.cfg.host, int(self.cfg.port)),
            timeout=float(self.cfg.connect_timeout_s),
        )
        s.settimeout(float(self.cfg.io_timeout_s))
        self._sock = s
        self._rx.clear()
        # Do not mark connected yet. A valid getAllData frame is the protocol
        # handshake and is what turns the GUI indicator green.

    def _close_socket(self) -> None:
        s = self._sock
        self._sock = None
        self._rx.clear()
        if s is not None:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                s.close()
            except Exception:
                pass

    def _drop_pending_commands(self) -> None:
        while True:
            try:
                self._commands.get_nowait()
            except queue.Empty:
                return

    def _recv_line(self) -> str:
        if self._sock is None:
            raise ConnectionError("Legacy socket is closed")
        while True:
            pos = self._rx.find(b"\r\n")
            if pos >= 0:
                line = bytes(self._rx[:pos])
                del self._rx[:pos + 2]
                return line.decode("ascii")
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("Legacy server closed the connection")
            self._rx.extend(chunk)
            if len(self._rx) > MAX_RESPONSE_BYTES:
                raise LegacyProtocolError("Legacy response exceeds safety limit")

    def _request(self, command: str) -> str:
        if self._sock is None:
            raise ConnectionError("Legacy socket is closed")
        wire = (str(command).strip() + "\r\n").encode("ascii")
        self._sock.sendall(wire)
        return self._recv_line()

    def _poll_snapshot(self) -> None:
        response = self._request("getAllData")
        words = parse_get_all_data_response(response)
        decoded = decode_snapshot(words)
        for name, value in decoded.items():
            quality = "good" if value is not None else "bad"
            self.model.update(name, value, source="legacy", quality=quality)
        self._set_connected(True)

    def _process_commands(self) -> None:
        while self.connected:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                return
            response = self._request(command)
            if response != "done":
                # A protocol-level command error does not mean the TCP link is
                # down, but it must not silently look successful.
                self.model.update(
                    "legacy/last_error",
                    f"{command}: {response}",
                    source="legacy",
                    quality="bad",
                )

    def _run(self) -> None:
        next_poll = 0.0
        while not self._stop.is_set():
            try:
                if self._sock is None:
                    self._connect()
                    next_poll = 0.0

                now = time.monotonic()
                if now >= next_poll:
                    self._poll_snapshot()
                    next_poll = time.monotonic() + float(self.cfg.poll_interval_s)

                self._process_commands()
                self._stop.wait(0.05)

            except (OSError, UnicodeError, LegacyProtocolError, ConnectionError) as exc:
                self.model.update(
                    "legacy/last_error",
                    str(exc),
                    source="legacy",
                    quality="bad",
                )
                self._set_connected(False)
                self._close_socket()
                # Safety: never replay an old hardware command after reconnect.
                self._drop_pending_commands()
                self._stop.wait(float(self.cfg.reconnect_interval_s))
