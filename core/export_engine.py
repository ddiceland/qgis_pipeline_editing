# -*- coding: utf-8 -*-
"""
总库导出：按裁剪范围从 PostgreSQL 取数，再按 MDB 库结构 + 导出映射写出 MDB 或 GDB。
"""

from qgis.core import QgsCoordinateReferenceSystem, QgsGeometry, QgsProject

from .gdb_writer import GdbWriter, gdb_write_unavailable_message, writable_gdb_drivers
from .mdb.coord_utils import map_xy_to_data_xy
from .mdb_decimals import apply_decimals_to_values
from .mdb.mdb_connector import MdbConnection, create_empty_mdb, python_to_odbc
from .mdb.structure_convert import (
    _group_by_id,
    _kind_mapping_rows,
    _row_get,
    _target_fields,
    _target_table_name,
    mapping_has_field_rows,
)
from .pipe_catalog import pipeline_display_name
from .pipe_type_filter import FZ_PIPE_CODE, split_pipeline_selection
from .rule_apply import apply_rule_value
from .spatial_export import collect_points_for_export, transform_geom_to_srid
from .sql_ident import ident_name
from .xyz_mapping import is_xyz_rule


class ExportResult:
    def __init__(self):
        self.profile_results = []
        self.errors = []
        self.cancelled = False

    def add(self, pipe_code, line_count, point_count):
        self.profile_results.append({
            "profile": pipe_code,
            "line_count": line_count,
            "point_count": point_count,
        })

    def add_error(self, pipe_code, message):
        self.errors.append({"profile": pipe_code, "message": message})


class ExportStopped(Exception):
    """用户点击「停止导出」。"""


def _export_cancelled(progress_dialog):
    return progress_dialog is not None and progress_dialog.was_cancelled()


def _check_export_stop(progress_dialog):
    if _export_cancelled(progress_dialog):
        raise ExportStopped()


def _xyz_from_wkt(wkt):
    geom = QgsGeometry.fromWkt(wkt or "")
    if geom is None or geom.isEmpty():
        return None, None, None
    point = geom.vertexAt(0) if hasattr(geom, "vertexAt") else None
    if point is None:
        try:
            point = geom.constGet()
        except Exception:
            point = None
    if point is None or not hasattr(point, "x"):
        try:
            pt = geom.asPoint()
            map_x, map_y, z = pt.x(), pt.y(), 0.0
        except Exception:
            return None, None, None
    else:
        map_x, map_y = point.x(), point.y()
        z = 0.0
        if hasattr(point, "z"):
            try:
                raw = point.z()
                if raw == raw:
                    z = float(raw)
            except (TypeError, ValueError):
                z = 0.0
    data_x, data_y = map_xy_to_data_xy(map_x, map_y)
    return data_x, data_y, z


def _map_export_row(source_row, mapping_rows, shared_config, row_seq, geom_col,
                    field_types=None):
    wkt = source_row.get("__geom_wkt")
    gx, gy, gz = _xyz_from_wkt(wkt)
    geom_name = ident_name(geom_col)
    types = field_types or {}
    values = {}
    for item in mapping_rows:
        dst = item.get("dst_field")
        if not dst:
            continue
        src = item.get("src_field")
        rule_set = item.get("rule_set") or ""
        rule_target = item.get("rule_target") or ""
        if is_xyz_rule(rule_set, rule_target, shared_config):
            axis = (rule_target or "").strip().lower()
            src_is_geom = (not src) or (geom_name and ident_name(src).lower() == geom_name.lower())
            if src_is_geom:
                if axis == "x":
                    values[dst] = gx
                elif axis == "y":
                    values[dst] = gy
                elif axis == "z":
                    values[dst] = gz if gz is not None else 0.0
                continue
        raw = _row_get(source_row, src) if src else None
        values[dst] = apply_rule_value(
            raw, rule_set, rule_target, shared_config, row_seq=row_seq,
            mdb_type=types.get(ident_name(dst).upper()),
        )
    return values


