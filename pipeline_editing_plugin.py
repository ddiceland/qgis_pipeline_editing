# -*- coding: utf-8 -*-
import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction


class PipelineEditingPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.dock = None
        self.action = None
        self.plugin_dir = os.path.dirname(__file__)
        self.plugin_icon = self._load_plugin_icon()

    def _load_plugin_icon(self):
        icon_path = os.path.join(self.plugin_dir, "resources", "icon.png")
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        return QIcon()

    def initGui(self):
        self.action = QAction(self.plugin_icon, "管网编辑工具", self.iface.mainWindow())
        self.action.setObjectName("PipelineEditingPluginAction")
        self.action.setToolTip("管网编辑工具")
        self.action.setCheckable(True)
        # 使用 triggered 而非 toggled：visibilityChanged 里 setChecked 不会再反向触发关闭面板
        self.action.triggered.connect(self._toggle_dock)

        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("管网编辑工具", self.action)

    def unload(self):
        if self.dock is not None:
            try:
                self.dock.visibilityChanged.disconnect(self._on_dock_visibility_changed)
            except (TypeError, RuntimeError):
                pass
            self.iface.removeDockWidget(self.dock)
            self.dock = None
        self.iface.removePluginMenu("管网编辑工具", self.action)
        self.iface.removeToolBarIcon(self.action)

    def _toggle_dock(self, checked):
        if checked:
            if self.dock is None:
                from .ui.main_dock import PipelineEditingDock
                self.dock = PipelineEditingDock(self.iface)
                if not self.plugin_icon.isNull():
                    self.dock.setWindowIcon(self.plugin_icon)
                self.dock.visibilityChanged.connect(self._on_dock_visibility_changed)
                self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
            self.dock.show()
            self.dock.raise_()
        else:
            if self.dock is not None:
                self.dock.hide()

    def _on_dock_visibility_changed(self, visible):
        if self.action is None:
            return
        # 避免 setChecked 与 triggered/toggled 形成反馈，导致面板被误关
        self.action.blockSignals(True)
        self.action.setChecked(visible)
        self.action.blockSignals(False)
