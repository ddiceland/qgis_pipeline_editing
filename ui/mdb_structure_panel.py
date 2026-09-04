# -*- coding: utf-8 -*-
"""MDB 库结构配置面板。"""

import copy

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QPushButton, QTabWidget, QInputDialog,
    QMessageBox, QListWidget, QListWidgetItem, QComboBox,
    QTableWidget, QTableWidgetItem,
)

from ..core.config_schema import sync_mdb_structure_fields_from_template
from ..core.pipe_catalog import PIPELINE_TYPES, pipeline_display_name
from ..core.access_field_types import (
    ACCESS_FIELD_TYPES, normalize_access_type,
    type_needs_size, type_needs_decimals,
    default_size_for_type, default_decimals_for_type,
    parse_decimal_places,
)
from .popup_combo_delegate import (
    PopupComboDelegate, enable_click_edit, set_choice_item,
)
from .table_reorder import add_row_reorder_buttons, install_row_reorder


class MdbFieldTable(QTableWidget):
    """MDB 字段表：字段名 / MDB类型 / MDB大小 / 小数位数。"""

    HEADERS = ["字段名", "MDB类型", "MDB大小", "小数位数"]
    TYPE_COL = 1
    SIZE_COL = 2
    DEC_COL = 3

    def __init__(self, parent=None):
        super().__init__(0, 4, parent)
        self._loading = False
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.horizontalHeader().setStretchLastSection(True)
        size_header = self.horizontalHeaderItem(self.SIZE_COL)
        if size_header is not None:
            size_header.setToolTip("文本字段的字符长度")
        dec_header = self.horizontalHeaderItem(self.DEC_COL)
        if dec_header is not None:
            dec_header.setToolTip("单精度/双精度写出时保留的小数位数")
        enable_click_edit(self)
        self._type_delegate = PopupComboDelegate(
            self,
            choices=[(item, item) for item in ACCESS_FIELD_TYPES],
        )
        self.setItemDelegateForColumn(self.TYPE_COL, self._type_delegate)
        self.cellClicked.connect(self._on_cell_clicked)
        self.itemChanged.connect(self._on_item_changed)
        install_row_reorder(self)

    def _on_cell_clicked(self, row, column):
        if column not in (self.TYPE_COL, self.SIZE_COL, self.DEC_COL):
            return
        item = self.item(row, column)
        if item is None:
            return
        if not (item.flags() & Qt.ItemIsEditable):
            return
        self.editItem(item)

    def _on_item_changed(self, item):
        if self._loading or item is None or item.column() != self.TYPE_COL:
            return
        self._apply_type_columns(item.row(), item.text(), keep_existing=True)

    def load_fields(self, fields):
        self._loading = True
        self.blockSignals(True)
        try:
            self.setRowCount(0)
            for item in fields or []:
                self._append_row(
                    item.get("name", ""),
                    item.get("mdb_type", "TEXT"),
                    item.get("mdb_size", "50"),
                    item.get("decimal_places", ""),
                )
        finally:
            self.blockSignals(False)
            self._loading = False

    def _append_row(self, name="", mdb_type="TEXT", mdb_size="50", decimal_places=""):
        row = self.rowCount()
        self.insertRow(row)
        self.setItem(row, 0, QTableWidgetItem(name))
        normalized = normalize_access_type(mdb_type)
        set_choice_item(self, row, self.TYPE_COL, normalized, normalized)
        self._apply_type_columns(
            row, normalized, mdb_size, decimal_places, keep_existing=False
        )

    def _plain_size_text(self, row):
        text = self._cell_text(row, self.SIZE_COL)
        return "" if text == "-" else text

    def _plain_dec_text(self, row):
        text = self._cell_text(row, self.DEC_COL)
        return "" if text == "-" else text

    def _locked_item(self, tooltip):
        item = QTableWidgetItem("-")
        item.setFlags(Qt.ItemIsSelectable)
        item.setForeground(QColor(140, 140, 140))
        item.setBackground(QColor(232, 232, 232))
        item.setToolTip(tooltip)
        return item

    def _editable_item(self, value, tooltip=""):
        item = QTableWidgetItem(value)
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
        item.setData(Qt.ForegroundRole, None)
        item.setData(Qt.BackgroundRole, None)
        item.setToolTip(tooltip)
        return item

    def _apply_type_columns(self, row, mdb_type, mdb_size="", decimal_places="",
                            keep_existing=False):
        normalized = normalize_access_type(mdb_type)
        existing_size = self._plain_size_text(row) if keep_existing else ""
        existing_dec = self._plain_dec_text(row) if keep_existing else ""
        if type_needs_size(normalized):
            size_value = (mdb_size or existing_size or default_size_for_type(normalized)).strip()
            size_item = self._editable_item(
                size_value or default_size_for_type(normalized),
                "文本字段的字符长度",
            )
        else:
            size_item = self._locked_item("该 Access 字段类型无需设置字段大小")
        if type_needs_decimals(normalized):
            dec_raw = decimal_places if decimal_places not in (None, "") else existing_dec
            dec_value = str(parse_decimal_places(dec_raw))
            dec_item = self._editable_item(dec_value, "单精度/双精度写出时保留的小数位数")
        else:
            dec_item = self._locked_item("仅单精度、双精度需要设置小数位数")
        self.blockSignals(True)
        try:
            self.setItem(row, self.SIZE_COL, size_item)
            self.setItem(row, self.DEC_COL, dec_item)
        finally:
            self.blockSignals(False)

    def add_row(self):
        self._append_row()

    def snapshot_rows(self):
        rows = []
        for row in range(self.rowCount()):
            rows.append(self._row_payload(row, require_name=False))
        return [item for item in rows if item is not None]

    def restore_rows(self, rows):
        self.load_fields(rows)

    def remove_selected(self):
        rows = sorted({idx.row() for idx in self.selectedIndexes()}, reverse=True)
        for r in rows:
            self.removeRow(r)

    def _cell_text(self, row, col):
        item = self.item(row, col)
        return item.text().strip() if item else ""

    def _row_payload(self, row, require_name=True):
        name = self._cell_text(row, 0)
        if require_name and not name:
            return None
        mdb_type = normalize_access_type(self._cell_text(row, self.TYPE_COL) or "TEXT")
        mdb_size = self._plain_size_text(row)
        decimal_places = self._plain_dec_text(row)
        if not type_needs_size(mdb_type):
            mdb_size = ""
        elif not mdb_size:
            mdb_size = default_size_for_type(mdb_type)
        if not type_needs_decimals(mdb_type):
            decimal_places = ""
        elif decimal_places == "":
            decimal_places = default_decimals_for_type(mdb_type)
        else:
            decimal_places = str(parse_decimal_places(decimal_places))
        return {
            "name": name,
            "mdb_type": mdb_type,
            "mdb_size": mdb_size,
            "decimal_places": decimal_places,
        }

    def to_fields(self):
        fields = []
        for row in range(self.rowCount()):
            item = self._row_payload(row, require_name=True)
            if item:
                fields.append(item)
        return fields


