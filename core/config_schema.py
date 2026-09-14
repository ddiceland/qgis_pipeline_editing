# -*- coding: utf-8 -*-
"""配置数据结构：PG 表快照、MDB 库结构、结构映射。"""

import copy
from datetime import datetime

from .pipe_catalog import PIPELINE_TYPES
from .sql_ident import ident_name


def _now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def empty_pg_table_snapshot():
    return {
        "schema": "public",
        "table": "",
        "loaded_at": "",
        "columns": [],  # [{name, data_type, udt_name, is_nullable, ordinal_position}]
    }


def empty_pg_pipe_types():
    return {
        "schema": "public",
        "table": "",
        "loaded_at": "",
        "codes": [],
        "error": "",
    }


def empty_pg_table_schemas():
    return {
        "point": empty_pg_table_snapshot(),
        "line": empty_pg_table_snapshot(),
        "pipe_types": empty_pg_pipe_types(),
    }


def order_pipe_codes(codes):
    """去重、转大写，目录内管类按 PIPELINE_TYPES 排序，其余跟在后面。"""
    seen = []
    have = set()
    for item in codes or []:
        code = str(item or "").strip().upper()
        if code and code not in have:
            have.add(code)
            seen.append(code)
    ordered = [c for c in PIPELINE_TYPES if c in have]
    extra = [c for c in seen if c not in PIPELINE_TYPES]
    return ordered + extra


def _pipe_dict_entry(pipes_src, code):
    if not isinstance(pipes_src, dict) or not code:
        return {}
    if isinstance(pipes_src.get(code), dict):
        return pipes_src.get(code)
    wanted = str(code).strip().upper()
    for key, val in pipes_src.items():
        if str(key or "").strip().upper() == wanted and isinstance(val, dict):
            return val
    return {}


def mdb_structure_pipe_codes(structure, default_all=True):
    """本结构实际配置的管类。未写 pipes 时，新增结构默认使用全部目录管类。"""
    pipes = (structure or {}).get("pipes")
    if isinstance(pipes, dict) and pipes:
        return order_pipe_codes(pipes.keys())
    if default_all:
        return list(PIPELINE_TYPES)
    return []


def _normalize_independent_pipes(raw, allowed_codes=None):
    codes = order_pipe_codes(raw)
    if allowed_codes is None:
        return codes
    allowed = {str(x).strip().upper() for x in allowed_codes if str(x).strip()}
    return [c for c in codes if c in allowed]


def empty_mdb_field(name="", mdb_type="TEXT", mdb_size="50", decimal_places=""):
    return {
        "name": name,
        "mdb_type": mdb_type or "TEXT",
        "mdb_size": mdb_size or "",
        "decimal_places": "" if decimal_places in (None, "") else str(decimal_places).strip(),
    }


def empty_mdb_pipe_structure(pipe_code):
    return {
        "point_table": f"{pipe_code}POINT",
        "line_table": f"{pipe_code}LINE",
        "point_fields": [],
        "line_fields": [],
    }


def empty_render_roles():
    return {
        "point": {
            "pk_field": "",
            "x_field": "",
            "y_field": "",
            "type_field": "",
        },
        "line": {
            "start_field": "",
            "end_field": "",
            "type_field": "",
        },
    }


def empty_mdb_structure(structure_id, label, template_pipe="JS", independent_pipes=None,
                        pipe_codes=None):
    codes = order_pipe_codes(pipe_codes) if pipe_codes else list(PIPELINE_TYPES)
    if not codes:
        codes = list(PIPELINE_TYPES)
    template = (template_pipe or "JS").strip().upper() or "JS"
    if template not in codes:
        template = "JS" if "JS" in codes else codes[0]
    pipes = {code: empty_mdb_pipe_structure(code) for code in codes}
    return {
        "id": structure_id,
        "label": label,
        "template_pipe": template,
        "independent_pipes": _normalize_independent_pipes(independent_pipes, codes),
        "render": empty_render_roles(),
        "pipes": pipes,
    }


