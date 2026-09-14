# -*- coding: utf-8 -*-
"""材质 / 埋设方式配置默认值（与导出插件一致）。"""

DEFAULT_MATERIAL_CONFIG = [
    {"name": "铸铁", "code": "ZT", "pipe_types": ""},
    {"name": "钢", "code": "G", "pipe_types": ""},
    {"name": "砼", "code": "T", "pipe_types": ""},
    {"name": "聚乙烯", "code": "PE", "pipe_types": ""},
    {"name": "聚氯乙烯", "code": "PVC", "pipe_types": ""},
    {"name": "玻璃钢", "code": "BLG", "pipe_types": ""},
    {"name": "球墨铸铁", "code": "QM", "pipe_types": ""},
    {"name": "砖石", "code": "ZS", "pipe_types": ""},
    {"name": "砖", "code": "Z", "pipe_types": ""},
    {"name": "石", "code": "S", "pipe_types": ""},
    {"name": "石棉", "code": "SM", "pipe_types": ""},
    {"name": "陶瓷", "code": "TC", "pipe_types": ""},
    {"name": "铜", "code": "TZ", "pipe_types": ""},
    {"name": "钢芯铝绞线", "code": "VL", "pipe_types": ""},
    {"name": "光纤", "code": "GX", "pipe_types": ""},
    {"name": "高密度聚乙烯", "code": "HDPE", "pipe_types": ""},
]

DEFAULT_DTYPE_CONFIG = [
    {"name": "直埋", "code": "ZM", "pipe_types": ""},
    {"name": "管埋", "code": "GM", "pipe_types": ""},
    {"name": "管块", "code": "GK", "pipe_types": ""},
    {"name": "管沟", "code": "GG", "pipe_types": ""},
    {"name": "架空", "code": "JK", "pipe_types": ""},
    {"name": "地面", "code": "DM", "pipe_types": ""},
    {"name": "上架", "code": "SJ", "pipe_types": ""},
    {"name": "小通道", "code": "XTD", "pipe_types": ""},
    {"name": "综合管沟", "code": "ZH", "pipe_types": ""},
    {"name": "人防", "code": "RF", "pipe_types": ""},
    {"name": "井内连线", "code": "JN", "pipe_types": ""},
    {"name": "顶管", "code": "DG", "pipe_types": ""},
    {"name": "水下", "code": "SX", "pipe_types": ""},
    {"name": "地铁", "code": "DT", "pipe_types": ""},
    {"name": "管廊", "code": "GL", "pipe_types": ""},
]


def normalize_lookup_rows(raw_list):
    """允许空表；不回退到内置默认值。"""
    result = []
    if not isinstance(raw_list, list):
        return result
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        name = (item.get("name") or "").strip()
        code = (item.get("code") or "").strip()
        if not name and not code:
            continue
        result.append({
            "name": name,
            "code": code,
            "pipe_types": (item.get("pipe_types") or "").strip(),
        })
    return result


def normalize_attribute_mapping_list(raw_list, defaults):
    if not isinstance(raw_list, list) or not raw_list:
        return [dict(item) for item in defaults]
    result = normalize_lookup_rows(raw_list)
    return result or [dict(item) for item in defaults]


def _default_targets(name_header="名称"):
    name_label = (name_header or "").strip() or "名称"
    return [
        {"id": "name", "label": name_label},
        {"id": "code", "label": "代码"},
    ]


BUILTIN_RULE_IDS = ("material", "dtype", "angle", "sequence", "wellno", "xyz", "date")

ANGLE_TARGETS = [
    {"id": "radians", "label": "弧度制"},
    {"id": "degrees", "label": "角度制"},
]

SEQUENCE_TARGETS = [
    {"id": "seq", "label": "顺序号"},
]

WELLNO_TARGETS = [
    {"id": "assign", "label": "重编井号"},
    {"id": "follow", "label": "对照更新"},
]

