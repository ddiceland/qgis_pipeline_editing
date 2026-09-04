# -*- coding: utf-8 -*-
"""管网编辑工具主面板。"""

from qgis.PyQt.QtCore import Qt, QSize
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QListWidget, QListWidgetItem, QTabWidget, QFrame,
    QButtonGroup, QRadioButton, QMessageBox, QFileDialog,
    QApplication, QSizePolicy, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QTextEdit,
    QScrollArea,
)
from qgis.core import QgsProject, QgsWkbTypes
from qgis.gui import QgsRubberBand

import os
from datetime import datetime

from ..core.pipe_catalog import PIPELINE_TYPES, pipeline_display_name
from ..core.pipe_type_filter import split_pipeline_selection
from ..core.pg_connection import load_connection_info
from ..core.pg_schema_loader import refresh_pg_pipe_types
from ..core.pg_connector import PgConnector
from ..core.pg_import import check_import_ready, import_mdb_to_pg
from ..core.polygon_tool import PolygonDrawTool
from ..core.export_engine import run_export
from .export_progress_dialog import ExportProgressDialog
from ..core.spatial_export import filter_pipeline_types_with_data
from ..core.gdb_writer import gdb_write_unavailable_message, writable_gdb_drivers
from ..core.mdb.structure_convert import mapping_has_field_rows
from ..core.shared_export_config import SharedExportConfig
from ..core.mdb.layer_builder import (
    MDB_LAYER_GROUP_NAME,
    list_mdb_pipe_types,
    load_mdb_layers,
)
from ..core.mdb.layer_refresh import (
    redraw_project_layers,
    sync_layers_after_save,
    update_project_session_snapshots,
)
from ..core.mdb.mdb_saver import (
    capture_project_edit_deltas,
    change_flags_from_deltas,
    save_project_session,
)
from ..core.mdb.schema_detect import MdbRenderGroupNotMatchedError
from ..core.txt_coord import (
    load_txt_coord_layer,
    parse_txt_coord_file,
    sync_segment_joints,
    write_txt_coord_file,
    _remove_txt_layers_for_path,
)
from .config_dialog import ConfigDialog


def _section_separator():
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    return line


def _titled_option_box(title):
    """标题画在边框内部；高度随选项数量收缩/增高。"""
    box = QFrame()
    box.setFrameShape(QFrame.StyledPanel)
    box.setFrameShadow(QFrame.Plain)
    box.setObjectName("titledOptionBox")
    box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    box.setStyleSheet(
        "#titledOptionBox {"
        "  border: 1px solid palette(mid);"
        "  border-radius: 3px;"
        "}"
    )
    outer = QVBoxLayout(box)
    outer.setContentsMargins(8, 6, 8, 8)
    outer.setSpacing(8)
    caption = QLabel(title)
    font = caption.font()
    font.setBold(True)
    caption.setFont(font)
    outer.addWidget(caption)
    inner = QVBoxLayout()
    inner.setContentsMargins(16, 0, 0, 0)
    inner.setSpacing(4)
    outer.addLayout(inner)
    return box, inner


def _limit_pipe_checklist_height(list_widget):
    """管类列表高度约为全部管类展开高度的 2/3。"""
    list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    row = list_widget.sizeHintForRow(0)
    if row <= 0:
        row = list_widget.fontMetrics().height() + 8
    full_h = len(PIPELINE_TYPES) * row + 2 * list_widget.frameWidth()
    list_widget.setMaximumHeight(int(full_h * 2 / 3))