def empty_structure_mapping_block(structure_id, template_pipe="JS", independent_pipes=None):
    return {
        "structure_id": structure_id,
        "template_pipe": template_pipe or "JS",
        "independent_pipes": list(independent_pipes or []),
        "point": [],
        "line": [],
        "pipes": {},  # convert 模式仍按管类
    }


def empty_structure_mappings():
    return {
        "export": {},   # structure_id -> block
        "import": {},
        "convert": {},  # "src_id__to__dst_id" -> block + source_id/target_id
    }


def normalize_pg_column(raw):
    src = raw if isinstance(raw, dict) else {}
    return {
        "name": (src.get("name") or "").strip(),
        "data_type": (src.get("data_type") or "").strip(),
        "udt_name": (src.get("udt_name") or "").strip(),
        "is_nullable": (src.get("is_nullable") or "YES").strip().upper() or "YES",
        "ordinal_position": int(src.get("ordinal_position") or 0),
    }


def normalize_pg_table_snapshot(raw):
    src = raw if isinstance(raw, dict) else {}
    cols = []
    for item in src.get("columns") or []:
        col = normalize_pg_column(item)
        if col["name"]:
            cols.append(col)
    return {
        "schema": (src.get("schema") or "public").strip() or "public",
        "table": (src.get("table") or "").strip(),
        "loaded_at": (src.get("loaded_at") or "").strip(),
        "columns": cols,
    }


def normalize_pg_pipe_types(raw):
    src = raw if isinstance(raw, dict) else {}
    return {
        "schema": (src.get("schema") or "public").strip() or "public",
        "table": (src.get("table") or "").strip(),
        "loaded_at": (src.get("loaded_at") or "").strip(),
        "codes": order_pipe_codes(src.get("codes")),
        "error": (src.get("error") or "").strip(),
    }


def normalize_pg_table_schemas(raw):
    src = raw if isinstance(raw, dict) else {}
    return {
        "point": normalize_pg_table_snapshot(src.get("point")),
        "line": normalize_pg_table_snapshot(src.get("line")),
        "pipe_types": normalize_pg_pipe_types(src.get("pipe_types")),
    }


def normalize_mdb_field(raw):
    from .access_field_types import type_needs_decimals, type_needs_size

    src = raw if isinstance(raw, dict) else {}
    field = empty_mdb_field(
        (src.get("name") or "").strip(),
        (src.get("mdb_type") or "TEXT").strip() or "TEXT",
        (src.get("mdb_size") or "").strip(),
        src.get("decimal_places"),
    )
    if not type_needs_size(field["mdb_type"]):
        field["mdb_size"] = ""
    if not type_needs_decimals(field["mdb_type"]):
        field["decimal_places"] = ""
    return field


def normalize_mdb_structure(raw, fallback_id="structure"):
    src = raw if isinstance(raw, dict) else {}
    sid = (src.get("id") or fallback_id).strip() or fallback_id
    label = (src.get("label") or sid).strip() or sid
    pipes_src = src.get("pipes") if isinstance(src.get("pipes"), dict) else {}
    codes = mdb_structure_pipe_codes({"pipes": pipes_src}, default_all=True)
    template = (src.get("template_pipe") or "JS").strip().upper() or "JS"
    if template not in codes:
        template = "JS" if "JS" in codes else (codes[0] if codes else "JS")
    independent = _normalize_independent_pipes(src.get("independent_pipes"), codes)
    render_src = src.get("render") if isinstance(src.get("render"), dict) else {}
    render = empty_render_roles()
    for kind in ("point", "line"):
        part = render_src.get(kind) if isinstance(render_src.get(kind), dict) else {}
        for key in render[kind]:
            render[kind][key] = (part.get(key) or "").strip()

    pipes = {}
    for code in codes:
        p = _pipe_dict_entry(pipes_src, code)
        pipes[code] = {
            "point_table": (p.get("point_table") or f"{code}POINT").strip(),
            "line_table": (p.get("line_table") or f"{code}LINE").strip(),
            "point_fields": [
                normalize_mdb_field(f) for f in (p.get("point_fields") or [])
                if (f or {}).get("name")
            ],
            "line_fields": [
                normalize_mdb_field(f) for f in (p.get("line_fields") or [])
                if (f or {}).get("name")
            ],
        }
    return sync_mdb_structure_fields_from_template({
        "id": sid,
        "label": label,
        "template_pipe": template,
        "independent_pipes": independent,
        "render": render,
        "pipes": pipes,
    })


