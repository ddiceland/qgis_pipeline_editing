# -*- coding: utf-8 -*-
"""管类筛选逻辑：FZ 为辅助数据，通过 gtype 与 ptype 组合区分。"""

from .sql_ident import ident_name, quote_ident

FZ_PIPE_CODE = "FZ"


def split_pipeline_selection(pipeline_types):
    """返回 (基础管类列表, 是否包含FZ辅助数据)。"""
    types = list(pipeline_types or [])
    base_types = [t for t in types if t != FZ_PIPE_CODE]
    include_fz = FZ_PIPE_CODE in types
    return base_types, include_fz


def symbology_pipeline_types(pipeline_types, all_base_types):
    """图层着色参考的管类代码列表（不含 FZ 虚拟代码）。"""
    base_types, include_fz = split_pipeline_selection(pipeline_types)
    if base_types:
        return base_types
    if include_fz:
        return [t for t in all_base_types if t != FZ_PIPE_CODE]
    return []


def build_layer_subset_filter(type_field, gtype_field, pipeline_types, all_type_count=None):
    """
    生成 QGIS 图层子集 SQL（不含 WHERE 关键字）。

    勾选类型与过滤条件：
    - 非 FZ 单类：ptype = 'YS' AND gtype IS NULL
    - 非 FZ 多类：ptype IN (...) AND gtype IS NULL
    - 仅 FZ：gtype IS NOT NULL
    - FZ + 单类： (ptype = 'YS' AND gtype IS NULL) OR (ptype = 'YS' AND gtype IS NOT NULL)
    - FZ + 多类： (ptype IN (...) AND gtype IS NULL) OR (ptype IN (...) AND gtype IS NOT NULL)
    """
    type_field = (type_field or "").strip()
    gtype_field = (gtype_field or "").strip()
    base_types, include_fz = split_pipeline_selection(pipeline_types)

    if not pipeline_types:
        return ""

    if all_type_count and len(pipeline_types) >= all_type_count:
        return ""

    if not gtype_field:
        if base_types and type_field:
            if len(base_types) == 1:
                return f"{type_field} = {_sql_literal(base_types[0])}"
            return f"{type_field} IN ({_sql_in_list(base_types)})"
        if include_fz:
            return ""
        return ""

    if include_fz and base_types:
        if len(base_types) == 1:
            code = _sql_literal(base_types[0])
            normal = f"({type_field} = {code} AND {gtype_field} IS NULL)"
            fz = f"({type_field} = {code} AND {gtype_field} IS NOT NULL)"
        else:
            codes = _sql_in_list(base_types)
            normal = f"({type_field} IN ({codes}) AND {gtype_field} IS NULL)"
            fz = f"({type_field} IN ({codes}) AND {gtype_field} IS NOT NULL)"
        return f"({normal} OR {fz})"

    if base_types:
        if len(base_types) == 1:
            return f"({type_field} = {_sql_literal(base_types[0])} AND {gtype_field} IS NULL)"
        return f"({type_field} IN ({_sql_in_list(base_types)}) AND {gtype_field} IS NULL)"

    if include_fz:
        return f"{gtype_field} IS NOT NULL"

    return ""


def build_export_filter_clause(cfg, pipeline_type, fz_base_types=None):
    """
    导出空间查询附加条件（返回 SQL 片段与参数列表）。
    fz_base_types：导出 FZ 时限定哪些 ptype 的辅助数据；空列表表示不限 ptype。
    """
    type_field = quote_ident(cfg.get("type_field")) if ident_name(cfg.get("type_field")) else ""
    gtype_field = quote_ident(cfg.get("gtype_field")) if ident_name(cfg.get("gtype_field")) else ""
    clauses = []
    params = []

    if pipeline_type == FZ_PIPE_CODE:
        if not gtype_field:
            return " AND FALSE", []
        clauses.append(f"{gtype_field} IS NOT NULL")
        if fz_base_types and type_field:
            clauses.append(f"{type_field} = ANY(%s)")
            params.append(list(fz_base_types))
        return (" AND " + " AND ".join(clauses)), params

    if type_field:
        clauses.append(f"{type_field} = %s")
        params.append(pipeline_type)
    if gtype_field:
        clauses.append(f"{gtype_field} IS NULL")

    if not clauses:
        return "", []
    return " AND " + " AND ".join(clauses), params


def _sql_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def _sql_in_list(values):
    return ",".join(_sql_literal(v) for v in values)