def run_export(pg_connector, shared_config, pipeline_types, structure_id,
               export_format, polygon_geometry, canvas_crs, output_path, log=None,
               progress_dialog=None):
    def _log(msg):
        if log:
            log(msg)

    pg = shared_config.get_pg_config()
    if not (pg.get("point") or {}).get("table") or not (pg.get("line") or {}).get("table"):
        raise RuntimeError("请先在「配置管理 → 数据库连接」中设置管点表和管线表。")

    structure = shared_config.get_mdb_structure(structure_id)
    if not structure:
        raise RuntimeError("未找到所选「MDB库结构」。")
    mapping_block = shared_config.get_mapping_block("export", structure_id)
    if not mapping_has_field_rows(mapping_block):
        raise RuntimeError(
            "未在「结构映射 → 导出映射」中配置「%s」的字段映射。"
            % (structure.get("label") or structure_id)
        )

    point_mapping = _kind_mapping_rows(
        mapping_block, "point", skip_xyz=False, allow_empty_src=True
    )
    line_mapping = _kind_mapping_rows(
        mapping_block, "line", skip_xyz=False, allow_empty_src=True
    )
    if not point_mapping and not line_mapping:
        raise RuntimeError("导出映射没有有效的点表或线表字段。")

    render_groups = shared_config.get_mdb_render_groups()
    render_group = _group_by_id(render_groups, structure_id)
    fmt = (export_format or "mdb").strip().lower()
    if fmt not in ("mdb", "gdb", "gpkg"):
        raise RuntimeError("不支持的导出格式。")
    if fmt == "gdb" and not writable_gdb_drivers():
        raise RuntimeError(gdb_write_unavailable_message())

    cursor = pg_connector.get_cursor()
    srid = pg_connector.get_srid(
        pg["line"].get("schema") or "public",
        pg["line"].get("table"),
        pg["line"].get("geom_col") or "geom",
    )
    polygon_wkt = transform_geom_to_srid(polygon_geometry, canvas_crs, srid)
    base_types, _include_fz = split_pipeline_selection(pipeline_types)
    result = ExportResult()

    mdb_conn = None
    gdb_writer = None
    try:
        if fmt == "mdb":
            _log("创建输出 MDB -> %s" % output_path)
            create_empty_mdb(output_path)
            mdb_conn = MdbConnection(output_path)
        else:
            label = "GeoPackage" if fmt == "gpkg" else "GDB"
            _log("创建输出 %s -> %s" % (label, output_path))
            if fmt == "gpkg":
                if srid > 0:
                    crs = QgsCoordinateReferenceSystem("EPSG:%s" % srid)
                else:
                    crs = canvas_crs or QgsProject.instance().crs()
                gdb_writer = GdbWriter(output_path, crs=crs, driver_names=["GPKG"])
            else:
                gdb_writer = GdbWriter(output_path, crs=None)

        for idx, pipe_code in enumerate(pipeline_types, start=1):
            pipe_label = pipeline_display_name(pipe_code)
            try:
                if _export_cancelled(progress_dialog):
                    result.cancelled = True
                    _log("导出已由用户停止")
                    break
                if progress_dialog:
                    progress_dialog.begin_pipe(idx, pipe_label, "查询范围内数据")
                _log("[%s] 查询范围内数据..." % pipe_code)
                fz_base = base_types if pipe_code == FZ_PIPE_CODE else None
                point_rows, line_rows = collect_points_for_export(
                    cursor, pg, pipe_code, polygon_wkt, srid, fz_base_types=fz_base
                )
                if _export_cancelled(progress_dialog):
                    result.cancelled = True
                    _log("导出已由用户停止")
                    break
                if progress_dialog:
                    progress_dialog.begin_pipe(
                        idx, pipe_label,
                        "写入数据 (点 %s 条, 线 %s 条)"
                        % (len(point_rows or []), len(line_rows or [])),
                    )
                point_table = _target_table_name(
                    pipe_code, "point", structure, render_group
                )
                line_table = _target_table_name(
                    pipe_code, "line", structure, render_group
                )
                p_count = 0
                l_count = 0
                if point_mapping:
                    p_count = _write_kind(
                        fmt, mdb_conn, gdb_writer,
                        pipe_code, "point", point_table, point_rows, point_mapping,
                        structure, shared_config, pg["point"].get("geom_col") or "geom",
                        progress_dialog=progress_dialog,
                    )
                _check_export_stop(progress_dialog)
                if line_mapping:
                    l_count = _write_kind(
                        fmt, mdb_conn, gdb_writer,
                        pipe_code, "line", line_table, line_rows, line_mapping,
                        structure, shared_config, pg["line"].get("geom_col") or "geom",
                        progress_dialog=progress_dialog,
                    )
                if mdb_conn is not None:
                    mdb_conn.commit()
                _log(
                    "[%s] 完成：点 %s 条，线 %s 条"
                    % (pipe_code, p_count, l_count)
                )
                result.add(pipe_code, l_count, p_count)
                if progress_dialog:
                    progress_dialog.finish_pipe(idx, pipe_label)
                if _export_cancelled(progress_dialog):
                    result.cancelled = True
                    _log("导出已由用户停止")
                    break
            except ExportStopped:
                if mdb_conn is not None:
                    try:
                        mdb_conn.rollback()
                    except Exception:
                        pass
                result.cancelled = True
                _log("[%s] 写入未完成，已停止；该管类未计入本次导出" % pipe_code)
                break
            except Exception as exc:
                if mdb_conn is not None:
                    try:
                        mdb_conn.rollback()
                    except Exception:
                        pass
                _log("[%s] 导出失败：%s" % (pipe_code, exc))
                result.add_error(pipe_code, str(exc))
                if progress_dialog:
                    progress_dialog.finish_pipe(idx, pipe_label)
        if progress_dialog and not result.cancelled:
            progress_dialog.set_finalizing()
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        if mdb_conn is not None:
            mdb_conn.close()
    return result