def sync_mdb_structure_fields_from_template(structure):
    """
    将模板管类的点/线字段复制到非独立管类。
    各管类自己的点表名、线表名保持不变。
    """
    src = structure if isinstance(structure, dict) else {}
    template = (src.get("template_pipe") or "JS").strip().upper() or "JS"
    independent = {
        str(code).strip().upper()
        for code in (src.get("independent_pipes") or [])
        if str(code).strip()
    }
    pipes = src.get("pipes")
    if not isinstance(pipes, dict):
        pipes = {}
        src["pipes"] = pipes
    template_pipe = pipes.get(template) if isinstance(pipes.get(template), dict) else {}
    point_fields = copy.deepcopy(template_pipe.get("point_fields") or [])
    line_fields = copy.deepcopy(template_pipe.get("line_fields") or [])
    for code in mdb_structure_pipe_codes(src, default_all=False):
        if code == template or code.upper() in independent:
            continue
        pipe = pipes.get(code)
        if not isinstance(pipe, dict):
            continue
        pipe["point_fields"] = copy.deepcopy(point_fields)
        pipe["line_fields"] = copy.deepcopy(line_fields)
    return src


def normalize_mapping_row(raw, src_key="src_field", dst_key="dst_field"):
    src = raw if isinstance(raw, dict) else {}
    # 兼容旧导出映射 pg_field/mdb_field
    src_field = ident_name(src.get(src_key) or src.get("pg_field") or src.get("src_field") or "")
    dst_field = ident_name(src.get(dst_key) or src.get("mdb_field") or src.get("dst_field") or "")
    return {
        "src_field": src_field,
        "dst_field": dst_field,
        "mdb_type": (src.get("mdb_type") or "TEXT").strip() or "TEXT",
        "mdb_size": (src.get("mdb_size") or "").strip(),
        "rule_set": (src.get("rule_set") or "").strip(),
        "rule_target": (src.get("rule_target") or "").strip(),
    }


def normalize_pipe_mapping(raw):
    src = raw if isinstance(raw, dict) else {}
    return {
        "point": [normalize_mapping_row(r) for r in (src.get("point") or src.get("point_field_mapping") or [])],
        "line": [normalize_mapping_row(r) for r in (src.get("line") or src.get("line_field_mapping") or [])],
    }


