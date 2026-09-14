# -*- coding: utf-8 -*-
"""规则集配置：材质、埋设方式、角度换算、顺序号、时间及其他转换规则。"""

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton,
    QTabWidget, QInputDialog, QMessageBox, QSpinBox, QLineEdit,
    QRadioButton, QButtonGroup,
)

from ..core.attribute_mappings import BUILTIN_RULE_IDS
from ..core.well_number import preview_wellno, wellno_format_options
from .shared_config_panels import AttributeMappingTable
from .table_reorder import add_row_reorder_buttons


class _LookupRulePage(QWidget):
    def __init__(self, rule_set, parent=None):
        super().__init__(parent)
        self.rule_id = rule_set.get("id") or ""
        self.kind = rule_set.get("kind") or "lookup"
        self.name_header = rule_set.get("name_header") or "中文名称"
        self.targets = list(rule_set.get("targets") or [])
        layout = QVBoxLayout(self)
        self.table = AttributeMappingTable(self.name_header, self)
        layout.addWidget(self.table)
        btns = QHBoxLayout()
        add_btn = QPushButton("添加行")
        add_btn.clicked.connect(self.table.add_row)
        del_btn = QPushButton("删除选中行")
        del_btn.clicked.connect(self.table.remove_selected)
        btns.addWidget(add_btn)
        btns.addWidget(del_btn)
        add_row_reorder_buttons(self, btns, self.table)
        btns.addStretch()
        layout.addLayout(btns)
        self.table.load_mapping(rule_set.get("rows") or [])

    def to_rule_set(self, label):
        return {
            "id": self.rule_id,
            "label": label,
            "kind": self.kind or "lookup",
            "name_header": self.name_header,
            "targets": self.targets,
            "rows": self.table.to_mapping(),
        }


class _AngleRulePage(QWidget):
    def __init__(self, rule_set, parent=None):
        super().__init__(parent)
        self.rule_id = rule_set.get("id") or "angle"
        self.targets = list(rule_set.get("targets") or [])
        layout = QVBoxLayout(self)
        tip = QLabel(
            "角度换算是公式规则，不需要对照表。\n"
            "在结构映射中选择本规则后：\n"
            "· 转换目标选「弧度制」：把源值按角度制转为弧度（×π/180）\n"
            "· 转换目标选「角度制」：把源值按弧度制转为角度（×180/π）\n"
            "例如正元「符号旋转角」入库/转到西安 ROTANG 时选弧度制。"
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)

        form = QFormLayout()
        self.decimals = QSpinBox()
        self.decimals.setRange(0, 12)
        try:
            places = int(rule_set.get("decimal_places"))
        except (TypeError, ValueError):
            places = 6
        self.decimals.setValue(places)
        form.addRow("结果保留小数位：", self.decimals)
        layout.addLayout(form)
        layout.addStretch()

    def to_rule_set(self, label):
        return {
            "id": self.rule_id,
            "label": label,
            "kind": "angle",
            "name_header": "",
            "targets": self.targets,
            "decimal_places": self.decimals.value(),
            "rows": [],
        }


class _SequenceRulePage(QWidget):
    def __init__(self, rule_set, parent=None):
        super().__init__(parent)
        self.rule_id = rule_set.get("id") or "sequence"
        self.targets = list(rule_set.get("targets") or [])
        layout = QVBoxLayout(self)
        tip = QLabel(
            "顺序号是公式规则，不需要对照表。\n"
            "在结构映射中为目标字段选择本规则（源字段可留空），"
            "转换时按当前表内行顺序从起始值起依次编号：1、2、3…\n"
            "适合给正元 ID 这类需要默认整数编号的字段赋值。"
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)

        form = QFormLayout()
        self.start_from = QSpinBox()
        self.start_from.setRange(1, 999999999)
        try:
            start = int(rule_set.get("start_from"))
        except (TypeError, ValueError):
            start = 1
        self.start_from.setValue(start if start >= 1 else 1)
        form.addRow("起始编号：", self.start_from)
        layout.addLayout(form)
        layout.addStretch()

    def to_rule_set(self, label):
        return {
            "id": self.rule_id,
            "label": label,
            "kind": "sequence",
            "name_header": "",
            "targets": self.targets,
            "start_from": self.start_from.value(),
            "rows": [],
        }


