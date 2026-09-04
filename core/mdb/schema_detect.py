# -*- coding: utf-8 -*-
"""从 MDB 表名与字段名识别管类、结构类型及关键字段。"""

import re

from ..pipe_catalog import PIPELINE_TYPES, PIPELINE_TYPE_LABELS

POINT_SUFFIXES = ("POINT", "_POINT")
LINE_SUFFIXES = ("LINE", "_LINE")

# 兼容旧逻辑的候选（无结构组配置时回退）
POINT_KEY_CANDIDATES = ("ID", "物探点号", "EXPNO", "expno", "Pt_No", "PT_NO")
LINE_KEY_CANDIDATES = ("ID",)
POINT_X_CANDIDATES = ("X", "x")
POINT_Y_CANDIDATES = ("Y", "y")
LINE_START_CANDIDATES = ("SPOINT", "起点点号", "spoint", "SPT_NO")
LINE_END_CANDIDATES = ("EPOINT", "终点点号", "连接点号", "连接方向", "epoint", "EPT_NO")


class MdbRenderGroupNotMatchedError(RuntimeError):
    """MDB 字段结构未能匹配任何「MDB库渲染」结构组。"""


def _has_chinese(text):
    return any("\u4e00" <= ch <= "\u9fff" for ch in text or "")


def detect_structure_type(columns):
    for col in columns or []:
        if _has_chinese(col):
            return "zhengyuan"
    upper = {c.upper() for c in (columns or [])}
    if "EXPNO" in upper or "SPOINT" in upper:
        return "xian"
    return "unknown"


def _pick_column(columns, candidates):
    col_map = {c: c for c in columns}
    upper_map = {c.upper(): c for c in columns}
    for cand in candidates:
        if not cand:
            continue
        if cand in col_map:
            return cand
        if cand.upper() in upper_map:
            return upper_map[cand.upper()]
    return None


def resolve_column(columns, configured_name):
    """按配置字段名在表字段中解析实际列名（大小写不敏感）。"""
    name = (configured_name or "").strip()
    if not name:
        return None
    return _pick_column(columns, (name,))


def columns_have_fields(columns, required_names):
    """required_names 中非空项均须在 columns 中存在。"""
    for name in required_names:
        name = (name or "").strip()
        if not name:
            continue
        if resolve_column(columns, name) is None:
            return False
    return True


def _normalize_table_name(table_name):
    return (table_name or "").strip().strip("\ufeff")


def _parse_pipe_table_name(table_name):
    raw = _normalize_table_name(table_name)
    upper = raw.upper()
    for code in PIPELINE_TYPES:
        for suffix in POINT_SUFFIXES:
            token = f"{code}{suffix}"
            if upper == token or upper == f"{code}_{suffix.strip('_')}":
                return code, "point"
        for suffix in LINE_SUFFIXES:
            token = f"{code}{suffix}"
            if upper == token or upper == f"{code}_{suffix.strip('_')}":
                return code, "line"

    # 中文表名：给水点 / 给水线
    for code, label in PIPELINE_TYPE_LABELS.items():
        if not label:
            continue
        if raw in (f"{label}点", f"{label}管点", f"{code}点"):
            return code, "point"
        if raw in (f"{label}线", f"{label}管线", f"{code}线"):
            return code, "line"

    m = re.match(r"^([A-Z]{2,4})[_]?(POINT|LINE)$", upper)
    if m:
        return m.group(1), "point" if m.group(2) == "POINT" else "line"
    return None, None


def _table_preference(table_name):
    """同管类多个候选时，优先无下划线名（正元 JSPOINT 优先于 JS_POINT）。"""
    upper = _normalize_table_name(table_name).upper()
    if "_" in upper:
        return 1
    return 0


