# -*- coding: utf-8 -*-
"""结构映射配置面板：导出 / 导入 / 结构转换。"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QPushButton, QTabWidget, QComboBox,
    QTableWidget, QTableWidgetItem, QMessageBox,
)

from ..core.config_schema import (
    empty_structure_mapping_block,
    mapping_block_has_rows,
    reverse_convert_mapping_block,
)
from ..core.sql_ident import ident_name
from .popup_combo_delegate import (
    PopupComboDelegate, enable_click_edit, set_choice_item, choice_item_data,
)
from .table_reorder import add_row_reorder_buttons, install_row_reorder


class _RuleComboHelper:
    """转换规则集 / 目标下拉框辅助（不参与 QWidget 多继承）。"""

    def __init__(self, shared_config):
        self.shared_config = shared_config

    def targets_for_rule_set(self, rule_set_id):
        for rs in self.shared_config.conversion_rule_sets():
            if rs.get("id") == rule_set_id:
                return rs.get("targets") or []
        return []

    def rule_set_choices(self):
        choices = [("", "")]
        for rs in self.shared_config.conversion_rule_sets():
            choices.append((rs.get("label") or rs.get("id") or "", rs.get("id") or ""))
        return choices

    def target_choices(self, rule_set_id):
        choices = [("", "")]
        for target in self.targets_for_rule_set(rule_set_id):
            choices.append(
                (target.get("label") or target.get("id") or "", target.get("id") or "")
            )
        return choices

    def label_for_rule_set(self, rule_set_id):
        if not rule_set_id:
            return ""
        for label, data in self.rule_set_choices():
            if data == rule_set_id:
                return label
        return rule_set_id

    def label_for_target(self, rule_set_id, target_id):
        if not target_id:
            return ""
        for label, data in self.target_choices(rule_set_id):
            if data == target_id:
                return label
        return target_id

    def resolve_target(self, rule_set_id, current=""):
        targets = self.targets_for_rule_set(rule_set_id)
        ids = [item.get("id") or "" for item in targets]
        if current and current in ids:
            return current
        if not current and len(targets) == 1:
            return targets[0].get("id") or ""
        return ""


def _mapping_row_payload(table, row):
    rule_set = choice_item_data(table, row, table.RULE_COL)
    rule_target = choice_item_data(table, row, table.TARGET_COL)
    src_item = table.item(row, 0)
    dst_item = table.item(row, 1)
    return {
        "src_field": ident_name(src_item.text() if src_item else ""),
        "dst_field": ident_name(dst_item.text() if dst_item else ""),
        "mdb_type": "",
        "mdb_size": "",
        "rule_set": rule_set or "",
        "rule_target": rule_target or "",
    }


def _mapping_snapshot(table):
    return [_mapping_row_payload(table, row) for row in range(table.rowCount())]


def _mapping_to_rows(table):
    rows = []
    for row in range(table.rowCount()):
        item = _mapping_row_payload(table, row)
        if not item["src_field"] and not item["dst_field"]:
            continue
        rows.append(item)
    return rows


class _MappingComboTable(QTableWidget):
    """字段映射表：规则列平时显示文字，点击后再下拉。"""

    RULE_COL = 2
    TARGET_COL = 3

    def _init_combo_columns(self):
        self._loading = False
        enable_click_edit(self)
        self._rule_delegate = PopupComboDelegate(
            self, choice_provider=lambda _index: self._rules.rule_set_choices()
        )
        self._target_delegate = PopupComboDelegate(
            self, choice_provider=self._target_choices_for_index
        )
        self.setItemDelegateForColumn(self.RULE_COL, self._rule_delegate)
        self.setItemDelegateForColumn(self.TARGET_COL, self._target_delegate)
        self.cellClicked.connect(self._on_cell_clicked)
        self.itemChanged.connect(self._on_item_changed)
        install_row_reorder(self)

    def _target_choices_for_index(self, index):
        rule_id = choice_item_data(self, index.row(), self.RULE_COL)
        return self._rules.target_choices(rule_id)

    def _on_cell_clicked(self, row, column):
        if column not in (self.RULE_COL, self.TARGET_COL):
            return
        item = self.item(row, column)
        if item is None:
            return
        if not (item.flags() & Qt.ItemIsEditable):
            return
        self.editItem(item)

    def _on_item_changed(self, item):
        if self._loading or item is None or item.column() != self.RULE_COL:
            return
        row = item.row()
        rule_id = choice_item_data(self, row, self.RULE_COL)
        current_target = choice_item_data(self, row, self.TARGET_COL)
        target_id = self._rules.resolve_target(rule_id, current_target)
        label = self._rules.label_for_target(rule_id, target_id)
        self._loading = True
        self.blockSignals(True)
        try:
            set_choice_item(self, row, self.TARGET_COL, label, target_id)
        finally:
            self.blockSignals(False)
            self._loading = False

    def load_rows(self, rows):
        self._loading = True
        self.blockSignals(True)
        try:
            self.setRowCount(0)
            for item in rows or []:
                self._append_row(
                    item.get("src_field", ""),
                    item.get("dst_field", ""),
                    item.get("rule_set", ""),
                    item.get("rule_target", ""),
                )
        finally:
            self.blockSignals(False)
            self._loading = False

    def _append_row(self, src_field="", dst_field="", rule_set="", rule_target=""):
        row = self.rowCount()
        self.insertRow(row)
        self.setItem(row, 0, QTableWidgetItem(src_field))
        self.setItem(row, 1, QTableWidgetItem(dst_field))
        rule_id = rule_set or ""
        target_id = self._rules.resolve_target(rule_id, rule_target or "")
        set_choice_item(
            self, row, self.RULE_COL,
            self._rules.label_for_rule_set(rule_id), rule_id,
        )
        set_choice_item(
            self, row, self.TARGET_COL,
            self._rules.label_for_target(rule_id, target_id), target_id,
        )

    def add_row(self):
        self._append_row()

    def remove_selected(self):
        rows = sorted({idx.row() for idx in self.selectedIndexes()}, reverse=True)
        for r in rows:
            self.removeRow(r)

    def snapshot_rows(self):
        return _mapping_snapshot(self)

    def restore_rows(self, rows):
        self.load_rows(rows)

    def to_rows(self):
        return _mapping_to_rows(self)


class _DirectionMappingTable(_MappingComboTable):
    """导出 / 导入字段映射表。"""

    def __init__(self, shared_config, direction, parent=None):
        super().__init__(0, 4, parent)
        self.shared_config = shared_config
        self._rules = _RuleComboHelper(shared_config)
        self.direction = direction
        if direction == "import":
            headers = ["MDB字段", "PG字段", "转换规则集", "转换目标"]
        else:
            headers = ["PG字段", "MDB字段", "转换规则集", "转换目标"]
        self.setHorizontalHeaderLabels(headers)
        self.horizontalHeader().setStretchLastSection(True)
        self._init_combo_columns()


class _ConvertMappingTable(_MappingComboTable):
    """结构转换字段映射表。"""

    def __init__(self, shared_config, parent=None):
        super().__init__(0, 4, parent)
        self.shared_config = shared_config
        self._rules = _RuleComboHelper(shared_config)
        self.setHorizontalHeaderLabels(["源字段", "目标字段", "转换规则集", "转换目标"])
        self.horizontalHeader().setStretchLastSection(True)
        self._init_combo_columns()


class _DirectionMappingPage(QWidget):
    """导出 / 导入映射页（统一总映射，不分管类）或结构转换映射页（按管类）。"""

    def __init__(self, shared_config, direction, parent=None):
        super().__init__(parent)
        self.shared_config = shared_config
        self.direction = direction
        self._loading = False
        self._block_key = None
        self._cached_block = None

        layout = QVBoxLayout(self)

        if direction == "convert":
            self._build_convert_header(layout)
            self._build_convert_body(layout)
            self._reload_convert_block()
        else:
            self._build_direction_header(layout)
            self._build_direction_body(layout)
            self._reload_direction_block()

    # ---- 导出 / 导入：无管类列表，直接展示点表/线表映射 ----

    def _build_direction_header(self, layout):
        header = QHBoxLayout()
        header.addWidget(QLabel("MDB 结构："))
        self.structure_combo = QComboBox()
        for sid, label in self.shared_config.list_structures():
            self.structure_combo.addItem(label, sid)
        self.structure_combo.currentIndexChanged.connect(self._on_structure_changed)
        header.addWidget(self.structure_combo, 1)

        info_box = QGroupBox("结构属性（只读）")
        info_form = QFormLayout()
        self.template_label = QLabel("-")
        self.independent_label = QLabel("-")
        info_form.addRow("模板管类：", self.template_label)
        info_form.addRow("独立管类：", self.independent_label)
        info_box.setLayout(info_form)
        layout.addLayout(header)
        layout.addWidget(info_box)

    def _build_direction_body(self, layout):
        self.point_table = _DirectionMappingTable(self.shared_config, self.direction)
        self.line_table = _DirectionMappingTable(self.shared_config, self.direction)

        tabs = QTabWidget()
        for label, table in (("点表映射", self.point_table), ("线表映射", self.line_table)):
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            tab_layout.addWidget(table)
            btns = QHBoxLayout()
            add_btn = QPushButton("添加")
            add_btn.clicked.connect(table.add_row)
            del_btn = QPushButton("删除选中")
            del_btn.clicked.connect(table.remove_selected)
            btns.addWidget(add_btn)
            btns.addWidget(del_btn)
            add_row_reorder_buttons(self, btns, table)
            tab_layout.addLayout(btns)
            tabs.addTab(tab, label)
        layout.addWidget(tabs)

    def _on_structure_changed(self, _index):
        if self._loading or self.direction == "convert":
            return
        self._reload_direction_block()

    def _reload_direction_block(self):
        structure_id = self.structure_combo.currentData()
        if not structure_id:
            self._block_key = None
            self._cached_block = None
            self._update_structure_info()
            self.point_table.setRowCount(0)
            self.line_table.setRowCount(0)
            return
        block = self.shared_config.get_mapping_block(self.direction, structure_id)
        if not block:
            mdb = self.shared_config.get_mdb_structure(structure_id)
            block = empty_structure_mapping_block(
                structure_id,
                (mdb or {}).get("template_pipe") or "JS",
                (mdb or {}).get("independent_pipes") or [],
            )
        self._block_key = structure_id
        self._cached_block = block
        self._update_structure_info(block)
        self.point_table.load_rows(block.get("point") or [])
        self.line_table.load_rows(block.get("line") or [])

    def _update_structure_info(self, block=None):
        if self.direction == "convert":
            return
        structure_id = self.structure_combo.currentData()
        mdb = self.shared_config.get_mdb_structure(structure_id) if structure_id else None
        template = (block or {}).get("template_pipe") if block else None
        independent = (block or {}).get("independent_pipes") if block else None
        if template is None and mdb:
            template = mdb.get("template_pipe")
        if independent is None and mdb:
            independent = mdb.get("independent_pipes")
        self.template_label.setText(template or "-")
        ind = independent or []
        self.independent_label.setText(",".join(ind) if ind else "-")

    def _flush_direction(self):
        if self._cached_block is None:
            return
        self._cached_block["point"] = self.point_table.to_rows()
        self._cached_block["line"] = self.line_table.to_rows()

    # ---- 结构转换：同样不分管类，统一总映射 ----

    def _build_convert_header(self, layout):
        header = QHBoxLayout()
        header.addWidget(QLabel("源结构："))
        self.source_combo = QComboBox()
        header.addWidget(self.source_combo, 1)
        header.addWidget(QLabel("目标结构："))
        self.target_combo = QComboBox()
        header.addWidget(self.target_combo, 1)
        open_btn = QPushButton("新建/打开此对映射")
        open_btn.clicked.connect(self._on_open_convert_pair)
        header.addWidget(open_btn)
        reverse_btn = QPushButton("生成反向映射")
        reverse_btn.setToolTip("根据当前方向的字段映射，自动生成对调后的反向映射。")
        reverse_btn.clicked.connect(self._on_generate_reverse)
        header.addWidget(reverse_btn)
        layout.addLayout(header)

        for sid, label in self.shared_config.list_structures():
            self.source_combo.addItem(label, sid)
            self.target_combo.addItem(label, sid)
        if self.source_combo.count() > 1:
            self.target_combo.setCurrentIndex(1)
        self.source_combo.currentIndexChanged.connect(self._on_convert_pair_changed)
        self.target_combo.currentIndexChanged.connect(self._on_convert_pair_changed)

    def _build_convert_body(self, layout):
        self.point_table = _ConvertMappingTable(self.shared_config)
        self.line_table = _ConvertMappingTable(self.shared_config)

        tabs = QTabWidget()
        for label, table in (("点表映射", self.point_table), ("线表映射", self.line_table)):
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            tab_layout.addWidget(table)
            btns = QHBoxLayout()
            add_btn = QPushButton("添加")
            add_btn.clicked.connect(table.add_row)
            del_btn = QPushButton("删除选中")
            del_btn.clicked.connect(table.remove_selected)
            btns.addWidget(add_btn)
            btns.addWidget(del_btn)
            add_row_reorder_buttons(self, btns, table)
            tab_layout.addLayout(btns)
            tabs.addTab(tab, label)
        layout.addWidget(tabs)

    def _structure_id(self):
        source_id = self.source_combo.currentData()
        target_id = self.target_combo.currentData()
        if not source_id or not target_id:
            return None
        return f"{source_id}__to__{target_id}"

    def _on_convert_pair_changed(self, _index):
        if self._loading:
            return
        self._reload_convert_block()

    def _on_open_convert_pair(self):
        key = self._structure_id()
        if not key:
            QMessageBox.warning(self, "提示", "请选择源结构与目标结构。")
            return
        block = self.shared_config.get_mapping_block("convert", key)
        if not block:
            source_id = self.source_combo.currentData()
            target_id = self.target_combo.currentData()
            block = {
                "structure_id": key,
                "source_id": source_id,
                "target_id": target_id,
                "point": [],
                "line": [],
            }
            self.shared_config.set_mapping_block("convert", key, block)
        self._block_key = key
        self._cached_block = block
        self.point_table.load_rows(block.get("point") or [])
        self.line_table.load_rows(block.get("line") or [])

    def _on_generate_reverse(self):
        source_id = self.source_combo.currentData()
        target_id = self.target_combo.currentData()
        if not source_id or not target_id or source_id == target_id:
            QMessageBox.warning(self, "提示", "请选择不同的源结构与目标结构。")
            return
        self._flush_convert()
        key = f"{source_id}__to__{target_id}"
        block = self._cached_block or self.shared_config.get_mapping_block("convert", key)
        if not mapping_block_has_rows(block):
            QMessageBox.warning(
                self, "提示",
                "当前方向还没有有效的字段映射，无法生成反向映射。"
            )
            return
        self.shared_config.set_mapping_block("convert", key, block)
        rev_key = f"{target_id}__to__{source_id}"
        rev_block = reverse_convert_mapping_block(block, target_id, source_id)
        self.shared_config.set_mapping_block("convert", rev_key, rev_block)
        source_label = self.source_combo.currentText()
        target_label = self.target_combo.currentText()
        QMessageBox.information(
            self, "生成反向映射",
            f"已根据「{source_label} → {target_label}」生成反向映射：\n"
            f"「{target_label} → {source_label}」\n"
            f"点表 {len(rev_block.get('point') or [])} 项，"
            f"线表 {len(rev_block.get('line') or [])} 项。\n"
            "请点击「保存配置」写入配置文件。"
        )

    def _reload_convert_block(self):
        key = self._structure_id()
        if not key:
            self._block_key = None
            self._cached_block = None
            self.point_table.setRowCount(0)
            self.line_table.setRowCount(0)
            return
        block = self.shared_config.get_mapping_block("convert", key)
        if block:
            self._block_key = key
            self._cached_block = block
            self.point_table.load_rows(block.get("point") or [])
            self.line_table.load_rows(block.get("line") or [])
        else:
            self._block_key = key
            self._cached_block = {
                "structure_id": key,
                "source_id": self.source_combo.currentData(),
                "target_id": self.target_combo.currentData(),
                "point": [],
                "line": [],
            }
            self.point_table.setRowCount(0)
            self.line_table.setRowCount(0)

    def _flush_convert(self):
        if self._cached_block is None:
            return
        self._cached_block["point"] = self.point_table.to_rows()
        self._cached_block["line"] = self.line_table.to_rows()

    # ---- 公共方法 ----

    def flush_to_config(self):
        if self.direction == "convert":
            self._flush_convert()
            key = self._structure_id()
            if not key:
                return
            source_id = self.source_combo.currentData()
            target_id = self.target_combo.currentData()
            block = self._cached_block or {"point": [], "line": []}
            block["structure_id"] = key
            block["source_id"] = source_id
            block["target_id"] = target_id
            self.shared_config.set_mapping_block("convert", key, block)
            return

        self._flush_direction()
        structure_id = self.structure_combo.currentData()
        if not structure_id:
            return
        mdb = self.shared_config.get_mdb_structure(structure_id)
        block = self._cached_block or empty_structure_mapping_block(structure_id)
        block["structure_id"] = structure_id
        block["template_pipe"] = (mdb or {}).get("template_pipe") or "JS"
        block["independent_pipes"] = (mdb or {}).get("independent_pipes") or []
        self.shared_config.set_mapping_block(self.direction, structure_id, block)

    def reload_from_config(self):
        self._loading = True
        if self.direction == "convert":
            self.source_combo.blockSignals(True)
            self.target_combo.blockSignals(True)
            self.source_combo.clear()
            self.target_combo.clear()
            for sid, label in self.shared_config.list_structures():
                self.source_combo.addItem(label, sid)
                self.target_combo.addItem(label, sid)
            if self.source_combo.count() > 1:
                self.target_combo.setCurrentIndex(1)
            self.source_combo.blockSignals(False)
            self.target_combo.blockSignals(False)
            self._reload_convert_block()
        else:
            current = self.structure_combo.currentData()
            self.structure_combo.blockSignals(True)
            self.structure_combo.clear()
            for sid, label in self.shared_config.list_structures():
                self.structure_combo.addItem(label, sid)
            if current:
                idx = self.structure_combo.findData(current)
                if idx >= 0:
                    self.structure_combo.setCurrentIndex(idx)
            self.structure_combo.blockSignals(False)
            self._reload_direction_block()
        self._loading = False


class StructureMappingPanel(QWidget):
    """结构映射：导出 / 导入 / 结构转换。"""

    def __init__(self, shared_config, parent=None):
        super().__init__(parent)
        self.shared_config = shared_config

        layout = QVBoxLayout(self)
        tip = QLabel(
            "写入 PostgreSQL 时，表名与字段名按配置原文加双引号（区分大小写）。"
            "读取 Access/MDB 时使用方括号；Access 驱动不能用双引号作为字段名。"
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)
        self.tabs = QTabWidget()

        self.export_page = _DirectionMappingPage(shared_config, "export", self)
        self.import_page = _DirectionMappingPage(shared_config, "import", self)
        self.convert_page = _DirectionMappingPage(shared_config, "convert", self)

        self.tabs.addTab(self.export_page, "导出映射")
        self.tabs.addTab(self.import_page, "导入映射")
        self.tabs.addTab(self.convert_page, "结构转换")
        layout.addWidget(self.tabs)

    def flush_to_config(self):
        self.export_page.flush_to_config()
        self.import_page.flush_to_config()
        self.convert_page.flush_to_config()

    def reload_from_config(self):
        self.export_page.reload_from_config()
        self.import_page.reload_from_config()
        self.convert_page.reload_from_config()
