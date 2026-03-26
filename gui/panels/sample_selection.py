# gui/panels/sample_selection.py
from __future__ import annotations

import os
from typing import Dict, List, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QGroupBox, QFormLayout, QComboBox, QPushButton, QSpinBox,
    QHBoxLayout, QLabel, QFileDialog, QMessageBox, QVBoxLayout
)

from gui.qt_adapter import QtBackendAdapter

SAMPLE_WHEEL_DIR = r"C:\Users\ALIS\Desktop\Samplel Wheel Lists"
DEFAULT_POS_FILE = r"C:\Users\ALIS\Desktop\Samplel Wheel Lists\ALIS_Positionen.txt"


class SampleSelectionPanel(QWidget):
    def __init__(self, backend, adapter: QtBackendAdapter, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.adapter = adapter

        self.sample_position_file = DEFAULT_POS_FILE
        self.sample_wheel_list_path: Optional[str] = None

        self.sample_positions: Dict[int, int] = {}
        self.sample_labels: Dict[int, str] = {}
        self.sample_index_order: List[int] = []
        self.sample_materials: Dict[int, str] = {}

        gb = QGroupBox("Sample Selection")
        gb.setStyleSheet("""
            QGroupBox { font-size: 14px; font-weight: 700; }
            QLabel { font-size: 12px; }
        """)
        form = QFormLayout()
        form.setVerticalSpacing(4)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.sample_combo = QComboBox()
        form.addRow("Sample:", self.sample_combo)

        self.sample_list_btn = QPushButton("Choose Sample Wheel List")
        self.sample_list_btn.clicked.connect(self.on_choose_sample_wheel_list)
        form.addRow("Wheel list:", self.sample_list_btn)

        self.sample_offset_spin = QSpinBox()
        self.sample_offset_spin.setRange(-10000, 10000)
        self.sample_offset_spin.setValue(-200)
        self.sample_offset_spin.setSuffix(" steps")
        form.addRow("Offset:", self.sample_offset_spin)

        btn_row = QHBoxLayout()
        self.sample_go_btn = QPushButton("Go")
        self.sample_home_btn = QPushButton("Home")
        self.sample_stop_btn = QPushButton("Stop")
        self.sample_stop_btn.setStyleSheet("background-color:#d9534f; color:white;")
        self.sample_go_btn.clicked.connect(self.on_sample_go_clicked)
        self.sample_home_btn.clicked.connect(self.on_sample_home_clicked)
        self.sample_stop_btn.clicked.connect(self.on_sample_stop_clicked)
        btn_row.addWidget(self.sample_go_btn)
        btn_row.addWidget(self.sample_home_btn)
        btn_row.addWidget(self.sample_stop_btn)
        form.addRow(btn_row)

        self.sample_status_label = QLabel("Stepper: unknown")
        self.sample_position_label = QLabel("Position: -")
        form.addRow("Status:", self.sample_status_label)
        form.addRow("Actual:", self.sample_position_label)

        # NEW: last command info
        self.last_cmd_label = QLabel("Last: —")
        self.last_cmd_label.setStyleSheet("font-weight:800;")
        form.addRow("Last cmd:", self.last_cmd_label)

        gb.setLayout(form)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(gb)

        # load positions immediately
        self.load_sample_positions()

        # subscribe stepper + last state
        self.adapter.channelUpdated.connect(self._on_update)
        for ch in [
            "stepper_connected",
            "stepper_position_meas",
            "stepper_moving",
            "sample/last_timestamp",
            "sample/last_command",
            "sample/last_pos_idx",
            "sample/last_target_steps",
            "sample/last_sample_name",
        ]:
            self.adapter.register_channel(ch)

    # -------- file parsing like old program --------
    def load_sample_positions(self):
        self.sample_positions.clear()
        self.sample_labels.clear()
        self.sample_index_order.clear()
        self.sample_materials.clear()
        self.sample_combo.clear()

        try:
            with open(self.sample_position_file, "r") as f:
                idx_counter = 1
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    try:
                        steps = int(parts[-1])
                    except ValueError:
                        continue

                    try:
                        pos_idx = int(parts[0])
                        label = " ".join(parts[:-1])
                    except ValueError:
                        pos_idx = idx_counter
                        idx_counter += 1
                        label = " ".join(parts[:-1])

                    if not label:
                        label = f"Pos {pos_idx}"

                    self.sample_positions[pos_idx] = steps
                    self.sample_labels[pos_idx] = label
                    self.sample_index_order.append(pos_idx)

            if self.sample_positions:
                self.sample_status_label.setText(f"Stepper: loaded {len(self.sample_positions)} samples")
                self.sample_status_label.setStyleSheet("color:#666;")
            else:
                self.sample_status_label.setText("Stepper: no positions found")
                self.sample_status_label.setStyleSheet("color:#a00;")
        except Exception as e:
            self.sample_status_label.setText(f"Stepper: error loading positions ({e})")
            self.sample_status_label.setStyleSheet("color:#a00;")

        self.refresh_sample_combo_labels()

    def refresh_sample_combo_labels(self):
        self.sample_combo.blockSignals(True)
        self.sample_combo.clear()
        self.sample_combo.addItem("Select sample", userData=None)
        for pos_idx in self.sample_index_order:
            base_label = self.sample_labels.get(pos_idx, f"Pos {pos_idx}")
            mat = self.sample_materials.get(pos_idx)
            display = f"{base_label} – {mat}" if mat else base_label
            self.sample_combo.addItem(display, userData=pos_idx)
        self.sample_combo.setCurrentIndex(0)
        self.sample_combo.blockSignals(False)

    def on_choose_sample_wheel_list(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Sample Wheel List",
            SAMPLE_WHEEL_DIR,
            "Sample wheel lists (*.ods *.xlsx *.xls *.csv *.txt);;All files (*)"
        )
        if not path:
            return
        try:
            materials = self._parse_sample_wheel_list(path)
        except Exception as e:
            QMessageBox.critical(self, "Error reading wheel list", f"Could not read sample wheel list:\n{e}")
            return

        self.sample_wheel_list_path = path
        self.sample_materials = materials
        self.refresh_sample_combo_labels()
        self.sample_status_label.setText(f"Stepper: wheel list loaded ({len(materials)} entries)")
        self.sample_status_label.setStyleSheet("color:#333;")

    def _parse_sample_wheel_list(self, path: str) -> Dict[int, str]:
        _, ext = os.path.splitext(path)
        ext = ext.lower()
        try:
            import pandas as pd
        except ImportError as e:
            raise RuntimeError("Reading wheel lists requires: pip install pandas odfpy") from e

        try:
            if ext in (".ods", ".xlsx", ".xls"):
                if ext == ".ods":
                    df = pd.read_excel(path, engine="odf")
                else:
                    df = pd.read_excel(path)
            else:
                df = pd.read_csv(path, sep=None, engine="python")
        except Exception as e:
            raise RuntimeError(f"Error reading table file: {e}") from e

        if df.empty:
            raise RuntimeError("File is empty.")

        col_map = {(str(c).strip().lower() if isinstance(c, str) else ""): c for c in df.columns}
        pos_col = None
        mat_col = None
        for key, orig in col_map.items():
            if "position" in key:
                pos_col = orig
            if "material" in key:
                mat_col = orig
        if pos_col is None:
            raise RuntimeError("No column named 'position' found.")
        if mat_col is None:
            raise RuntimeError("No column named 'Material' found.")

        materials: Dict[int, str] = {}
        for _, row in df.iterrows():
            pos_val = row[pos_col]
            mat_val = row[mat_col]
            if pd.isna(pos_val) or pd.isna(mat_val):
                continue
            try:
                pos_idx = int(pos_val)
            except Exception:
                s = str(pos_val).strip()
                digits = "".join(ch for ch in s if ch.isdigit())
                if not digits:
                    continue
                pos_idx = int(digits)
            mat_str = str(mat_val).strip()
            if not mat_str:
                continue
            materials[pos_idx] = mat_str

        if not materials:
            raise RuntimeError("No (position, Material) entries found.")
        return materials

    # -------- actions --------
    def on_sample_go_clicked(self):
        pos_idx = self.sample_combo.currentData()
        if not isinstance(pos_idx, int):
            self.sample_status_label.setText("Stepper: please select a valid sample")
            self.sample_status_label.setStyleSheet("color:#a00;")
            return

        base_pos = self.sample_positions.get(pos_idx)
        if base_pos is None:
            self.sample_status_label.setText("Stepper: no position for selected sample")
            self.sample_status_label.setStyleSheet("color:#a00;")
            return

        offset = self.sample_offset_spin.value()
        target = base_pos + offset

        label = self.sample_labels.get(pos_idx, f"Pos {pos_idx}")
        material = self.sample_materials.get(pos_idx)
        sample_name = f"{label} ({material})" if material else label

        self.backend.move_sample_to_position(target)
        self.backend.sample_state.record("GO", pos_idx=pos_idx, target_steps=target, sample_name=sample_name)

        self.sample_status_label.setText(f"Stepper: moving to '{sample_name}' (pos {target})")
        self.sample_status_label.setStyleSheet("color:#333;")

    def on_sample_stop_clicked(self):
        self.backend.stop_stepper()
        self.backend.sample_state.record("STOP", pos_idx=None, target_steps=None, sample_name="")
        self.sample_status_label.setText("Stepper: stop requested")
        self.sample_status_label.setStyleSheet("color:#d68b00;")

    def on_sample_home_clicked(self):
        self.backend.home_stepper()
        self.backend.sample_state.record("HOME", pos_idx=None, target_steps=None, sample_name="")
        self.sample_status_label.setText("Stepper: home requested")
        self.sample_status_label.setStyleSheet("color:#333;")

    # -------- model updates --------
    def _on_update(self, name: str, value):
        if name == "stepper_connected":
            ok = bool(value)
            self.sample_status_label.setText("Stepper: connected" if ok else "Stepper: disconnected")
            self.sample_status_label.setStyleSheet("color:#333;" if ok else "color:#a00;")
            return

        if name == "stepper_position_meas":
            self.sample_position_label.setText(f"Position: {value}")
            return

        if name.startswith("sample/last_"):
            ts = self.backend.model.get("sample/last_timestamp").value if self.backend.model.get("sample/last_timestamp") else ""
            cmd = self.backend.model.get("sample/last_command").value if self.backend.model.get("sample/last_command") else ""
            idx = self.backend.model.get("sample/last_pos_idx").value if self.backend.model.get("sample/last_pos_idx") else None
            steps = self.backend.model.get("sample/last_target_steps").value if self.backend.model.get("sample/last_target_steps") else None
            sname = self.backend.model.get("sample/last_sample_name").value if self.backend.model.get("sample/last_sample_name") else ""

            parts = [str(cmd or "—")]
            if sname:
                parts.append(str(sname))
            if idx is not None:
                parts.append(f"idx={idx}")
            if steps is not None:
                parts.append(f"steps={steps}")
            if ts:
                parts.append(str(ts))

            self.last_cmd_label.setText(" | ".join(parts))