def discover_pipe_layers(table_names, render_groups=None):
    """返回 {pipe_code: {'point': table_or_none, 'line': table_or_none}}"""
    candidates = {}
    for table in table_names or []:
        code, kind = _parse_pipe_table_name(table)
        if not code:
            continue
        candidates.setdefault((code, kind), []).append(table)

    result = {}
    for (code, kind), names in candidates.items():
        names = sorted(names, key=_table_preference)
        entry = result.setdefault(code, {"point": None, "line": None})
        entry[kind] = names[0]

    for group in render_groups or []:
        point_pat = (group.get("point") or {}).get("table_pattern")
        line_pat = (group.get("line") or {}).get("table_pattern")
        for code in PIPELINE_TYPES:
            entry = result.setdefault(code, {"point": None, "line": None})
            if not entry.get("point"):
                entry["point"] = resolve_existing_table(
                    table_names, [apply_table_pattern(point_pat, code)]
                )
            if not entry.get("line"):
                entry["line"] = resolve_existing_table(
                    table_names, [apply_table_pattern(line_pat, code)]
                )

    # 模板管类 JS：若没有 JSPOINT/JS_POINT，尝试无前缀 POINT/LINE
    js_entry = result.setdefault("JS", {"point": None, "line": None})
    if not js_entry.get("point") or not js_entry.get("line"):
        for table in table_names or []:
            upper = _normalize_table_name(table).upper()
            if not js_entry.get("point") and upper in ("POINT", "PNT"):
                js_entry["point"] = table
            if not js_entry.get("line") and upper in ("LINE", "LIN"):
                js_entry["line"] = table
    empty_codes = [
        code for code, info in result.items()
        if not info.get("point") and not info.get("line")
    ]
    for code in empty_codes:
        result.pop(code, None)
    return result


def apply_table_pattern(pattern, pipe_code):
    """
    把表命名规则展开为实际表名。
    {code} / {管类} 表示管类代码；若只写 POINT、_POINT，则拼到管类后面。
    """
    text = (pattern or "").strip()
    code = (pipe_code or "").strip()
    if not text or not code:
        return None
    if re.search(r"\{code\}", text, flags=re.I) or "{管类}" in text:
        out = re.sub(r"\{code\}", code, text, flags=re.I)
        return out.replace("{管类}", code)
    return f"{code}{text}"


def resolve_existing_table(table_names, candidates):
    """在实际表名中按候选列表（大小写不敏感）解析存在的表。"""
    by_upper = {_normalize_table_name(n).upper(): n for n in (table_names or []) if n}
    for cand in candidates or []:
        key = _normalize_table_name(cand).upper()
        if key and key in by_upper:
            return by_upper[key]
    return None


def _sample_tables(discovered):
    """取一张点表、一张线表用于结构组匹配。优先用 JS 模板表。"""
    point_table = None
    line_table = None
    items = []
    js_info = (discovered or {}).get("JS")
    if js_info:
        items.append(("JS", js_info))
    for code, info in (discovered or {}).items():
        if code != "JS":
            items.append((code, info))
    for _code, info in items:
        if point_table is None and info.get("point"):
            point_table = info["point"]
        if line_table is None and info.get("line"):
            line_table = info["line"]
        if point_table and line_table:
            break
    return point_table, line_table


def match_mdb_render_group(point_columns, line_columns, render_groups):
    """
    用样例点/线表字段匹配「MDB库渲染」结构组。
    返回匹配到的 group dict；未匹配返回 None。
    """
    point_cols = list(point_columns or [])
    line_cols = list(line_columns or [])
    for group in render_groups or []:
        point_cfg = group.get("point") or {}
        line_cfg = group.get("line") or {}
        point_ok = columns_have_fields(
            point_cols,
            [
                point_cfg.get("pk_field"),
                point_cfg.get("x_field"),
                point_cfg.get("y_field"),
                point_cfg.get("type_field"),
            ],
        )
        line_ok = columns_have_fields(
            line_cols,
            [
                line_cfg.get("start_field"),
                line_cfg.get("end_field"),
                line_cfg.get("type_field"),
            ],
        )
        # 至少要能校验到已有的几何侧；若某侧样例表缺失则只校验另一侧
        if point_cols and line_cols:
            if point_ok and line_ok:
                return group
        elif point_cols:
            if point_ok:
                return group
        elif line_cols:
            if line_ok:
                return group
    return None


