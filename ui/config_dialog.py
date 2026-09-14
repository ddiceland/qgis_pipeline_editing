# -*- coding: utf-8 -*-
"""配置管理对话框。"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QLabel, QPushButton, QMessageBox,
)

from .db_connection_panel import DbConnectionPanel
from .mdb_render_config_panel import MdbRenderConfigPanel
from .mdb_structure_panel import MdbStructurePanel
from .rule_sets_panel import RuleSetsPanel
from .shared_config_panels import PipeColorConfigPanel
from .structure_mapping_panel import StructureMappingPanel


class ConfigDialog(QDialog):
    def __init__(self, shared_config, parent=None):
        super().__init__(parent)
        self.shared_config = shared_config
        self.setWindowTitle("配置管理")
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowTitleHint
            | Qt.WindowSystemMenuHint
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        self.resize(1000, 680)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.db_panel = DbConnectionPanel(shared_config, self)
        self.tabs.addTab(self.db_panel, "数据库连接")

        self.color_panel = PipeColorConfigPanel(shared_config, self)
        self.tabs.addTab(self.color_panel, "管类颜色")

        self.rule_sets_panel = RuleSetsPanel(shared_config, self)
        self.tabs.addTab(self.rule_sets_panel, "规则集")

        self.render_panel = MdbRenderConfigPanel(shared_config, self)
        self.tabs.addTab(self.render_panel, "MDB库渲染")

        self.mdb_structure_panel = MdbStructurePanel(shared_config, self)
        self.tabs.addTab(self.mdb_structure_panel, "MDB库结构")

        self.structure_mapping_panel = StructureMappingPanel(shared_config, self)
        self.tabs.addTab(self.structure_mapping_panel, "结构映射")

        bottom = QHBoxLayout()
        tip = QLabel(
            "配置保存在本插件目录 config/profiles.json。"
            "先配「MDB库渲染」（产生内部编号），再配同编号的「MDB库结构」和「结构映射」。"
            "「规则集」供结构映射做字段值转换。"
        )
        tip.setWordWrap(True)
        bottom.addWidget(tip, 1)
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._on_save)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.reject)
        bottom.addWidget(save_btn)
        bottom.addWidget(close_btn)
        layout.addLayout(bottom)

        if getattr(shared_config, "_migrated", False):
            try:
                shared_config.save()
                QMessageBox.information(
                    self, "配置迁移",
                    "已整理配置：渲染组与库结构改为共用内部编号（汉字名称转为拼音），"
                    "并迁移了对应的结构映射。"
                )
            except OSError as exc:
                QMessageBox.warning(self, "配置迁移", f"迁移后保存失败：{exc}")

    def _on_save(self):
        self.db_panel.flush_to_config()
        self.shared_config.set_pipe_colors(self.color_panel.to_colors())
        self.rule_sets_panel.flush_to_config()
        self.render_panel.flush_to_config()
        self.mdb_structure_panel.flush_to_config()
        self.structure_mapping_panel.flush_to_config()
        try:
            self.shared_config.save()
        except OSError as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        # 刷新映射页结构下拉与规则集选项
        self.structure_mapping_panel.reload_from_config()
        QMessageBox.information(
            self, "提示",
            f"配置已保存到：\n{self.shared_config.config_path}"
        )
