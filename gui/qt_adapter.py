# gui/qt_adapter.py
from __future__ import annotations

from PyQt5.QtCore import QObject, pyqtSignal

from backend.backend import Backend
from backend.model import Channel


class QtBackendAdapter(QObject):
    """Thread-safe bridge: DataModel -> Qt signals."""
    channelUpdated = pyqtSignal(str, object)

    def __init__(self, backend: Backend):
        super().__init__()
        self.backend = backend
        self._subscribed_channels: set[str] = set()

    def register_channel(self, name: str) -> None:
        if name in self._subscribed_channels:
            return
        self._subscribed_channels.add(name)

        self.backend.model.subscribe(name, self._on_channel_update)

        ch = self.backend.model.get(name)
        if ch is not None:
            self.channelUpdated.emit(ch.name, ch.value)

    def _on_channel_update(self, ch: Channel) -> None:
        self.channelUpdated.emit(ch.name, ch.value)