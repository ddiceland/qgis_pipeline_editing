# -*- coding: utf-8 -*-
"""
MDB 结构转换：按「结构映射 → 结构转换」将源 MDB 另存为目标结构的新 MDB 或 GDB。

流程：
1. 校验源/目标结构，以及「结构映射」中是否已配置该对映射
2. 新建空目标库（绝不覆盖源文件）
3. 按目标结构的表名/字段建表，并按映射写入源库数据
   GDB 另含 OBJECTID、Shape，不写坐标系
"""

import os

from ..access_field_types import normalize_access_type, odbc_type_to_mdb_type
from ..mdb_decimals import apply_decimals_to_values
from ..pipe_catalog import PIPELINE_TYPES, pipeline_display_name
from ..rule_apply import apply_rule_value
from ..sql_ident import ident_name
from ..xyz_mapping import is_xyz_rule
from .mdb_connector import MdbConnection, create_empty_mdb
from .schema_detect import (
    apply_table_pattern,
    discover_pipe_layers,
    resolve_column,
    resolve_existing_table,
    TableProfile,
)
from .geometry_builder import (
    build_point_lookup,
    line_geometry_from_row,
    point_geometry_from_row,
)


def _is_sequence_row(row):
    return (
        (row.get("rule_set") or "").strip() == "sequence"
        or (row.get("rule_target") or "").strip() == "seq"
    )


def _is_xyz_row(row):
    return is_xyz_rule(row.get("rule_set"), row.get("rule_target"))


def mapping_has_field_rows(block):
    """映射块是否配置了至少一条有效的源→目标字段（顺序号、XYZ 可无源字段）。"""
    if not isinstance(block, dict):
        return False
    for kind in ("point", "line"):
        for row in block.get(kind) or []:
            src = ident_name(row.get("src_field"))
            dst = ident_name(row.get("dst_field"))
            if dst and (src or _is_sequence_row(row) or _is_xyz_row(row)):
                return True
    return False


def _apply_rule_value(value, rule_set, rule_target, shared_config, row_seq=None,
                      mdb_type=None):
    return apply_rule_value(
        value, rule_set, rule_target, shared_config, row_seq=row_seq, mdb_type=mdb_type
    )


def _group_by_id(groups, structure_id):
    sid = (structure_id or "").strip()
    for group in groups or []:
        if (group.get("id") or "").strip() == sid:
            return group
    return None


def _kind_mapping_rows(block, kind, skip_xyz=True, allow_empty_src=False):
    rows = []
    seen = set()
    for row in (block or {}).get(kind) or []:
        src = ident_name(row.get("src_field"))
        dst = ident_name(row.get("dst_field"))
        if skip_xyz and _is_xyz_row(row):
            continue
        if not dst:
            continue
        if (
            not src
            and not _is_sequence_row(row)
            and not allow_empty_src
            and not _is_xyz_row(row)
        ):
            continue
        key = dst
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "src_field": src,
            "dst_field": dst,
            "mdb_type": (row.get("mdb_type") or "").strip(),
            "mdb_size": (row.get("mdb_size") or "").strip(),
            "rule_set": (row.get("rule_set") or "").strip(),
            "rule_target": (row.get("rule_target") or "").strip(),
        })
    return rows


def _row_get(row, field_name):
    """按映射字段名取值：先精确匹配，再按 Access 习惯忽略大小写。"""
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


def _target_fields(pipe_code, kind, structure, mapping_rows, source_columns):
    """目标表字段 = 目标库结构字段 ∪ 映射目标字段。"""
    table_key = "point_fields" if kind == "point" else "line_fields"
    pipe_cfg = ((structure or {}).get("pipes") or {}).get(pipe_code) or {}
    source_types = {}
    for col in source_columns or []:
        name = (col.get("name") or "").strip()
        if name:
            source_types[name.upper()] = odbc_type_to_mdb_type(col.get("type"))
    fields = []
    seen = set()
    for item in pipe_cfg.get(table_key) or []:
        name = ident_name(item.get("name"))
        if not name or name.upper() in seen:
            continue
        seen.add(name.upper())
        fields.append({
            "name": name,
            "mdb_type": normalize_access_type(item.get("mdb_type")),
            "mdb_size": (item.get("mdb_size") or "").strip(),
            "decimal_places": str(item.get("decimal_places") or "").strip(),
        })
    for row in mapping_rows or []:
        dst = row.get("dst_field")
        if not dst or dst.upper() in seen:
            continue
        seen.add(dst.upper())
        src_type = source_types.get((row.get("src_field") or "").upper(), "")
        if _is_sequence_row(row) and not src_type:
            src_type = "LONG"
        fields.append({
            "name": dst,
            "mdb_type": normalize_access_type(row.get("mdb_type") or src_type or "TEXT"),
            "mdb_size": (row.get("mdb_size") or "").strip(),
            "decimal_places": str(row.get("decimal_places") or "").strip(),
        })
    return fields