class _StructureTabPage(QWidget):
    """单个 MDB 库结构配置页。"""

    def __init__(self, structure, parent=None):
        super().__init__(parent)
        self._structure = copy.deepcopy(structure)
        self._current_pipe = None
        self._loading = False

        layout = QVBoxLayout(self)

        form_box = QGroupBox("结构属性")
        form = QFormLayout()
        self.template_combo = QComboBox()
        for code in PIPELINE_TYPES:
            self.template_combo.addItem(code)
        idx = self.template_combo.findText(self._structure.get("template_pipe") or "JS")
        self.template_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.template_combo.currentTextChanged.connect(self._on_template_changed)
        self.independent_edit = QLineEdit()
        self.independent_edit.setPlaceholderText("逗号分隔，如 ZH,FZ")
        independent = self._structure.get("independent_pipes") or []
        self.independent_edit.setText(",".join(independent))
        self.independent_edit.textChanged.connect(lambda _t: self._update_pipe_list_labels())
        self.independent_edit.editingFinished.connect(self._on_independent_changed)
        form.addRow("模板管类：", self.template_combo)
        form.addRow("独立管类：", self.independent_edit)
        tip = QLabel("非独立管类的点/线字段跟随模板管类，保存时自动同步；表名仍按各管类单独保存。")
        tip.setWordWrap(True)
        form.addRow(tip)
        form_box.setLayout(form)
        layout.addWidget(form_box)

        body = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("管线种类"))
        self.pipe_list = QListWidget()
        for code in PIPELINE_TYPES:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, code)
            self.pipe_list.addItem(item)
        self.pipe_list.currentItemChanged.connect(self._on_pipe_selected)
        left.addWidget(self.pipe_list)
        body.addLayout(left, 1)

        right = QVBoxLayout()
        table_form = QFormLayout()
        self.point_table_edit = QLineEdit()
        self.line_table_edit = QLineEdit()
        table_form.addRow("点表名：", self.point_table_edit)
        table_form.addRow("线表名：", self.line_table_edit)
        table_box = QGroupBox("MDB 表绑定")
        table_box.setLayout(table_form)
        right.addWidget(table_box)

        self.point_fields_table = MdbFieldTable()
        self.line_fields_table = MdbFieldTable()

        field_tabs = QTabWidget()
        point_tab = QWidget()
        point_layout = QVBoxLayout(point_tab)
        point_layout.addWidget(self.point_fields_table)
        point_btns = QHBoxLayout()
        p_add = QPushButton("添加")
        p_add.clicked.connect(self.point_fields_table.add_row)
        p_del = QPushButton("删除选中")
        p_del.clicked.connect(self.point_fields_table.remove_selected)
        point_btns.addWidget(p_add)
        point_btns.addWidget(p_del)
        add_row_reorder_buttons(self, point_btns, self.point_fields_table)
        point_btns.addStretch()
        point_layout.addLayout(point_btns)
        field_tabs.addTab(point_tab, "点表字段")

        line_tab = QWidget()
        line_layout = QVBoxLayout(line_tab)
        line_layout.addWidget(self.line_fields_table)
        line_btns = QHBoxLayout()
        l_add = QPushButton("添加")
        l_add.clicked.connect(self.line_fields_table.add_row)
        l_del = QPushButton("删除选中")
        l_del.clicked.connect(self.line_fields_table.remove_selected)
        line_btns.addWidget(l_add)
        line_btns.addWidget(l_del)
        add_row_reorder_buttons(self, line_btns, self.line_fields_table)
        line_btns.addStretch()
        line_layout.addLayout(line_btns)
        field_tabs.addTab(line_tab, "线表字段")
        self.field_tabs = field_tabs

        right.addWidget(field_tabs)
        body.addLayout(right, 3)
        layout.addLayout(body)

        self._update_pipe_list_labels()
        if self.pipe_list.count() > 0:
            self.pipe_list.setCurrentRow(0)

    def _template_code(self):
        return (self.template_combo.currentText() or "JS").strip() or "JS"

    def _independent_codes(self):
        return {
            x.strip().upper()
            for x in self.independent_edit.text().split(",")
            if x.strip()
        }

    def _is_follower(self, code):
        if not code:
            return False
        if code == self._template_code():
            return False
        return code.upper() not in self._independent_codes()

    def _update_pipe_list_labels(self):
        template = self._template_code()
        independent = self._independent_codes()
        for i, code in enumerate(PIPELINE_TYPES):
            item = self.pipe_list.item(i)
            if item is None:
                continue
            text = pipeline_display_name(code)
            if code == template:
                text += " [模板]"
            elif code.upper() in independent:
                text += " [独立]"
            item.setText(text)
            item.setData(Qt.UserRole, code)

    def _on_template_changed(self, _text):
        if self._loading:
            return
        if self._current_pipe:
            self._flush_pipe(self._current_pipe)
        self._update_pipe_list_labels()
        if self._current_pipe:
            self._load_pipe(self._current_pipe)

    def _on_independent_changed(self):
        if self._loading:
            return
        self._update_pipe_list_labels()
        if self._current_pipe:
            self._load_pipe(self._current_pipe)

    def _on_pipe_selected(self, current, previous):
        if previous is not None and not self._loading:
            prev_code = previous.data(Qt.UserRole) or self._pipe_code_from_item(previous)
            self._flush_pipe(prev_code)
        if current is None:
            self._current_pipe = None
            return
        code = current.data(Qt.UserRole) or self._pipe_code_from_item(current)
        self._current_pipe = code
        self._load_pipe(code)

    @staticmethod
    def _pipe_code_from_item(item):
        role = item.data(Qt.UserRole) if item is not None else None
        if role:
            return role
        text = item.text() if item is not None else ""
        for code in PIPELINE_TYPES:
            if text.endswith(code) or (")%s" % code) in text or text.startswith(code):
                return code
        return (text.split(" ", 1)[0] if text else "").strip()

    def _load_pipe(self, code):
        self._loading = True
        pipes = self._structure.get("pipes") or {}
        pipe = pipes.get(code) or {}
        field_source = pipe
        if self._is_follower(code):
            field_source = pipes.get(self._template_code()) or pipe
        self.point_table_edit.setText(pipe.get("point_table") or f"{code}POINT")
        self.line_table_edit.setText(pipe.get("line_table") or f"{code}LINE")
        self.point_fields_table.load_fields(field_source.get("point_fields") or [])
        self.line_fields_table.load_fields(field_source.get("line_fields") or [])
        self.field_tabs.setEnabled(not self._is_follower(code))
        self._loading = False

    def _flush_pipe(self, code):
        if not code:
            return
        if "pipes" not in self._structure:
            self._structure["pipes"] = {}
        existing = (self._structure.get("pipes") or {}).get(code) or {}
        if self._is_follower(code):
            point_fields = copy.deepcopy(existing.get("point_fields") or [])
            line_fields = copy.deepcopy(existing.get("line_fields") or [])
        else:
            point_fields = self.point_fields_table.to_fields()
            line_fields = self.line_fields_table.to_fields()
        self._structure["pipes"][code] = {
            "point_table": self.point_table_edit.text().strip(),
            "line_table": self.line_table_edit.text().strip(),
            "point_fields": point_fields,
            "line_fields": line_fields,
        }

    def flush_current_pipe(self):
        if self._current_pipe:
            self._flush_pipe(self._current_pipe)

    def to_structure(self, label):
        self.flush_current_pipe()
        independent = [
            x.strip()
            for x in self.independent_edit.text().split(",")
            if x.strip()
        ]
        self._structure["label"] = label
        self._structure["template_pipe"] = self._template_code()
        self._structure["independent_pipes"] = independent
        sync_mdb_structure_fields_from_template(self._structure)
        if self._current_pipe:
            self._load_pipe(self._current_pipe)
        return copy.deepcopy(self._structure)