XYZ_TARGETS = [
    {"id": "x", "label": "X"},
    {"id": "y", "label": "Y"},
    {"id": "z", "label": "Z"},
]

DATE_TARGETS = [
    {"id": "dashed", "label": "带分隔日期 2026-08-22"},
    {"id": "compact", "label": "紧凑日期 20260822"},
]


def default_angle_rule_set():
    return {
        "id": "angle",
        "label": "角度换算",
        "kind": "angle",
        "name_header": "",
        "targets": [dict(item) for item in ANGLE_TARGETS],
        "decimal_places": 6,
        "rows": [],
    }


def default_sequence_rule_set():
    return {
        "id": "sequence",
        "label": "顺序号",
        "kind": "sequence",
        "name_header": "",
        "targets": [dict(item) for item in SEQUENCE_TARGETS],
        "start_from": 1,
        "rows": [],
    }


def default_wellno_rule_set():
    return {
        "id": "wellno",
        "label": "井编号",
        "kind": "wellno",
        "name_header": "",
        "targets": [dict(item) for item in WELLNO_TARGETS],
        "type_width": 2,
        "seq_width": 10,
        "separator": "",
        "ptype_position": "prefix",
        "prefix": "",
        "suffix": "",
        "rows": [],
    }


def default_xyz_rule_set():
    return {
        "id": "xyz",
        "label": "坐标",
        "kind": "xyz",
        "name_header": "",
        "targets": [dict(item) for item in XYZ_TARGETS],
        "rows": [],
    }


def default_date_rule_set():
    return {
        "id": "date",
        "label": "时间",
        "kind": "date",
        "name_header": "",
        "targets": [dict(item) for item in DATE_TARGETS],
        "rows": [],
    }


def default_rule_sets():
    return [
        {
            "id": "material",
            "label": "材质",
            "kind": "lookup",
            "name_header": "中文名称",
            "targets": [
                {"id": "name", "label": "中文名称"},
                {"id": "code", "label": "代码"},
            ],
            "rows": [dict(item) for item in DEFAULT_MATERIAL_CONFIG],
        },
        {
            "id": "dtype",
            "label": "埋设方式",
            "kind": "lookup",
            "name_header": "中文名称",
            "targets": [
                {"id": "name", "label": "中文名称"},
                {"id": "code", "label": "代码"},
            ],
            "rows": [dict(item) for item in DEFAULT_DTYPE_CONFIG],
        },
        default_angle_rule_set(),
        default_sequence_rule_set(),
        default_wellno_rule_set(),
        default_xyz_rule_set(),
        default_date_rule_set(),
    ]


def empty_rule_set(rule_id, label):
    name = (label or rule_id or "规则").strip() or "规则"
    return {
        "id": rule_id,
        "label": name,
        "kind": "lookup",
        "name_header": "名称",
        "targets": _default_targets("名称"),
        "rows": [],
    }


def _normalize_targets(raw_targets, fallback):
    targets = []
    seen = set()
    for item in raw_targets or []:
        if not isinstance(item, dict):
            continue
        tid = (item.get("id") or "").strip()
        if not tid or tid in seen:
            continue
        seen.add(tid)
        targets.append({
            "id": tid,
            "label": (item.get("label") or tid).strip() or tid,
        })
    return targets or [dict(item) for item in fallback]


