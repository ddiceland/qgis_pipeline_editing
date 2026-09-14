# -*- coding: utf-8 -*-
"""本插件 profiles.json 配置读写（独立于导出插件）。"""

import copy
import json
import os

from .attribute_mappings import (
    build_rule_sets_from_legacy,
    default_rule_sets,
    empty_rule_set,
    normalize_rule_sets,
)
from .config_ids import align_render_structure_ids
from .config_schema import (
    build_default_mdb_structures_and_mappings,
    empty_mdb_structure,
    empty_structure_mapping_block,
    migrate_profiles_dict,
    normalize_mdb_structure,
    normalize_pg_table_schemas,
    normalize_structure_mappings,
)
from .pinyin_slug import unique_config_id
from .pipe_catalog import PIPELINE_TYPES
from .pipe_colors import build_default_pipe_colors

PIPELINE_COLOR_TYPES = list(PIPELINE_TYPES)

# MDB 库图形渲染字段结构组（点/线必填字段名；管线类型字段可空=按表名判断）
DEFAULT_MDB_RENDER_GROUPS = [
    {
        "id": "zhengyuan",
        "label": "正元结构",
        "point": {
            "table_pattern": "{code}POINT",
            "pk_field": "物探点号",
            "x_field": "X",
            "y_field": "Y",
            "type_field": "",
        },
        "line": {
            "table_pattern": "{code}LINE",
            "start_field": "起点点号",
            "end_field": "连接方向",
            "type_field": "",
        },
    },
    {
        "id": "xian",
        "label": "西安结构",
        "point": {
            "table_pattern": "{code}_POINT",
            "pk_field": "EXPNO",
            "x_field": "X",
            "y_field": "Y",
            "type_field": "",
        },
        "line": {
            "table_pattern": "{code}_LINE",
            "start_field": "SPOINT",
            "end_field": "EPOINT",
            "type_field": "",
        },
    },
]

DEFAULT_PG_CONFIG = {
    "point": {
        "schema": "public",
        "table": "",
        "geom_col": "geom",
        "key_field": "",
        "wellno_field": "expno",
        "type_field": "",
        "gtype_field": "gtype",
    },
    "line": {
        "schema": "public",
        "table": "",
        "geom_col": "geom",
        "start_field": "",
        "end_field": "",
        "type_field": "",
        "gtype_field": "gtype",
    },
    "max_expno": {
        "schema": "public",
        "table": "",
        "ptype_field": "ptype",
        "max_field": "max_expno",
    },
}


def default_pipe_colors():
    return build_default_pipe_colors(PIPELINE_COLOR_TYPES)


def plugin_root_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_profiles_path():
    """本插件 config/profiles.json（与导出插件完全独立）。"""
    return os.path.join(plugin_root_dir(), "config", "profiles.json")


def _merge_pipe_colors(pipe_colors):
    merged = default_pipe_colors()
    if isinstance(pipe_colors, dict):
        for code in PIPELINE_COLOR_TYPES:
            if code in pipe_colors and pipe_colors[code]:
                merged[code] = str(pipe_colors[code]).strip()
    return merged


def _merge_pg_config(pg_config):
    merged = copy.deepcopy(DEFAULT_PG_CONFIG)
    if not isinstance(pg_config, dict):
        return merged
    for layer in ("point", "line"):
        if layer in pg_config and isinstance(pg_config[layer], dict):
            merged[layer].update(pg_config[layer])
    if isinstance(pg_config.get("max_expno"), dict):
        merged["max_expno"].update(pg_config["max_expno"])
    if not (merged["point"].get("wellno_field") or "").strip():
        merged["point"]["wellno_field"] = "expno"
    for dead in ("material_field", "dtype_field"):
        merged["line"].pop(dead, None)
    merged.pop("road_network", None)
    merged.pop("road_centerline", None)
    return merged


def _default_render_table_pattern(gid, kind):
    """已保存结构组缺表命名时，按内置结构补默认值（西安用下划线）。"""
    for item in DEFAULT_MDB_RENDER_GROUPS:
        if item.get("id") == gid:
            return ((item.get(kind) or {}).get("table_pattern") or "").strip()
    return "{code}POINT" if kind == "point" else "{code}LINE"