def _fill_total_pipe_checklist(list_widget, available_codes, empty_reason=""):
    """总数据库列出全部目录管类；视图表中没有的灰色禁用。"""
    available = {(c or "").strip().upper() for c in (available_codes or [])}
    list_widget.clear()
    gray = QColor(160, 160, 160)
    missing_tip = "总库视图表中无此管类，已禁用"
    all_disabled_tip = (empty_reason or "").strip() or "当前无可用管类，已禁用"
    for code in PIPELINE_TYPES:
        item = QListWidgetItem(pipeline_display_name(code))
        item.setData(Qt.UserRole, code)
        if code.upper() in available:
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            item.setCheckState(Qt.Checked)
        else:
            item.setFlags(Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setForeground(gray)
            item.setToolTip(all_disabled_tip if not available else missing_tip)
        list_widget.addItem(item)


def _fill_mdb_pipe_checklist(list_widget, items):
    list_widget.clear()
    gray = QColor(160, 160, 160)
    for info in items or []:
        code = info.get("code")
        if not code:
            continue
        item = QListWidgetItem(pipeline_display_name(code))
        item.setData(Qt.UserRole, code)
        if info.get("empty"):
            item.setFlags(Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setForeground(gray)
            reason = info.get("reason") or "无数据"
            item.setToolTip("空表，已禁用：%s" % reason)
        else:
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            item.setCheckState(Qt.Checked)
            if info.get("has_point") and not info.get("has_line"):
                item.setToolTip("仅点表有数据，加载时只渲染点图层")
        list_widget.addItem(item)


def _set_checklist_state(list_widget, checked):
    state = Qt.Checked if checked else Qt.Unchecked
    for i in range(list_widget.count()):
        item = list_widget.item(i)
        if not (item.flags() & Qt.ItemIsEnabled):
            continue
        item.setCheckState(state)


def _checked_codes(list_widget):
    codes = []
    for i in range(list_widget.count()):
        item = list_widget.item(i)
        if item.checkState() == Qt.Checked:
            code = item.data(Qt.UserRole)
            codes.append(code if code else item.text())
    return codes


def _enabled_codes(list_widget):
    codes = []
    for i in range(list_widget.count()):
        item = list_widget.item(i)
        if not (item.flags() & Qt.ItemIsEnabled):
            continue
        code = item.data(Qt.UserRole)
        codes.append(code if code else item.text())
    return codes


TXT_COL_SEQ = 0
TXT_COL_START = 1
TXT_COL_END = 2
TXT_COL_X1 = 3
TXT_COL_Y1 = 4
TXT_COL_Z1 = 5
TXT_COL_X2 = 6
TXT_COL_Y2 = 7
TXT_COL_Z2 = 8
TXT_COL_DIAM = 9
TXT_COORD_COLS = (
    TXT_COL_X1, TXT_COL_Y1, TXT_COL_Z1,
    TXT_COL_X2, TXT_COL_Y2, TXT_COL_Z2,
)
TXT_JOINT_PAIRS = {
    TXT_COL_X1: TXT_COL_X2,
    TXT_COL_Y1: TXT_COL_Y2,
    TXT_COL_Z1: TXT_COL_Z2,
    TXT_COL_X2: TXT_COL_X1,
    TXT_COL_Y2: TXT_COL_Y1,
    TXT_COL_Z2: TXT_COL_Z1,
}


class PipelineEditingDock(QDockWidget):
    def __init__(self, iface, parent=None):
        super().__init__("管网编辑工具", parent)
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.shared_config = SharedExportConfig()

        # 总库：裁剪范围
        self.last_polygon_geom = None
        self.polygon_tool = None
        self.prev_map_tool = None
        self._range_band = None

        # MDB：会话
        self.mdb_path = None
        self.project_session = None
        # TXT
        self.txt_path = None
        self.txt_pipe_code = None
        self.txt_header = ""
        self.txt_encoding = "utf-8"
        self.txt_layer = None
        self.txt_swap_xy = True
        self._txt_table_loading = False

        root = QWidget()
        layout = QVBoxLayout(root)

        top_row = QHBoxLayout()
        self.config_btn = QPushButton("配置管理")
        self.config_btn.clicked.connect(self._on_config)
        top_row.addWidget(self.config_btn)
        top_row.addStretch()
        layout.addLayout(top_row)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_total_db_page(), "总数据库")
        self.tabs.addTab(self._build_mdb_page(), "MDB数据库")
        self.tabs.addTab(self._build_txt_page(), "TXT管线")
        self.tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        layout.addWidget(self.tabs, 0)

        layout.addWidget(_section_separator())
        layout.addWidget(QLabel("日志："))
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(80)
        layout.addWidget(self.log_box, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        scroll.setWidget(root)
        self._scroll_root = root
        self.setWidget(scroll)
        self._match_txt_table_to_mdb_height()
        self._sync_scroll_content_height()
        self._refresh_export_enabled()
        self._set_mdb_layer_actions_enabled(False)
        self._set_txt_actions_enabled(False)
        self._refresh_pg_pipe_types_on_startup()

    def minimumSizeHint(self):
        # 完整内容高度交给滚动区，不要据此撑高 QGIS 主窗口。
        return QSize(280, 180)

    def sizeHint(self):
        inner = getattr(self, "_scroll_root", None)
        width = 320
        if inner is not None:
            width = max(width, inner.sizeHint().width())
        height = 480
        main = self.iface.mainWindow() if getattr(self, "iface", None) else None
        if main is not None:
            central = main.centralWidget()
            if central is not None and central.height() > 80:
                height = central.height()
            else:
                height = max(180, main.height() - 120)
        return QSize(width, height)

    def _sync_scroll_content_height(self):
        """内容按完整布局占位；停靠区不够高时出现侧边滚动条。"""
        root = getattr(self, "_scroll_root", None)
        if root is None:
            return
        root.setMinimumHeight(0)
        hint_h = root.sizeHint().height()
        if hint_h > 0:
            root.setMinimumHeight(hint_h)

    def _match_txt_table_to_mdb_height(self):
        """让 TXT 页整体高度与 MDB 页一致，日志高度三个页签统一。"""
        if not hasattr(self, "txt_table") or not hasattr(self, "tabs"):
            return
        mdb_page = self.tabs.widget(1)
        txt_page = self.tabs.widget(2)
        if mdb_page is None or txt_page is None:
            return
        mdb_h = mdb_page.sizeHint().height()
        other = 0
        txt_layout = txt_page.layout()
        if txt_layout is not None:
            margins = txt_layout.contentsMargins()
            other += margins.top() + margins.bottom()
            spacing = txt_layout.spacing()
            counted = 0
            for i in range(txt_layout.count()):
                item = txt_layout.itemAt(i)
                widget = item.widget()
                if widget is self.txt_table:
                    continue
                if widget is not None:
                    other += widget.sizeHint().height()
                    counted += 1
                elif item.layout() is not None:
                    other += item.layout().sizeHint().height()
                    counted += 1
            if counted:
                other += spacing * counted
        target = mdb_h - other
        if target < 140:
            target = 140
        self.txt_table.setMinimumHeight(target)
        self.txt_table.setMaximumHeight(target)
        self.txt_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.tabs.updateGeometry()
        self._sync_scroll_content_height()

    def showEvent(self, event):
        super(PipelineEditingDock, self).showEvent(event)
        if not getattr(self, "_txt_table_height_matched", False):
            self._match_txt_table_to_mdb_height()
            self._txt_table_height_matched = True
        self._sync_scroll_content_height()

    def _log(self, msg, new_group=False):
        if getattr(self, "log_box", None) is None:
            return
        if new_group and self.log_box.toPlainText().strip():
            self.log_box.append("────────────────────────")
        stamp = datetime.now().strftime("%H:%M:%S")
        text = "" if msg is None else str(msg)
        self.log_box.append("[%s] %s" % (stamp, text))

    def _refresh_total_pipe_checklist(self):
        snap = (self.shared_config.get_pg_table_schemas() or {}).get("pipe_types") or {}
        codes = snap.get("codes") or []
        error = (snap.get("error") or "").strip()
        _fill_total_pipe_checklist(self.total_pipe_list, codes, error)
        has_usable = False
        for i in range(self.total_pipe_list.count()):
            item = self.total_pipe_list.item(i)
            if item.flags() & Qt.ItemIsEnabled:
                has_usable = True
                break
        self.total_load_btn.setEnabled(has_usable)
        self.total_select_all_btn.setEnabled(has_usable)

    def _refresh_pg_pipe_types_on_startup(self):
        snap = refresh_pg_pipe_types(self.shared_config, persist=True)
        self._refresh_total_pipe_checklist()
        codes = snap.get("codes") or []
        err = (snap.get("error") or "").strip()
        if err:
            self._log("总库管类：已全部禁用（%s）" % err, new_group=True)
        elif codes:
            self._log(
                "总库管类：已从视图表加载 %d 类（%s）"
                % (len(codes), "、".join(pipeline_display_name(c) for c in codes)),
                new_group=True,
            )
        else:
            self._log("总库管类：视图表无记录，已全部禁用", new_group=True)

    # ------------------------------------------------------------------ #
    # 总数据库
    # ------------------------------------------------------------------ #
    def _build_total_db_page(self):
        page = QWidget()
        page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignTop)

        layout.addWidget(QLabel("选择管类"))

        btn_row = QHBoxLayout()
        self.total_select_all_btn = QPushButton("全选")
        self.total_select_all_btn.clicked.connect(
            lambda: _set_checklist_state(self.total_pipe_list, True)
        )
        btn_row.addWidget(self.total_select_all_btn)

        self.total_select_none_btn = QPushButton("取消")
        self.total_select_none_btn.clicked.connect(
            lambda: _set_checklist_state(self.total_pipe_list, False)
        )
        btn_row.addWidget(self.total_select_none_btn)

        self.total_load_btn = QPushButton("加载")
        self.total_load_btn.clicked.connect(self._on_total_load)
        btn_row.addWidget(self.total_load_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.total_pipe_list = QListWidget()
        self.total_pipe_list.setSelectionMode(QListWidget.NoSelection)
        _limit_pipe_checklist_height(self.total_pipe_list)
        layout.addWidget(self.total_pipe_list)

        layout.addWidget(_section_separator())

        self.draw_clip_btn = QPushButton("绘制裁剪范围")
        self.draw_clip_btn.setToolTip(
            "左键加点，右键/双击结束，Backspace/Ctrl+Z 撤销，Esc 取消"
        )
        self.draw_clip_btn.clicked.connect(self._on_draw_clip)
        layout.addWidget(self.draw_clip_btn)

        self.clip_status_label = QLabel("裁剪范围：未绘制")
        layout.addWidget(self.clip_status_label)

        export_opts_row = QHBoxLayout()
        export_opts_row.setAlignment(Qt.AlignTop)
        export_opts_row.addWidget(
            self._build_export_structure_group(), 1, Qt.AlignTop
        )
        export_opts_row.addWidget(
            self._build_export_format_group(), 1, Qt.AlignTop
        )
        layout.addLayout(export_opts_row)
        self.export_btn = QPushButton("导出")
        self.export_btn.setEnabled(False)
        self.export_btn.setToolTip("请先选择导出结构和导出格式")
        self.export_btn.clicked.connect(self._on_export)
        layout.addWidget(self.export_btn)
        layout.setAlignment(Qt.AlignTop)
        return page

    def _build_export_structure_group(self):
        box, self.export_structure_layout = _titled_option_box("导出结构")
        self.export_structure_group = QButtonGroup(self)
        self.export_structure_group.setExclusive(True)
        self.export_structure_group.buttonClicked.connect(self._refresh_export_enabled)
        self._rebuild_export_structure_radios(refresh_enabled=False)
        return box

    def _rebuild_export_structure_radios(self, preferred_key=None, refresh_enabled=True):
        """按配置中的结构列表刷新单选框；默认正元结构，否则保留当前选中项。"""
        prev_key = preferred_key
        if prev_key is None and hasattr(self, "export_structure_group"):
            checked = self.export_structure_group.checkedButton()
            if checked is not None:
                prev_key = checked.property("structure_key")
        if not prev_key:
            prev_key = "zhengyuan"

        for btn in list(self.export_structure_group.buttons()):
            self.export_structure_group.removeButton(btn)

        while self.export_structure_layout.count():
            item = self.export_structure_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        checked_any = False
        for key, label in self.shared_config.list_structures():
            radio = QRadioButton(label)
            radio.setProperty("structure_key", key)
            self.export_structure_group.addButton(radio)
            self.export_structure_layout.addWidget(radio)
            if key == prev_key:
                radio.setChecked(True)
                checked_any = True

        if not checked_any:
            first = self.export_structure_group.buttons()
            if first:
                first[0].setChecked(True)

        if refresh_enabled and hasattr(self, "export_format_group"):
            self._refresh_export_enabled()

    def _build_export_format_group(self):
        box, box_layout = _titled_option_box("导出格式")
        self.export_format_group = QButtonGroup(self)
        self.export_format_group.setExclusive(True)
        self.export_mdb_radio = QRadioButton("MDB库")
        self.export_gdb_radio = QRadioButton("GDB库")
        self.export_mdb_radio.setChecked(True)
        self.export_format_group.addButton(self.export_mdb_radio)
        self.export_format_group.addButton(self.export_gdb_radio)
        box_layout.addWidget(self.export_mdb_radio)
        box_layout.addWidget(self.export_gdb_radio)
        self.export_format_group.buttonClicked.connect(self._refresh_export_enabled)
        return box

    def _refresh_export_enabled(self):
        structure_ok = self.export_structure_group.checkedButton() is not None
        format_ok = self.export_format_group.checkedButton() is not None
        self.export_btn.setEnabled(structure_ok and format_ok)

    def _selected_export_structure(self):
        btn = self.export_structure_group.checkedButton()
        if btn is None:
            return None
        return btn.property("structure_key")

    def _selected_export_format(self):
        if getattr(self, "export_gdb_radio", None) is not None and self.export_gdb_radio.isChecked():
            return "gdb"
        return "mdb"

    def _on_export(self):
        info, _mode = load_connection_info()
        if not (info.host or "").strip() or not (info.dbname or "").strip():
            QMessageBox.warning(
                self, "导出",
                "请先在「配置管理 → 数据库连接」中填写并保存 PostgreSQL 连接信息。",
            )
            return
        pg = self.shared_config.get_pg_config()
        if not pg["point"].get("table") or not pg["line"].get("table"):
            QMessageBox.warning(
                self, "导出",
                "请先在「配置管理 → 数据库连接」中设置管点表和管段表。",
            )
            return
        if self.last_polygon_geom is None:
            QMessageBox.warning(self, "导出", "请先绘制裁剪范围。")
            return
        pipeline_types = _checked_codes(self.total_pipe_list)
        if not pipeline_types:
            QMessageBox.warning(self, "导出", "请至少勾选一种管类。")
            return
        structure_id = self._selected_export_structure()
        if not structure_id:
            QMessageBox.warning(self, "导出", "请选择导出结构。")
            return
        mapping_block = self.shared_config.get_mapping_block("export", structure_id)
        if not mapping_has_field_rows(mapping_block):
            QMessageBox.warning(
                self, "导出",
                "未在「结构映射 → 导出映射」中配置所选结构的字段映射。",
            )
            return

        fmt = self._selected_export_format()
        if fmt == "gdb":
            if not writable_gdb_drivers():
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Warning)
                box.setWindowTitle("无法写入 FileGDB")
                box.setText(gdb_write_unavailable_message())
                box.setInformativeText(
                    "也可以改为导出 GeoPackage（.gpkg）：同样是矢量数据库，"
                    "含 OBJECTID 与图形（Shape）。"
                )
                gpkg_btn = box.addButton("改为 GeoPackage", QMessageBox.AcceptRole)
                box.addButton("取消", QMessageBox.RejectRole)
                box.exec_()
                if box.clickedButton() is not gpkg_btn:
                    return
                fmt = "gpkg"
            if fmt == "gdb":
                out_path, _flt = QFileDialog.getSaveFileName(
                    self, "导出 GDB 库", "导出结果.gdb", "File Geodatabase (*.gdb)"
                )
            else:
                out_path, _flt = QFileDialog.getSaveFileName(
                    self, "导出 GeoPackage", "导出结果.gpkg", "GeoPackage (*.gpkg)"
                )
        else:
            out_path, _flt = QFileDialog.getSaveFileName(
                self, "导出 MDB 库", "导出结果.mdb", "Access 数据库 (*.mdb)"
            )
        if not out_path:
            return
        root, ext = os.path.splitext(out_path)
        if fmt == "gdb" and ext.lower() != ".gdb":
            out_path = root + ".gdb"
        if fmt == "gpkg" and ext.lower() != ".gpkg":
            out_path = root + ".gpkg"
        if fmt == "mdb" and ext.lower() != ".mdb":
            out_path = root + ".mdb"

        self._log("开始导出：%s" % out_path, new_group=True)

        QApplication.setOverrideCursor(Qt.WaitCursor)
        result = None
        skipped = []
        empty_range = False
        error = None
        types_to_export = []
        progress_dlg = None
        cursor_overridden = True
        try:
            connector = PgConnector(info)
            types_to_export, skipped = filter_pipeline_types_with_data(
                connector,
                pg,
                pipeline_types,
                self.last_polygon_geom,
                self.canvas.mapSettings().destinationCrs(),
                log=self._log,
            )
            if not types_to_export:
                empty_range = True
            else:
                QApplication.restoreOverrideCursor()
                cursor_overridden = False
                progress_dlg = ExportProgressDialog(len(types_to_export), self)
                result = run_export(
                    pg_connector=connector,
                    shared_config=self.shared_config,
                    pipeline_types=types_to_export,
                    structure_id=structure_id,
                    export_format=fmt,
                    polygon_geometry=self.last_polygon_geom,
                    canvas_crs=self.canvas.mapSettings().destinationCrs(),
                    output_path=out_path,
                    log=self._log,
                    progress_dialog=progress_dlg,
                )
                if result is not None and not result.cancelled:
                    progress_dlg.set_finalizing()
                    progress_dlg.accept()
        except Exception as exc:
            error = exc
        finally:
            if progress_dlg is not None:
                progress_dlg.finish_and_close()
            if cursor_overridden:
                QApplication.restoreOverrideCursor()

        if error is not None:
            self._log("导出失败：%s" % error)
            QMessageBox.critical(self, "导出失败", str(error))
            return
        if empty_range or result is None:
            self._log("裁剪范围内无已勾选管类的数据，无需导出。")
            QMessageBox.information(
                self, "导出",
                "裁剪范围内无已勾选管类的数据，无需导出。",
            )
            return

        struct_btn = self.export_structure_group.checkedButton()
        struct_label = struct_btn.text() if struct_btn is not None else structure_id
        format_label = "MDB库"
        if fmt == "gdb":
            format_label = "GDB库"
        elif fmt == "gpkg":
            format_label = "GeoPackage（因当前 GDAL 无法写入 FileGDB）"
        cancelled = bool(result.cancelled)
        lines = [
            "导出已停止。" if cancelled else "导出完成。",
            "输出：%s" % out_path,
            "格式：%s" % format_label,
            "结构：%s" % struct_label,
        ]
        if cancelled:
            if result.profile_results:
                lines.append("停止前已完成的管类：")
            else:
                lines.append("停止前未完成任何管类。")
        for item in result.profile_results:
            lines.append(
                "[%s] 点 %s 条，线 %s 条"
                % (
                    pipeline_display_name(item.get("profile") or ""),
                    item.get("point_count") or 0,
                    item.get("line_count") or 0,
                )
            )
        total_points = sum((item.get("point_count") or 0) for item in result.profile_results)
        total_lines = sum((item.get("line_count") or 0) for item in result.profile_results)
        if result.profile_results:
            lines.append("合计：管点 %s 条，管线 %s 条" % (total_points, total_lines))
        if skipped:
            names = "、".join(pipeline_display_name(c) for c in skipped)
            lines.append("已跳过（范围内无数据）：%s" % names)
        if result.errors:
            lines.append("失败：")
            for err in result.errors:
                lines.append(
                    "[%s] %s"
                    % (
                        pipeline_display_name(err.get("profile") or ""),
                        err.get("message") or "",
                    )
                )
        for line in lines:
            self._log(line)
        if not cancelled:
            self._clear_clip_range()
            self._log("已清除裁剪范围")
        QMessageBox.information(
            self,
            "导出已停止" if cancelled else "导出",
            "\n".join(lines),
        )

    def _on_total_load(self):
        pipeline_types = _checked_codes(self.total_pipe_list)
        if not pipeline_types:
            QMessageBox.warning(self, "提示", "请选择要加载的管类")
            return

        info, _mode = load_connection_info()
        if not (info.host or "").strip() or not (info.dbname or "").strip():
            QMessageBox.warning(
                self, "提示",
                "请先在「配置管理 → 数据库连接」中填写并保存 PostgreSQL 连接信息。"
            )
            return

        pg = self.shared_config.get_pg_config()
        if not pg["point"].get("table") or not pg["line"].get("table"):
            QMessageBox.warning(
                self, "提示",
                "请先在「配置管理 → 数据库连接」中设置管点表和管段表。"
            )
            return

        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self._log("正在加载总库图层：%s" % "、".join(
                pipeline_display_name(c) for c in pipeline_types
            ), new_group=True)
            connector = PgConnector(info)
            color_map = self.shared_config.get_pipe_colors()
            connector.load_pipeline_layers(
                pg, pipeline_types, color_map, PIPELINE_TYPES
            )
            self.iface.mapCanvas().refresh()
            self._log("总库图层加载完成")
        except Exception as exc:
            self._log("总库加载失败：%s" % exc)
            QMessageBox.critical(self, "加载失败", str(exc))
        finally:
            QApplication.restoreOverrideCursor()

    def _clear_range_band(self):
        if self._range_band is not None:
            self.canvas.scene().removeItem(self._range_band)
            self._range_band = None

    def _clear_clip_range(self):
        self._clear_range_band()
        self.last_polygon_geom = None
        if getattr(self, "clip_status_label", None) is not None:
            self.clip_status_label.setText("裁剪范围：未绘制")
        self.canvas.refresh()

    def _show_persistent_range(self, geometry):
        self._clear_range_band()
        self._range_band = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry)
        self._range_band.setColor(QColor(255, 0, 0, 60))
        self._range_band.setStrokeColor(QColor(255, 0, 0, 200))
        self._range_band.setWidth(2)
        crs = self.canvas.mapSettings().destinationCrs()
        self._range_band.setToGeometry(geometry, crs)
        self._range_band.show()
        self.canvas.refresh()

    def _on_draw_clip(self):
        self._clear_range_band()
        self.last_polygon_geom = None
        self.clip_status_label.setText(
            "裁剪范围：绘制中...（左键加点，右键/双击结束，Backspace 撤销）"
        )
        self._log("开始绘制裁剪范围", new_group=True)
        self.prev_map_tool = self.canvas.mapTool()
        self.polygon_tool = PolygonDrawTool(
            self.canvas,
            on_finished=self._on_polygon_finished,
            on_cancelled=self._on_polygon_cancelled,
        )
        self.canvas.setMapTool(self.polygon_tool)

    def _on_polygon_finished(self, geometry):
        self.last_polygon_geom = geometry
        self._show_persistent_range(geometry)
        area = geometry.area()
        self.clip_status_label.setText(f"裁剪范围：已绘制（面积约 {area:.1f}）")
        self._log("裁剪范围绘制完成（面积约 %.1f）" % area)
        if self.prev_map_tool:
            self.canvas.setMapTool(self.prev_map_tool)

    def _on_polygon_cancelled(self):
        self.clip_status_label.setText("裁剪范围：已取消绘制")
        self._log("已取消绘制裁剪范围")
        if self.prev_map_tool:
            self.canvas.setMapTool(self.prev_map_tool)

    # ------------------------------------------------------------------ #
    # MDB数据库
    # ------------------------------------------------------------------ #
    def _build_mdb_page(self):
        page = QWidget()
        page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignTop)

        self.mdb_status_label = QLabel("状态：未打开")
        self.mdb_status_label.setWordWrap(False)
        self.mdb_status_label.setMinimumWidth(0)
        self.mdb_status_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(self.mdb_status_label)

        open_row = QHBoxLayout()
        self.mdb_open_btn = QPushButton("打开MDB库")
        self.mdb_open_btn.clicked.connect(self._on_mdb_open)
        open_row.addWidget(self.mdb_open_btn)
        self.mdb_close_btn = QPushButton("关闭")
        self.mdb_close_btn.setEnabled(False)
        self.mdb_close_btn.setToolTip("关闭当前打开的 MDB 库")
        self.mdb_close_btn.clicked.connect(self._on_mdb_close)
        open_row.addWidget(self.mdb_close_btn)
        open_row.addStretch()
        layout.addLayout(open_row)

        layout.addWidget(_section_separator())

        btn_row = QHBoxLayout()
        self.mdb_select_all_btn = QPushButton("全选")
        self.mdb_select_all_btn.clicked.connect(
            lambda: _set_checklist_state(self.mdb_pipe_list, True)
        )
        btn_row.addWidget(self.mdb_select_all_btn)

        self.mdb_select_none_btn = QPushButton("取消")
        self.mdb_select_none_btn.clicked.connect(
            lambda: _set_checklist_state(self.mdb_pipe_list, False)
        )
        btn_row.addWidget(self.mdb_select_none_btn)

        self.mdb_load_btn = QPushButton("加载")
        self.mdb_load_btn.setEnabled(False)
        self.mdb_load_btn.setToolTip("按测绘坐标加载：交换 X/Y 后绘制")
        self.mdb_load_btn.clicked.connect(lambda: self._on_mdb_load(True))
        btn_row.addWidget(self.mdb_load_btn)
        self.mdb_load_noswap_btn = QPushButton("加载(不交换XY)")
        self.mdb_load_noswap_btn.setEnabled(False)
        self.mdb_load_noswap_btn.setToolTip("按数学坐标加载：X/Y 原样绘制")
        self.mdb_load_noswap_btn.clicked.connect(lambda: self._on_mdb_load(False))
        btn_row.addWidget(self.mdb_load_noswap_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.mdb_pipe_list = QListWidget()
        self.mdb_pipe_list.setSelectionMode(QListWidget.NoSelection)
        _limit_pipe_checklist_height(self.mdb_pipe_list)
        layout.addWidget(self.mdb_pipe_list)

        action_row = QHBoxLayout()
        self.save_btn = QPushButton("保存修改")
        self.save_btn.clicked.connect(self._on_mdb_save)
        action_row.addWidget(self.save_btn)
        self.remove_layers_btn = QPushButton("移除图层")
        self.remove_layers_btn.clicked.connect(self._on_mdb_remove_layers)
        action_row.addWidget(self.remove_layers_btn)
        layout.addLayout(action_row)

        layout.addWidget(_section_separator())

        self.import_to_db_btn = QPushButton("数据入库")
        self.import_to_db_btn.clicked.connect(self._on_import_to_db)
        layout.addWidget(self.import_to_db_btn)

        layout.addWidget(_section_separator())

        convert_opts_row = QHBoxLayout()
        convert_opts_row.setAlignment(Qt.AlignTop)
        convert_opts_row.addWidget(
            self._build_convert_structure_group(), 1, Qt.AlignTop
        )
        convert_opts_row.addWidget(
            self._build_convert_format_group(), 1, Qt.AlignTop
        )
        layout.addLayout(convert_opts_row)
        self.convert_btn = QPushButton("结构转换")
        self.convert_btn.clicked.connect(self._on_structure_convert)
        layout.addWidget(self.convert_btn)
        layout.setAlignment(Qt.AlignTop)
        return page

    # ------------------------------------------------------------------ #
    # TXT管线
    # ------------------------------------------------------------------ #
    def _build_txt_page(self):
        page = QWidget()
        page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignTop)

        self.txt_status_label = QLabel("状态：未打开")
        self.txt_status_label.setWordWrap(False)
        self.txt_status_label.setMinimumWidth(0)
        self.txt_status_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(self.txt_status_label)

        open_row = QHBoxLayout()
        self.txt_open_btn = QPushButton("打开txt文件")
        self.txt_open_btn.clicked.connect(self._on_txt_open)
        open_row.addWidget(self.txt_open_btn)
        self.txt_close_btn = QPushButton("关闭")
        self.txt_close_btn.setEnabled(False)
        self.txt_close_btn.setToolTip("关闭当前打开的 TXT 文件")
        self.txt_close_btn.clicked.connect(self._on_txt_close)
        open_row.addWidget(self.txt_close_btn)
        open_row.addStretch()
        layout.addLayout(open_row)

        layout.addWidget(_section_separator())

        self.txt_title_label = QLabel("识别到的管类")
        layout.addWidget(self.txt_title_label)

        load_row = QHBoxLayout()
        self.txt_load_btn = QPushButton("加载")
        self.txt_load_btn.setEnabled(False)
        self.txt_load_btn.setToolTip("按测绘坐标加载：交换 X/Y 后绘制")
        self.txt_load_btn.clicked.connect(lambda: self._on_txt_load(True))
        load_row.addWidget(self.txt_load_btn)
        self.txt_load_noswap_btn = QPushButton("加载(不交换XY)")
        self.txt_load_noswap_btn.setEnabled(False)
        self.txt_load_noswap_btn.setToolTip("按数学坐标加载：X/Y 原样绘制")
        self.txt_load_noswap_btn.clicked.connect(lambda: self._on_txt_load(False))
        load_row.addWidget(self.txt_load_noswap_btn)
        load_row.addStretch()
        layout.addLayout(load_row)

        self.txt_table = QTableWidget(0, 10)
        self.txt_table.setHorizontalHeaderLabels(
            ["序号", "起点", "终点", "X1", "Y1", "Z1", "X2", "Y2", "Z2", "管径"]
        )
        self.txt_table.verticalHeader().setVisible(False)
        self.txt_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.txt_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.txt_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.txt_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        header = self.txt_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(48)
        for col in range(10):
            header.setSectionResizeMode(col, QHeaderView.Interactive)
        self.txt_table.setColumnWidth(TXT_COL_SEQ, 60)
        self.txt_table.setColumnWidth(TXT_COL_START, 73)
        self.txt_table.setColumnWidth(TXT_COL_END, 73)
        for col in TXT_COORD_COLS:
            self.txt_table.setColumnWidth(col, 96)
        self.txt_table.setColumnWidth(TXT_COL_DIAM, 88)
        self.txt_table.itemChanged.connect(self._on_txt_table_item_changed)
        self.txt_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self.txt_table)

        action_row = QHBoxLayout()
        self.txt_add_btn = QPushButton("新增")
        self.txt_add_btn.clicked.connect(self._on_txt_add_row)
        action_row.addWidget(self.txt_add_btn)
        self.txt_del_btn = QPushButton("删除")
        self.txt_del_btn.clicked.connect(self._on_txt_delete_row)
        action_row.addWidget(self.txt_del_btn)
        self.txt_save_btn = QPushButton("保存")
        self.txt_save_btn.clicked.connect(self._on_txt_save)
        action_row.addWidget(self.txt_save_btn)
        action_row.addStretch()
        layout.addLayout(action_row)
        return page

    def resizeEvent(self, event):
        super(PipelineEditingDock, self).resizeEvent(event)
        self._refresh_mdb_status_label()
        self._refresh_txt_status_label()

    def _mdb_status_path_width(self):
        label = self.mdb_status_label
        width = label.contentsRect().width()
        if width <= 20:
            parent = label.parentWidget()
            if parent is not None:
                layout = parent.layout()
                margins = layout.contentsMargins() if layout is not None else None
                width = parent.contentsRect().width()
                if margins is not None:
                    width -= margins.left() + margins.right()
        if width <= 20:
            width = max(self.contentsRect().width() - 24, 40)
        return max(int(width), 40)

    def _refresh_mdb_status_label(self):
        if not hasattr(self, "mdb_status_label"):
            return
        if not self.mdb_path:
            self.mdb_status_label.setText("状态：未打开")
            self.mdb_status_label.setToolTip("")
            return
        prefix = "状态：已打开  "
        metrics = self.mdb_status_label.fontMetrics()
        avail = self._mdb_status_path_width() - metrics.width(prefix)
        elided = metrics.elidedText(self.mdb_path, Qt.ElideMiddle, max(avail, 40))
        self.mdb_status_label.setText(prefix + elided)
        self.mdb_status_label.setToolTip(self.mdb_path)

    def _txt_status_path_width(self):
        label = self.txt_status_label
        width = label.contentsRect().width()
        if width <= 20:
            parent = label.parentWidget()
            if parent is not None:
                layout = parent.layout()
                margins = layout.contentsMargins() if layout is not None else None
                width = parent.contentsRect().width()
                if margins is not None:
                    width -= margins.left() + margins.right()
        if width <= 20:
            width = max(self.contentsRect().width() - 24, 40)
        return max(int(width), 40)

    def _refresh_txt_status_label(self):
        if not hasattr(self, "txt_status_label"):
            return
        if not self.txt_path:
            self.txt_status_label.setText("状态：未打开")
            self.txt_status_label.setToolTip("")
            return
        prefix = "状态：已打开  "
        metrics = self.txt_status_label.fontMetrics()
        avail = self._txt_status_path_width() - metrics.width(prefix)
        elided = metrics.elidedText(self.txt_path, Qt.ElideMiddle, max(avail, 40))
        self.txt_status_label.setText(prefix + elided)
        self.txt_status_label.setToolTip(self.txt_path)

    def _set_txt_actions_enabled(self, enabled):
        if not hasattr(self, "txt_load_btn"):
            return
        self.txt_load_btn.setEnabled(enabled)
        if hasattr(self, "txt_load_noswap_btn"):
            self.txt_load_noswap_btn.setEnabled(enabled)
        self.txt_add_btn.setEnabled(enabled)
        self.txt_del_btn.setEnabled(enabled)
        self.txt_save_btn.setEnabled(enabled)
        self.txt_table.setEnabled(enabled)
        if hasattr(self, "txt_close_btn"):
            self.txt_close_btn.setEnabled(enabled)

    def _txt_readonly_item(self, text):
        item = QTableWidgetItem("" if text is None else str(text))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        return item

    def _txt_edit_item(self, text):
        return QTableWidgetItem("" if text is None else str(text))

    def _txt_cell_text(self, row, col):
        item = self.txt_table.item(row, col)
        if item is None:
            return ""
        return (item.text() or "").strip()

    def _txt_set_cell_text(self, row, col, text, editable=True):
        item = self.txt_table.item(row, col)
        value = "" if text is None else str(text)
        if item is None:
            item = self._txt_edit_item(value) if editable else self._txt_readonly_item(value)
            self.txt_table.setItem(row, col, item)
        else:
            item.setText(value)

    def _txt_parse_coord_cell(self, row, col, label):
        text = self._txt_cell_text(row, col)
        if not text:
            return 0.0
        try:
            return float(text)
        except ValueError:
            raise ValueError("第 %s 行的 %s 不是有效数字" % (row + 1, label))

    def _txt_renumber_rows(self):
        self._txt_table_loading = True
        try:
            for row in range(self.txt_table.rowCount()):
                seq = row + 1
                self.txt_table.setItem(row, TXT_COL_SEQ, self._txt_readonly_item(seq))
                self.txt_table.setItem(row, TXT_COL_START, self._txt_readonly_item("S%s" % seq))
                self.txt_table.setItem(row, TXT_COL_END, self._txt_readonly_item("S%s" % (seq + 1)))
        finally:
            self._txt_table_loading = False

    def _fill_txt_table(self, segments):
        self._txt_table_loading = True
        try:
            self.txt_table.setRowCount(0)
            for index, seg in enumerate(segments or [], start=1):
                row = self.txt_table.rowCount()
                self.txt_table.insertRow(row)
                x1 = seg.get("x1", seg.get("X"))
                y1 = seg.get("y1", seg.get("Y"))
                z1 = seg.get("z1", seg.get("Z"))
                x2 = seg.get("x2", x1)
                y2 = seg.get("y2", y1)
                z2 = seg.get("z2", z1)
                self.txt_table.setItem(row, TXT_COL_SEQ, self._txt_readonly_item(index))
                self.txt_table.setItem(
                    row, TXT_COL_START,
                    self._txt_readonly_item(seg.get("起点") or ("S%s" % index)),
                )
                self.txt_table.setItem(
                    row, TXT_COL_END,
                    self._txt_readonly_item(seg.get("终点") or ("S%s" % (index + 1))),
                )
                self.txt_table.setItem(row, TXT_COL_X1, self._txt_edit_item(x1))
                self.txt_table.setItem(row, TXT_COL_Y1, self._txt_edit_item(y1))
                self.txt_table.setItem(row, TXT_COL_Z1, self._txt_edit_item(z1))
                self.txt_table.setItem(row, TXT_COL_X2, self._txt_edit_item(x2))
                self.txt_table.setItem(row, TXT_COL_Y2, self._txt_edit_item(y2))
                self.txt_table.setItem(row, TXT_COL_Z2, self._txt_edit_item(z2))
                self.txt_table.setItem(row, TXT_COL_DIAM, self._txt_edit_item(seg.get("管径")))
        finally:
            self._txt_table_loading = False

    def _txt_segments_from_table(self):
        segments = []
        labels = {
            TXT_COL_X1: "X1", TXT_COL_Y1: "Y1", TXT_COL_Z1: "Z1",
            TXT_COL_X2: "X2", TXT_COL_Y2: "Y2", TXT_COL_Z2: "Z2",
        }
        for row in range(self.txt_table.rowCount()):
            x1 = self._txt_parse_coord_cell(row, TXT_COL_X1, labels[TXT_COL_X1])
            y1 = self._txt_parse_coord_cell(row, TXT_COL_Y1, labels[TXT_COL_Y1])
            z1 = self._txt_parse_coord_cell(row, TXT_COL_Z1, labels[TXT_COL_Z1])
            x2 = self._txt_parse_coord_cell(row, TXT_COL_X2, labels[TXT_COL_X2])
            y2 = self._txt_parse_coord_cell(row, TXT_COL_Y2, labels[TXT_COL_Y2])
            z2 = self._txt_parse_coord_cell(row, TXT_COL_Z2, labels[TXT_COL_Z2])
            segments.append({
                "起点": self._txt_cell_text(row, TXT_COL_START) or ("S%s" % (row + 1)),
                "终点": self._txt_cell_text(row, TXT_COL_END) or ("S%s" % (row + 2)),
                "X": x1,
                "Y": y1,
                "Z": z1,
                "管径": self._txt_cell_text(row, TXT_COL_DIAM),
                "x1": x1,
                "y1": y1,
                "z1": z1,
                "x2": x2,
                "y2": y2,
                "z2": z2,
            })
        return segments

    def _on_txt_table_item_changed(self, item):
        if self._txt_table_loading or item is None:
            return
        col = item.column()
        if col not in TXT_COORD_COLS:
            return
        text = (item.text() or "").strip()
        if not text:
            return
        try:
            float(text)
        except ValueError:
            QMessageBox.warning(self, "提示", "坐标必须是数字")
            self._txt_table_loading = True
            item.setText("0")
            self._txt_table_loading = False
            return
        row = item.row()
        pair_col = TXT_JOINT_PAIRS.get(col)
        if pair_col is None:
            return
        self._txt_table_loading = True
        try:
            if col in (TXT_COL_X1, TXT_COL_Y1, TXT_COL_Z1) and row > 0:
                self._txt_set_cell_text(row - 1, pair_col, text)
            elif col in (TXT_COL_X2, TXT_COL_Y2, TXT_COL_Z2) and row + 1 < self.txt_table.rowCount():
                self._txt_set_cell_text(row + 1, pair_col, text)
        finally:
            self._txt_table_loading = False

    def _txt_layer_loaded(self):
        if not self.txt_path:
            return False
        abs_path = os.path.abspath(self.txt_path)
        for layer in QgsProject.instance().mapLayers().values():
            if layer.customProperty("txt_coord/source_path") == abs_path:
                return True
        return False

    def _render_txt_layer(self, segments, zoom=True, swap_xy=None):
        if swap_xy is None:
            swap_xy = bool(getattr(self, "txt_swap_xy", True))
        else:
            swap_xy = bool(swap_xy)
        self.txt_swap_xy = swap_xy
        layer, pipe_code, seg_count = load_txt_coord_layer(
            self.txt_path,
            pipe_code=self.txt_pipe_code,
            segments=segments,
            log=self._log,
            swap_xy=swap_xy,
        )
        self.txt_layer = layer
        if zoom:
            self.iface.mapCanvas().setExtent(layer.extent())
        self.iface.mapCanvas().refresh()
        return layer, pipe_code, seg_count

    def _on_txt_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 TXT 文件", "", "文本文件 (*.txt);;所有文件 (*.*)"
        )
        if not path:
            return
        try:
            parsed = parse_txt_coord_file(path)
        except Exception as exc:
            self._log("打开 TXT 失败：%s" % exc, new_group=True)
            QMessageBox.critical(self, "打开失败", str(exc))
            return
        self.txt_path = path
        self.txt_pipe_code = parsed.get("pipe_code")
        self.txt_header = parsed.get("header") or ""
        self.txt_encoding = parsed.get("encoding") or "utf-8"
        self.txt_title_label.setText(
            "识别到的管类：%s" % pipeline_display_name(self.txt_pipe_code)
        )
        self._refresh_txt_status_label()
        self._fill_txt_table(parsed.get("segments") or [])
        self._set_txt_actions_enabled(True)
        self._log("已打开 TXT：%s" % path, new_group=True)
        self._log(
            "管类：%s，坐标行：%s"
            % (
                pipeline_display_name(self.txt_pipe_code),
                len(parsed.get("segments") or []),
            )
        )

    def _on_txt_close(self):
        if not self.txt_path:
            return
        path = self.txt_path
        layer = self.txt_layer
        _remove_txt_layers_for_path(path)
        if layer is not None:
            try:
                QgsProject.instance().removeMapLayer(layer.id())
            except Exception:
                pass
        self.txt_layer = None
        self.txt_path = None
        self.txt_pipe_code = None
        self.txt_header = ""
        self.txt_encoding = "utf-8"
        self.txt_title_label.setText("识别到的管类")
        self._fill_txt_table([])
        self._set_txt_actions_enabled(False)
        self._refresh_txt_status_label()
        self.iface.mapCanvas().refresh()
        self._log("已关闭 TXT：%s" % path, new_group=True)

    def _on_txt_add_row(self):
        if not self.txt_path:
            QMessageBox.warning(self, "提示", "请先打开 TXT 文件")
            return
        self._txt_table_loading = True
        try:
            row = self.txt_table.rowCount()
            x1 = y1 = z1 = "0"
            if row > 0:
                x1 = self._txt_cell_text(row - 1, TXT_COL_X2) or "0"
                y1 = self._txt_cell_text(row - 1, TXT_COL_Y2) or "0"
                z1 = self._txt_cell_text(row - 1, TXT_COL_Z2) or "0"
            self.txt_table.insertRow(row)
            self.txt_table.setItem(row, TXT_COL_SEQ, self._txt_readonly_item(row + 1))
            self.txt_table.setItem(row, TXT_COL_START, self._txt_readonly_item(""))
            self.txt_table.setItem(row, TXT_COL_END, self._txt_readonly_item(""))
            self.txt_table.setItem(row, TXT_COL_X1, self._txt_edit_item(x1))
            self.txt_table.setItem(row, TXT_COL_Y1, self._txt_edit_item(y1))
            self.txt_table.setItem(row, TXT_COL_Z1, self._txt_edit_item(z1))
            self.txt_table.setItem(row, TXT_COL_X2, self._txt_edit_item(""))
            self.txt_table.setItem(row, TXT_COL_Y2, self._txt_edit_item(""))
            self.txt_table.setItem(row, TXT_COL_Z2, self._txt_edit_item(""))
            self.txt_table.setItem(row, TXT_COL_DIAM, self._txt_edit_item(""))
        finally:
            self._txt_table_loading = False
        self._txt_renumber_rows()
        self.txt_table.selectRow(self.txt_table.rowCount() - 1)
        self._log("已新增第 %s 行" % self.txt_table.rowCount(), new_group=True)

    def _on_txt_delete_row(self):
        if not self.txt_path:
            QMessageBox.warning(self, "提示", "请先打开 TXT 文件")
            return
        row = self.txt_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选择要删除的行")
            return
        self.txt_table.removeRow(row)
        self._txt_renumber_rows()
        self._log("已删除第 %s 行" % (row + 1), new_group=True)
        self._txt_table_loading = True
        try:
            for i in range(self.txt_table.rowCount() - 1):
                for src_col, dst_col in (
                    (TXT_COL_X2, TXT_COL_X1),
                    (TXT_COL_Y2, TXT_COL_Y1),
                    (TXT_COL_Z2, TXT_COL_Z1),
                ):
                    self._txt_set_cell_text(
                        i + 1, dst_col, self._txt_cell_text(i, src_col) or "0"
                    )
        finally:
            self._txt_table_loading = False

    def _on_txt_save(self):
        if not self.txt_path:
            QMessageBox.warning(self, "提示", "请先打开 TXT 文件")
            return
        try:
            segments = sync_segment_joints(self._txt_segments_from_table())
            write_txt_coord_file(
                self.txt_path,
                self.txt_pipe_code,
                segments,
                encoding=self.txt_encoding,
                header=self.txt_header,
            )
            self._fill_txt_table(segments)
        except Exception as exc:
            self._log("TXT 保存失败：%s" % exc, new_group=True)
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        self._log("已修改保存：%s（%s 段）" % (self.txt_path, len(segments)), new_group=True)
        if self._txt_layer_loaded():
            try:
                QApplication.setOverrideCursor(Qt.WaitCursor)
                self._render_txt_layer(segments, zoom=False)
            except Exception as exc:
                QApplication.restoreOverrideCursor()
                self._log("TXT 已保存，但图层刷新失败：%s" % exc)
                QMessageBox.critical(self, "保存失败", "文件已保存，但图层刷新失败：%s" % exc)
                return
            QApplication.restoreOverrideCursor()
        QMessageBox.information(self, "保存完成", "已修改保存。")

    def _on_txt_load(self, swap_xy=True):
        if not self.txt_path:
            QMessageBox.warning(self, "提示", "请先打开 TXT 文件")
            return
        swap_xy = bool(swap_xy)
        try:
            parsed = parse_txt_coord_file(self.txt_path)
        except Exception as exc:
            self._log("TXT 加载失败：%s" % exc, new_group=True)
            QMessageBox.critical(self, "加载失败", str(exc))
            return
        segments = parsed.get("segments") or []
        if not segments:
            self._log("TXT 加载失败：文件中没有可加载的坐标行", new_group=True)
            QMessageBox.warning(self, "提示", "TXT 文件中没有可加载的坐标行")
            return
        self.txt_pipe_code = parsed.get("pipe_code") or self.txt_pipe_code
        self.txt_header = parsed.get("header") or self.txt_header
        self.txt_encoding = parsed.get("encoding") or self.txt_encoding
        self.txt_title_label.setText(
            "识别到的管类：%s" % pipeline_display_name(self.txt_pipe_code)
        )
        self._fill_txt_table(segments)
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self._log(
                "正在加载 TXT 图层（%s）…"
                % ("交换 X/Y" if swap_xy else "不交换 X/Y"),
                new_group=True,
            )
            layer, pipe_code, seg_count = self._render_txt_layer(
                segments, zoom=True, swap_xy=swap_xy
            )
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            self._log("TXT 加载失败：%s" % exc)
            QMessageBox.critical(self, "加载失败", str(exc))
            return
        QApplication.restoreOverrideCursor()
        self._log(
            "TXT 加载完成：管类 %s，线段数 %s，图层 %s（%s）"
            % (
                pipeline_display_name(pipe_code),
                seg_count,
                layer.name(),
                "交换 X/Y" if swap_xy else "不交换 X/Y",
            )
        )
        QMessageBox.information(
            self, "加载完成",
            "管类：%s\n线段数：%s\n图层：%s\n坐标约定：%s"
            % (
                pipeline_display_name(pipe_code),
                seg_count,
                layer.name(),
                "交换 X/Y" if swap_xy else "不交换 X/Y",
            ),
        )

    def _build_convert_structure_group(self):
        box, self.convert_target_layout = _titled_option_box("目标结构")
        self.convert_target_group = QButtonGroup(self)
        self.convert_target_group.setExclusive(True)
        self._rebuild_convert_target_radios()
        return box

    def _build_convert_format_group(self):
        box, box_layout = _titled_option_box("目标格式")
        self.convert_format_group = QButtonGroup(self)
        self.convert_format_group.setExclusive(True)
        self.convert_mdb_radio = QRadioButton("MDB库")
        self.convert_gdb_radio = QRadioButton("GDB库")
        self.convert_mdb_radio.setChecked(True)
        self.convert_format_group.addButton(self.convert_mdb_radio)
        self.convert_format_group.addButton(self.convert_gdb_radio)
        box_layout.addWidget(self.convert_mdb_radio)
        box_layout.addWidget(self.convert_gdb_radio)
        return box

    def _rebuild_convert_target_radios(self):
        if not hasattr(self, "convert_target_layout"):
            return
        prev_key = None
        checked = self.convert_target_group.checkedButton()
        if checked is not None:
            prev_key = checked.property("structure_key")
        for btn in list(self.convert_target_group.buttons()):
            self.convert_target_group.removeButton(btn)
        while self.convert_target_layout.count():
            item = self.convert_target_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for key, label in self.shared_config.list_structures():
            radio = QRadioButton(label)
            radio.setProperty("structure_key", key)
            self.convert_target_group.addButton(radio)
            self.convert_target_layout.addWidget(radio)
            if prev_key and key == prev_key:
                radio.setChecked(True)

    def _set_mdb_layer_actions_enabled(self, enabled):
        self.save_btn.setEnabled(enabled)
        self.remove_layers_btn.setEnabled(enabled)

    def _on_mdb_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 MDB 文件", "", "Access 数据库 (*.mdb *.accdb)"
        )
        if not path:
            return
        try:
            pipe_items = list_mdb_pipe_types(
                path, render_groups=self.shared_config.get_mdb_render_groups()
            )
            if not pipe_items:
                QMessageBox.warning(self, "提示", "未能从 MDB 中识别管类表")
                self._log("打开 MDB 失败：未能识别管类表", new_group=True)
                return
            self.mdb_path = path
            self._refresh_mdb_status_label()
            _fill_mdb_pipe_checklist(self.mdb_pipe_list, pipe_items)
            has_usable = any(not item.get("empty") for item in pipe_items)
            self.mdb_load_btn.setEnabled(has_usable)
            self.mdb_load_noswap_btn.setEnabled(has_usable)
            self.mdb_close_btn.setEnabled(True)
            codes = [item["code"] for item in pipe_items]
            empty_items = [item for item in pipe_items if item.get("empty")]
            usable = [item["code"] for item in pipe_items if not item.get("empty")]
            self._log("已打开 MDB：%s" % path, new_group=True)
            self._log("识别管类：%s" % "、".join(pipeline_display_name(c) for c in codes))
            if usable:
                self._log(
                    "有数据（默认可加载）：%s"
                    % "、".join(pipeline_display_name(c) for c in usable)
                )
            if empty_items:
                empty_text = "、".join(
                    "%s（%s）" % (pipeline_display_name(item["code"]), item.get("reason") or "无数据")
                    for item in empty_items
                )
                self._log("空表（已禁用）：%s" % empty_text)
        except Exception as exc:
            self._log("打开 MDB 失败：%s" % exc, new_group=True)
            QMessageBox.critical(self, "打开失败", str(exc))

    def _on_mdb_close(self):
        if not self.mdb_path:
            return
        if self.project_session:
            self._remove_mdb_layers_only()
            self._set_mdb_layer_actions_enabled(False)
        path = self.mdb_path
        self.mdb_path = None
        self.matched_structure_id = None
        self.mdb_pipe_list.clear()
        self.mdb_load_btn.setEnabled(False)
        self.mdb_load_noswap_btn.setEnabled(False)
        self.mdb_close_btn.setEnabled(False)
        self._refresh_mdb_status_label()
        self._log("已关闭 MDB：%s" % path, new_group=True)

    def _on_mdb_load(self, swap_xy=True):
        if not self.mdb_path:
            QMessageBox.warning(self, "提示", "请先打开 MDB 库")
            return
        codes = _checked_codes(self.mdb_pipe_list)
        if not codes:
            QMessageBox.warning(self, "提示", "请至少勾选一个管类")
            return
        base_types, include_fz = split_pipeline_selection(codes)
        if include_fz and not base_types:
            QMessageBox.warning(
                self, "提示",
                "FZ（辅助）不是独立管线数据，请至少再勾选一种其他管类后再加载。",
            )
            return
        enabled = _enabled_codes(self.mdb_pipe_list)
        load_all_fz = include_fz and bool(enabled) and set(codes) == set(enabled)
        swap_xy = bool(swap_xy)
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self._log(
                "正在加载 MDB 图层（%s）…" % ("交换 X/Y" if swap_xy else "不交换 X/Y"),
                new_group=True,
            )
            if self.project_session:
                self._remove_mdb_layers_only()
            color_map = self.shared_config.get_pipe_colors()
            render_groups = self.shared_config.get_mdb_render_groups()
            self.project_session = load_mdb_layers(
                self.mdb_path, codes,
                color_map=color_map,
                render_groups=render_groups,
                mdb_structures=self.shared_config.get_mdb_structures(),
                log=self._log,
                swap_xy=swap_xy,
                load_all_fz=load_all_fz,
            )
            self._set_mdb_layer_actions_enabled(True)
            self.iface.mapCanvas().refresh()
            loaded_count = len(self.project_session.layer_sessions)
            loaded_codes = list(getattr(self.project_session, "loaded_pipe_codes", None) or [])
            group_label = getattr(self.project_session, "render_group_label", "") or ""
            self.matched_structure_id = getattr(
                self.project_session, "render_group_id", None
            )
        except MdbRenderGroupNotMatchedError as exc:
            QApplication.restoreOverrideCursor()
            self._log("MDB 加载失败：%s" % exc)
            QMessageBox.warning(self, "无法加载", str(exc))
            return
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            self._log("MDB 加载失败：%s" % exc)
            QMessageBox.critical(self, "加载失败", str(exc))
            return
        QApplication.restoreOverrideCursor()
        layer_names = []
        if self.project_session.layer_session_by_kind("point"):
            layer_names.append("MDB管点")
        if self.project_session.layer_session_by_kind("line"):
            layer_names.append("MDB管线")
        tip = "已加载 %s。" % (" / ".join(layer_names) or "%s 个图层" % loaded_count)
        if loaded_codes:
            tip += "\n管类：%s" % "、".join(pipeline_display_name(c) for c in loaded_codes)
        if group_label:
            tip += f"\n匹配渲染结构组：{group_label}"
        tip += "\n坐标约定：%s" % ("交换 X/Y" if swap_xy else "不交换 X/Y")
        self._log(tip.replace("\n", " "))
        QMessageBox.information(self, "加载完成", tip)

    def _on_mdb_save(self):
        if not self.project_session:
            QMessageBox.warning(self, "提示", "请先加载 MDB 图层")
            return
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self._log("正在保存 MDB 修改…", new_group=True)
            deltas = capture_project_edit_deltas(self.project_session)
            change_flags = change_flags_from_deltas(self.project_session, deltas)
            save_project_session(self.project_session, log=self._log, deltas=deltas)
            sync_layers_after_save(
                self.project_session, log=self._log, change_flags=change_flags,
                deltas=deltas,
            )
            update_project_session_snapshots(
                self.project_session, log=self._log, deltas=deltas
            )
        except Exception as exc:
            self._log("MDB 保存失败：%s" % exc)
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()

        redraw_project_layers(self.project_session, self.iface, log=self._log)

    def _remove_mdb_layers_only(self):
        root = QgsProject.instance().layerTreeRoot()
        for name in (MDB_LAYER_GROUP_NAME, "MDB管线"):
            group = root.findGroup(name)
            if group:
                root.removeChildNode(group)
        self.project_session = None

    def _on_mdb_remove_layers(self):
        if not self.project_session:
            return
        self._remove_mdb_layers_only()
        self._set_mdb_layer_actions_enabled(False)
        self._log("已移除 MDB 图层", new_group=True)

    def _on_import_to_db(self):
        if not self.project_session:
            QMessageBox.warning(
                self, "提示",
                "数据入库前请先「加载」MDB 图层到地图。"
            )
            return
        pipe_codes = _checked_codes(self.mdb_pipe_list)
        if not pipe_codes:
            QMessageBox.warning(self, "提示", "请至少勾选一个管类后再入库。")
            return
        base_types, include_fz = split_pipeline_selection(pipe_codes)
        if include_fz and not base_types:
            QMessageBox.warning(
                self, "提示",
                "FZ（辅助）不是独立管线数据，请至少再勾选一种其他管类后再入库。",
            )
            return
        enabled = _enabled_codes(self.mdb_pipe_list)
        load_all_fz = include_fz and bool(enabled) and set(pipe_codes) == set(enabled)
        structure_id = getattr(self.project_session, "render_group_id", None) or self.matched_structure_id
        if not structure_id:
            QMessageBox.warning(
                self, "提示",
                "未能识别当前加载 MDB 对应的结构，请重新加载后再入库。"
            )
            return
        info, _mode = load_connection_info()
        mapping_block = self.shared_config.get_mapping_block("import", structure_id)
        errors = check_import_ready(
            self.shared_config, info, structure_id, mapping_block
        )
        if errors:
            QMessageBox.warning(self, "无法入库", "\n".join(errors))
            return
        names = "、".join(pipeline_display_name(c) for c in pipe_codes) or "（无）"
        reply = QMessageBox.question(
            self, "数据入库",
            "未勾选管类与空表不会入库。\n"
            "结构：%s\n管类：%s\n"
            "井编号：导入映射中选择了「井编号」规则的字段会续编/对照更新，"
            "未选择的字段按原始井号写入。\n\n是否继续？"
            % (
                structure_id,
                names,
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        progress_dlg = None
        cursor_overridden = True
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self._log(
                "开始入库：结构 %s，管类 %s（%s）"
                % (
                    structure_id,
                    names,
                    "交换 X/Y" if getattr(self.project_session, "swap_xy", True) else "不交换 X/Y",
                ),
                new_group=True,
            )
            QApplication.restoreOverrideCursor()
            cursor_overridden = False
            progress_dlg = ExportProgressDialog(
                max(1, len(pipe_codes) * 2), self, verb="导入"
            )
            stats = import_mdb_to_pg(
                self.project_session.mdb_path,
                pipe_codes,
                structure_id,
                self.shared_config,
                info,
                swap_xy=bool(getattr(self.project_session, "swap_xy", True)),
                load_all_fz=load_all_fz,
                log=self._log,
                progress_dialog=progress_dlg,
            )
            if stats.get("cancelled"):
                progress_dlg.finish_and_close()
                progress_dlg = None
                self._log("入库已停止，未写入任何数据")
                QMessageBox.information(
                    self, "入库已停止",
                    "已停止导入，总库未导入任何数据。",
                )
                return
            progress_dlg.accept()
        except Exception as exc:
            if cursor_overridden:
                QApplication.restoreOverrideCursor()
                cursor_overridden = False
            if progress_dlg is not None:
                progress_dlg.finish_and_close()
                progress_dlg = None
            self._log("入库失败：%s" % exc)
            QMessageBox.critical(self, "入库失败", str(exc))
            return
        finally:
            if progress_dlg is not None:
                progress_dlg.finish_and_close()
            if cursor_overridden:
                QApplication.restoreOverrideCursor()
        skipped = stats.get("skipped") or []
        extra = ""
        if skipped:
            extra = "\n跳过：\n- " + "\n- ".join(skipped[:20])
            if len(skipped) > 20:
                extra += "\n- … 共 %s 条" % len(skipped)
        summary = "已写入管点 %s 条、管线 %s 条。" % (
            stats.get("point_rows") or 0, stats.get("line_rows") or 0
        )
        self._log(summary)
        if skipped:
            self._log("入库跳过 %s 条" % len(skipped))
        QMessageBox.information(
            self, "入库完成",
            "%s%s" % (summary, extra)
        )

    def _resolve_source_structure_id(self):
        """打开的 MDB 匹配源结构（不依赖是否已加载图层）。"""
        if not self.mdb_path:
            return None, "请先打开 MDB 库"
        from ..core.mdb.mdb_connector import MdbConnection
        from ..core.mdb.schema_detect import (
            discover_pipe_layers,
            match_mdb_render_group_from_connection,
        )
        try:
            conn = MdbConnection(self.mdb_path)
            try:
                tables = conn.list_user_tables()
                render_groups = self.shared_config.get_mdb_render_groups()
                discovered = discover_pipe_layers(tables, render_groups=render_groups)
                group = match_mdb_render_group_from_connection(
                    conn, discovered, render_groups, table_names=tables
                )
            finally:
                conn.close()
        except Exception as exc:
            return None, str(exc)
        if not group:
            return None, (
                "未能识别当前 MDB 对应的「MDB库渲染」结构组。\n"
                "请先在配置管理中完善渲染用字段后再转换。"
            )
        return group.get("id"), None

    def _on_structure_convert(self):
        target_btn = self.convert_target_group.checkedButton()
        if target_btn is None:
            QMessageBox.warning(self, "提示", "请先勾选目标结构")
            return
        target_id = target_btn.property("structure_key")
        source_id, err = self._resolve_source_structure_id()
        if err:
            QMessageBox.warning(self, "结构转换", err)
            return

        fmt = "mdb"
        if getattr(self, "convert_gdb_radio", None) is not None and self.convert_gdb_radio.isChecked():
            fmt = "gdb"

        same_structure = source_id == target_id
        if same_structure and fmt == "mdb":
            QMessageBox.warning(self, "提示", "目标结构不能与源结构相同")
            return

        from ..core.mdb.structure_convert import (
            convert_mdb_to_new_file,
            mapping_has_field_rows,
        )

        pipe_codes = _checked_codes(self.mdb_pipe_list)
        if not pipe_codes:
            QMessageBox.warning(self, "结构转换", "请先勾选要转换的管类")
            return

        if not same_structure:
            pair_key = f"{source_id}__to__{target_id}"
            block = self.shared_config.get_mapping_block("convert", pair_key)
            if not mapping_has_field_rows(block):
                QMessageBox.warning(
                    self, "结构转换",
                    "未找到已配置的结构转换映射。\n"
                    "请到「配置管理 → 结构映射 → 结构转换」中"
                    "选择对应的源结构/目标结构，配置点表、线表字段映射并保存。"
                )
                return

        if fmt == "gdb":
            if not writable_gdb_drivers():
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Warning)
                box.setWindowTitle("无法写入 FileGDB")
                box.setText(gdb_write_unavailable_message())
                box.setInformativeText(
                    "也可以改为导出 GeoPackage（.gpkg）：同样是矢量数据库，"
                    "含 OBJECTID 与图形（Shape）。"
                )
                gpkg_btn = box.addButton("改为 GeoPackage", QMessageBox.AcceptRole)
                box.addButton("取消", QMessageBox.RejectRole)
                box.exec_()
                if box.clickedButton() is not gpkg_btn:
                    return
                fmt = "gpkg"
            if same_structure:
                reply = QMessageBox.question(
                    self, "结构转换",
                    "目标结构与源结构相同，将在结构不变的前提下导出为矢量数据"
                    "（含 OBJECTID、Shape，不改变字段结构）。\n是否继续？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if reply != QMessageBox.Yes:
                    return
            if fmt == "gdb":
                out_path, _ = QFileDialog.getSaveFileName(
                    self, "另存为新 GDB", "转换结果.gdb", "File Geodatabase (*.gdb)"
                )
            else:
                out_path, _ = QFileDialog.getSaveFileName(
                    self, "另存为 GeoPackage", "转换结果.gpkg", "GeoPackage (*.gpkg)"
                )
        else:
            out_path, _ = QFileDialog.getSaveFileName(
                self, "另存为新 MDB", "转换结果.mdb", "Access 数据库 (*.mdb *.accdb)"
            )
        if not out_path:
            return
        root, ext = os.path.splitext(out_path)
        if fmt == "gdb" and ext.lower() != ".gdb":
            out_path = root + ".gdb"
        elif fmt == "gpkg" and ext.lower() != ".gpkg":
            out_path = root + ".gpkg"
        elif fmt == "mdb" and not ext:
            out_path = root + ".mdb"
        if fmt == "mdb" and os.path.abspath(out_path) == os.path.abspath(self.mdb_path):
            QMessageBox.warning(self, "提示", "不能覆盖当前打开的 MDB，请另选路径")
            return

        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self._log("开始结构转换：%s → %s（%s）" % (source_id, target_id, fmt), new_group=True)
            self._log(
                "转换管类：%s"
                % "、".join(pipeline_display_name(c) for c in pipe_codes)
            )
            swap_xy = True
            if (
                self.project_session is not None
                and getattr(self.project_session, "mdb_path", None) == self.mdb_path
            ):
                swap_xy = bool(getattr(self.project_session, "swap_xy", True))
            self._log("坐标约定：%s" % ("交换 X/Y" if swap_xy else "不交换 X/Y"))
            stats = convert_mdb_to_new_file(
                self.mdb_path,
                out_path,
                source_id=source_id,
                target_id=target_id,
                shared_config=self.shared_config,
                output_format=fmt,
                swap_xy=swap_xy,
                pipe_codes=pipe_codes,
            )
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            self._log("结构转换失败：%s" % exc)
            QMessageBox.critical(self, "结构转换失败", str(exc))
            return
        QApplication.restoreOverrideCursor()

        format_label = "MDB库"
        if fmt == "gdb":
            format_label = "GDB库"
        elif fmt == "gpkg":
            format_label = "GeoPackage"
        lines = [
            "已按映射转换为目标结构。",
            "输出：%s" % (stats.get("out_path") or out_path),
            "格式：%s" % format_label,
            "",
        ]
        for item in stats.get("tables") or []:
            kind_label = "点表" if item.get("kind") == "point" else "线表"
            pipe_label = pipeline_display_name(item.get("pipe") or "")
            lines.append(
                f"{pipe_label} {kind_label}：{item.get('src')} → {item.get('dst')}"
                f"（{item.get('rows') or 0} 条）"
            )
        total_points = sum(
            (item.get("rows") or 0)
            for item in (stats.get("tables") or [])
            if item.get("kind") == "point"
        )
        total_lines = sum(
            (item.get("rows") or 0)
            for item in (stats.get("tables") or [])
            if item.get("kind") != "point"
        )
        lines.append("合计：管点 %s 条，管线 %s 条" % (total_points, total_lines))
        skipped = stats.get("skipped") or []
        if skipped:
            lines.append("\n跳过：")
            lines.extend(skipped[:30])
        for line in lines:
            if line:
                self._log(line)
        QMessageBox.information(self, "结构转换", "\n".join(lines))

    # ------------------------------------------------------------------ #
    def _on_config(self):
        self.shared_config.load()
        dlg = ConfigDialog(self.shared_config, self)
        dlg.exec_()
        self.shared_config.load()
        self._rebuild_export_structure_radios()
        self._rebuild_convert_target_radios()
        self._refresh_total_pipe_checklist()
