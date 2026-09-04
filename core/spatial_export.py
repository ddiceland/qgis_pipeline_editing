# -*- coding: utf-8 -*-
"""按裁剪多边形从 PostgreSQL 查询管点、管线，并补全跨边界线的起终点。"""

from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject

from .pipe_type_filter import FZ_PIPE_CODE, build_export_filter_clause, split_pipeline_selection
from .sql_ident import ident_name, quote_ident, quote_qualified


def _row_value(row, field_name):
    name = ident_name(field_name)
    if not name or not isinstance(row, dict):
        return None
    if name in row:
        return row.get(name)
    upper = name.upper()
    for key, value in row.items():
        if ident_name(key).upper() == upper:
            return value
    return None


def _well_key(value):
    """井编号比较用：转字符串并去掉首尾空白。"""
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _geom_wkt_sql(geom_sql):
    return "regexp_replace(ST_AsEWKT(%s), '^SRID=[0-9]+;', '')" % geom_sql


def transform_geom_to_srid(geometry, source_crs, target_srid):
    """画布几何转到目标表 SRID，返回 WKT。SRID 为 0 时不变换。"""
    try:
        srid = int(target_srid or 0)
    except (TypeError, ValueError):
        srid = 0
    if srid > 0:
        target_crs = QgsCoordinateReferenceSystem("EPSG:%s" % srid)
        if target_crs.isValid() and source_crs is not None and source_crs != target_crs:
            transform = QgsCoordinateTransform(
                source_crs, target_crs, QgsProject.instance()
            )
            geom_copy = type(geometry)(geometry)
            geom_copy.transform(transform)
            return geom_copy.asWkt()
    return geometry.asWkt()


def _relation_sql(cfg):
    return quote_qualified(cfg.get("schema") or "public", cfg.get("table"))


def _geom_sql(cfg):
    return quote_ident(cfg.get("geom_col") or "geom")


def fetch_lines_in_polygon(cursor, pg_line_cfg, polygon_wkt, srid,
                           pipeline_type=None, fz_base_types=None):
    geom_sql = _geom_sql(pg_line_cfg)
    filter_sql, filter_params = build_export_filter_clause(
        pg_line_cfg, pipeline_type, fz_base_types
    )
    sql = """
        SELECT *, %s AS __geom_wkt
        FROM %s
        WHERE ST_Intersects(
            %s,
            ST_SetSRID(ST_GeomFromText(%%s), %%s)
        )%s
    """ % (_geom_wkt_sql(geom_sql), _relation_sql(pg_line_cfg), geom_sql, filter_sql)
    cursor.execute(sql, (polygon_wkt, srid, *filter_params))
    return cursor.fetchall()


def fetch_points_in_polygon(cursor, pg_point_cfg, polygon_wkt, srid,
                            pipeline_type=None, fz_base_types=None):
    geom_sql = _geom_sql(pg_point_cfg)
    filter_sql, filter_params = build_export_filter_clause(
        pg_point_cfg, pipeline_type, fz_base_types
    )
    sql = """
        SELECT *, %s AS __geom_wkt
        FROM %s
        WHERE ST_Intersects(
            %s,
            ST_SetSRID(ST_GeomFromText(%%s), %%s)
        )%s
    """ % (_geom_wkt_sql(geom_sql), _relation_sql(pg_point_cfg), geom_sql, filter_sql)
    cursor.execute(sql, (polygon_wkt, srid, *filter_params))
    return cursor.fetchall()


def fetch_points_by_keys(cursor, pg_point_cfg, key_values, match_field,
                         pipeline_type=None, fz_base_types=None):
    """按指定字段（井编号）批量取点，不做空间过滤。"""
    if not key_values:
        return []
    field_name = ident_name(match_field)
    if not field_name:
        return []
    geom_sql = _geom_sql(pg_point_cfg)
    filter_sql, filter_params = build_export_filter_clause(
        pg_point_cfg, pipeline_type, fz_base_types
    )
    sql = """
        SELECT *, %s AS __geom_wkt
        FROM %s
        WHERE btrim(%s::text) = ANY(%%s)%s
    """ % (
        _geom_wkt_sql(geom_sql),
        _relation_sql(pg_point_cfg),
        quote_ident(field_name),
        filter_sql,
    )
    str_values = []
    seen = set()
    for value in key_values:
        key = _well_key(value)
        if key and key not in seen:
            seen.add(key)
            str_values.append(key)
    if not str_values:
        return []
    cursor.execute(sql, (str_values, *filter_params))
    return cursor.fetchall()