def normalize_structure_mapping_block(raw, structure_id):
    src = raw if isinstance(raw, dict) else {}
    sid = (src.get("structure_id") or structure_id or "").strip()
    template = (src.get("template_pipe") or "JS").strip() or "JS"
    independent = [
        str(x).strip() for x in (src.get("independent_pipes") or []) if str(x).strip()
    ]

    # 总映射（导出/导入）：顶层 point/line
    top_point = [normalize_mapping_row(r) for r in (src.get("point") or [])]
    top_line = [normalize_mapping_row(r) for r in (src.get("line") or [])]

    # 兼容旧格式：若顶层为空但 pipes 中有数据，取模板管类的映射作为总映射
    pipes_src = src.get("pipes") if isinstance(src.get("pipes"), dict) else {}
    if not top_point and not top_line and pipes_src:
        fallback_pipe = pipes_src.get(template) or {}
        if not fallback_pipe:
            for code in PIPELINE_TYPES:
                fallback_pipe = pipes_src.get(code) or {}
                if fallback_pipe.get("point") or fallback_pipe.get("line"):
                    break
        fallback = normalize_pipe_mapping(fallback_pipe)
        top_point = fallback["point"]
        top_line = fallback["line"]

    # convert 仍按管类（只保留已有的，不补全目录）
    pipes = {}
    for code in order_pipe_codes(pipes_src.keys()):
        entry = _pipe_dict_entry(pipes_src, code)
        if entry:
            pipes[code] = normalize_pipe_mapping(entry)

    block = {
        "structure_id": sid,
        "template_pipe": template,
        "independent_pipes": independent,
        "point": top_point,
        "line": top_line,
        "pipes": pipes,
    }
    if src.get("source_id"):
        block["source_id"] = str(src.get("source_id")).strip()
    if src.get("target_id"):
        block["target_id"] = str(src.get("target_id")).strip()
    return block


def _parse_convert_pair_ids(key, block=None):
    src = ((block or {}).get("source_id") or "").strip()
    dst = ((block or {}).get("target_id") or "").strip()
    if src and dst:
        return src, dst
    text = (key or "").strip()
    if "__to__" in text:
        left, right = text.split("__to__", 1)
        return left.strip(), right.strip()
    return "", ""


def mapping_block_has_rows(block):
    if not isinstance(block, dict):
        return False
    for kind in ("point", "line"):
        for row in block.get(kind) or []:
            dst = (row.get("dst_field") or "").strip()
            src = (row.get("src_field") or "").strip()
            is_seq = (
                (row.get("rule_set") or "").strip() == "sequence"
                or (row.get("rule_target") or "").strip() == "seq"
            )
            if dst and (src or is_seq):
                return True
    return False


def reverse_convert_mapping_block(block, source_id, target_id):
    """
    把 A→B 字段映射对调为 B→A。
    仅保留源、目标字段都有值的行；对照规则在名称/代码之间对调，角度规则在弧度/角度之间对调，
    时间规则在带分隔日期与紧凑日期之间对调。
    顺序号、井编号、坐标规则不反向（坐标在写入 geom 时使用，编号在写入时重新生成或对照更新）。
    """
    src = block if isinstance(block, dict) else {}

    def reverse_rows(rows):
        result = []
        seen = set()
        for row in rows or []:
            src_field = (row.get("src_field") or "").strip()
            dst_field = (row.get("dst_field") or "").strip()
            if not src_field or not dst_field:
                continue
            key = (dst_field.upper(), src_field.upper())
            if key in seen:
                continue
            seen.add(key)
            rule_set = (row.get("rule_set") or "").strip()
            rule_target = (row.get("rule_target") or "").strip()
            if rule_set == "sequence" or rule_target == "seq":
                continue
            if rule_set == "wellno" or rule_target in ("assign", "follow"):
                continue
            if rule_set == "xyz" or rule_target in ("x", "y", "z"):
                continue
            if rule_target == "code":
                rule_target = "name"
            elif rule_target == "name":
                rule_target = "code"
            elif rule_target == "radians":
                rule_target = "degrees"
            elif rule_target == "degrees":
                rule_target = "radians"
            elif rule_target == "dashed":
                rule_target = "compact"
            elif rule_target == "compact":
                rule_target = "dashed"
            elif not rule_set:
                rule_target = ""
            result.append({
                "src_field": dst_field,
                "dst_field": src_field,
                "mdb_type": (row.get("mdb_type") or "TEXT").strip() or "TEXT",
                "mdb_size": (row.get("mdb_size") or "").strip(),
                "rule_set": rule_set,
                "rule_target": rule_target if rule_set else "",
            })
        return result

    return {
        "structure_id": f"{source_id}__to__{target_id}",
        "source_id": source_id,
        "target_id": target_id,
        "template_pipe": (src.get("template_pipe") or "JS").strip() or "JS",
        "independent_pipes": list(src.get("independent_pipes") or []),
        "point": reverse_rows(src.get("point")),
        "line": reverse_rows(src.get("line")),
        "pipes": {},
    }