class _WellNoRulePage(QWidget):
    def __init__(self, rule_set, parent=None):
        super().__init__(parent)
        self.rule_id = rule_set.get("id") or "wellno"
        self.targets = list(rule_set.get("targets") or [])
        fmt = wellno_format_options(rule_set)
        layout = QVBoxLayout(self)
        tip = QLabel(
            "井编号用于入库时续编井号。格式可按项目/单位自行调整，"
            "默认示例：管类(2位) + 顺序数字号(10位)，如 JS0000000042。\n"
            "顺序号从「数据库连接」中「管线最大井编号」视图表（字段 ptype、max_expno）已有最大值继续编，并自动补零。\n"
            "在「结构映射 → 导入映射」中：\n"
            "· 管点 expno 选「重编井号」：按视图表续编新井号；\n"
            "· 管点 offset 选「对照更新」：按 expno 重编前的旧号找到新号后写回；\n"
            "· 管段 spoint / epoint / expno 选「对照更新」：同样按管点旧井号对照更新。\n"
            "字段未选择本规则时，按原始井编号导入。"
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)

        form = QFormLayout()
        self.type_width = QSpinBox()
        self.type_width.setRange(0, 8)
        self.type_width.setValue(fmt["type_width"])
        self.type_width.setToolTip("0 表示编号中不含管类代码")
        form.addRow("管类位数：", self.type_width)

        self.seq_width = QSpinBox()
        self.seq_width.setRange(1, 18)
        self.seq_width.setValue(fmt["seq_width"])
        form.addRow("顺序号位数：", self.seq_width)

        self.separator = QLineEdit()
        self.separator.setText(fmt["separator"])
        self.separator.setPlaceholderText("可选，例如 -")
        self.separator.setMaxLength(8)
        form.addRow("分隔符：", self.separator)

        pos_wrap = QWidget()
        pos_row = QHBoxLayout(pos_wrap)
        pos_row.setContentsMargins(0, 0, 0, 0)
        self.ptype_prefix = QRadioButton("在前")
        self.ptype_suffix = QRadioButton("在后")
        self.ptype_pos_group = QButtonGroup(self)
        self.ptype_pos_group.setExclusive(True)
        self.ptype_pos_group.addButton(self.ptype_prefix)
        self.ptype_pos_group.addButton(self.ptype_suffix)
        if fmt["ptype_position"] == "suffix":
            self.ptype_suffix.setChecked(True)
        else:
            self.ptype_prefix.setChecked(True)
        pos_row.addWidget(self.ptype_prefix)
        pos_row.addWidget(self.ptype_suffix)
        pos_row.addStretch()
        form.addRow("管类位置：", pos_wrap)

        self.prefix = QLineEdit()
        self.prefix.setText(fmt["prefix"])
        self.prefix.setPlaceholderText("可选")
        self.prefix.setMaxLength(16)
        form.addRow("固定前缀：", self.prefix)

        self.suffix = QLineEdit()
        self.suffix.setText(fmt["suffix"])
        self.suffix.setPlaceholderText("可选")
        self.suffix.setMaxLength(16)
        form.addRow("固定后缀：", self.suffix)

        self.preview = QLabel()
        form.addRow("示例：", self.preview)
        layout.addLayout(form)

        for widget in (
            self.type_width, self.seq_width, self.separator,
            self.prefix, self.suffix,
        ):
            if hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(self._refresh_preview)
            else:
                widget.textChanged.connect(self._refresh_preview)
        self.ptype_prefix.toggled.connect(self._refresh_preview)
        self._refresh_preview()
        layout.addStretch()

    def _current_format(self):
        return {
            "type_width": self.type_width.value(),
            "seq_width": self.seq_width.value(),
            "separator": self.separator.text(),
            "ptype_position": "suffix" if self.ptype_suffix.isChecked() else "prefix",
            "prefix": self.prefix.text(),
            "suffix": self.suffix.text(),
        }

    def _refresh_preview(self, *_args):
        sample = preview_wellno(self._current_format(), pipe_code="JS", seq=42)
        self.preview.setText(sample)

    def to_rule_set(self, label):
        fmt = wellno_format_options(self._current_format())
        return {
            "id": self.rule_id,
            "label": label,
            "kind": "wellno",
            "name_header": "",
            "targets": self.targets,
            "type_width": fmt["type_width"],
            "seq_width": fmt["seq_width"],
            "separator": fmt["separator"],
            "ptype_position": fmt["ptype_position"],
            "prefix": fmt["prefix"],
            "suffix": fmt["suffix"],
            "rows": [],
        }


class _DateRulePage(QWidget):
    def __init__(self, rule_set, parent=None):
        super().__init__(parent)
        self.rule_id = rule_set.get("id") or "date"
        self.targets = list(rule_set.get("targets") or [])
        layout = QVBoxLayout(self)
        tip = QLabel(
            "时间是公式规则，不需要对照表。\n"
            "在结构映射中选择本规则后：\n"
            "· 转换目标选「带分隔日期 2026-08-22」：把源值写成带横线的日期\n"
            "· 转换目标选「紧凑日期 20260822」：把源值写成八位数字\n"
            "源值可以是文本（2026-08-22 / 20260822）或日期类型；"
            "写出后的字段类型按目标「MDB库结构」走："
            "配置为日期则写入日期，配置为文本则写入对应格式的字符串。"
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)
        layout.addStretch()

    def to_rule_set(self, label):
        return {
            "id": self.rule_id,
            "label": label,
            "kind": "date",
            "name_header": "",
            "targets": self.targets,
            "rows": [],
        }


