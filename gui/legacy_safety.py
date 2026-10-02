from __future__ import annotations

import time
from collections import deque
from typing import Deque, Tuple

from PyQt5.QtWidgets import QMessageBox


ACC_TERMINAL_CHANNEL = "legacy/acc/terminal_voltage/set_kv"
_WINDOW_S = 5.0
_LIMIT_KV = 1000.0
_history: Deque[Tuple[float, float]] = deque()
_last_accepted_value = None


def confirm_terminal_voltage_change(parent, backend, new_value_kv: float) -> bool:
    """Apply the operator-confirmation rule for fast ACC terminal changes.

    A confirmation is required when the requested setpoint has moved by more
    than 1000 kV relative to the oldest accepted request in the last 5 s.
    The model value is used as the initial baseline when available.
    """
    global _last_accepted_value
    now = time.monotonic()
    value = float(new_value_kv)

    while _history and (now - _history[0][0]) > _WINDOW_S:
        _history.popleft()

    if not _history:
        baseline = value if _last_accepted_value is None else float(_last_accepted_value)
        ch = backend.model.get(ACC_TERMINAL_CHANNEL)
        try:
            if ch is not None and ch.value is not None:
                baseline = float(ch.value)
        except Exception:
            pass
        _history.append((now, baseline))

    delta = abs(value - _history[0][1])
    if delta > _LIMIT_KV:
        answer = QMessageBox.question(
            parent,
            "ACC Terminal Voltage",
            "The requested terminal-voltage change exceeds 1000 kV within 5 seconds.\n\nAre you sure?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return False
        _history.clear()

    _history.append((now, value))
    _last_accepted_value = value
    return True