def _source_table_candidates(pipe_code, kind, structure, render_group, discovered):
    key = "point_table" if kind == "point" else "line_table"
    pattern_key = "point" if kind == "point" else "line"
    defaults = (
        [f"{pipe_code}POINT", f"{pipe_code}_POINT"]
        if kind == "point"
        else [f"{pipe_code}LINE", f"{pipe_code}_LINE"]
    )
    pattern = ((render_group or {}).get(pattern_key) or {}).get("table_pattern")
    pipe_cfg = ((structure or {}).get("pipes") or {}).get(pipe_code) or {}
    discovered_name = ((discovered or {}).get(pipe_code) or {}).get(kind)
    return [
        apply_table_pattern(pattern, pipe_code),
        pipe_cfg.get(key),
        discovered_name,
    ] + defaults


def _target_table_name(pipe_code, kind, structure, render_group):
    """
    目标表名：优先用「MDB库渲染」该结构的表命名（与加载一致），
    否则用「MDB库结构」中的点表/线表名。
    """
    pattern_key = "point" if kind == "point" else "line"
    table_key = "point_table" if kind == "point" else "line_table"
    pattern = ((render_group or {}).get(pattern_key) or {}).get("table_pattern")
    patterned = apply_table_pattern(pattern, pipe_code)
    if patterned:
        return patterned
    pipe_cfg = ((structure or {}).get("pipes") or {}).get(pipe_code) or {}
    configured = (pipe_cfg.get(table_key) or "").strip()
    if configured:
        return configured
    return f"{pipe_code}POINT" if kind == "point" else f"{pipe_code}LINE"


def _map_row(source_row, mapping_rows, shared_config, row_seq=1, field_types=None):
    types = field_types or {}
    values = {}
    for item in mapping_rows:
        raw = _row_get(source_row, item["src_field"])
        dst = item["dst_field"]
        mdb_type = types.get(ident_name(dst).upper())
        values[dst] = _apply_rule_value(
            raw, item.get("rule_set"), item.get("rule_target"), shared_config,
            row_seq=row_seq, mdb_type=mdb_type,
        )
    return values


def _ordered_pipe_codes(discovered):
    found = set((discovered or {}).keys())
    ordered = [code for code in PIPELINE_TYPES if code in found]
    extra = sorted(code for code in found if code not in PIPELINE_TYPES)
    return ordered + extra


def _column_names(source_columns):
    names = []
    for col in source_columns or []:
        if isinstance(col, dict):
            name = (col.get("name") or "").strip()
        else:
            name = str(col or "").strip()
        if name:
            names.append(name)
    return names


def _point_z_field(columns):
    return (
        resolve_column(columns, "Z")
        or resolve_column(columns, "H")
        or resolve_column(columns, "SURF_H")
    )


def _remove_output(path):
    if os.path.isdir(path):
        import shutil
        try:
            shutil.rmtree(path)
        except OSError:
            pass
    elif os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def _identity_mapping_rows(source_columns):
    """源=目标时按原表字段 1:1 写出，不依赖结构转换映射。"""
    rows = []
    seen = set()
    for col in source_columns or []:
        if isinstance(col, dict):
            name = ident_name(col.get("name"))
            mdb_type = odbc_type_to_mdb_type(col.get("type"))
        else:
            name = ident_name(col)
            mdb_type = "TEXT"
        if not name or name.upper() in seen:
            continue
        seen.add(name.upper())
        rows.append({
            "src_field": name,
            "dst_field": name,
            "mdb_type": mdb_type or "TEXT",
            "mdb_size": "",
            "rule_set": "",
            "rule_target": "",
        })
    return rows