def _write_kind(fmt, mdb_conn, gdb_writer, pipe_code, kind, table_name, source_rows,
                mapping_rows, structure, shared_config, geom_col, progress_dialog=None):
    mapped_rows = []
    geom_wkts = []
    fields = _target_fields(pipe_code, kind, structure, mapping_rows, [])
    field_types = {
        ident_name(item.get("name")).upper(): item.get("mdb_type")
        for item in fields
        if ident_name(item.get("name"))
    }
    for index, source_row in enumerate(source_rows or [], start=1):
        if index == 1 or index % 25 == 0:
            _check_export_stop(progress_dialog)
        mapped = _map_export_row(
            source_row, mapping_rows, shared_config, index, geom_col,
            field_types=field_types,
        )
        if not mapped:
            continue
        mapped = apply_decimals_to_values(mapped, structure, pipe_code, kind)
        mapped_rows.append(mapped)
        geom_wkts.append(source_row.get("__geom_wkt") or "")

    _check_export_stop(progress_dialog)
    if fmt == "mdb":
        if not fields:
            raise RuntimeError(
                "%s %s 没有字段定义，无法建表" % (
                    pipeline_display_name(pipe_code), table_name
                )
            )
        mdb_conn.create_table(table_name, fields)
        count = 0
        for index, mapped in enumerate(mapped_rows, start=1):
            if index == 1 or index % 25 == 0:
                _check_export_stop(progress_dialog)
            values = {
                key: python_to_odbc(value) for key, value in mapped.items()
            }
            if values:
                mdb_conn.insert_row(table_name, values)
                count += 1
        return count

    _check_export_stop(progress_dialog)
    return gdb_writer.write_feature_class(
        table_name, kind, fields, mapped_rows, geom_wkts
    )
