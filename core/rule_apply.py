# -*- coding: utf-8 -*-
"""按规则集转换字段值：对照表（名称/代码）、角度换算、顺序号。"""

import math


def convert_angle_value(value, target, decimal_places=6):
    """
    target=radians：源值按角度制转为弧度。
    target=degrees：源值按弧度制转为角度。
    """
    if value is None or value == "":
        return value
    try:
        num = float(value)
    except (TypeError, ValueError):
        return value
    if target == "radians":
        out = num * math.pi / 180.0
    elif target == "degrees":
        out = num * 180.0 / math.pi
    else:
        return value
    try:
        places = int(decimal_places)
    except (TypeError, ValueError):
        places = 6
    if places < 0:
        return out
    return round(out, places)


def _apply_lookup_rule(value, rows, rule_target):
    text = "" if value is None else str(value).strip()
    if not text:
        return value
    if rule_target == "code":
        for item in rows or []:
            if (item.get("name") or "").strip() == text:
                return item.get("code") or value
            if (item.get("code") or "").strip() == text:
                return item.get("code") or value
    elif rule_target == "name":
        for item in rows or []:
            if (item.get("code") or "").strip() == text:
                return item.get("name") or value
            if (item.get("name") or "").strip() == text:
                return item.get("name") or value
    return value


def next_sequence_value(rule, row_seq):
    """按表内行号生成从 start_from 起的整数顺序号（默认从 1 开始）。"""
    try:
        start = int((rule or {}).get("start_from", 1))
    except (TypeError, ValueError):
        start = 1
    if start < 1:
        start = 1
    try:
        seq = int(row_seq)
    except (TypeError, ValueError):
        seq = 1
    if seq < 1:
        seq = 1
    return start + seq - 1


def apply_rule_value(value, rule_set_id, rule_target, shared_config, row_seq=None):
    if not rule_set_id:
        return value
    rule = None
    if shared_config is not None and hasattr(shared_config, "get_rule_set"):
        rule = shared_config.get_rule_set(rule_set_id)
    kind = (rule or {}).get("kind") or ""
    if not kind and rule_set_id == "angle":
        kind = "angle"
    elif not kind and rule_set_id == "sequence":
        kind = "sequence"
    elif not kind and rule_set_id == "wellno":
        kind = "wellno"
    elif not kind and rule_set_id == "xyz":
        kind = "xyz"
    if kind == "sequence" or rule_target == "seq":
        return next_sequence_value(rule, row_seq)
    if kind == "wellno" or rule_set_id == "wellno" or rule_target in ("assign", "follow"):
        return value
    if kind == "xyz" or rule_set_id == "xyz" or rule_target in ("x", "y", "z"):
        return value
    if not rule_target:
        return value
    if kind == "angle" or rule_target in ("radians", "degrees"):
        places = (rule or {}).get("decimal_places", 6)
        return convert_angle_value(value, rule_target, places)
    rows = []
    if rule is not None:
        rows = rule.get("rows") or []
    elif shared_config is not None and hasattr(shared_config, "get_rule_set_rows"):
        rows = shared_config.get_rule_set_rows(rule_set_id)
    return _apply_lookup_rule(value, rows, rule_target)