def convert_mdb_to_new_file(src_path, out_path, source_id, target_id, shared_config,
                            output_format="mdb", swap_xy=True, pipe_codes=None):
    src_path = os.path.abspath(src_path)
    out_path = os.path.abspath(out_path)
    fmt = (output_format or "mdb").strip().lower()
    if fmt not in ("mdb", "gdb", "gpkg"):
        raise RuntimeError("不支持的目标格式。")
    if fmt == "mdb" and src_path == out_path:
        raise RuntimeError("输出路径不能与源 MDB 相同")

    pair_key = f"{source_id}__to__{target_id}"
    block = shared_config.get_mapping_block("convert", pair_key)
    same_structure = source_id == target_id
    if same_structure and fmt == "mdb":
        raise RuntimeError("目标结构不能与源结构相同")
    source_structure = shared_config.get_mdb_structure(source_id) or {}
    target_structure = shared_config.get_mdb_structure(target_id)
    if not same_structure and not source_structure:
        raise RuntimeError(
            "已识别渲染组，但未配置对应的「MDB库结构」。"
            "请先在「配置管理 → MDB库结构」中为该渲染组新增结构，"
            "并配置「结构映射 → 结构转换」。"
        )
    if not same_structure and not mapping_has_field_rows(block):
        raise RuntimeError(
            "未在「结构映射 → 结构转换」中配置「%s → %s」的字段映射。"
            % (source_id, target_id)
        )

    if not target_structure:
        raise RuntimeError("未找到目标「MDB库结构」，请先在配置管理中完善后再转换。")
    render_groups = shared_config.get_mdb_render_groups()
    source_render = _group_by_id(render_groups, source_id)
    target_render = _group_by_id(render_groups, target_id)

    stats = {
        "out_path": out_path,
        "source_id": source_id,
        "target_id": target_id,
        "format": fmt,
        "tables": [],
        "skipped": [],
    }

    created = False
    src_conn = None
    dst_conn = None
    gdb_writer = None
    try:
        src_conn = MdbConnection(src_path)
        tables = src_conn.list_user_tables()
        discovered = discover_pipe_layers(tables, render_groups=render_groups)
        if not discovered:
            raise RuntimeError("源 MDB 中未识别到管线点/线表，无法转换。")

        wanted = []
        seen_wanted = set()
        for code in pipe_codes or []:
            key = (code or "").strip().upper()
            if key and key not in seen_wanted:
                seen_wanted.add(key)
                wanted.append(key)
        if pipe_codes is not None and not wanted:
            raise RuntimeError("请先勾选要转换的管类。")

        convert_codes = _ordered_pipe_codes(discovered)
        if wanted:
            missing = [c for c in wanted if c not in discovered]
            for code in missing:
                stats["skipped"].append(
                    "%s：源库无此管类表" % pipeline_display_name(code)
                )
            convert_codes = [c for c in wanted if c in discovered]
            if not convert_codes:
                raise RuntimeError("勾选的管类在源 MDB 中均未找到对应表，无法转换。")

        if fmt == "mdb":
            create_empty_mdb(out_path)
            created = True
            dst_conn = MdbConnection(out_path)
        else:
            from ..gdb_writer import (
                GdbWriter,
                gdb_write_unavailable_message,
                writable_gdb_drivers,
            )
            if fmt == "gdb" and not writable_gdb_drivers():
                raise RuntimeError(gdb_write_unavailable_message())
            if fmt == "gpkg":
                gdb_writer = GdbWriter(out_path, crs=None, driver_names=["GPKG"])
            else:
                gdb_writer = GdbWriter(out_path, crs=None)
            created = True

        point_lookups = {}
        for pipe_code in convert_codes:
            for kind in ("point", "line"):
                src_table = resolve_existing_table(
                    tables,
                    _source_table_candidates(
                        pipe_code, kind, source_structure, source_render, discovered
                    ),
                )
                if not src_table:
                    stats["skipped"].append(
                        f"{pipeline_display_name(pipe_code)} {('点表' if kind == 'point' else '线表')}：源库无对应表"
                    )
                    continue
                source_columns = src_conn.get_columns(src_table)
                _, source_rows = src_conn.read_all_rows(src_table)
                if same_structure:
                    mapping_rows = _identity_mapping_rows(source_columns)
                else:
                    mapping_rows = _kind_mapping_rows(block, kind)
                if not mapping_rows:
                    continue
                dst_table = _target_table_name(pipe_code, kind, target_structure, target_render)
                dst_fields = _target_fields(
                    pipe_code, kind, target_structure, mapping_rows, source_columns
                )
                if not dst_fields:
                    stats["skipped"].append(
                        f"{pipeline_display_name(pipe_code)} {dst_table}：目标结构没有字段定义"
                    )
                    continue

                mapped_pairs = []
                field_types = {
                    ident_name(item.get("name")).upper(): item.get("mdb_type")
                    for item in dst_fields
                    if ident_name(item.get("name"))
                }
                for index, source_row in enumerate(source_rows, start=1):
                    mapped = _map_row(
                        source_row, mapping_rows, shared_config,
                        row_seq=index, field_types=field_types,
                    )
                    if mapped:
                        mapped = apply_decimals_to_values(
                            mapped, target_structure, pipe_code, kind
                        )
                        mapped_pairs.append((source_row, mapped))

                if fmt == "mdb":
                    try:
                        dst_conn.create_table(dst_table, dst_fields)
                    except Exception as exc:
                        raise RuntimeError(f"创建目标表 [{dst_table}] 失败：{exc}")
                    count = 0
                    for _source_row, mapped in mapped_pairs:
                        try:
                            dst_conn.insert_row(dst_table, mapped)
                        except Exception as exc:
                            raise RuntimeError(
                                f"写入目标表 [{dst_table}] 第 {count + 1} 条失败：{exc}"
                            )
                        count += 1
                else:
                    col_names = _column_names(source_columns)
                    profile = TableProfile(src_table, kind, col_names, source_render)
                    mapped_rows = []
                    geom_wkts = []
                    if kind == "point":
                        z_field = _point_z_field(col_names)
                        point_lookups[pipe_code] = build_point_lookup(
                            source_rows,
                            profile.pk_field,
                            profile.x_field,
                            profile.y_field,
                            z_field=z_field,
                            with_z=True,
                            swap_xy=swap_xy,
                        )
                        for source_row, mapped in mapped_pairs:
                            geom = point_geometry_from_row(
                                profile.x_field, profile.y_field, source_row,
                                z_field=z_field, with_z=True,
                                swap_xy=swap_xy,
                            )
                            mapped_rows.append(mapped)
                            geom_wkts.append(geom.asWkt() if geom else "")
                    else:
                        lookup = point_lookups.get(pipe_code) or {}
                        for source_row, mapped in mapped_pairs:
                            geom = line_geometry_from_row(
                                profile.start_field, profile.end_field, source_row, lookup
                            )
                            mapped_rows.append(mapped)
                            geom_wkts.append(geom.asWkt() if geom else "")
                    count = gdb_writer.write_feature_class(
                        dst_table, kind, dst_fields, mapped_rows, geom_wkts
                    )

                stats["tables"].append({
                    "pipe": pipe_code,
                    "kind": kind,
                    "src": src_table,
                    "dst": dst_table,
                    "rows": count,
                })

        if not stats["tables"]:
            raise RuntimeError(
                "已找到源管类表，但未能按映射写出任何目标表。\n"
                "请检查源表名、目标表命名以及点/线映射是否完整。"
            )
        if dst_conn is not None:
            dst_conn.commit()
    except Exception:
        if dst_conn is not None:
            try:
                dst_conn.rollback()
            except Exception:
                pass
        if created:
            try:
                if dst_conn is not None:
                    dst_conn.close()
                    dst_conn = None
            except Exception:
                pass
            _remove_output(out_path)
        raise
    finally:
        if src_conn is not None:
            src_conn.close()
        if dst_conn is not None:
            dst_conn.close()
    return stats
