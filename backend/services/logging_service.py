# backend/services/logging_service.py
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from ..model import DataModel
from ..channels import CHANNELS


def _default_log_channels() -> List[str]:
    names: List[str] = []
    for name, c in CHANNELS.items():
        if name == "mqtt_connected":
            continue
        if "/dbg/" in name:
            continue
        # logge alles was vom MQTT kommt (set/meas/state) + wichtige worker states
        if c.kind in ("set", "meas", "state"):
            names.append(name)
    # deterministisch sortieren
    return sorted(set(names))


@dataclass
class LoggingConfig:
    interval_s: float = 1.0
    channels: Optional[List[str]] = None


class LoggingService(threading.Thread):
    def __init__(self, model: DataModel):
        super().__init__(daemon=True)
        self.model = model
        self._stop = threading.Event()
        self._running = threading.Event()
        self._lock = threading.RLock()

        self._cfg = LoggingConfig()
        self._file: Optional[Path] = None
        self._fh = None

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    def start_logging(self, filepath: str, cfg: Optional[LoggingConfig] = None) -> None:
        with self._lock:
            self._file = Path(filepath)
            self._cfg = cfg or LoggingConfig()
            if self._cfg.channels is None:
                self._cfg.channels = _default_log_channels()

            self._file.parent.mkdir(parents=True, exist_ok=True)

            # (re)open file
            if self._fh:
                try:
                    self._fh.close()
                except Exception:
                    pass
            self._fh = self._file.open("w", encoding="utf-8", newline="")

            # header
            header = ["timestamp_s"] + list(self._cfg.channels)
            self._fh.write("\t".join(header) + "\n")
            self._fh.flush()

            self._running.set()

        if not self.is_alive():
            super().start()

    def stop_logging(self) -> None:
        self._running.clear()
        with self._lock:
            if self._fh:
                try:
                    self._fh.flush()
                    self._fh.close()
                except Exception:
                    pass
                self._fh = None

    def shutdown(self) -> None:
        self._stop.set()
        self._running.clear()
        self.join(timeout=2.0)
        with self._lock:
            if self._fh:
                try:
                    self._fh.close()
                except Exception:
                    pass
                self._fh = None

    def run(self) -> None:
        while not self._stop.is_set():
            if not self._running.is_set():
                time.sleep(0.1)
                continue

            with self._lock:
                fh = self._fh
                cfg = self._cfg

            if fh is None or cfg.channels is None:
                time.sleep(0.1)
                continue

            ts = time.time()
            row = [f"{ts:.6f}"]
            for name in cfg.channels:
                ch = self.model.get(name)
                if ch is None or ch.value is None:
                    row.append("")
                else:
                    row.append(str(ch.value))

            try:
                fh.write("\t".join(row) + "\n")
                fh.flush()
            except Exception:
                # wenn Schreiben fehlschlägt: Logging beenden
                self._running.clear()

            time.sleep(max(0.05, float(cfg.interval_s)))