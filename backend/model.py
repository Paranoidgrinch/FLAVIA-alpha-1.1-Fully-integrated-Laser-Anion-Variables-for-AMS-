# backend/model.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Callable, Optional
import threading
import time


@dataclass
class Channel:
    name: str
    unit: str = ""
    value: Any = None
    timestamp: float = field(default_factory=time.time)
    source: str = ""
    quality: str = "unknown"


class DataModel:
    """Thread-sicheres Datenmodell für alle Kanäle."""

    def __init__(self, unit_resolver: Optional[Callable[[str], str]] = None):
        self._lock = threading.RLock()
        self._channels: Dict[str, Channel] = {}
        self._subscribers: Dict[str, List[Callable[[Channel], None]]] = {}
        self._unit_resolver = unit_resolver

    def update(self, name: str, value: Any, *, source: str = "", quality: str = "good") -> None:
        with self._lock:
            unit = self._unit_resolver(name) if self._unit_resolver else ""
            ch = self._channels.get(name)
            if ch is None:
                ch = Channel(name=name, unit=unit, value=value, source=source, quality=quality)
                self._channels[name] = ch
            else:
                if unit and (ch.unit != unit):
                    ch.unit = unit
                ch.value = value
                ch.timestamp = time.time()
                ch.source = source
                ch.quality = quality

            subs = list(self._subscribers.get(name, []))

        for cb in subs:
            try:
                cb(ch)
            except Exception:
                pass

    def get(self, name: str) -> Optional[Channel]:
        with self._lock:
            return self._channels.get(name)

    def subscribe(self, name: str, callback: Callable[[Channel], None]) -> None:
        with self._lock:
            self._subscribers.setdefault(name, []).append(callback)

    def snapshot(self, names: List[str]) -> Dict[str, Optional[Channel]]:
        with self._lock:
            return {n: self._channels.get(n) for n in names}