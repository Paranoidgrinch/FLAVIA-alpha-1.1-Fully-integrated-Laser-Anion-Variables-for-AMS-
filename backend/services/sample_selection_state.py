# backend/services/sample_selection_state.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
from typing import Optional

from backend.model import DataModel


@dataclass
class SampleLastState:
    timestamp: str = ""
    command: str = ""
    pos_idx: Optional[int] = None
    target_steps: Optional[int] = None
    sample_name: str = ""


class SampleSelectionStateService:
    """
    Persist last Sample Selection command to disk and mirror it into DataModel,
    so GUI can show it immediately after restart.
    """
    def __init__(self, model: DataModel, file_path: str = "data/sample_selection_last.json"):
        self.model = model
        self.path = Path(file_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state = SampleLastState()
        self.load_into_model()

    def load_into_model(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.state = SampleLastState(
                    timestamp=str(data.get("timestamp", "")),
                    command=str(data.get("command", "")),
                    pos_idx=data.get("pos_idx", None),
                    target_steps=data.get("target_steps", None),
                    sample_name=str(data.get("sample_name", "")),
                )
            except Exception:
                self.state = SampleLastState()

        self._write_model()

    def record(self, command: str, pos_idx: Optional[int], target_steps: Optional[int], sample_name: str) -> None:
        self.state = SampleLastState(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            command=str(command),
            pos_idx=pos_idx if isinstance(pos_idx, int) else None,
            target_steps=target_steps if isinstance(target_steps, int) else None,
            sample_name=str(sample_name or ""),
        )
        try:
            self.path.write_text(json.dumps(self.state.__dict__, indent=2), encoding="utf-8")
        except Exception:
            pass
        self._write_model()

    def _write_model(self) -> None:
        self.model.update("sample/last_timestamp", self.state.timestamp, source="sample")
        self.model.update("sample/last_command", self.state.command, source="sample")
        self.model.update("sample/last_pos_idx", self.state.pos_idx, source="sample")
        self.model.update("sample/last_target_steps", self.state.target_steps, source="sample")
        self.model.update("sample/last_sample_name", self.state.sample_name, source="sample")