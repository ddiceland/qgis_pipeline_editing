# -*- coding: utf-8 -*-
"""MDB 中 FZ 辅助数据按管线类型字段筛选（渲染与入库共用）。"""

from ..pipe_type_filter import FZ_PIPE_CODE, split_pipeline_selection
from ..sql_ident import quote_access_ident


def resolve_fz_allowed(pipe_codes, load_all_fz=False, action="加载"):
    """
    返回 (fz_allowed, base_types, include_fz)。
    fz_allowed 为 None 表示不筛选（未勾选 FZ，或全选后全部加载/入库）。
    仅勾选 FZ 时抛错。
    """
    base_types, include_fz = split_pipeline_selection(pipe_codes)
    if include_fz and not base_types:
        raise RuntimeError(
            "FZ（辅助）不是独立管线数据，请至少再勾选一种其他管类后再%s。"
            % action
        )
    if not include_fz or load_all_fz:
        return None, base_types, include_fz
    return list(base_types), base_types, include_fz


def row_field_text(row, field_name):
    if not field_name or row is None:
        return ""
    getter = getattr(row, "get", None)
    if getter is None:
        return ""
    if isinstance(row, dict):
        if field_name in row:
            raw = row.get(field_name)
        else:
            upper = field_name.upper()
            raw = None
            for key, value in row.items():
                if str(key).upper() == upper:
                    raw = value
                    break
            if raw is None:
                return ""
    else:
        raw = getter(field_name)
    return str(raw or "").strip()


def normalize_type_code(value):
    text = (value or "").strip().upper()
    if not text:
        return ""
    return text.split()[0].split("(")[0].split("-")[0].strip() or text


def access_type_in_clause(type_field, allowed_codes):
    """Access WHERE：管线类型字段属于已勾选基础管类（供 FZ 表下推过滤）。"""
    field = quote_access_ident(type_field)
    values = []
    seen = set()
    for code in allowed_codes or []:
        text = str(code or "").strip().upper()
        if not text or text in seen:
            continue
        seen.add(text)
        values.append("'%s'" % text.replace("'", "''"))
    if not values:
        return "1=0"
    return "UCase(Trim(%s)) IN (%s)" % (field, ", ".join(values))


def filter_rows_by_pipe_types(rows, type_field, allowed_codes):
    allowed = {str(code).strip().upper() for code in (allowed_codes or []) if code}
    if not allowed:
        return []
    matched = []
    for row in rows or []:
        code = normalize_type_code(row_field_text(row, type_field))
        if code in allowed:
            matched.append(row)
    return matched


def apply_fz_row_filter(pipe_code, rows, type_field, fz_allowed, kind_label, log=None):
    """非全选时，FZ 只保留管线类型属于已勾选基础管类的辅助数据。"""
    def _log(msg):
        if log:
            log(msg)

    if pipe_code != FZ_PIPE_CODE or fz_allowed is None:
        return list(rows or [])
    rows = list(rows or [])
    if not type_field:
        _log(
            "[%s] 未配置管线类型字段，无法按勾选管类筛选辅助%s，已跳过"
            % (FZ_PIPE_CODE, kind_label)
        )
        return []
    if not rows:
        return []
    filtered = filter_rows_by_pipe_types(rows, type_field, fz_allowed)
    if not filtered:
        _log(
            "[%s] 没有与已勾选管类相关的辅助%s，已跳过"
            % (FZ_PIPE_CODE, kind_label)
        )
    return filtered