def fill_missing_reverse_convert_mappings(mappings, overwrite=False):
    """若已有 A→B 且缺少（或覆盖）B→A，则按字段对调补上。"""
    convert = (mappings or {}).get("convert")
    if not isinstance(convert, dict):
        return mappings
    existing_keys = list(convert.keys())
    for key in existing_keys:
        block = convert.get(key) or {}
        src_id, dst_id = _parse_convert_pair_ids(key, block)
        if not src_id or not dst_id or src_id == dst_id:
            continue
        if not mapping_block_has_rows(block):
            continue
        rev_key = f"{dst_id}__to__{src_id}"
        if not overwrite and mapping_block_has_rows(convert.get(rev_key)):
            continue
        convert[rev_key] = reverse_convert_mapping_block(block, dst_id, src_id)
    return mappings


def normalize_structure_mappings(raw):
    src = raw if isinstance(raw, dict) else {}
    result = empty_structure_mappings()
    for direction in ("export", "import", "convert"):
        part = src.get(direction) if isinstance(src.get(direction), dict) else {}
        for key, block in part.items():
            result[direction][str(key)] = normalize_structure_mapping_block(block, str(key))
    fill_missing_reverse_convert_mappings(result, overwrite=False)
    return result


# ---------- 从旧配置迁移 ----------

def _fields_from_old_mapping(mapping_list):
    fields = []
    seen = set()
    for item in mapping_list or []:
        name = (item.get("mdb_field") or "").strip()
        if not name or name.upper() in seen:
            continue
        seen.add(name.upper())
        fields.append(empty_mdb_field(
            name,
            item.get("mdb_type") or "TEXT",
            item.get("mdb_size") or "",
        ))
    return fields


def migrate_old_pipe_config_to_mdb_pipe(pipe_code, pipe_cfg):
    cfg = pipe_cfg or {}
    point = cfg.get("mdb_point") or {}
    line = cfg.get("mdb_line") or {}
    return {
        "point_table": (point.get("table") or f"{pipe_code}POINT").strip(),
        "line_table": (line.get("table") or f"{pipe_code}LINE").strip(),
        "point_fields": _fields_from_old_mapping(cfg.get("point_field_mapping")),
        "line_fields": _fields_from_old_mapping(cfg.get("line_field_mapping")),
    }


def migrate_old_structure_to_mdb_structure(structure_id, label, pipes_dict, render_group=None,
                                          template_pipe="JS", independent_pipes=None):
    structure = empty_mdb_structure(
        structure_id, label, template_pipe, independent_pipes
    )
    src_pipes = pipes_dict if isinstance(pipes_dict, dict) else {}
    for code in PIPELINE_TYPES:
        if code in src_pipes:
            structure["pipes"][code] = migrate_old_pipe_config_to_mdb_pipe(
                code, src_pipes.get(code)
            )
    if render_group and isinstance(render_group, dict):
        rp = render_group.get("point") or {}
        rl = render_group.get("line") or {}
        structure["render"] = {
            "point": {
                "pk_field": (rp.get("pk_field") or "").strip(),
                "x_field": (rp.get("x_field") or "").strip(),
                "y_field": (rp.get("y_field") or "").strip(),
                "type_field": (rp.get("type_field") or "").strip(),
            },
            "line": {
                "start_field": (rl.get("start_field") or "").strip(),
                "end_field": (rl.get("end_field") or "").strip(),
                "type_field": (rl.get("type_field") or "").strip(),
            },
        }
    elif structure_id == "zhengyuan":
        structure["render"] = {
            "point": {
                "pk_field": "物探点号", "x_field": "X", "y_field": "Y", "type_field": ""
            },
            "line": {
                "start_field": "起点点号", "end_field": "连接方向", "type_field": ""
            },
        }
    elif structure_id == "xian":
        structure["render"] = {
            "point": {
                "pk_field": "EXPNO", "x_field": "X", "y_field": "Y", "type_field": ""
            },
            "line": {
                "start_field": "SPOINT", "end_field": "EPOINT", "type_field": ""
            },
        }
        structure["independent_pipes"] = ["ZH", "FZ"]
    return structure


