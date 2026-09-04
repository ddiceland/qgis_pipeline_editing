# -*- coding: utf-8 -*-
"""管类颜色配置面板。"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QColorDialog,
)

from ..core.pipe_catalog import pipeline_display_name
from ..core.shared_export_config import PIPELINE_COLOR_TYPES
from .table_reorder import install_row_reorder


class AttributeMappingTable(QTableWidget):
    """对照表：中文名称、代码、说明。"""

    def __init__(self, name_header, parent=None):
        super().__init__(0, 3, parent)
        self.setHorizontalHeaderLabels([name_header or "中文名称", "代码", "说明"])
        self.horizontalHeader().setStretchLastSection(True)
        install_row_reorder(self)

    def load_mapping(self, mapping_list):
        self.setRowCount(0)
        for item in mapping_list or []:
            self._append_row(
                item.get("name", ""),
                item.get("code", ""),
                item.get("pipe_types") or item.get("note") or "",
            )

    def _append_row(self, name="", code="", pipe_types=""):
        row = self.rowCount()
        self.insertRow(row)
        self.setItem(row, 0, QTableWidgetItem(name))
        self.setItem(row, 1, QTableWidgetItem(code))
        note_item = QTableWidgetItem(pipe_types)
        note_item.setToolTip("说明文字，仅供查看，不参与转换逻辑")
        self.setItem(row, 2, note_item)

    def add_row(self):
        self._append_row()

    def snapshot_rows(self):
        rows = []
        for row in range(self.rowCount()):
            rows.append({
                "name": self._cell_text(row, 0),
                "code": self._cell_text(row, 1),
                "pipe_types": self._cell_text(row, 2),
            })
        return rows

    def restore_rows(self, rows):
        self.load_mapping(rows)

    def remove_selected(self):
        rows = sorted({idx.row() for idx in self.selectedIndexes()}, reverse=True)
        for r in rows:
            self.removeRow(r)

    def _cell_text(self, row, col):
        item = self.item(row, col)
        return item.text().strip() if item else ""

    def to_mapping(self):
        mapping = []
        for row in range(self.rowCount()):
            name = self._cell_text(row, 0)
            code = self._cell_text(row, 1)
            if not name and not code:
                continue
            mapping.append({
                "name": name,
                "code": code,
                "pipe_types": self._cell_text(row, 2),
            })
        return mapping


class PipeColorConfigPanel(QWidget):
    """管类显示颜色配置。"""

    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self._color_buttons = {}

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("加载图层时，管点与管线均按此处配置的颜色显示。"))

        self.table = QTableWidget(len(PIPELINE_COLOR_TYPES), 2)
        self.table.setHorizontalHeaderLabels(["管类", "颜色"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)

        for row, code in enumerate(PIPELINE_COLOR_TYPES):
            code_item = QTableWidgetItem(pipeline_display_name(code))
            code_item.setFlags(code_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, code_item)

            btn = QPushButton()
            btn.setMinimumHeight(28)
            btn.clicked.connect(lambda _checked, c=code: self._pick_color(c))
            self.table.setCellWidget(row, 1, btn)
            self._color_buttons[code] = btn

        layout.addWidget(self.table)
        self.load_colors(self.config_manager.get_pipe_colors())

    def _set_button_color(self, btn, color_hex):
        color = QColor(_normalize_color_hex(color_hex))
        btn.setText(color.name().upper())
        btn.setStyleSheet(
            f"background-color: {color.name()}; "
            f"color: {'#FFFFFF' if color.lightness() < 128 else '#000000'};"
        )
        btn.setProperty("color_hex", color.name())

    def _pick_color(self, code):
        btn = self._color_buttons[code]
        current = QColor(btn.property("color_hex") or "#808080")
        color = QColorDialog.getColor(current, self, f"选择 {code} 管类颜色")
        if color.isValid():
            self._set_button_color(btn, color.name())

    def load_colors(self, colors):
        for code, btn in self._color_buttons.items():
            self._set_button_color(btn, colors.get(code, "#808080"))

    def to_colors(self):
        result = {}
        for code, btn in self._color_buttons.items():
            result[code] = btn.property("color_hex") or "#808080"
        return result


def _normalize_color_hex(color):
    c = str(color or "#808080").strip()
    if not c.startswith("#"):
        c = "#" + c
    return c
