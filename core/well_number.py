# -*- coding: utf-8 -*-
"""井编号：按可配置规则生成，并按 PostgreSQL 视图表续编。"""

import re


def _as_int(value, default, minimum, maximum):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    if number < minimum:
        return minimum
    if number > maximum:
        return maximum
    return number


def wellno_format_options(rule=None):
    """从规则集读取井编号格式；缺省为 管类(2位)+顺序号(10位)。"""
    src = rule if isinstance(rule, dict) else {}
    type_width = _as_int(src.get("type_width"), 2, 0, 8)
    seq_width = _as_int(src.get("seq_width"), 10, 1, 18)
    separator = str(src.get("separator") if src.get("separator") is not None else "")
    prefix = str(src.get("prefix") if src.get("prefix") is not None else "")
    suffix = str(src.get("suffix") if src.get("suffix") is not None else "")
    position = (src.get("ptype_position") or "prefix").strip().lower()
    if position not in ("prefix", "suffix"):
        position = "prefix"
    return {
        "type_width": type_width,
        "seq_width": seq_width,
        "separator": separator,
        "ptype_position": position,
        "prefix": prefix,
        "suffix": suffix,
    }


def parse_max_seq(value, seq_width=None, type_width=None, ptype_position="prefix",
                  prefix="", suffix="", separator=""):
    """从视图表 max_expno 取出数字顺序号。"""
    if value is None or value == "":
        return 0
    text = str(value).strip()
    if not text:
        return 0
    if prefix and text.startswith(prefix):
        text = text[len(prefix):]
    if suffix and text.endswith(suffix):
        text = text[:-len(suffix)]
    tw = _as_int(type_width, 0, 0, 8)
    if tw > 0 and (ptype_position or "prefix") == "suffix":
        text = re.sub(r"[A-Za-z0-9]{%d}$" % tw, "", text)
        sep = separator or ""
        if sep and text.endswith(sep):
            text = text[:-len(sep)]
    try:
        return int(text)
    except (TypeError, ValueError):
        pass
    match = re.search(r"(\d+)$", text)
    if not match:
        return 0
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return 0


def normalize_pipe_code(pipe_code, type_width=2):
    code = (pipe_code or "").strip().upper()
    width = max(int(type_width or 0), 0)
    if width <= 0:
        return ""
    if len(code) >= width:
        return code[:width]
    return code.ljust(width, "X")


def format_wellno(pipe_code, seq, type_width=2, seq_width=10,
                  separator="", ptype_position="prefix",
                  prefix="", suffix=""):
    width = max(int(seq_width or 10), 1)
    try:
        number = int(seq)
    except (TypeError, ValueError):
        number = 1
    if number < 1:
        number = 1
    seq_part = "%0*d" % (width, number)
    tw = int(type_width or 0)
    if tw > 0:
        code = normalize_pipe_code(pipe_code, tw)
        sep = separator or ""
        if (ptype_position or "prefix") == "suffix":
            body = seq_part + sep + code
        else:
            body = code + sep + seq_part
    else:
        body = seq_part
    return "%s%s%s" % (prefix or "", body, suffix or "")


def preview_wellno(rule, pipe_code="JS", seq=42):
    return format_wellno(pipe_code, seq, **wellno_format_options(rule))


def normalize_well_key(value):
    if value is None:
        return ""
    return str(value).strip()


def is_wellno_rule(rule_set_id, rule_target, shared_config=None):
    target = (rule_target or "").strip()
    if target in ("assign", "follow"):
        return True
    rid = (rule_set_id or "").strip()
    if rid == "wellno":
        return True
    if shared_config is not None and hasattr(shared_config, "get_rule_set"):
        kind = (shared_config.get_rule_set(rid) or {}).get("kind") or ""
        return kind == "wellno"
    return False


def mapping_uses_wellno(block, shared_config=None):
    if not isinstance(block, dict):
        return False
    for kind in ("point", "line"):
        for row in block.get(kind) or []:
            if is_wellno_rule(row.get("rule_set"), row.get("rule_target"), shared_config):
                return True
    return False


class WellNumberAllocator:
    """按管类从已有最大号续编，并保存旧井号 → 新井号对照。"""

    def __init__(self, max_by_ptype=None, rule=None, **overrides):
        src = dict(wellno_format_options(rule))
        src.update(overrides)
        self.fmt = wellno_format_options(src)
        self.counters = {}
        for key, value in (max_by_ptype or {}).items():
            code = (key or "").strip().upper()
            if code:
                self.counters[code] = parse_max_seq(value, **self.fmt)
        self.maps = {}

    def assign(self, pipe_code, old_value):
        code = (pipe_code or "").strip().upper()
        table = self.maps.setdefault(code, {})
        key = normalize_well_key(old_value)
        if key and key in table:
            return table[key]
        seq = self.counters.get(code, 0) + 1
        self.counters[code] = seq
        new_value = format_wellno(code, seq, **self.fmt)
        if key:
            table[key] = new_value
        return new_value

    def follow(self, pipe_code, old_value):
        if old_value is None or old_value == "":
            return old_value
        code = (pipe_code or "").strip().upper()
        key = normalize_well_key(old_value)
        if not key:
            return old_value
        mapped = (self.maps.get(code) or {}).get(key)
        if mapped:
            return mapped
        for table in self.maps.values():
            if key in table:
                return table[key]
        return old_value