def match_mdb_render_group_from_connection(conn, discovered, render_groups, table_names=None):
    """打开连接后，优先按各结构组的表命名规则取样例表，再匹配字段。"""
    tables = list(table_names or [])
    for group in render_groups or []:
        point_pat = (group.get("point") or {}).get("table_pattern")
        line_pat = (group.get("line") or {}).get("table_pattern")
        point_table = None
        line_table = None
        for code in ["JS"] + list(PIPELINE_TYPES):
            point_table = resolve_existing_table(
                tables, [apply_table_pattern(point_pat, code)]
            )
            line_table = resolve_existing_table(
                tables, [apply_table_pattern(line_pat, code)]
            )
            if not point_table:
                point_table = (discovered.get(code) or {}).get("point")
            if not line_table:
                line_table = (discovered.get(code) or {}).get("line")
            if point_table or line_table:
                break
        point_columns = [c["name"] for c in conn.get_columns(point_table)] if point_table else []
        line_columns = [c["name"] for c in conn.get_columns(line_table)] if line_table else []
        if not point_columns and not line_columns:
            continue
        matched = match_mdb_render_group(point_columns, line_columns, [group])
        if matched:
            return matched

    point_table, line_table = _sample_tables(discovered)
    point_columns = []
    line_columns = []
    if point_table:
        point_columns = [c["name"] for c in conn.get_columns(point_table)]
    if line_table:
        line_columns = [c["name"] for c in conn.get_columns(line_table)]
    if not point_columns and not line_columns:
        return None
    return match_mdb_render_group(point_columns, line_columns, render_groups)


class TableProfile:
    def __init__(self, table_name, geom_kind, columns, render_group=None):
        self.table_name = table_name
        self.geom_kind = geom_kind
        self.columns = list(columns or [])
        self.render_group = render_group
        self.structure_type = (
            (render_group or {}).get("id")
            or detect_structure_type(self.columns)
        )
        self.type_field = None

        if render_group:
            self._apply_render_group(render_group)
        else:
            self._apply_legacy_candidates()

    def _apply_legacy_candidates(self):
        self.pk_field = _pick_column(
            self.columns,
            POINT_KEY_CANDIDATES if self.geom_kind == "point" else LINE_KEY_CANDIDATES,
        )
        self.x_field = (
            _pick_column(self.columns, POINT_X_CANDIDATES)
            if self.geom_kind == "point" else None
        )
        self.y_field = (
            _pick_column(self.columns, POINT_Y_CANDIDATES)
            if self.geom_kind == "point" else None
        )
        self.start_field = (
            _pick_column(self.columns, LINE_START_CANDIDATES)
            if self.geom_kind == "line" else None
        )
        self.end_field = (
            _pick_column(self.columns, LINE_END_CANDIDATES)
            if self.geom_kind == "line" else None
        )
        self.type_field = None

    def _apply_render_group(self, group):
        point_cfg = group.get("point") or {}
        line_cfg = group.get("line") or {}
        if self.geom_kind == "point":
            self.pk_field = resolve_column(self.columns, point_cfg.get("pk_field"))
            self.x_field = resolve_column(self.columns, point_cfg.get("x_field"))
            self.y_field = resolve_column(self.columns, point_cfg.get("y_field"))
            self.start_field = None
            self.end_field = None
            self.type_field = resolve_column(self.columns, point_cfg.get("type_field"))
        else:
            self.pk_field = None
            self.x_field = None
            self.y_field = None
            self.start_field = resolve_column(self.columns, line_cfg.get("start_field"))
            self.end_field = resolve_column(self.columns, line_cfg.get("end_field"))
            self.type_field = resolve_column(self.columns, line_cfg.get("type_field"))
            # 线表主键：若有 ID 用 ID，否则用起点号
            self.pk_field = _pick_column(self.columns, LINE_KEY_CANDIDATES) or self.start_field

    def validate(self):
        if self.geom_kind == "point":
            if not self.x_field or not self.y_field:
                raise ValueError(f"表 {self.table_name} 缺少 X/Y 坐标字段，无法构建点几何")
            if not self.pk_field:
                raise ValueError(f"表 {self.table_name} 缺少点号/主键字段")
        else:
            if not self.start_field or not self.end_field:
                raise ValueError(
                    f"表 {self.table_name} 缺少起点/终点（连接方向）字段，无法构建线几何"
                )
            if not self.pk_field:
                self.pk_field = self.start_field
