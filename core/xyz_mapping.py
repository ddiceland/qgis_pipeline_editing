# -*- coding: utf-8 -*-
"""结构映射中的坐标规则：指定 MDB 的 X / Y / Z 字段，用于生成带高程的 geom。"""

from .sql_ident import ident_name


def is_xyz_rule(rule_set_id, rule_target=None, shared_config=None):
    rid = (rule_set_id or "").strip()
    if rid == "xyz":
        return True
    if shared_config is not None and hasattr(shared_config, "get_rule_set"):
        kind = (shared_config.get_rule_set(rid) or {}).get("kind") or ""
        return kind == "xyz"
    target = (rule_target or "").strip().lower()
    return rid and target in ("x", "y", "z") and rid == "xyz"


def mapping_xyz_fields(block, kind, shared_config=None):
    """从映射块读取点/线表上配置的 X/Y/Z 源字段名。"""
    result = {"x": "", "y": "", "z": ""}
    for item in mapping_xyz_bindings(block, kind, shared_config).values():
        if item.get("axis") and item.get("src"):
            result[item["axis"]] = item["src"]
    return result


def mapping_xyz_bindings(block, kind, shared_config=None):
    """返回 {x|y|z: {src, dst, axis}}。"""
    result = {}
    if not isinstance(block, dict):
        return result
    for row in block.get(kind) or []:
        if not is_xyz_rule(row.get("rule_set"), row.get("rule_target"), shared_config):
            continue
        axis = (row.get("rule_target") or "").strip().lower()
        if axis not in ("x", "y", "z"):
            continue
        result[axis] = {
            "axis": axis,
            "src": ident_name(row.get("src_field")),
            "dst": ident_name(row.get("dst_field")),
        }
    return result