class _XyzRulePage(QWidget):
    def __init__(self, rule_set, parent=None):
        super().__init__(parent)
        self.rule_id = rule_set.get("id") or "xyz"
        self.targets = list(rule_set.get("targets") or [])
        layout = QVBoxLayout(self)
        tip = QLabel(
            "坐标规则用于生成管点、管线的三维 geom（带 Z 高程）。\n"
            "在「结构映射 → 导入映射」的点表中增加三行，MDB 源字段分别填 X、Y、高程字段，"
            "PG 字段可填 geom（或留空），转换规则集选「坐标」，转换目标分别选 X / Y / Z。\n"
            "管线 geom 的起终点 Z 取对应管点的 Z。未配置 Z 时按 0 写入，"
            "避免目标库 geom 为三维时出现 “Column has Z dimension but geometry does not”。"
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)
        layout.addStretch()

    def to_rule_set(self, label):
        return {
            "id": self.rule_id,
            "label": label,
            "kind": "xyz",
            "name_header": "",
            "targets": self.targets,
            "rows": [],
        }


def _make_rule_page(rule_set, parent=None):
    kind = rule_set.get("kind") or ""
    rid = rule_set.get("id") or ""
    if kind == "angle" or rid == "angle":
        return _AngleRulePage(rule_set, parent)
    if kind == "sequence" or rid == "sequence":
        return _SequenceRulePage(rule_set, parent)
    if kind == "wellno" or rid == "wellno":
        return _WellNoRulePage(rule_set, parent)
    if kind == "xyz" or rid == "xyz":
        return _XyzRulePage(rule_set, parent)
    if kind == "date" or rid == "date":
        return _DateRulePage(rule_set, parent)
    return _LookupRulePage(rule_set, parent)


class RuleSetsPanel(QWidget):
    """统一管理转换规则集。"""

    def __init__(self, shared_config, parent=None):
        super().__init__(parent)
        self.shared_config = shared_config
        layout = QVBoxLayout(self)
        tip = QLabel(
            "规则集用于结构映射中的字段值转换。"
            "对照类规则（材质、埋设方式）先选规则集再选「中文名称」或「代码」；"
            "角度换算再选「弧度制」或「角度制」；"
            "时间规则再选「带分隔日期」或「紧凑日期」（写出类型跟目标库结构走）；"
            "顺序号用于给目标字段生成从 1 起的整数编号；"
            "井编号用于入库时按视图表续编井号（未选则按原号导入）；"
            "坐标用于在映射中指定 X / Y / Z 字段，生成带高程的 geom。"
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)

        toolbar = QHBoxLayout()
        add_btn = QPushButton("新增规则集")
        add_btn.clicked.connect(self._on_add)
        del_btn = QPushButton("删除当前规则集")
        del_btn.clicked.connect(self._on_remove)
        toolbar.addWidget(add_btn)
        toolbar.addWidget(del_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.reload_from_config()

    def reload_from_config(self):
        self.tabs.clear()
        for item in self.shared_config.get_rule_sets():
            page = _make_rule_page(item, self)
            self.tabs.addTab(page, item.get("label") or item.get("id") or "规则集")

    def _on_add(self):
        name, ok = QInputDialog.getText(self, "新增规则集", "规则集名称：")
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            QMessageBox.warning(self, "提示", "规则集名称不能为空。")
            return
        try:
            self.flush_to_config()
            item = self.shared_config.add_rule_set(name)
        except ValueError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        page = _make_rule_page(item, self)
        idx = self.tabs.addTab(page, item.get("label") or name)
        self.tabs.setCurrentIndex(idx)

    def _on_remove(self):
        if self.tabs.count() <= 1:
            QMessageBox.warning(self, "提示", "至少保留一个规则集。")
            return
        idx = self.tabs.currentIndex()
        if idx < 0:
            return
        page = self.tabs.widget(idx)
        rule_id = getattr(page, "rule_id", "") or ""
        if rule_id in BUILTIN_RULE_IDS:
            QMessageBox.warning(self, "提示", "内置规则集不能删除。")
            return
        label = self.tabs.tabText(idx)
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定删除规则集「{label}」？\n"
            "结构映射里若已引用该规则，转换时将不再生效。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self.tabs.removeTab(idx)

    def flush_to_config(self):
        items = []
        for i in range(self.tabs.count()):
            page = self.tabs.widget(i)
            label = self.tabs.tabText(i)
            if hasattr(page, "to_rule_set"):
                items.append(page.to_rule_set(label))
        self.shared_config.set_rule_sets(items)