def _normalize_mdb_render_group(raw, fallback_id="group"):
    src = raw if isinstance(raw, dict) else {}
    point = src.get("point") if isinstance(src.get("point"), dict) else {}
    line = src.get("line") if isinstance(src.get("line"), dict) else {}
    gid = (src.get("id") or fallback_id or "group").strip() or fallback_id
    label = (src.get("label") or gid).strip() or gid
    point_pat = (point.get("table_pattern") or "").strip() or _default_render_table_pattern(gid, "point")
    line_pat = (line.get("table_pattern") or "").strip() or _default_render_table_pattern(gid, "line")
    return {
        "id": gid,
        "label": label,
        "point": {
            "table_pattern": point_pat or "{code}POINT",
            "pk_field": (point.get("pk_field") or "").strip(),
            "x_field": (point.get("x_field") or "").strip(),
            "y_field": (point.get("y_field") or "").strip(),
            "type_field": (point.get("type_field") or "").strip(),
        },
        "line": {
            "table_pattern": line_pat or "{code}LINE",
            "start_field": (line.get("start_field") or "").strip(),
            "end_field": (line.get("end_field") or "").strip(),
            "type_field": (line.get("type_field") or "").strip(),
        },
    }


def _merge_mdb_render_groups(raw):
    if not isinstance(raw, list) or not raw:
        return [copy.deepcopy(g) for g in DEFAULT_MDB_RENDER_GROUPS]
    result = []
    seen = set()
    for idx, item in enumerate(raw):
        group = _normalize_mdb_render_group(item, fallback_id=f"group_{idx + 1}")
        if group["id"] in seen:
            group["id"] = f"{group['id']}_{idx + 1}"
        seen.add(group["id"])
        result.append(group)
    return result


