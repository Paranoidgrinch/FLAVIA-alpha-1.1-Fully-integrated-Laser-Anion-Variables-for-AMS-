import socket
import threading
import time

from backend.model import DataModel
from backend.workers.legacy_tcp_worker import LegacyTcpConfig, LegacyTcpWorker


def _fake_server(listener, commands, stop_event):
    conn, _ = listener.accept()
    conn.settimeout(2.0)
    rx = bytearray()
    try:
        while not stop_event.is_set():
            while b"\r\n" not in rx:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                rx.extend(chunk)
            pos = rx.index(b"\r\n")
            command = bytes(rx[:pos]).decode("ascii")
            del rx[:pos + 2]
            commands.append(command)
            if command == "getAllData":
                response = ("DATA 807 " + ",".join("0" for _ in range(807)) + "\r\n").encode("ascii")
                # Deliberately split the response to prove the client is line-oriented,
                # not based on one recv() call.
                cut = len(response) // 2
                conn.sendall(response[:cut])
                time.sleep(0.01)
                conn.sendall(response[cut:])
            else:
                conn.sendall(b"done\r\n")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def test_worker_validates_snapshot_sets_connected_and_sends_command():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    commands = []
    stop_event = threading.Event()
    server_thread = threading.Thread(target=_fake_server, args=(listener, commands, stop_event), daemon=True)
    server_thread.start()

    model = DataModel()
    worker = LegacyTcpWorker(model, LegacyTcpConfig(
        host="127.0.0.1",
        port=port,
        poll_interval_s=0.1,
        connect_timeout_s=0.5,
        io_timeout_s=0.5,
        reconnect_interval_s=0.1,
    ))
    worker.start()
    try:
        deadline = time.time() + 2.0
        while time.time() < deadline:
            ch = model.get("legacy/connected")
            if ch is not None and ch.value is True:
                break
            time.sleep(0.01)
        else:
            raise AssertionError("worker never reached validated connected state")

        worker.send_command("setDigital 5 8 0")
        deadline = time.time() + 2.0
        while time.time() < deadline and "setDigital 5 8 0" not in commands:
            time.sleep(0.01)
        assert "setDigital 5 8 0" in commands
    finally:
        worker.stop()
        stop_event.set()
        try:
            listener.close()
        except Exception:
            pass