class MdbStructurePanel(QWidget):
    """MDB 库结构：模板管类与各管类 MDB 表结构（不含渲染字段）。"""

    def __init__(self, shared_config, parent=None):
        super().__init__(parent)
        self.shared_config = shared_config

        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        add_btn = QPushButton("新增结构")
        add_btn.clicked.connect(self._on_add_structure)
        del_btn = QPushButton("删除当前结构")
        del_btn.clicked.connect(self._on_remove_structure)
        toolbar.addWidget(add_btn)
        toolbar.addWidget(del_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.reload_from_config()

    def reload_from_config(self):
        self.tabs.clear()
        for structure in self.shared_config.get_mdb_structures():
            page = _StructureTabPage(structure, self)
            label = structure.get("label") or structure.get("id") or "结构"
            self.tabs.addTab(page, label)

    def _on_add_structure(self):
        name, ok = QInputDialog.getText(self, "新增结构", "结构名称：")
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            QMessageBox.warning(self, "提示", "结构名称不能为空。")
            return
        try:
            self.flush_to_config()
            structure = self.shared_config.add_mdb_structure(name)
        except ValueError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        page = _StructureTabPage(structure, self)
        idx = self.tabs.addTab(page, structure.get("label") or name)
        self.tabs.setCurrentIndex(idx)

    def _on_remove_structure(self):
        if self.tabs.count() <= 1:
            QMessageBox.warning(self, "提示", "至少保留一个结构。")
            return
        idx = self.tabs.currentIndex()
        if idx < 0:
            return
        label = self.tabs.tabText(idx)
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定删除结构「{label}」？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self.tabs.removeTab(idx)
        self.flush_to_config()

    def flush_to_config(self):
        structures = []
        for i in range(self.tabs.count()):
            page = self.tabs.widget(i)
            label = self.tabs.tabText(i)
            if isinstance(page, _StructureTabPage):
                structures.append(page.to_structure(label))
        self.shared_config.set_mdb_structures(structures)
