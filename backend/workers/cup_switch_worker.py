# backend/workers/cup_switch_worker.py
from __future__ import annotations

import queue
import re
import threading
import time
from dataclasses import dataclass
from urllib.request import urlopen, Request

from ..model import DataModel


@dataclass(frozen=True)
class CupSwitchConfig:
    ip: str = "192.168.0.19"
    poll_s: float = 0.8
    timeout_s: float = 2.5

    status_path: str = "/"
    select_path: str = "/select?c={c}"
    hv_on_path: str = "/hv?cmd=on"
    hv_off_path: str = "/hv?cmd=off"


def parse_status(text: str) -> dict:
    out = {"selected_cup": None, "hv": None}
    m = re.search(r"SelectedCup:\s*(\d+)", text, re.IGNORECASE)
    if m:
        out["selected_cup"] = int(m.group(1))
    m = re.search(r"HV:\s*(ON|OFF)", text, re.IGNORECASE)
    if m:
        out["hv"] = m.group(1).upper()
    return out


class CupSwitchWorker(threading.Thread):
    """
    Background worker for Cup Umschaltung.

    Model channels:
    - cup/connected (bool)
    - cup/selected  (int)
    - cup/hv        ("ON"/"OFF")
    """

    def __init__(self, model: DataModel, cfg: CupSwitchConfig = CupSwitchConfig()):
        super().__init__(daemon=True)
        self.model = model
        self.cfg = cfg

        self._stop = threading.Event()
        self._cmdq: "queue.Queue[tuple[str, object]]" = queue.Queue()

        self.model.update("cup/connected", False, source="cup", quality="bad")

    def stop(self) -> None:
        self._stop.set()
        self.join(timeout=3.0)

    def select_cup(self, c: int) -> None:
        self._cmdq.put(("select", int(c)))

    def hv_on(self) -> None:
        self._cmdq.put(("hv", "on"))

    def hv_off(self) -> None:
        self._cmdq.put(("hv", "off"))

    def _url(self, path: str) -> str:
        return f"http://{self.cfg.ip}{path}"

    def _http_get(self, path: str) -> str:
        req = Request(self._url(path), method="GET")
        with urlopen(req, timeout=float(self.cfg.timeout_s)) as r:
            data = r.read()
        return data.decode("utf-8", errors="replace")

    def _poll_status(self) -> None:
        try:
            text = self._http_get(self.cfg.status_path)
            st = parse_status(text)
            self.model.update("cup/connected", True, source="cup", quality="good")
            if st.get("selected_cup") is not None:
                self.model.update("cup/selected", st["selected_cup"], source="cup")
            if st.get("hv") is not None:
                self.model.update("cup/hv", st["hv"], source="cup")
        except Exception:
            self.model.update("cup/connected", False, source="cup", quality="bad")

    def _do_select(self, c: int) -> None:
        try:
            self._http_get(self.cfg.select_path.format(c=int(c)))
        except Exception:
            pass

    def _do_hv(self, cmd: str) -> None:
        try:
            if cmd == "on":
                self._http_get(self.cfg.hv_on_path)
            else:
                self._http_get(self.cfg.hv_off_path)
        except Exception:
            pass

    def run(self) -> None:
        next_poll = 0.0
        while not self._stop.is_set():
            try:
                while True:
                    cmd, payload = self._cmdq.get_nowait()
                    if cmd == "select":
                        self._do_select(int(payload))
                    elif cmd == "hv":
                        self._do_hv(str(payload))
            except queue.Empty:
                pass

            now = time.time()
            if now >= next_poll:
                self._poll_status()
                next_poll = now + float(self.cfg.poll_s)

            time.sleep(0.02)