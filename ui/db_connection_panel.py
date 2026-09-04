# -*- coding: utf-8 -*-
"""数据库连接：PostgreSQL 账号 + 点/线表名 + 加载表结构。"""

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLineEdit, QSpinBox, QPushButton, QLabel, QMessageBox, QScrollArea,
    QTableWidget, QTableWidgetItem, QComboBox, QTabWidget, QListWidget,
    QListWidgetItem, QSizePolicy, QHeaderView, QAbstractScrollArea,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor

from ..core.pg_connection import (
    load_connection_info,
    save_connection_info,
    test_pg_connection,
    PgConnectionInfo,
)
from ..core.pg_schema_loader import fetch_table_columns, refresh_pg_pipe_types
from ..core.pipe_catalog import pipeline_display_name


def _follow_window(widget):
    widget.setMinimumWidth(0)
    policy = widget.sizePolicy()
    policy.setHorizontalPolicy(QSizePolicy.Ignored)
    widget.setSizePolicy(policy)


def _half_width_field(widget):
    """参数框占所在列可用宽度的 3/4（现有一半再加一半），并随窗口伸缩。"""
    widget.setMinimumWidth(0)
    widget.setMaximumWidth(16777215)
    widget.setSizePolicy(QSizePolicy.Expanding, widget.sizePolicy().verticalPolicy())
    wrap = QWidget()
    wrap.setMinimumWidth(0)
    wrap.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
    row = QHBoxLayout(wrap)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(0)
    row.addWidget(widget, 3)
    row.addStretch(1)
    return wrap