def has_pipe_data_in_polygon(cursor, pg_config, pipeline_type, polygon_wkt, srid,
                             fz_base_types=None):
    for cfg in (pg_config["line"], pg_config["point"]):
        geom_sql = _geom_sql(cfg)
        filter_sql, filter_params = build_export_filter_clause(
            cfg, pipeline_type, fz_base_types
        )
        sql = """
            SELECT 1
            FROM %s
            WHERE ST_Intersects(
                %s,
                ST_SetSRID(ST_GeomFromText(%%s), %%s)
            )%s
            LIMIT 1
        """ % (_relation_sql(cfg), geom_sql, filter_sql)
        cursor.execute(sql, (polygon_wkt, srid, *filter_params))
        if cursor.fetchone():
            return True
    return False


def filter_pipeline_types_with_data(pg_connector, pg_config, pipeline_types,
                                    polygon_geometry, canvas_crs, log=None):
    if not pipeline_types:
        return [], []

    base_types, include_fz = split_pipeline_selection(pipeline_types)
    fz_base_types = base_types if include_fz else None

    cursor = pg_connector.get_cursor()
    srid = pg_connector.get_srid(
        pg_config["line"].get("schema") or "public",
        pg_config["line"].get("table"),
        pg_config["line"].get("geom_col") or "geom",
    )
    polygon_wkt = transform_geom_to_srid(polygon_geometry, canvas_crs, srid)

    with_data = []
    skipped = []
    for code in pipeline_types:
        extra_fz = fz_base_types if code == FZ_PIPE_CODE else None
        if has_pipe_data_in_polygon(
            cursor, pg_config, code, polygon_wkt, srid, fz_base_types=extra_fz
        ):
            with_data.append(code)
        else:
            skipped.append(code)
    cursor.close()

    if log and skipped:
        log("范围内无数据，已自动跳过：%s" % "、".join(skipped))
    return with_data, skipped


def collect_points_for_export(cursor, pg_config, pipeline_type, polygon_wkt, srid,
                              fz_base_types=None):
    """范围内的点 + 相交线上的起终点（按点表井编号关联并去重）。"""
    pg_line_cfg = pg_config["line"]
    pg_point_cfg = pg_config["point"]
    wellno_field = ident_name(pg_point_cfg.get("wellno_field"))
    start_field = ident_name(pg_line_cfg.get("start_field"))
    end_field = ident_name(pg_line_cfg.get("end_field"))

    fz_filter = fz_base_types if pipeline_type == FZ_PIPE_CODE else None

    line_rows = fetch_lines_in_polygon(
        cursor, pg_line_cfg, polygon_wkt, srid, pipeline_type, fz_filter
    )
    point_rows = fetch_points_in_polygon(
        cursor, pg_point_cfg, polygon_wkt, srid, pipeline_type, fz_filter
    )

    if line_rows:
        missing = []
        if not wellno_field:
            missing.append("点井编号")
        if not start_field:
            missing.append("线起点号")
        if not end_field:
            missing.append("线终点号")
        if missing:
            raise RuntimeError(
                "导出补点需要在「配置管理 → 数据库连接」中设置：%s。"
                "管点与管线通过井编号关联，不能使用点表主键。"
                % "、".join(missing)
            )

    existing_keys = set()
    if wellno_field:
        for row in point_rows:
            key = _well_key(_row_value(row, wellno_field))
            if key:
                existing_keys.add(key)

    referenced_keys = set()
    for row in line_rows:
        if start_field:
            start = _well_key(_row_value(row, start_field))
            if start and start not in existing_keys:
                referenced_keys.add(start)
        if end_field:
            end = _well_key(_row_value(row, end_field))
            if end and end not in existing_keys:
                referenced_keys.add(end)

    if referenced_keys:
        extra_points = fetch_points_by_keys(
            cursor, pg_point_cfg, referenced_keys, wellno_field,
            pipeline_type, fz_filter
        )
        extras = []
        for row in extra_points:
            key = _well_key(_row_value(row, wellno_field))
            if key and key in existing_keys:
                continue
            extras.append(row)
            if key:
                existing_keys.add(key)
        if extras:
            point_rows = list(point_rows) + extras

    return point_rows, line_rows