def normalize_rule_set(raw, fallback_id="rule"):
    src = raw if isinstance(raw, dict) else {}
    gid = (src.get("id") or fallback_id or "rule").strip() or fallback_id
    label = (src.get("label") or gid).strip() or gid
    kind = (src.get("kind") or "").strip() or "lookup"
    if gid == "angle":
        kind = "angle"
        label = label or "角度换算"
    elif gid == "sequence":
        kind = "sequence"
        label = label or "顺序号"
    elif gid == "wellno":
        kind = "wellno"
        label = label or "井编号"
    elif gid == "xyz":
        kind = "xyz"
        label = label or "坐标"
    elif gid == "date":
        kind = "date"
        label = label or "时间"

    if kind == "angle":
        try:
            places = int(src.get("decimal_places"))
        except (TypeError, ValueError):
            places = 6
        if places < 0:
            places = 0
        if places > 12:
            places = 12
        return {
            "id": gid,
            "label": label or "角度换算",
            "kind": "angle",
            "name_header": "",
            "targets": _normalize_targets(src.get("targets"), ANGLE_TARGETS),
            "decimal_places": places,
            "rows": [],
        }

    if kind == "sequence":
        try:
            start_from = int(src.get("start_from"))
        except (TypeError, ValueError):
            start_from = 1
        if start_from < 1:
            start_from = 1
        return {
            "id": gid,
            "label": label or "顺序号",
            "kind": "sequence",
            "name_header": "",
            "targets": _normalize_targets(src.get("targets"), SEQUENCE_TARGETS),
            "start_from": start_from,
            "rows": [],
        }

    if kind == "wellno":
        from .well_number import wellno_format_options
        fmt = wellno_format_options(src)
        return {
            "id": gid,
            "label": label or "井编号",
            "kind": "wellno",
            "name_header": "",
            "targets": _normalize_targets(src.get("targets"), WELLNO_TARGETS),
            "type_width": fmt["type_width"],
            "seq_width": fmt["seq_width"],
            "separator": fmt["separator"],
            "ptype_position": fmt["ptype_position"],
            "prefix": fmt["prefix"],
            "suffix": fmt["suffix"],
            "rows": [],
        }

    if kind == "xyz":
        return {
            "id": gid,
            "label": label or "坐标",
            "kind": "xyz",
            "name_header": "",
            "targets": _normalize_targets(src.get("targets"), XYZ_TARGETS),
            "rows": [],
        }

    if kind == "date":
        return {
            "id": gid,
            "label": label or "时间",
            "kind": "date",
            "name_header": "",
            "targets": _normalize_targets(src.get("targets"), DATE_TARGETS),
            "rows": [],
        }

    name_header = (src.get("name_header") or "").strip()
    if gid in ("material", "dtype"):
        name_header = "中文名称"
    elif not name_header:
        name_header = "名称"
    rows = src.get("rows")
    if rows is None:
        if isinstance(raw, list):
            rows = raw
        else:
            rows = src.get("items") or src.get("mapping") or []
    targets = _normalize_targets(src.get("targets"), _default_targets(name_header))
    if gid in ("material", "dtype"):
        for item in targets:
            if item.get("id") == "name":
                item["label"] = "中文名称"
            elif item.get("id") == "code":
                item["label"] = "代码"
    return {
        "id": gid,
        "label": label,
        "kind": "lookup",
        "name_header": name_header,
        "targets": targets,
        "rows": normalize_lookup_rows(rows),
    }


def normalize_rule_sets(raw):
    if not isinstance(raw, list) or not raw:
        return default_rule_sets()
    result = []
    seen = set()
    for idx, item in enumerate(raw):
        group = normalize_rule_set(item, fallback_id=f"rule_{idx + 1}")
        if group["id"] in seen:
            group["id"] = f"{group['id']}_{idx + 1}"
        seen.add(group["id"])
        result.append(group)
    have = {item.get("id") for item in result}
    for builtin in default_rule_sets():
        if builtin["id"] not in have:
            result.append(builtin)
    return result or default_rule_sets()


def build_rule_sets_from_legacy(material_raw, dtype_raw):
    sets = default_rule_sets()
    sets[0]["rows"] = normalize_attribute_mapping_list(
        material_raw, DEFAULT_MATERIAL_CONFIG
    )
    sets[1]["rows"] = normalize_attribute_mapping_list(
        dtype_raw, DEFAULT_DTYPE_CONFIG
    )
    return sets
