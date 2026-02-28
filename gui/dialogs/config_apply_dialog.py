# gui/dialogs/config_apply_dialog.py
from __future__ import annotations

from typing import Dict, Any, Set

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QTreeWidget, QTreeWidgetItem, QLabel
)

from gui.panels.common import pretty_name


def _label_for_key(k: str) -> str:
    if k == "magnet_current_set":
        return "Magnet current"
    if k == "rfq/fg_freq_hz":
        return "FG frequency"
    if k == "rfq/fg_vpp":
        return "FG amplitude"
    return pretty_name(k)


class ConfigApplyDialog(QDialog):
    def __init__(self, setpoints: Dict[str, Any], states: Dict[str, Any], extras: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Load config – select parameters to apply")
        self.resize(650, 520)

        self._selected: Set[str] = set()

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select which parameters should be applied from the config file:"))

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Parameter", "Value"])
        self.tree.setColumnWidth(0, 430)
        layout.addWidget(self.tree, 1)

        root_set = QTreeWidgetItem(self.tree, ["Setpoints (ramped)", ""])
        root_set.setFlags(root_set.flags() & ~Qt.ItemIsSelectable)

        for k, v in sorted(setpoints.items()):
            it = QTreeWidgetItem(root_set, [_label_for_key(k), str(v)])
            it.setData(0, Qt.UserRole, k)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Checked)

        root_ext = QTreeWidgetItem(self.tree, ["Extras (ramped)", ""])
        root_ext.setFlags(root_ext.flags() & ~Qt.ItemIsSelectable)

        for k, v in sorted(extras.items()):
            it = QTreeWidgetItem(root_ext, [_label_for_key(k), str(v)])
            it.setData(0, Qt.UserRole, k)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Checked)

        root_state = QTreeWidgetItem(self.tree, ["States (immediate)", ""])
        root_state.setFlags(root_state.flags() & ~Qt.ItemIsSelectable)

        for k, v in sorted(states.items()):
            it = QTreeWidgetItem(root_state, [_label_for_key(k), str(v)])
            it.setData(0, Qt.UserRole, k)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Checked)

        self.tree.expandAll()

        btns = QHBoxLayout()
        self.btn_all = QPushButton("Select all")
        self.btn_none = QPushButton("Select none")
        self.btn_ok = QPushButton("Apply")
        self.btn_cancel = QPushButton("Cancel")

        self.btn_all.clicked.connect(self._select_all)
        self.btn_none.clicked.connect(self._select_none)
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)

        btns.addWidget(self.btn_all)
        btns.addWidget(self.btn_none)
        btns.addStretch(1)
        btns.addWidget(self.btn_ok)
        btns.addWidget(self.btn_cancel)
        layout.addLayout(btns)

    def _walk_items(self, root: QTreeWidgetItem):
        for i in range(root.childCount()):
            it = root.child(i)
            yield it
            yield from self._walk_items(it)

    def _select_all(self):
        root = self.tree.invisibleRootItem()
        for it in self._walk_items(root):
            if it.flags() & Qt.ItemIsUserCheckable:
                it.setCheckState(0, Qt.Checked)

    def _select_none(self):
        root = self.tree.invisibleRootItem()
        for it in self._walk_items(root):
            if it.flags() & Qt.ItemIsUserCheckable:
                it.setCheckState(0, Qt.Unchecked)

    def selected_keys(self) -> Set[str]:
        sel: Set[str] = set()
        root = self.tree.invisibleRootItem()
        for it in self._walk_items(root):
            if not (it.flags() & Qt.ItemIsUserCheckable):
                continue
            if it.checkState(0) == Qt.Checked:
                k = it.data(0, Qt.UserRole)
                if k:
                    sel.add(str(k))
        return sel