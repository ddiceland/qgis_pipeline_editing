# -*- coding: utf-8 -*-
"""
PostgreSQL/PostGIS 连接与图层加载。

画布加载使用 QGIS 原生 postgres provider（QgsVectorLayer）。
"""
from qgis.core import (
    QgsDataSourceUri, QgsProject, QgsVectorLayer, QgsVectorSimplifyMethod,
)

from .pg_connection import PgConnectionInfo
from .pg_layer_style import apply_pipeline_symbology
from .pipe_type_filter import (
    build_layer_subset_filter, symbology_pipeline_types, split_pipeline_selection,
)

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None


class PgConnector:
    PIPELINE_LAYER_NAMES = ("总管点", "总管线")
    PIPELINE_GROUP_NAME = "总库"

    @staticmethod
    def build_pipeline_subset_filter(type_field, gtype_field, pipeline_types, all_type_count=None):
        return build_layer_subset_filter(type_field, gtype_field, pipeline_types, all_type_count)

    def __init__(self, conn_info: PgConnectionInfo):
        self.conn_info = conn_info
        self._conn = None

    def connect(self):
        if psycopg2 is None:
            raise RuntimeError(
                "未找到 psycopg2 模块，请在QGIS的Python环境里安装：\n"
                "python3 -m pip install psycopg2-binary"
            )
        self._conn = psycopg2.connect(
            host=self.conn_info.host,
            port=self.conn_info.port,
            dbname=self.conn_info.dbname,
            user=self.conn_info.user,
            password=self.conn_info.password,
        )
        return self._conn


    def get_cursor(self):
        if self._conn is None or self._conn.closed:
            self.connect()
        return self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def close(self):
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
        self._conn = None

    def remove_pg_layers(self):
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        for name in self.PIPELINE_LAYER_NAMES:
            for layer in list(project.mapLayersByName(name)):
                project.removeMapLayer(layer.id())
        group = root.findGroup(self.PIPELINE_GROUP_NAME)
        if group is not None and not group.children():
            root.removeChildNode(group)

    def _ensure_pipeline_group(self):
        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup(self.PIPELINE_GROUP_NAME)
        if group is None:
            group = root.insertGroup(0, self.PIPELINE_GROUP_NAME)
        return group

    def _apply_large_table_optimizations(self, layer):
        """针对百万级数据优化：几何简化、关闭要素计数（兼容 QGIS 3.18）。"""
        try:
            simplification = QgsVectorSimplifyMethod()
            hint = getattr(QgsVectorSimplifyMethod, "GeometrySimplification", None)
            if hint is None:
                simplify_hint = getattr(QgsVectorSimplifyMethod, "SimplifyHint", None)
                if simplify_hint is not None:
                    hint = getattr(simplify_hint, "GeometrySimplification", 1)
                else:
                    hint = 1
            simplification.setSimplifyHints(hint)
            simplification.setThreshold(1.0)
            simplification.setForceLocalOptimization(True)
            layer.setSimplifyMethod(simplification)
        except Exception:
            pass

        try:
            node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
            if node is not None:
                node.setCustomProperty("showFeatureCount", False)
        except Exception:
            pass

    def load_layer_to_canvas(self, schema, table, geom_col, layer_name,
                             key_column=None, subset_filter="", visible=True):
        uri = QgsDataSourceUri()
        uri.setConnection(
            self.conn_info.host, str(self.conn_info.port),
            self.conn_info.dbname, self.conn_info.user, self.conn_info.password
        )
        uri.setDataSource(schema, table, geom_col, subset_filter or "", key_column or "")
        uri.setParam("estimatedmetadata", "true")
        uri.setParam("selectatid", "false")

        layer = QgsVectorLayer(uri.uri(False), layer_name, "postgres")
        if not layer.isValid():
            raise RuntimeError(f"图层加载失败：{schema}.{table}（请检查表名/geom字段是否正确）")

        self._apply_large_table_optimizations(layer)
        QgsProject.instance().addMapLayer(layer, False)
        return layer

    def load_pipeline_layers(self, pg_config, pipeline_types, color_map, all_base_types):
        """加载总管点/总管线，并按 ptype 分类着色（FZ 辅助数据沿用原 ptype 颜色）。"""
        self.remove_pg_layers()

        type_field_point = (pg_config["point"].get("type_field") or "ptype").strip()
        type_field_line = (pg_config["line"].get("type_field") or "ptype").strip()
        gtype_field_point = (pg_config["point"].get("gtype_field") or "gtype").strip()
        gtype_field_line = (pg_config["line"].get("gtype_field") or "gtype").strip()

        point_filter = self.build_pipeline_subset_filter(
            type_field_point, gtype_field_point, pipeline_types, len(all_base_types)
        )
        line_filter = self.build_pipeline_subset_filter(
            type_field_line, gtype_field_line, pipeline_types, len(all_base_types)
        )

        style_types = symbology_pipeline_types(pipeline_types, all_base_types)
        base_types, include_fz = split_pipeline_selection(pipeline_types)
        symbology_types = base_types if include_fz else style_types

        point_layer = self.load_layer_to_canvas(
            pg_config["point"]["schema"],
            pg_config["point"]["table"],
            pg_config["point"]["geom_col"],
            "总管点",
            key_column=pg_config["point"].get("key_field") or None,
            subset_filter=point_filter,
            visible=False,
        )
        line_layer = self.load_layer_to_canvas(
            pg_config["line"]["schema"],
            pg_config["line"]["table"],
            pg_config["line"]["geom_col"],
            "总管线",
            key_column=pg_config["line"].get("key_field")
            or pg_config["point"].get("key_field")
            or None,
            subset_filter=line_filter,
        )

        group = self._ensure_pipeline_group()
        group.addLayer(point_layer)
        group.addLayer(line_layer)
        for layer, visible in ((point_layer, False), (line_layer, True)):
            self._apply_large_table_optimizations(layer)
            node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
            if node is not None:
                node.setItemVisibilityChecked(visible)

        apply_pipeline_symbology(
            point_layer, "point", type_field_point, gtype_field_point,
            symbology_types, color_map, include_fz,
        )
        apply_pipeline_symbology(
            line_layer, "line", type_field_line, gtype_field_line,
            symbology_types, color_map, include_fz,
        )
        return point_layer, line_layer

    def get_srid(self, schema, table, geom_col):
        cur = self.get_cursor()
        try:
            cur.execute(
                "SELECT Find_SRID(%s, %s, %s) AS srid",
                (schema or "public", table, geom_col),
            )
            row = cur.fetchone()
        finally:
            cur.close()
        if not row:
            return 0
        try:
            return int(row.get("srid") or 0)
        except (TypeError, ValueError):
            return 0