def migrate_old_mappings_to_export_block(structure_id, pipes_dict, template_pipe="JS",
                                         independent_pipes=None):
    block = empty_structure_mapping_block(
        structure_id, template_pipe, independent_pipes
    )
    src_pipes = pipes_dict if isinstance(pipes_dict, dict) else {}
    # 取模板管类的映射作为统一的总映射
    template_cfg = src_pipes.get(template_pipe or "JS") or {}
    if not template_cfg:
        for code in PIPELINE_TYPES:
            template_cfg = src_pipes.get(code) or {}
            if template_cfg.get("point_field_mapping") or template_cfg.get("line_field_mapping"):
                break
    for item in template_cfg.get("point_field_mapping") or []:
        block["point"].append(normalize_mapping_row({
            "src_field": item.get("pg_field"),
            "dst_field": item.get("mdb_field"),
            "mdb_type": item.get("mdb_type"),
            "mdb_size": item.get("mdb_size"),
        }))
    for item in template_cfg.get("line_field_mapping") or []:
        block["line"].append(normalize_mapping_row({
            "src_field": item.get("pg_field"),
            "dst_field": item.get("mdb_field"),
            "mdb_type": item.get("mdb_type"),
            "mdb_size": item.get("mdb_size"),
        }))
    return block


def build_default_mdb_structures_and_mappings():
    """无旧数据时的默认正元/西安。"""
    zhengyuan = empty_mdb_structure("zhengyuan", "正元结构", "JS", [])
    zhengyuan["render"] = {
        "point": {"pk_field": "物探点号", "x_field": "X", "y_field": "Y", "type_field": ""},
        "line": {"start_field": "起点点号", "end_field": "连接方向", "type_field": ""},
    }
    xian = empty_mdb_structure("xian", "西安结构", "JS", ["ZH", "FZ"])
    xian["render"] = {
        "point": {"pk_field": "EXPNO", "x_field": "X", "y_field": "Y", "type_field": ""},
        "line": {"start_field": "SPOINT", "end_field": "EPOINT", "type_field": ""},
    }
    structures = [zhengyuan, xian]
    mappings = empty_structure_mappings()
    mappings["export"]["zhengyuan"] = empty_structure_mapping_block("zhengyuan", "JS", [])
    mappings["export"]["xian"] = empty_structure_mapping_block("xian", "JS", ["ZH", "FZ"])
    mappings["import"]["zhengyuan"] = empty_structure_mapping_block("zhengyuan", "JS", [])
    mappings["import"]["xian"] = empty_structure_mapping_block("xian", "JS", ["ZH", "FZ"])
    return structures, mappings