class SharedExportConfig:
    """读写本插件 config/profiles.json。"""

    def __init__(self, config_path=None):
        self.config_path = config_path or resolve_profiles_path()
        self.pg_config = copy.deepcopy(DEFAULT_PG_CONFIG)
        self.pg_table_schemas = normalize_pg_table_schemas(None)
        self.pipe_colors = default_pipe_colors()
        self.rule_sets = default_rule_sets()
        self.mdb_structures = []
        self.mdb_render_groups = [copy.deepcopy(g) for g in DEFAULT_MDB_RENDER_GROUPS]
        self.structure_mappings = normalize_structure_mappings(None)
        self._migrated = False
        self.load()

    def load(self):
        self.pg_config = copy.deepcopy(DEFAULT_PG_CONFIG)
        self.pg_table_schemas = normalize_pg_table_schemas(None)
        self.pipe_colors = default_pipe_colors()
        self.rule_sets = default_rule_sets()
        self.mdb_structures = []
        self.mdb_render_groups = [copy.deepcopy(g) for g in DEFAULT_MDB_RENDER_GROUPS]
        self.structure_mappings = normalize_structure_mappings(None)
        self._migrated = False

        defaults_st, defaults_map = build_default_mdb_structures_and_mappings()
        self.mdb_structures = defaults_st
        self.structure_mappings = defaults_map

        if not os.path.isfile(self.config_path):
            return
        try:
            with open(self.config_path, "r", encoding="utf-8") as fp:
                loaded = json.load(fp)
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(loaded, dict):
            return

        self.pg_config = _merge_pg_config(loaded.get("pg_config", {}))
        self.pipe_colors = _merge_pipe_colors(loaded.get("pipe_colors", {}))
        self.rule_sets, rule_sets_migrated = self._load_rule_sets(loaded)
        # zhengyuan / xian / custom_structures 仍由 migrate_profiles_dict 从 JSON 读取
        pg_schemas, structures, mappings, migrated = migrate_profiles_dict(loaded)
        self.pg_table_schemas = pg_schemas
        self.mdb_structures = structures
        self.structure_mappings = mappings
        self._migrated = migrated
        self.mdb_render_groups = self._load_mdb_render_groups(loaded)
        aligned = align_render_structure_ids(
            self.mdb_render_groups, self.mdb_structures, self.structure_mappings
        )
        if aligned:
            self._migrated = True
        self._sync_pg_config_table_names_from_schemas()
        if aligned or rule_sets_migrated:
            try:
                self.save()
                if aligned or migrated:
                    self._migrated = True
            except OSError:
                pass

    def _load_rule_sets(self, loaded):
        raw = loaded.get("rule_sets") if isinstance(loaded, dict) else None
        if isinstance(raw, list) and raw:
            have_ids = {
                (item.get("id") or "")
                for item in raw
                if isinstance(item, dict)
            }
            missing_builtin = any(
                builtin not in have_ids
                for builtin in ("angle", "sequence", "wellno", "xyz", "date")
            )
            return normalize_rule_sets(raw), missing_builtin
        return build_rule_sets_from_legacy(
            loaded.get("material_config") if isinstance(loaded, dict) else None,
            loaded.get("dtype_config") if isinstance(loaded, dict) else None,
        ), True

    def _load_mdb_render_groups(self, loaded):
        """独立加载渲染结构组；没有单独配置时再从库结构.render 兜底一次。"""
        raw = loaded.get("mdb_render_groups") if isinstance(loaded, dict) else None
        if isinstance(raw, list) and raw:
            return _merge_mdb_render_groups(raw)
        derived = []
        for s in self.mdb_structures or []:
            render = s.get("render") if isinstance(s.get("render"), dict) else {}
            point = render.get("point") if isinstance(render.get("point"), dict) else {}
            line = render.get("line") if isinstance(render.get("line"), dict) else {}
            if any((point or {}).values()) or any((line or {}).values()):
                derived.append({
                    "id": s.get("id"),
                    "label": s.get("label") or s.get("id"),
                    "point": point,
                    "line": line,
                })
        if derived:
            self._migrated = True
            return _merge_mdb_render_groups(derived)
        return _merge_mdb_render_groups(None)

    def _sync_pg_config_table_names_from_schemas(self):
        """快照中的 schema/table 写回 pg_config，供图层加载使用。"""
        for kind in ("point", "line"):
            snap = self.pg_table_schemas.get(kind) or {}
            if snap.get("schema"):
                self.pg_config[kind]["schema"] = snap["schema"]
            if snap.get("table"):
                self.pg_config[kind]["table"] = snap["table"]

    def get_pg_config(self):
        return copy.deepcopy(self.pg_config)

    def set_pg_config(self, pg_config):
        self.pg_config = _merge_pg_config(pg_config)

    def get_pg_table_schemas(self):
        return copy.deepcopy(self.pg_table_schemas)

    def set_pg_table_schemas(self, schemas):
        self.pg_table_schemas = normalize_pg_table_schemas(schemas)
        self._sync_pg_config_table_names_from_schemas()

    def get_pg_pipe_type_codes(self):
        snap = (self.pg_table_schemas or {}).get("pipe_types") or {}
        return list(snap.get("codes") or [])

    def get_pipe_colors(self):
        return copy.deepcopy(self.pipe_colors)

    def set_pipe_colors(self, pipe_colors):
        self.pipe_colors = _merge_pipe_colors(pipe_colors)

    def get_rule_sets(self):
        return copy.deepcopy(self.rule_sets)

    def set_rule_sets(self, rule_sets):
        self.rule_sets = normalize_rule_sets(rule_sets)

    def add_rule_set(self, name):
        name = (name or "").strip()
        if not name:
            raise ValueError("规则集名称不能为空")
        for item in self.rule_sets:
            if (item.get("label") or "") == name:
                raise ValueError(f"规则集名称已存在：{name}")
        existing = {item.get("id") for item in self.rule_sets}
        idx = 1
        while f"rule_{idx}" in existing:
            idx += 1
        gid = f"rule_{idx}"
        item = empty_rule_set(gid, name)
        self.rule_sets.append(item)
        return copy.deepcopy(item)

    def get_rule_set(self, rule_set_id):
        sid = (rule_set_id or "").strip()
        for item in self.rule_sets:
            if (item.get("id") or "") == sid:
                return copy.deepcopy(item)
        return None

    def get_rule_set_rows(self, rule_set_id):
        sid = (rule_set_id or "").strip()
        for item in self.rule_sets:
            if (item.get("id") or "") == sid:
                return copy.deepcopy(item.get("rows") or [])
        return []

    def list_structures(self):
        """MDB 库结构列表 [(id, label), ...]。"""
        return [
            (s.get("id"), s.get("label") or s.get("id"))
            for s in self.mdb_structures
        ]

    def get_mdb_structures(self):
        return copy.deepcopy(self.mdb_structures)

    def set_mdb_structures(self, structures):
        result = []
        for i, item in enumerate(structures or []):
            result.append(normalize_mdb_structure(item, fallback_id=f"structure_{i+1}"))
        self.mdb_structures = result or build_default_mdb_structures_and_mappings()[0]

    def get_mdb_structure(self, structure_id):
        for s in self.mdb_structures:
            if s.get("id") == structure_id:
                return copy.deepcopy(s)
        return None

    def list_render_groups_without_structure(self):
        """已有渲染组、尚未配置库结构的 (id, label)。"""
        have = {(item.get("id") or "").strip() for item in self.mdb_structures}
        result = []
        for group in self.mdb_render_groups:
            gid = (group.get("id") or "").strip()
            if gid and gid not in have:
                result.append((gid, group.get("label") or gid))
        return result

    def add_mdb_structure_for_render_group(self, render_group_id):
        gid = (render_group_id or "").strip()
        if not gid:
            raise ValueError("请选择已配置的「MDB库渲染」结构组")
        group = None
        for item in self.mdb_render_groups:
            if (item.get("id") or "").strip() == gid:
                group = item
                break
        if group is None:
            raise ValueError("未找到该「MDB库渲染」结构组，请先新增渲染组。")
        if self.get_mdb_structure(gid):
            raise ValueError("渲染组「%s」已有对应的库结构" % (group.get("label") or gid))
        label = (group.get("label") or gid).strip() or gid
        st = empty_mdb_structure(gid, label, "JS", [])
        self.mdb_structures.append(st)
        for direction in ("export", "import"):
            self.structure_mappings[direction][gid] = empty_structure_mapping_block(
                gid, "JS", []
            )
        return st

    def get_structure_mappings(self):
        return copy.deepcopy(self.structure_mappings)

    def set_structure_mappings(self, mappings):
        self.structure_mappings = normalize_structure_mappings(mappings)

    def get_mapping_block(self, direction, key):
        part = self.structure_mappings.get(direction) or {}
        block = part.get(key)
        return copy.deepcopy(block) if block else None

    def set_mapping_block(self, direction, key, block):
        from .config_schema import normalize_structure_mapping_block as _norm_block
        if direction not in self.structure_mappings:
            self.structure_mappings[direction] = {}
        self.structure_mappings[direction][key] = _norm_block(block, key)

    def get_mdb_render_group(self, group_id):
        gid = (group_id or "").strip()
        for group in self.mdb_render_groups:
            if (group.get("id") or "").strip() == gid:
                return copy.deepcopy(group)
        return None

    def get_mdb_render_groups(self):
        """独立的 MDB 渲染结构组，供加载匹配使用。"""
        return copy.deepcopy(self.mdb_render_groups)

    def set_mdb_render_groups(self, groups):
        self.mdb_render_groups = _merge_mdb_render_groups(groups)

    def add_mdb_render_group(self, name):
        name = (name or "").strip()
        if not name:
            raise ValueError("结构组名称不能为空")
        for g in self.mdb_render_groups:
            if (g.get("label") or "") == name:
                raise ValueError(f"结构组名称已存在：{name}")
        existing = {g.get("id") for g in self.mdb_render_groups}
        gid = unique_config_id(name, existing, fallback="group")
        group = _normalize_mdb_render_group(
            {"id": gid, "label": name}, fallback_id=gid
        )
        self.mdb_render_groups.append(group)
        return copy.deepcopy(group)

    def conversion_rule_sets(self):
        """可供映射选择的转换规则集。"""
        result = []
        for item in self.rule_sets or []:
            result.append({
                "id": item.get("id"),
                "label": item.get("label") or item.get("id"),
                "targets": copy.deepcopy(item.get("targets") or []),
            })
        return result

    def save(self):
        data = {}
        if os.path.isfile(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as fp:
                    loaded = json.load(fp)
                if isinstance(loaded, dict):
                    data = loaded
            except (OSError, json.JSONDecodeError):
                data = {}

        data["pg_config"] = self.get_pg_config()
        data["pg_table_schemas"] = self.get_pg_table_schemas()
        data["pipe_colors"] = self.get_pipe_colors()
        data["rule_sets"] = self.get_rule_sets()
        data["mdb_structures"] = self.get_mdb_structures()
        data["mdb_render_groups"] = self.get_mdb_render_groups()
        data["structure_mappings"] = self.get_structure_mappings()
        # 旧导出插件字段已迁移到 mdb_structures / rule_sets，保存时不再回写。
        for legacy_key in (
            "zhengyuan", "xian", "custom_structures",
            "material_config", "dtype_config",
        ):
            data.pop(legacy_key, None)

        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)
        self._migrated = False