class DbConnectionPanel(QWidget):
    def __init__(self, shared_config, parent=None):
        super().__init__(parent)
        self.shared_config = shared_config

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setMinimumWidth(0)
        layout = QVBoxLayout(content)

        layout.addWidget(self._build_connection_box())
        layout.addWidget(self._build_role_box())
        layout.addWidget(self._build_schema_box(), 1)

        scroll.setWidget(content)
        _follow_window(content)
        outer.addWidget(scroll)

        self._load_connection_form()
        self._populate_table_names()
        self._populate_schema_view()
        self._populate_role_combos()

    def _build_connection_box(self):
        box = QGroupBox("PostgreSQL连接配置")
        self.host_edit = QLineEdit()
        self.port_edit = QSpinBox()
        self.port_edit.setRange(1, 65535)
        self.port_edit.setValue(5432)
        self.db_edit = QLineEdit()
        self.user_edit = QLineEdit()
        self.pwd_edit = QLineEdit()
        self.pwd_edit.setEchoMode(QLineEdit.Password)
        self.point_schema_edit = QLineEdit()
        self.point_table_edit = QLineEdit()
        self.line_schema_edit = QLineEdit()
        self.line_table_edit = QLineEdit()
        self.max_expno_schema_edit = QLineEdit()
        self.max_expno_table_edit = QLineEdit()
        self.max_expno_table_edit.setPlaceholderText("含 ptype、max_expno 的视图")

        left_form = QFormLayout()
        left_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        left_form.addRow("主机 Host：", _half_width_field(self.host_edit))
        left_form.addRow("端口 Port：", _half_width_field(self.port_edit))
        left_form.addRow("数据库 Database：", _half_width_field(self.db_edit))
        left_form.addRow("用户名 User：", _half_width_field(self.user_edit))
        left_form.addRow("密码 Password：", _half_width_field(self.pwd_edit))

        right_form = QFormLayout()
        right_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        right_form.addRow("管点表 schema：", _half_width_field(self.point_schema_edit))
        right_form.addRow("管点表名称：", _half_width_field(self.point_table_edit))
        right_form.addRow("管线表 schema：", _half_width_field(self.line_schema_edit))
        right_form.addRow("管线表名称：", _half_width_field(self.line_table_edit))
        right_form.addRow("管线最大井编号 schema：", _half_width_field(self.max_expno_schema_edit))
        right_form.addRow("管线最大井编号：", _half_width_field(self.max_expno_table_edit))

        cols = QHBoxLayout()
        cols.addLayout(left_form, 1)
        cols.addLayout(right_form, 1)

        btn_row = QHBoxLayout()
        self.test_btn = QPushButton("测试连接")
        self.test_btn.clicked.connect(self._on_test)
        self.save_conn_btn = QPushButton("保存配置")
        self.save_conn_btn.clicked.connect(self._on_save_connection)
        self.load_schema_btn = QPushButton("加载表结构")
        self.load_schema_btn.clicked.connect(self._on_load_schemas)
        btn_row.addWidget(self.test_btn)
        btn_row.addWidget(self.save_conn_btn)
        btn_row.addWidget(self.load_schema_btn)
        btn_row.addStretch()

        self.conn_status = QLabel("")
        wrap = QVBoxLayout()
        wrap.addLayout(cols)
        wrap.addLayout(btn_row)
        wrap.addWidget(self.conn_status)
        box.setLayout(wrap)
        _follow_window(box)
        return box

    def _build_role_box(self):
        box = QGroupBox("关键字段角色（从已加载字段中选择）")
        self.point_geom_combo = QComboBox()
        self.point_key_combo = QComboBox()
        self.point_wellno_combo = QComboBox()
        self.point_type_combo = QComboBox()
        self.point_gtype_combo = QComboBox()
        self.line_geom_combo = QComboBox()
        self.line_start_combo = QComboBox()
        self.line_end_combo = QComboBox()
        self.line_type_combo = QComboBox()
        self.line_gtype_combo = QComboBox()

        point_form = QFormLayout()
        point_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        point_form.addRow("点 geom：", _half_width_field(self.point_geom_combo))
        point_form.addRow("点主键：", _half_width_field(self.point_key_combo))
        point_form.addRow("点井编号：", _half_width_field(self.point_wellno_combo))
        point_form.addRow("点管线种类：", _half_width_field(self.point_type_combo))
        point_form.addRow("点 gtype：", _half_width_field(self.point_gtype_combo))
        point_wrap = QGroupBox("管点")
        point_wrap.setLayout(point_form)
        _follow_window(point_wrap)

        line_form = QFormLayout()
        line_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        line_form.addRow("线 geom：", _half_width_field(self.line_geom_combo))
        line_form.addRow("线起点号：", _half_width_field(self.line_start_combo))
        line_form.addRow("线终点号：", _half_width_field(self.line_end_combo))
        line_form.addRow("线管线种类：", _half_width_field(self.line_type_combo))
        line_form.addRow("线 gtype：", _half_width_field(self.line_gtype_combo))
        line_wrap = QGroupBox("管线")
        line_wrap.setLayout(line_form)
        _follow_window(line_wrap)

        cols = QHBoxLayout()
        cols.addWidget(point_wrap, 1)
        cols.addWidget(line_wrap, 1)
        box.setLayout(cols)
        _follow_window(box)
        return box

    def _build_schema_box(self):
        box = QGroupBox("总库表结构（由「加载表结构」写入配置）")
        layout = QVBoxLayout()
        self.schema_loaded_label = QLabel("尚未加载表结构")
        self.schema_loaded_label.setWordWrap(True)
        self.schema_loaded_label.setMinimumWidth(0)
        layout.addWidget(self.schema_loaded_label)

        self.schema_tabs = QTabWidget()
        self.point_cols_table = self._make_cols_table()
        self.line_cols_table = self._make_cols_table()
        self.pipe_types_list = QListWidget()
        self.pipe_types_list.setSelectionMode(QListWidget.NoSelection)
        _follow_window(self.pipe_types_list)
        self.schema_tabs.addTab(self.point_cols_table, "管点表字段")
        self.schema_tabs.addTab(self.line_cols_table, "管线表字段")
        self.schema_tabs.addTab(self.pipe_types_list, "管类")
        layout.addWidget(self.schema_tabs)

        box.setLayout(layout)
        _follow_window(box)
        _follow_window(self.schema_tabs)
        box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.schema_tabs.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        return box

    def _make_cols_table(self):
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["字段名", "类型", "udt", "可空"])
        table.setMinimumWidth(0)
        table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
        table.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        header = table.horizontalHeader()
        header.setMinimumSectionSize(40)
        header.setStretchLastSection(True)
        for index in range(4):
            header.setSectionResizeMode(index, QHeaderView.Stretch)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        return table

    def _load_connection_form(self):
        info, _ = load_connection_info()
        self.host_edit.setText(info.host or "")
        self.port_edit.setValue(info.port or 5432)
        self.db_edit.setText(info.dbname or "")
        self.user_edit.setText(info.user or "")
        self.pwd_edit.setText(info.password or "")

    def _populate_table_names(self):
        pg = self.shared_config.get_pg_config()
        schemas = self.shared_config.get_pg_table_schemas()
        point = schemas.get("point") or {}
        line = schemas.get("line") or {}
        pgp = pg.get("point") or {}
        pgl = pg.get("line") or {}
        mx = pg.get("max_expno") or {}
        self.point_schema_edit.setText(point.get("schema") or pgp.get("schema") or "public")
        self.point_table_edit.setText(point.get("table") or pgp.get("table") or "")
        self.line_schema_edit.setText(line.get("schema") or pgl.get("schema") or "public")
        self.line_table_edit.setText(line.get("table") or pgl.get("table") or "")
        self.max_expno_schema_edit.setText(mx.get("schema") or "public")
        self.max_expno_table_edit.setText(mx.get("table") or "")

    def _fill_cols_table(self, table_widget, columns):
        table_widget.setRowCount(0)
        for col in columns or []:
            row = table_widget.rowCount()
            table_widget.insertRow(row)
            table_widget.setItem(row, 0, QTableWidgetItem(col.get("name") or ""))
            table_widget.setItem(row, 1, QTableWidgetItem(col.get("data_type") or ""))
            table_widget.setItem(row, 2, QTableWidgetItem(col.get("udt_name") or ""))
            table_widget.setItem(row, 3, QTableWidgetItem(col.get("is_nullable") or ""))

    def _populate_schema_view(self):
        schemas = self.shared_config.get_pg_table_schemas()
        point = schemas.get("point") or {}
        line = schemas.get("line") or {}
        pipe_types = schemas.get("pipe_types") or {}
        self._fill_cols_table(self.point_cols_table, point.get("columns"))
        self._fill_cols_table(self.line_cols_table, line.get("columns"))
        self._fill_pipe_types_list(pipe_types)
        parts = []
        if point.get("loaded_at"):
            parts.append(
                f"点表 {point.get('schema')}.{point.get('table')} "
                f"({len(point.get('columns') or [])} 列, {point.get('loaded_at')})"
            )
        if line.get("loaded_at"):
            parts.append(
                f"线表 {line.get('schema')}.{line.get('table')} "
                f"({len(line.get('columns') or [])} 列, {line.get('loaded_at')})"
            )
        if pipe_types.get("loaded_at") or pipe_types.get("error"):
            n = len(pipe_types.get("codes") or [])
            view_name = "%s.%s" % (
                pipe_types.get("schema") or "public",
                pipe_types.get("table") or "（未配置）",
            )
            if pipe_types.get("error"):
                parts.append(
                    "管类 %s（已清空，%s）" % (view_name, pipe_types.get("error"))
                )
            else:
                stamp = pipe_types.get("loaded_at") or ""
                parts.append("管类 %s (%d 类, %s)" % (view_name, n, stamp))
        self.schema_loaded_label.setText(
            "；".join(parts) if parts else "尚未加载表结构"
        )

    def _fill_pipe_types_list(self, pipe_types):
        self.pipe_types_list.clear()
        codes = (pipe_types or {}).get("codes") or []
        error = ((pipe_types or {}).get("error") or "").strip()
        gray = QColor(160, 160, 160)
        if not codes:
            text = "（无可用管类，总数据库将全部禁用）"
            if error:
                text = "（无可用管类：%s）" % error
            item = QListWidgetItem(text)
            item.setFlags(Qt.NoItemFlags)
            item.setForeground(gray)
            self.pipe_types_list.addItem(item)
            return
        for code in codes:
            item = QListWidgetItem(pipeline_display_name(code))
            item.setFlags(Qt.ItemIsEnabled)
            self.pipe_types_list.addItem(item)

    def _fill_combo(self, combo, columns, current):
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("", "")
        names = [c.get("name") for c in (columns or []) if c.get("name")]
        for name in names:
            combo.addItem(name, name)
        if current:
            idx = combo.findData(current)
            if idx < 0:
                combo.addItem(current, current)
                idx = combo.findData(current)
            combo.setCurrentIndex(max(idx, 0))
        combo.blockSignals(False)

    def _populate_role_combos(self):
        schemas = self.shared_config.get_pg_table_schemas()
        pg = self.shared_config.get_pg_config()
        point_cols = (schemas.get("point") or {}).get("columns") or []
        line_cols = (schemas.get("line") or {}).get("columns") or []
        pgp = pg.get("point") or {}
        pgl = pg.get("line") or {}
        self._fill_combo(self.point_geom_combo, point_cols, pgp.get("geom_col") or "geom")
        self._fill_combo(self.point_key_combo, point_cols, pgp.get("key_field"))
        self._fill_combo(self.point_wellno_combo, point_cols, pgp.get("wellno_field") or "expno")
        self._fill_combo(self.point_type_combo, point_cols, pgp.get("type_field"))
        self._fill_combo(self.point_gtype_combo, point_cols, pgp.get("gtype_field") or "gtype")
        self._fill_combo(self.line_geom_combo, line_cols, pgl.get("geom_col") or "geom")
        self._fill_combo(self.line_start_combo, line_cols, pgl.get("start_field"))
        self._fill_combo(self.line_end_combo, line_cols, pgl.get("end_field"))
        self._fill_combo(self.line_type_combo, line_cols, pgl.get("type_field"))
        self._fill_combo(self.line_gtype_combo, line_cols, pgl.get("gtype_field") or "gtype")

    def get_connection_info(self):
        return PgConnectionInfo(
            host=self.host_edit.text().strip(),
            port=self.port_edit.value(),
            dbname=self.db_edit.text().strip(),
            user=self.user_edit.text().strip(),
            password=self.pwd_edit.text(),
        )

    def _on_test(self):
        info = self.get_connection_info()
        ok, msg = test_pg_connection(info)
        if ok:
            self.conn_status.setText("✔ 连接成功")
            QMessageBox.information(self, "测试连接", "连接成功")
        else:
            self.conn_status.setText("✘ 连接失败")
            QMessageBox.critical(self, "测试连接", f"连接失败：\n{msg}")

    def _on_save_connection(self):
        info = self.get_connection_info()
        if not info.host or not info.dbname or not info.user:
            QMessageBox.warning(self, "保存配置", "请至少填写主机、数据库名和用户名")
            return
        save_connection_info(info)
        self.flush_table_names_to_config()
        self.conn_status.setText("✔ 连接配置已保存")
        QMessageBox.information(
            self, "保存配置",
            "PostgreSQL 连接、点/线表名以及管线最大井编号视图已保存。"
        )

    def _on_load_schemas(self):
        info = self.get_connection_info()
        point_schema = self.point_schema_edit.text().strip() or "public"
        point_table = self.point_table_edit.text().strip()
        line_schema = self.line_schema_edit.text().strip() or "public"
        line_table = self.line_table_edit.text().strip()
        if not point_table or not line_table:
            QMessageBox.warning(self, "加载表结构", "请先填写管点表名称和管线表名称")
            return
        try:
            point_snap = fetch_table_columns(info, point_schema, point_table)
            line_snap = fetch_table_columns(info, line_schema, line_table)
        except Exception as exc:
            QMessageBox.critical(self, "加载表结构失败", str(exc))
            return

        schemas = self.shared_config.get_pg_table_schemas()
        schemas["point"] = point_snap
        schemas["line"] = line_snap
        self.shared_config.set_pg_table_schemas(schemas)
        self.flush_table_names_to_config()
        self.flush_roles_to_config()
        pipe_snap = refresh_pg_pipe_types(
            self.shared_config,
            conn_info=info,
            persist=False,
            view_schema=self.max_expno_schema_edit.text().strip() or "public",
            view_table=self.max_expno_table_edit.text().strip(),
        )
        self._populate_schema_view()
        self._populate_role_combos()
        self.schema_tabs.setCurrentWidget(self.pipe_types_list)
        self.conn_status.setText("✔ 表结构已加载（覆盖）")
        pipe_codes = pipe_snap.get("codes") or []
        pipe_err = (pipe_snap.get("error") or "").strip()
        if pipe_err:
            pipe_msg = "管类已清空（总数据库将全部禁用）：%s" % pipe_err
        elif pipe_codes:
            pipe_msg = "管类 %d 项：%s" % (
                len(pipe_codes),
                "、".join(pipeline_display_name(c) for c in pipe_codes),
            )
        else:
            pipe_msg = "管类视图表无记录，总数据库将全部禁用。"
        QMessageBox.information(
            self, "加载表结构",
            f"已覆盖写入点表 {len(point_snap.get('columns') or [])} 列、"
            f"线表 {len(line_snap.get('columns') or [])} 列。\n"
            f"{pipe_msg}\n"
            "请再点配置管理底部「保存」写入 profiles.json。"
        )

    def flush_table_names_to_config(self):
        current = self.shared_config.get_pg_config()
        schemas = self.shared_config.get_pg_table_schemas()
        point_schema = self.point_schema_edit.text().strip() or "public"
        point_table = self.point_table_edit.text().strip()
        line_schema = self.line_schema_edit.text().strip() or "public"
        line_table = self.line_table_edit.text().strip()
        current["point"]["schema"] = point_schema
        current["point"]["table"] = point_table
        current["line"]["schema"] = line_schema
        current["line"]["table"] = line_table
        current.setdefault("max_expno", {})
        current["max_expno"]["schema"] = self.max_expno_schema_edit.text().strip() or "public"
        current["max_expno"]["table"] = self.max_expno_table_edit.text().strip()
        current["max_expno"]["ptype_field"] = current["max_expno"].get("ptype_field") or "ptype"
        current["max_expno"]["max_field"] = current["max_expno"].get("max_field") or "max_expno"
        schemas["point"]["schema"] = point_schema
        schemas["point"]["table"] = point_table
        schemas["line"]["schema"] = line_schema
        schemas["line"]["table"] = line_table
        self.shared_config.set_pg_config(current)
        self.shared_config.set_pg_table_schemas(schemas)

    def flush_roles_to_config(self):
        current = self.shared_config.get_pg_config()
        current["point"].update({
            "geom_col": self.point_geom_combo.currentData() or self.point_geom_combo.currentText() or "geom",
            "key_field": self.point_key_combo.currentData() or self.point_key_combo.currentText() or "",
            "wellno_field": self.point_wellno_combo.currentData() or self.point_wellno_combo.currentText() or "expno",
            "type_field": self.point_type_combo.currentData() or self.point_type_combo.currentText() or "",
            "gtype_field": self.point_gtype_combo.currentData() or self.point_gtype_combo.currentText() or "gtype",
        })
        current["line"].update({
            "geom_col": self.line_geom_combo.currentData() or self.line_geom_combo.currentText() or "geom",
            "start_field": self.line_start_combo.currentData() or self.line_start_combo.currentText() or "",
            "end_field": self.line_end_combo.currentData() or self.line_end_combo.currentText() or "",
            "type_field": self.line_type_combo.currentData() or self.line_type_combo.currentText() or "",
            "gtype_field": self.line_gtype_combo.currentData() or self.line_gtype_combo.currentText() or "gtype",
        })
        self.shared_config.set_pg_config(current)

    def flush_to_config(self):
        self.flush_table_names_to_config()
        self.flush_roles_to_config()
