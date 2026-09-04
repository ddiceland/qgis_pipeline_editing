# -*- coding: utf-8 -*-
"""MDB 库渲染字段结构组配置面板。"""

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QPushButton, QTabWidget, QInputDialog, QMessageBox,
)


class _GroupFieldsForm(QWidget):
    """单个结构组的点/线渲染字段表单。"""

    def __init__(self, group, parent=None):
        super().__init__(parent)
        self.group_id = group.get("id") or ""
        layout = QVBoxLayout(self)

        tip = QLabel(
            "填写该结构 MDB 点/线表中用于图形渲染的字段名，以及点表/线表命名规则。"
            "仅用于「MDB数据库 → 加载」显示，与入库/导出用的「MDB库结构」相互独立。"
            "表命名中用 {code} 表示管类，例如 {code}POINT、{code}_POINT。"
            "「管线类型」可留空：留空时按表名识别管类；填写则仅用于合并图层分类着色，不会写回 MDB。"
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)

        cols = QHBoxLayout()
        point_form = QFormLayout()
        self.point_table_pattern = QLineEdit()
        self.point_table_pattern.setPlaceholderText("{code}POINT")
        self.point_pk = QLineEdit()
        self.point_x = QLineEdit()
        self.point_y = QLineEdit()
        self.point_type = QLineEdit()
        point_form.addRow("表命名：", self.point_table_pattern)
        point_form.addRow("井编号：", self.point_pk)
        point_form.addRow("X坐标：", self.point_x)
        point_form.addRow("Y坐标：", self.point_y)
        point_form.addRow("管线类型 (可选)：", self.point_type)
        point_wrap = QGroupBox("管点")
        point_wrap.setLayout(point_form)
        cols.addWidget(point_wrap)

        line_form = QFormLayout()
        self.line_table_pattern = QLineEdit()
        self.line_table_pattern.setPlaceholderText("{code}LINE")
        self.line_start = QLineEdit()
        self.line_end = QLineEdit()
        self.line_type = QLineEdit()
        line_form.addRow("表命名：", self.line_table_pattern)
        line_form.addRow("起点井编号：", self.line_start)
        line_form.addRow("终点井编号：", self.line_end)
        line_form.addRow("管线类型 (可选)：", self.line_type)
        line_wrap = QGroupBox("管线")
        line_wrap.setLayout(line_form)
        cols.addWidget(line_wrap)
        layout.addLayout(cols)

        layout.addStretch()
        self.load_group(group)

    def _default_patterns(self):
        if self.group_id == "xian":
            return "{code}_POINT", "{code}_LINE"
        return "{code}POINT", "{code}LINE"

    def load_group(self, group):
        self.group_id = group.get("id") or self.group_id
        point = group.get("point") or {}
        line = group.get("line") or {}
        point_pat, line_pat = self._default_patterns()
        self.point_table_pattern.setText(point.get("table_pattern") or point_pat)
        self.point_pk.setText(point.get("pk_field") or "")
        self.point_x.setText(point.get("x_field") or "")
        self.point_y.setText(point.get("y_field") or "")
        self.point_type.setText(point.get("type_field") or "")
        self.line_table_pattern.setText(line.get("table_pattern") or line_pat)
        self.line_start.setText(line.get("start_field") or "")
        self.line_end.setText(line.get("end_field") or "")
        self.line_type.setText(line.get("type_field") or "")

    def to_group(self, label):
        point_pat, line_pat = self._default_patterns()
        return {
            "id": self.group_id,
            "label": label,
            "point": {
                "table_pattern": self.point_table_pattern.text().strip() or point_pat,
                "pk_field": self.point_pk.text().strip(),
                "x_field": self.point_x.text().strip(),
                "y_field": self.point_y.text().strip(),
                "type_field": self.point_type.text().strip(),
            },
            "line": {
                "table_pattern": self.line_table_pattern.text().strip() or line_pat,
                "start_field": self.line_start.text().strip(),
                "end_field": self.line_end.text().strip(),
                "type_field": self.line_type.text().strip(),
            },
        }


class MdbRenderConfigPanel(QWidget):
    """MDB库渲染：多结构组字段配置。"""

    def __init__(self, shared_config, parent=None):
        super().__init__(parent)
        self.shared_config = shared_config
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        add_btn = QPushButton("新增结构组")
        add_btn.clicked.connect(self._on_add_group)
        del_btn = QPushButton("删除当前组")
        del_btn.clicked.connect(self._on_remove_group)
        toolbar.addWidget(add_btn)
        toolbar.addWidget(del_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.reload_from_config()

    def reload_from_config(self):
        self.tabs.clear()
        for group in self.shared_config.get_mdb_render_groups():
            form = _GroupFieldsForm(group, self)
            self.tabs.addTab(form, group.get("label") or group.get("id") or "结构组")

    def _on_add_group(self):
        name, ok = QInputDialog.getText(self, "新增结构组", "结构组名称：")
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            QMessageBox.warning(self, "提示", "结构组名称不能为空。")
            return
        try:
            # 先把当前表单写回，再新增
            self.flush_to_config()
            group = self.shared_config.add_mdb_render_group(name)
        except ValueError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        form = _GroupFieldsForm(group, self)
        idx = self.tabs.addTab(form, group.get("label") or name)
        self.tabs.setCurrentIndex(idx)

    def _on_remove_group(self):
        if self.tabs.count() <= 1:
            QMessageBox.warning(self, "提示", "至少保留一个结构组。")
            return
        idx = self.tabs.currentIndex()
        if idx < 0:
            return
        label = self.tabs.tabText(idx)
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定删除结构组「{label}」？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self.tabs.removeTab(idx)

    def flush_to_config(self):
        groups = []
        for i in range(self.tabs.count()):
            form = self.tabs.widget(i)
            label = self.tabs.tabText(i)
            if isinstance(form, _GroupFieldsForm):
                groups.append(form.to_group(label))
        self.shared_config.set_mdb_render_groups(groups)
