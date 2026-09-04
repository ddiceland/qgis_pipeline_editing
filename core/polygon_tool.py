# -*- coding: utf-8 -*-
"""
在画布上绘制任意多边形范围框的交互工具。

交互方式：
- 左键单击：添加一个顶点
- 右键单击 / 双击左键：结束绘制，触发回调，返回 QgsGeometry（多边形，画布CRS下）
- Backspace / Ctrl+Z：撤销上一个顶点
- Esc：取消当前绘制
"""
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QCursor
from qgis.gui import QgsMapTool, QgsRubberBand, QgsVertexMarker
from qgis.core import QgsWkbTypes, QgsGeometry, QgsPointXY


class PolygonDrawTool(QgsMapTool):
    def __init__(self, canvas, on_finished, on_cancelled=None):
        super().__init__(canvas)
        self.canvas = canvas
        self.on_finished = on_finished
        self.on_cancelled = on_cancelled
        self.points = []
        self._cursor_point = None
        self._ignore_next_release = False

        self.polygon_band = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
        self.polygon_band.setColor(QColor(255, 0, 0, 60))
        self.polygon_band.setStrokeColor(QColor(255, 0, 0, 200))
        self.polygon_band.setWidth(2)

        self.vertex_markers = []

    def activate(self):
        super().activate()
        self.canvas.setCursor(QCursor(Qt.CrossCursor))

    def deactivate(self):
        self.canvas.unsetCursor()
        self._reset()
        super().deactivate()

    def canvasReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            self._finish()
            return
        if event.button() != Qt.LeftButton:
            return
        if self._ignore_next_release:
            self._ignore_next_release = False
            return

        pt = self.toMapCoordinates(event.pos())
        self.points.append(QgsPointXY(pt))
        self._cursor_point = QgsPointXY(pt)
        self._add_vertex_marker(pt)
        self._update_band()

    def canvasMoveEvent(self, event):
        if not self.points:
            return
        self._cursor_point = self.toMapCoordinates(event.pos())
        self._update_band()

    def canvasDoubleClickEvent(self, event):
        self._ignore_next_release = True
        self._finish()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._cancel()
            return
        if event.key() == Qt.Key_Backspace:
            self._undo_last_vertex()
            return
        if event.key() == Qt.Key_Z and event.modifiers() & Qt.ControlModifier:
            self._undo_last_vertex()

    def _undo_last_vertex(self):
        """撤销最近添加的一个顶点。"""
        if not self.points:
            return
        self.points.pop()
        if self.vertex_markers:
            marker = self.vertex_markers.pop()
            self.canvas.scene().removeItem(marker)
        if self.points:
            self._cursor_point = QgsPointXY(self.points[-1])
            self._update_band()
        else:
            self._cursor_point = None
            self.polygon_band.reset(QgsWkbTypes.PolygonGeometry)
        self.canvas.refresh()

    def _add_vertex_marker(self, point):
        marker = QgsVertexMarker(self.canvas)
        marker.setCenter(point)
        marker.setColor(QColor(255, 0, 0))
        marker.setIconSize(10)
        marker.setIconType(QgsVertexMarker.ICON_CROSS)
        marker.setPenWidth(2)
        self.vertex_markers.append(marker)

    def _update_band(self):
        """用半透明填充多边形预览当前范围（首个顶点后即显示预览面）。"""
        self.polygon_band.reset(QgsWkbTypes.PolygonGeometry)
        if not self.points:
            return

        ring = self._preview_ring()
        if len(ring) < 3:
            return

        for i, p in enumerate(ring):
            self.polygon_band.addPoint(p, i == len(ring) - 1)

        self.polygon_band.show()

    def _preview_ring(self):
        if len(self.points) == 1:
            start = self.points[0]
            cursor = self._cursor_point or start
            if cursor.x() == start.x() and cursor.y() == start.y():
                step = max(self.canvas.mapUnitsPerPixel(), 1e-9) * 8
                cursor = QgsPointXY(start.x() + step, start.y())
            return [start, cursor, start]

        ring = list(self.points)
        if self._cursor_point is not None:
            ring.append(self._cursor_point)
        return ring

    def _finish(self):
        if len(self.points) < 3:
            self._cancel()
            return
        geom = QgsGeometry.fromPolygonXY([self.points[:]])
        self._reset()
        if self.on_finished:
            self.on_finished(geom)

    def _cancel(self):
        self._reset()
        if self.on_cancelled:
            self.on_cancelled()

    def _reset(self):
        self.points = []
        self._cursor_point = None
        self._ignore_next_release = False
        self.polygon_band.reset(QgsWkbTypes.PolygonGeometry)
        for marker in self.vertex_markers:
            self.canvas.scene().removeItem(marker)
        self.vertex_markers = []