def migrate_profiles_dict(loaded):
    """
    从旧 profiles 迁移出 mdb_structures / structure_mappings / pg_table_schemas。
    若已有新字段则规范化后返回；否则从 zhengyuan/xian/custom/mdb_render_groups 迁移。
    """
    data = loaded if isinstance(loaded, dict) else {}
    pg_table_schemas = normalize_pg_table_schemas(data.get("pg_table_schemas"))

    # 若点/线表名在 pg_config 里，同步到快照的 schema/table（不覆盖已有 columns）
    pg = data.get("pg_config") if isinstance(data.get("pg_config"), dict) else {}
    for kind in ("point", "line"):
        cfg = pg.get(kind) if isinstance(pg.get(kind), dict) else {}
        if cfg.get("schema"):
            pg_table_schemas[kind]["schema"] = cfg.get("schema") or "public"
        if cfg.get("table") and not pg_table_schemas[kind].get("table"):
            pg_table_schemas[kind]["table"] = cfg.get("table") or ""

    has_new = isinstance(data.get("mdb_structures"), list) and bool(data.get("mdb_structures"))
    if has_new:
        structures = [
            normalize_mdb_structure(item, fallback_id=f"structure_{i+1}")
            for i, item in enumerate(data.get("mdb_structures") or [])
        ]
        mappings = normalize_structure_mappings(data.get("structure_mappings"))
        return pg_table_schemas, structures, mappings, False

    # --- 自动迁移 ---
    render_by_id = {}
    for g in data.get("mdb_render_groups") or []:
        if isinstance(g, dict) and g.get("id"):
            render_by_id[str(g["id"])] = g

    structures = []
    mappings = empty_structure_mappings()

    zhengyuan_pipes = data.get("zhengyuan") if isinstance(data.get("zhengyuan"), dict) else {}
    xian_pipes = data.get("xian") if isinstance(data.get("xian"), dict) else {}

    if zhengyuan_pipes or True:
        st = migrate_old_structure_to_mdb_structure(
            "zhengyuan", "正元结构", zhengyuan_pipes,
            render_group=render_by_id.get("zhengyuan"),
            template_pipe="JS", independent_pipes=[],
        )
        structures.append(st)
        mappings["export"]["zhengyuan"] = migrate_old_mappings_to_export_block(
            "zhengyuan", zhengyuan_pipes, "JS", []
        )
        mappings["import"]["zhengyuan"] = empty_structure_mapping_block("zhengyuan", "JS", [])

    if xian_pipes or True:
        st = migrate_old_structure_to_mdb_structure(
            "xian", "西安结构", xian_pipes,
            render_group=render_by_id.get("xian"),
            template_pipe="JS", independent_pipes=["ZH", "FZ"],
        )
        structures.append(st)
        mappings["export"]["xian"] = migrate_old_mappings_to_export_block(
            "xian", xian_pipes, "JS", ["ZH", "FZ"]
        )
        mappings["import"]["xian"] = empty_structure_mapping_block(
            "xian", "JS", ["ZH", "FZ"]
        )

    customs = data.get("custom_structures") if isinstance(data.get("custom_structures"), dict) else {}
    for key, meta in customs.items():
        if not isinstance(meta, dict):
            continue
        label = (meta.get("label") or key).strip() or key
        pipes = meta.get("pipes") if isinstance(meta.get("pipes"), dict) else {}
        st = migrate_old_structure_to_mdb_structure(
            str(key), label, pipes,
            render_group=render_by_id.get(str(key)),
            template_pipe="JS", independent_pipes=[],
        )
        structures.append(st)
        mappings["export"][str(key)] = migrate_old_mappings_to_export_block(
            str(key), pipes, "JS", []
        )
        mappings["import"][str(key)] = empty_structure_mapping_block(str(key), "JS", [])

    # 渲染组中有、结构中没有的，补空结构
    existing_ids = {s["id"] for s in structures}
    for gid, g in render_by_id.items():
        if gid in existing_ids:
            continue
        label = (g.get("label") or gid).strip() or gid
        st = migrate_old_structure_to_mdb_structure(
            gid, label, {}, render_group=g, template_pipe="JS", independent_pipes=[]
        )
        structures.append(st)
        mappings["export"][gid] = empty_structure_mapping_block(gid, "JS", [])
        mappings["import"][gid] = empty_structure_mapping_block(gid, "JS", [])

    if not structures:
        structures, mappings = build_default_mdb_structures_and_mappings()

    return pg_table_schemas, structures, mappings, True
