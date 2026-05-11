from __future__ import annotations

import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Tuple, Any

from backend.model import DataModel


IONIZER_SETPOINT_CHANNEL = "cs/ionizer/set_i_a"
OVEN_TEMP_CHANNEL = "cs/oven/temp_c"
IONIZER_TARGET_A = 22.0
IONIZER_TOL_A = 0.001

EXPOSURE_COLUMNS = {
    "selected_s": "sputter_selected_s",
    "selected_hms": "sputter_selected_hhmmss",
    "ionizer22_s": "sputter_ionizer22_s",
    "ionizer22_hms": "sputter_ionizer22_hhmmss",
    "ionizer22_oven_s": "sputter_ionizer22_oven_s",
    "ionizer22_oven_hms": "sputter_ionizer22_oven_hhmmss",
    "oven_threshold_c": "sputter_oven_threshold_c",
    "last_update": "sputter_last_update",
}


@dataclass
class ExposureTotals:
    selected_s: float = 0.0
    ionizer22_s: float = 0.0
    ionizer22_oven_s: float = 0.0


@dataclass
class ActiveSample:
    pos_idx: int
    sample_name: str
    wheel_list_path: Optional[str]
    oven_threshold_c: float


class SampleExposureCounterService:
    """
    Accumulates per-sample sputter/exposure times.

    Counters start on GO, because SampleSelectionPanel calls select_sample()
    directly after move_sample_to_position(). The actual stepper movement is not
    touched by this service.
    """

    def __init__(self, model: DataModel, *, tick_s: float = 1.0, file_update_s: float = 60.0):
        self.model = model
        self.tick_s = max(0.2, float(tick_s))
        self.file_update_s = max(5.0, float(file_update_s))

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._active: Optional[ActiveSample] = None
        self._totals: Dict[Tuple[str, int], ExposureTotals] = {}
        self._last_tick = time.monotonic()
        self._last_file_write = 0.0
        self._backed_up_paths: set[str] = set()

        self._write_model_status("inactive")
        self._write_model_times(ExposureTotals())

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._last_tick = time.monotonic()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self.flush(force=True)
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    # ------------------------------------------------------------------
    # Public API used by GUI
    # ------------------------------------------------------------------
    def select_sample(
        self,
        *,
        pos_idx: int,
        sample_name: str,
        wheel_list_path: Optional[str],
        oven_threshold_c: float,
    ) -> None:
        # First persist the previous active sample, if any.
        self.flush(force=True)

        active = ActiveSample(
            pos_idx=int(pos_idx),
            sample_name=str(sample_name or f"Pos {pos_idx}"),
            wheel_list_path=str(wheel_list_path) if wheel_list_path else None,
            oven_threshold_c=float(oven_threshold_c),
        )

        with self._lock:
            key = self._key_for(active)
            if key not in self._totals:
                self._totals[key] = self._load_totals_from_file(active)

            self._active = active
            self._last_tick = time.monotonic()
            self._last_file_write = self._last_tick
            self._write_model_active(active, is_active=True)
            self._write_model_times(self._totals[key])
            self._write_model_status("active")

    def clear_active_sample(self, *, reason: str = "") -> None:
        self.flush(force=True)
        with self._lock:
            self._active = None
            self._last_tick = time.monotonic()
            self.model.update("sample/exposure/active", False, source="sample_exposure")
            self._write_model_status(f"inactive {reason}".strip())

    def set_oven_threshold(self, oven_threshold_c: float) -> None:
        with self._lock:
            if self._active is not None:
                self._active.oven_threshold_c = float(oven_threshold_c)
                self.model.update(
                    "sample/exposure/oven_threshold_c",
                    float(oven_threshold_c),
                    source="sample_exposure",
                )

    def flush(self, *, force: bool = False) -> None:
        with self._lock:
            now = time.monotonic()
            self._commit_elapsed_locked(now)
            active = self._active
            if active is None:
                return
            key = self._key_for(active)
            totals = self._totals.get(key, ExposureTotals())

        # File IO outside the timing lock as much as possible.
        self._write_totals_to_file(active, totals, force=force)

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop_event.is_set():
            time.sleep(self.tick_s)
            should_write = False

            with self._lock:
                now = time.monotonic()
                self._commit_elapsed_locked(now)

                if self._active is not None:
                    key = self._key_for(self._active)
                    self._write_model_times(self._totals.get(key, ExposureTotals()))
                    should_write = (now - self._last_file_write) >= self.file_update_s

            if should_write:
                self.flush(force=True)

    def _commit_elapsed_locked(self, now: float) -> None:
        dt = max(0.0, float(now - self._last_tick))
        self._last_tick = now

        if self._active is None or dt <= 0.0:
            return

        key = self._key_for(self._active)
        totals = self._totals.setdefault(key, ExposureTotals())

        totals.selected_s += dt

        ionizer_ok = self._ionizer_setpoint_is_22()
        if ionizer_ok:
            totals.ionizer22_s += dt

        if ionizer_ok and self._oven_is_hot_enough(self._active.oven_threshold_c):
            totals.ionizer22_oven_s += dt

    # ------------------------------------------------------------------
    # Conditions
    # ------------------------------------------------------------------
    def _channel_float(self, channel: str) -> Optional[float]:
        ch = self.model.get(channel)
        if ch is None or ch.value is None:
            return None
        try:
            return float(ch.value)
        except Exception:
            return None

    def _ionizer_setpoint_is_22(self) -> bool:
        v = self._channel_float(IONIZER_SETPOINT_CHANNEL)
        if v is None:
            return False
        return abs(v - IONIZER_TARGET_A) <= IONIZER_TOL_A

    def _oven_is_hot_enough(self, threshold_c: float) -> bool:
        v = self._channel_float(OVEN_TEMP_CHANNEL)
        if v is None:
            return False
        return v >= float(threshold_c)

    # ------------------------------------------------------------------
    # DataModel output
    # ------------------------------------------------------------------
    def _write_model_active(self, active: ActiveSample, *, is_active: bool) -> None:
        self.model.update("sample/exposure/active", bool(is_active), source="sample_exposure")
        self.model.update("sample/exposure/active_pos_idx", int(active.pos_idx), source="sample_exposure")
        self.model.update("sample/exposure/active_sample_name", active.sample_name, source="sample_exposure")
        self.model.update("sample/exposure/wheel_list_path", active.wheel_list_path or "", source="sample_exposure")
        self.model.update("sample/exposure/oven_threshold_c", float(active.oven_threshold_c), source="sample_exposure")

    def _write_model_times(self, totals: ExposureTotals) -> None:
        self.model.update("sample/exposure/selected_s", float(totals.selected_s), source="sample_exposure")
        self.model.update("sample/exposure/selected_hhmmss", _format_hhmmss(totals.selected_s), source="sample_exposure")
        self.model.update("sample/exposure/ionizer22_s", float(totals.ionizer22_s), source="sample_exposure")
        self.model.update("sample/exposure/ionizer22_hhmmss", _format_hhmmss(totals.ionizer22_s), source="sample_exposure")
        self.model.update("sample/exposure/ionizer22_oven_s", float(totals.ionizer22_oven_s), source="sample_exposure")
        self.model.update("sample/exposure/ionizer22_oven_hhmmss", _format_hhmmss(totals.ionizer22_oven_s), source="sample_exposure")

    def _write_model_status(self, msg: str) -> None:
        self.model.update("sample/exposure/file_status", str(msg or ""), source="sample_exposure")

    # ------------------------------------------------------------------
    # File IO
    # ------------------------------------------------------------------
    def _key_for(self, active: ActiveSample) -> Tuple[str, int]:
        return (
            str(Path(active.wheel_list_path).resolve()) if active.wheel_list_path else "",
            int(active.pos_idx),
        )

    def _read_table(self, path: str):
        import pandas as pd

        p = Path(path)
        ext = p.suffix.lower()

        if ext == ".ods":
            return pd.read_excel(p, engine="odf")
        if ext in (".xlsx", ".xls"):
            return pd.read_excel(p)

        return pd.read_csv(p, sep=None, engine="python")

    def _write_table(self, df, path: str) -> None:
        p = Path(path)
        ext = p.suffix.lower()
        tmp = p.with_name(p.stem + ".tmp" + p.suffix)

        if ext == ".ods":
            df.to_excel(tmp, index=False, engine="odf")
        elif ext in (".xlsx", ".xls"):
            df.to_excel(tmp, index=False)
        else:
            df.to_csv(tmp, index=False)

        tmp.replace(p)

    def _ensure_backup(self, path: str) -> None:
        if path in self._backed_up_paths:
            return

        p = Path(path)
        if not p.exists():
            return

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = p.with_name(f"{p.name}.bak_{stamp}")
        shutil.copy2(p, backup)
        self._backed_up_paths.add(path)

    def _load_totals_from_file(self, active: ActiveSample) -> ExposureTotals:
        if not active.wheel_list_path:
            return ExposureTotals()

        try:
            df = self._read_table(active.wheel_list_path)
            pos_col = _find_position_column(df.columns)

            if pos_col is None:
                self._write_model_status("no position column in wheel list")
                return ExposureTotals()

            mask = df[pos_col].apply(_parse_position_value) == int(active.pos_idx)
            if not mask.any():
                self._write_model_status(f"position {active.pos_idx} not found in wheel list")
                return ExposureTotals()

            row = df.loc[mask].iloc[0]
            return ExposureTotals(
                selected_s=_safe_float(row.get(EXPOSURE_COLUMNS["selected_s"], 0.0)),
                ionizer22_s=_safe_float(row.get(EXPOSURE_COLUMNS["ionizer22_s"], 0.0)),
                ionizer22_oven_s=_safe_float(row.get(EXPOSURE_COLUMNS["ionizer22_oven_s"], 0.0)),
            )

        except Exception as exc:
            self._write_model_status(f"could not read previous exposure values: {exc}")
            return ExposureTotals()

    def _write_totals_to_file(self, active: ActiveSample, totals: ExposureTotals, *, force: bool) -> None:
        if not active.wheel_list_path:
            self._write_model_status("no wheel list selected; counters shown only")
            return

        try:
            self._ensure_backup(active.wheel_list_path)
            df = self._read_table(active.wheel_list_path)
            pos_col = _find_position_column(df.columns)

            if pos_col is None:
                self._write_model_status("no position column in wheel list")
                return

            mask = df[pos_col].apply(_parse_position_value) == int(active.pos_idx)
            if not mask.any():
                self._write_model_status(f"position {active.pos_idx} not found in wheel list")
                return

            for col in EXPOSURE_COLUMNS.values():
                if col not in df.columns:
                    df[col] = ""

            now_txt = datetime.now().isoformat(timespec="seconds")

            df.loc[mask, EXPOSURE_COLUMNS["selected_s"]] = round(float(totals.selected_s), 3)
            df.loc[mask, EXPOSURE_COLUMNS["selected_hms"]] = _format_hhmmss(totals.selected_s)

            df.loc[mask, EXPOSURE_COLUMNS["ionizer22_s"]] = round(float(totals.ionizer22_s), 3)
            df.loc[mask, EXPOSURE_COLUMNS["ionizer22_hms"]] = _format_hhmmss(totals.ionizer22_s)

            df.loc[mask, EXPOSURE_COLUMNS["ionizer22_oven_s"]] = round(float(totals.ionizer22_oven_s), 3)
            df.loc[mask, EXPOSURE_COLUMNS["ionizer22_oven_hms"]] = _format_hhmmss(totals.ionizer22_oven_s)

            df.loc[mask, EXPOSURE_COLUMNS["oven_threshold_c"]] = float(active.oven_threshold_c)
            df.loc[mask, EXPOSURE_COLUMNS["last_update"]] = now_txt

            self._write_table(df, active.wheel_list_path)

            with self._lock:
                self._last_file_write = time.monotonic()

            self._write_model_status(f"saved {now_txt}")

        except Exception as exc:
            self._write_model_status(f"save failed: {exc}")


def _format_hhmmss(seconds: float) -> str:
    total = int(round(max(0.0, float(seconds))))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, float) and value != value:
            return default
        return float(value)
    except Exception:
        return default


def _find_position_column(columns) -> Optional[str]:
    for c in columns:
        if "position" in str(c).strip().lower():
            return c
    return None


def _parse_position_value(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        if isinstance(value, float) and value != value:
            return None
        return int(float(value))
    except Exception:
        s = str(value).strip()
        digits = "".join(ch for ch in s if ch.isdigit())
        if not digits:
            return None
        try:
            return int(digits)
        except Exception:
            return None