# -*- coding: utf-8 -*-
"""渲染组 id 为源，库结构 / 映射共用同一套编号。"""

from .pinyin_slug import (
    is_auto_generated_id,
    is_stable_id,
    rewrite_mapping_key,
    unique_config_id,
)


def align_render_structure_ids(render_groups, structures, mappings):
    """
    把自动编号的渲染组改成拼音/英文 id，
    再把同名库结构及映射键改成同一 id。
    正元 / 西安保持 zhengyuan、xian。
    返回是否改过。
    """
    groups = list(render_groups or [])
    structs = list(structures or [])
    maps = mappings if isinstance(mappings, dict) else {}
    id_map = {}

    occupied = set()
    for group in groups:
        gid = (group.get("id") or "").strip()
        if gid and not is_auto_generated_id(gid):
            occupied.add(gid)

    for group in groups:
        old = (group.get("id") or "").strip()
        if not old or is_stable_id(old) or not is_auto_generated_id(old):
            if old:
                occupied.add(old)
            continue
        new = unique_config_id(group.get("label") or old, occupied, fallback="group")
        occupied.add(new)
        if new != old:
            id_map[old] = new
            group["id"] = new
        else:
            occupied.add(old)

    render_by_label = {}
    for group in groups:
        label = (group.get("label") or "").strip()
        gid = (group.get("id") or "").strip()
        if label and gid and label not in render_by_label:
            render_by_label[label] = gid

    struct_occupied = {(g.get("id") or "").strip() for g in groups if (g.get("id") or "").strip()}
    for item in structs:
        oid = (item.get("id") or "").strip()
        if oid:
            struct_occupied.add(oid)

    for item in structs:
        old = (item.get("id") or "").strip()
        label = (item.get("label") or "").strip()
        new = old
        if label and label in render_by_label:
            new = render_by_label[label]
        elif is_stable_id(old):
            new = old
        elif is_auto_generated_id(old):
            others = set(struct_occupied)
            others.discard(old)
            new = unique_config_id(label or old, others, fallback="structure")
        if new and new != old:
            id_map[old] = new
            item["id"] = new
            struct_occupied.discard(old)
            struct_occupied.add(new)

    if not id_map:
        return False
    _apply_id_map_to_mappings(maps, id_map)
    return True


def _apply_id_map_to_mappings(mappings, id_map):
    if not isinstance(mappings, dict) or not id_map:
        return
    for direction in ("export", "import", "convert"):
        part = mappings.get(direction)
        if not isinstance(part, dict):
            continue
        rewritten = {}
        for key, block in part.items():
            new_key = rewrite_mapping_key(key, id_map)
            payload = dict(block) if isinstance(block, dict) else block
            if isinstance(payload, dict):
                for field in ("structure_id", "source_id", "target_id"):
                    value = payload.get(field)
                    if value:
                        mapped = id_map.get(value, value)
                        if field == "structure_id" and direction == "convert":
                            mapped = new_key
                        payload[field] = mapped
            if new_key in rewritten and _mapping_row_count(rewritten[new_key]) >= _mapping_row_count(payload):
                continue
            rewritten[new_key] = payload
        mappings[direction] = rewritten


def _mapping_row_count(block):
    if not isinstance(block, dict):
        return 0
    return len(block.get("point") or []) + len(block.get("line") or [])
