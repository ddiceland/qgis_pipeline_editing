# -*- coding: utf-8 -*-
"""按 MDB 库结构把浮点数值收到配置的小数位。"""

from .access_field_types import (
    DEFAULT_DECIMAL_PLACES,
    field_decimal_places,
    round_mdb_number,
)
from .sql_ident import ident_name


def structure_field_index(structure, pipe_code, kind):
    """字段名大写 → 结构字段定义。"""
    table_key = "point_fields" if kind == "point" else "line_fields"
    pipe = ((structure or {}).get("pipes") or {}).get(pipe_code) or {}
    index = {}
    for item in pipe.get(table_key) or []:
        name = ident_name(item.get("name"))
        if name:
            index[name.upper()] = item
    return index


def structure_field(structure, pipe_code, kind, field_name):
    name = ident_name(field_name)
    if not name:
        return None
    return structure_field_index(structure, pipe_code, kind).get(name.upper())


def apply_decimals_to_values(values, structure, pipe_code, kind):
    """按目标结构字段名，对 SINGLE/DOUBLE 取值四舍五入。"""
    if not values:
        return values
    fmap = structure_field_index(structure, pipe_code, kind)
    if not fmap:
        return values
    out = {}
    for key, value in values.items():
        field = fmap.get(ident_name(key).upper()) if key else None
        places = field_decimal_places(field)
        if places is not None:
            out[key] = round_mdb_number(value, places)
        else:
            out[key] = value
    return out


def apply_source_field_decimals(mapped, mapping_rows, structure, pipe_code, kind):
    """入库：按源 MDB 字段的小数位，收口已映射到目标列的值。"""
    if not mapped:
        return mapped
    fmap = structure_field_index(structure, pipe_code, kind)
    if not fmap:
        return mapped
    out = dict(mapped)
    for item in mapping_rows or []:
        dst = ident_name(item.get("dst_field"))
        if not dst or dst not in out:
            continue
        field = fmap.get(ident_name(item.get("src_field")).upper())
        places = field_decimal_places(field)
        if places is not None:
            out[dst] = round_mdb_number(out[dst], places)
    return out


def apply_save_decimals(values, structure, pipe_code, kind, profile=None):
    """
    编辑回写：有结构则按字段小数位；结构中没有的字段不改。
    X/Y（渲染配置中的坐标字段）在未配成浮点时仍保留 3 位。
    """
    if not values:
        return values
    fmap = structure_field_index(structure, pipe_code, kind) if structure else {}
    xy_names = set()
    if profile is not None:
        for name in (getattr(profile, "x_field", None), getattr(profile, "y_field", None)):
            ident = ident_name(name)
            if ident:
                xy_names.add(ident.upper())
    out = {}
    for key, value in values.items():
        ident = ident_name(key)
        field = fmap.get(ident.upper()) if ident else None
        places = field_decimal_places(field)
        if places is None and ident and ident.upper() in xy_names:
            places = DEFAULT_DECIMAL_PLACES
        if places is not None:
            out[key] = round_mdb_number(value, places)
        else:
            out[key] = value
    return out
