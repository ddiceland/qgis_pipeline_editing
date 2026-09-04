# -*- coding: utf-8 -*-
"""从 MDB 数据创建可编辑 QGIS 内存图层。"""

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsEditorWidgetSetup,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsProject,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QDate, QDateTime, QTime, QVariant

from .geometry_builder import (
    build_point_lookup,
    line_geometry_from_row,
    point_geometry_from_row,
)
from .layer_session import INTERNAL_PIPE_FIELD, LayerSession, MdbProjectSession
from .layer_style import apply_pipe_category_symbology
from .mdb_connector import MdbConnection, wrap_records
from ..pipe_catalog import PIPELINE_TYPES, pipeline_display_name
from ..pipe_colors import build_default_pipe_colors
from .schema_detect import (
    MdbRenderGroupNotMatchedError,
    TableProfile,
    apply_table_pattern,
    discover_pipe_layers,
    match_mdb_render_group_from_connection,
    resolve_existing_table,
)
from .value_utils import to_python_value
from .fz_filter import (
    access_type_in_clause,
    apply_fz_row_filter,
    resolve_fz_allowed,
)
from ..pipe_type_filter import FZ_PIPE_CODE

FEATURE_BATCH = 4000


def _pipe_colors(color_map=None):
    if color_map is not None:
        return color_map
    return build_default_pipe_colors(PIPELINE_TYPES)


def _access_type_to_qvariant(access_type):
    t = (access_type or "").upper()
    if t in ("INTEGER", "SMALLINT", "LONG", "COUNTER", "BYTE", "INT"):
        return QVariant.Int
    if t in ("DOUBLE", "SINGLE", "REAL", "FLOAT", "DECIMAL", "NUMERIC"):
        return QVariant.Double
    if t in ("DATETIME", "DATE"):
        return QVariant.DateTime
    return QVariant.String


def _python_to_qvariant(value, qtype):
    if value is None:
        return None
    if qtype == QVariant.DateTime:
        if hasattr(value, "hour"):
            return QDateTime(value)
        if hasattr(value, "year") and not hasattr(value, "hour"):
            return QDateTime(QDate(value.year, value.month, value.day), QTime(0, 0, 0))
    if qtype == QVariant.Double:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if qtype == QVariant.Int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return str(value)


def _row_to_attributes(columns, column_types, row):
    attrs = {}
    for col in columns:
        qtype = column_types.get(col, QVariant.String)
        attrs[col] = _python_to_qvariant(row.get(col), qtype)
    return attrs


def _build_fields(columns, column_meta):
    fields = QgsFields()
    type_map = {}
    meta_by_name = {}
    for meta in column_meta or []:
        name = meta.get("name")
        if name:
            meta_by_name[name] = meta
    for col in columns:
        meta = meta_by_name.get(col) or {"name": col, "type": "TEXT"}
        qtype = _access_type_to_qvariant(meta.get("type"))
        type_map[col] = qtype
        fields.append(QgsField(col, qtype))
    return fields, type_map


def _merge_column_metas(meta_lists):
    """各管类表字段并集：同名（忽略大小写）保留先出现的名称与类型。"""
    seen = {}
    order = []
    for metas in meta_lists or []:
        for meta in metas or []:
            name = (meta.get("name") or "").strip()
            if not name:
                continue
            key = name.upper()
            if key in seen:
                continue
            seen[key] = {
                "name": name,
                "type": meta.get("type") or "TEXT",
            }
            order.append(key)
    return [seen[key] for key in order]


def _configured_type_field(render_group, kind):
    cfg = (render_group or {}).get("point" if kind == "point" else "line") or {}
    return (cfg.get("type_field") or "").strip()


def _resolve_display_type_field(configured, union_columns):
    if not configured:
        return ""
    upper = configured.upper()
    for name in union_columns:
        if name.upper() == upper:
            return name
    return configured


def _lock_routing_fields(layer, display_type_field):
    form = layer.editFormConfig()
    names = [INTERNAL_PIPE_FIELD]
    if display_type_field:
        names.append(display_type_field)
    for name in names:
        idx = layer.fields().indexFromName(name)
        if idx < 0:
            continue
        if name == INTERNAL_PIPE_FIELD:
            layer.setEditorWidgetSetup(idx, QgsEditorWidgetSetup("Hidden", {}))
        form.setReadOnly(idx, True)
    layer.setEditFormConfig(form)


def _load_pipe_rows(conn, table_name, pipe_code, type_field, fz_allowed, kind_label, log):
    """读取点/线表。FZ 非全选时在 Access 里按管线类型过滤。"""
    where = None
    if pipe_code == FZ_PIPE_CODE and fz_allowed is not None:
        if not type_field:
            if log:
                log(
                    "[%s] 未配置管线类型字段，无法按勾选管类筛选辅助%s，已跳过"
                    % (FZ_PIPE_CODE, kind_label)
                )
            return [], False
        where = access_type_in_clause(type_field, fz_allowed)
    try:
        columns, records = conn.read_records(table_name, where=where)
    except Exception:
        if where is None:
            raise
        columns, records = conn.read_records(table_name)
        rows = wrap_records(columns, records)
        filtered = apply_fz_row_filter(
            pipe_code, rows, type_field, fz_allowed, kind_label, log
        )
        return filtered, not rows
    rows = wrap_records(columns, records)
    if where is not None and not rows:
        if log:
            log(
                "[%s] 没有与已勾选管类相关的辅助%s，已跳过"
                % (FZ_PIPE_CODE, kind_label)
            )
        return [], False
    return rows, not rows


def _flush_feature_batch(provider, batch, identity_queue):
    """写入内存图层，并按写入顺序记下 Access 主键，供稍后对齐 fid。"""
    if not batch:
        return
    feats = [item[0] for item in batch]
    result = provider.addFeatures(feats)
    ok = result[0] if isinstance(result, (tuple, list)) else result
    if not ok:
        raise RuntimeError("写入内存图层失败")
    for _src, pk, pipe_code in batch:
        identity_queue.append((pk, pipe_code))
    del batch[:]


def _bind_identities(layer_session, layer, identity_queue):
    """把写入顺序上的 Access 主键绑到图层真实 fid。"""
    provider = layer.dataProvider()
    iterator = provider.getFeatures() if provider is not None else layer.getFeatures()
    feats = [feat for feat in iterator if feat is not None and feat.isValid()]
    if identity_queue and len(feats) == len(identity_queue):
        for feat, (pk, pipe_code) in zip(feats, identity_queue):
            fid = feat.id()
            if fid is None or fid <= 0 or pk is None:
                continue
            layer_session.register_identity(fid, pk, pipe_code, feat)
        if layer_session.feature_pk:
            return
    columns = layer_session.columns
    for feat in feats:
        fid = feat.id()
        if fid is None or fid <= 0:
            continue
        if layer_session.feature_pk.get(fid) is not None:
            continue
        pipe_code = ""
        if INTERNAL_PIPE_FIELD in columns:
            try:
                pipe_code = (feat[INTERNAL_PIPE_FIELD] or "").strip().upper()
            except Exception:
                pipe_code = ""
        profile = layer_session.profile_for(pipe_code)
        pk = row_pk_value(feat, profile, columns) if profile else None
        if pk is None:
            continue
        layer_session.register_identity(fid, pk, pipe_code, feat)


MDB_LAYER_GROUP_NAME = "MDB库"


def _layer_group_name():
    return MDB_LAYER_GROUP_NAME


def load_mdb_layers(mdb_path, pipe_codes, color_map=None, render_groups=None,
                    mdb_structures=None, log=None, swap_xy=True, load_all_fz=False):
    """
    打开 MDB，加载指定管类的点/线图层到 QGIS。
    render_groups：配置管理「MDB库渲染」结构组列表；必须能匹配到一组，否则抛错。
    mdb_structures：MDB库结构，用于按配置表名（JSPOINT / JS_POINT）解析实际表。
    load_all_fz：全选可用管类时为 True，FZ 辅助数据全部加载；否则只加载与已勾选基础管类相关的 FZ。
    返回 MdbProjectSession。
    """
    def _log(msg):
        if log:
            log(msg)

    fz_allowed, base_types, include_fz = resolve_fz_allowed(
        pipe_codes, load_all_fz=load_all_fz, action="加载"
    )

    if not render_groups:
        raise MdbRenderGroupNotMatchedError(
            "未配置任何「MDB库渲染」结构组。\n"
            "请先在「配置管理 → MDB库渲染」中新增并保存。"
        )

    conn = MdbConnection(mdb_path)
    try:
        tables = conn.list_user_tables()
        discovered = discover_pipe_layers(tables, render_groups=render_groups)
        if not discovered:
            raise RuntimeError("MDB 中未识别到管线点/线表（命名如 JSPOINT/JSLINE 或 JS_POINT/JS_LINE）")

        render_group = match_mdb_render_group_from_connection(
            conn, discovered, render_groups, table_names=tables
        )
        if render_group is None:
            labels = "、".join(
                (g.get("label") or g.get("id") or "") for g in render_groups
            )
            raise MdbRenderGroupNotMatchedError(
                "未能根据当前 MDB 的点/线表字段匹配到「MDB库渲染」中的结构组，已取消加载。\n\n"
                f"已配置的渲染结构组：{labels or '（无）'}\n\n"
                "请到「配置管理 → MDB库渲染」中完善渲染用字段后再加载。"
            )
        _log(
            f"MDB 渲染结构组：{render_group.get('label') or render_group.get('id')}"
        )

        structure = None
        for item in mdb_structures or []:
            if item.get("id") == render_group.get("id"):
                structure = item
                break
        structure_pipes = (structure or {}).get("pipes") or {}

        session = MdbProjectSession(mdb_path, swap_xy=swap_xy)
        session.mdb_structure = structure
        _log("坐标约定：%s" % ("交换 X/Y" if swap_xy else "不交换 X/Y"))
        if structure:
            _log("MDB 库结构：%s" % (structure.get("label") or structure.get("id") or ""))
        else:
            _log("未匹配到 MDB 库结构，保存时仅 X/Y 保留 3 位小数")
        colors = _pipe_colors(color_map)
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        group = root.findGroup(_layer_group_name())
        if group is None:
            group = root.insertGroup(0, _layer_group_name())

        point_bundles = []
        line_bundles = []
        loaded_codes = []
        if include_fz:
            if load_all_fz:
                _log("[%s] 已全选可用管类，辅助数据全部加载" % FZ_PIPE_CODE)
            else:
                _log(
                    "[%s] 辅助数据按勾选管类筛选：%s"
                    % (FZ_PIPE_CODE, "、".join(pipeline_display_name(c) for c in base_types))
                )

        for pipe_code in pipe_codes:
            info = discovered.get(pipe_code) or {}
            pipe_cfg = structure_pipes.get(pipe_code) or {}
            point_pat = (render_group.get("point") or {}).get("table_pattern")
            line_pat = (render_group.get("line") or {}).get("table_pattern")
            point_table = resolve_existing_table(tables, [
                apply_table_pattern(point_pat, pipe_code),
                info.get("point"),
                f"{pipe_code}POINT",
                pipe_cfg.get("point_table"),
                f"{pipe_code}_POINT",
            ])
            line_table = resolve_existing_table(tables, [
                apply_table_pattern(line_pat, pipe_code),
                info.get("line"),
                f"{pipe_code}LINE",
                pipe_cfg.get("line_table"),
                f"{pipe_code}_LINE",
            ])
            if not point_table and not line_table:
                _log(f"[{pipe_code}] MDB 中无对应点/线表，已跳过")
                continue

            point_lookup = {}
            point_rows = []
            if point_table:
                col_meta = conn.get_columns(point_table)
                columns = [c["name"] for c in col_meta]
                point_profile = TableProfile(
                    point_table, "point", columns, render_group=render_group
                )
                point_profile.validate()
                session.point_profiles[pipe_code] = point_profile
                point_rows, point_empty = _load_pipe_rows(
                    conn, point_table, pipe_code, point_profile.type_field,
                    fz_allowed, "点", _log,
                )
                if point_rows:
                    point_lookup = build_point_lookup(
                        point_rows,
                        point_profile.pk_field,
                        point_profile.x_field,
                        point_profile.y_field,
                        swap_xy=swap_xy,
                    )
                    point_bundles.append({
                        "pipe_code": pipe_code,
                        "profile": point_profile,
                        "col_meta": col_meta,
                        "rows": point_rows,
                    })
                elif point_empty:
                    _log("[%s] 点表无数据，未加入点图层" % pipe_code)

            if line_table:
                if not point_lookup and point_rows:
                    pp = session.point_profiles.get(pipe_code)
                    if pp:
                        point_lookup = build_point_lookup(
                            point_rows,
                            pp.pk_field,
                            pp.x_field,
                            pp.y_field,
                            swap_xy=swap_xy,
                        )
                if not point_lookup:
                    _log("[%s] 点表无数据，无法构建线几何，未加入线图层" % pipe_code)
                else:
                    col_meta = conn.get_columns(line_table)
                    columns = [c["name"] for c in col_meta]
                    line_profile = TableProfile(
                        line_table, "line", columns, render_group=render_group
                    )
                    line_profile.validate()
                    line_rows, line_empty = _load_pipe_rows(
                        conn, line_table, pipe_code, line_profile.type_field,
                        fz_allowed, "线", _log,
                    )
                    if not line_rows:
                        if line_empty:
                            _log("[%s] 线表无数据，未加入线图层" % pipe_code)
                    else:
                        line_bundles.append({
                            "pipe_code": pipe_code,
                            "profile": line_profile,
                            "col_meta": col_meta,
                            "rows": line_rows,
                            "point_lookup": point_lookup,
                        })

            if point_rows or (line_table and point_lookup):
                loaded_codes.append(pipe_code)

        session.loaded_pipe_codes = list(loaded_codes)

        if point_bundles:
            layer = _create_merged_point_layer(
                session, mdb_path, point_bundles, render_group, colors, swap_xy=swap_xy,
            )
            project.addMapLayer(layer, False)
            node = group.addLayer(layer)
            if node is not None:
                node.setItemVisibilityChecked(False)

        if line_bundles:
            layer = _create_merged_line_layer(
                session, mdb_path, line_bundles, render_group, colors,
            )
            project.addMapLayer(layer, False)
            group.addLayer(layer)

        if not session.layer_sessions:
            raise RuntimeError("没有成功加载任何图层")

        session.render_group_id = render_group.get("id")
        session.render_group_label = render_group.get("label")
        names = []
        if session.layer_session_by_kind("point"):
            names.append("MDB管点")
        if session.layer_session_by_kind("line"):
            names.append("MDB管线")
        _log(
            "已从 MDB 加载 %s（管类：%s）"
            % (" / ".join(names), "、".join(pipeline_display_name(c) for c in loaded_codes))
        )
        return session
    finally:
        conn.close()


def _memory_layer_no_crs(kind, name):
    uri = "Point" if kind == "point" else "LineString"
    layer = QgsVectorLayer(uri, name, "memory")
    if layer.isValid():
        layer.setCrs(QgsCoordinateReferenceSystem(), False)
    return layer


def _union_layer_columns(bundles, render_group, kind):
    union_meta = _merge_column_metas([item.get("col_meta") for item in bundles])
    columns = [item["name"] for item in union_meta]
    configured = _configured_type_field(render_group, kind)
    display_field = _resolve_display_type_field(configured, columns)
    if display_field and display_field not in columns:
        union_meta.append({"name": display_field, "type": "TEXT"})
        columns.append(display_field)
    if INTERNAL_PIPE_FIELD not in columns:
        union_meta.append({"name": INTERNAL_PIPE_FIELD, "type": "TEXT"})
        columns.append(INTERNAL_PIPE_FIELD)
    return columns, union_meta, display_field


def _source_has_field(source_columns, field_name):
    if not field_name:
        return False
    upper = str(field_name).upper()
    for name in source_columns or []:
        if str(name).upper() == upper:
            return True
    return False


def _stamp_pipe_attrs(attrs, columns, type_map, pipe_code, display_field,
                      source_columns=None):
    """_mdb_pipe 始终为表名管类；显示用管类列仅在源表无此字段时用表名补值。"""
    has_real_type = _source_has_field(source_columns, display_field)
    values = []
    for col in columns:
        if col == INTERNAL_PIPE_FIELD:
            values.append(pipe_code)
        elif display_field and col == display_field and not has_real_type:
            values.append(pipe_code)
        else:
            values.append(to_python_value(attrs.get(col)))
    return values


def _finish_merged_layer(project_session, layer, layer_session, mdb_path, geom_kind,
                         display_field, codes, colors):
    apply_pipe_category_symbology(layer, geom_kind, INTERNAL_PIPE_FIELD, codes, colors)
    _lock_routing_fields(layer, display_field)
    layer.setReadOnly(False)
    layer.startEditing()
    layer_session.qgis_layer = layer
    layer.setCustomProperty("mdb_editor/mdb_path", mdb_path)
    layer.setCustomProperty("mdb_editor/geom_kind", geom_kind)
    layer.setCustomProperty("mdb_editor/merged", "1")
    project_session.add_layer_session(layer.id(), layer_session)
    return layer


def _create_merged_point_layer(project_session, mdb_path, bundles, render_group, colors,
                               swap_xy=True):
    columns, union_meta, display_field = _union_layer_columns(bundles, render_group, "point")
    fields, type_map = _build_fields(columns, union_meta)
    layer = _memory_layer_no_crs("point", "MDB管点")
    if not layer.isValid():
        raise RuntimeError("创建 MDB管点 图层失败")

    provider = layer.dataProvider()
    provider.addAttributes(fields)
    layer.updateFields()

    layer_session = LayerSession(mdb_path, "point", columns, display_field)
    pending = []
    identity_queue = []
    codes = []
    for item in bundles:
        pipe_code = item["pipe_code"]
        profile = item["profile"]
        codes.append(pipe_code)
        layer_session.profiles[pipe_code] = profile
        layer_session.table_columns[pipe_code] = [c["name"] for c in item["col_meta"]]
        pk_field = profile.pk_field
        for row in item["rows"]:
            geom = point_geometry_from_row(
                profile.x_field, profile.y_field, row, swap_xy=swap_xy
            )
            if geom is None or geom.isEmpty():
                continue
            feat = QgsFeature(fields)
            feat.setAttributes(
                _stamp_pipe_attrs(
                    _row_to_attributes(columns, type_map, row),
                    columns, type_map, pipe_code, display_field,
                    source_columns=[c["name"] for c in item["col_meta"]],
                )
            )
            feat.setGeometry(geom)
            pk = to_python_value(row.get(pk_field)) if pk_field else None
            pending.append((feat, pk, pipe_code))
            if len(pending) >= FEATURE_BATCH:
                _flush_feature_batch(provider, pending, identity_queue)
    _flush_feature_batch(provider, pending, identity_queue)
    layer.updateExtents()
    _bind_identities(layer_session, layer, identity_queue)
    return _finish_merged_layer(
        project_session, layer, layer_session, mdb_path, "point",
        display_field, codes, colors,
    )


def _create_merged_line_layer(project_session, mdb_path, bundles, render_group, colors):
    columns, union_meta, display_field = _union_layer_columns(bundles, render_group, "line")
    fields, type_map = _build_fields(columns, union_meta)
    layer = _memory_layer_no_crs("line", "MDB管线")
    if not layer.isValid():
        raise RuntimeError("创建 MDB管线 图层失败")

    provider = layer.dataProvider()
    provider.addAttributes(fields)
    layer.updateFields()

    layer_session = LayerSession(mdb_path, "line", columns, display_field)
    pending = []
    identity_queue = []
    codes = []
    for item in bundles:
        pipe_code = item["pipe_code"]
        profile = item["profile"]
        codes.append(pipe_code)
        layer_session.profiles[pipe_code] = profile
        layer_session.table_columns[pipe_code] = [c["name"] for c in item["col_meta"]]
        lookup = item.get("point_lookup") or {}
        pk_field = profile.pk_field
        for row in item["rows"]:
            geom = line_geometry_from_row(
                profile.start_field, profile.end_field, row, lookup
            )
            if geom is None or geom.isEmpty():
                continue
            feat = QgsFeature(fields)
            feat.setAttributes(
                _stamp_pipe_attrs(
                    _row_to_attributes(columns, type_map, row),
                    columns, type_map, pipe_code, display_field,
                    source_columns=[c["name"] for c in item["col_meta"]],
                )
            )
            feat.setGeometry(geom)
            pk = to_python_value(row.get(pk_field)) if pk_field else None
            pending.append((feat, pk, pipe_code))
            if len(pending) >= FEATURE_BATCH:
                _flush_feature_batch(provider, pending, identity_queue)
    _flush_feature_batch(provider, pending, identity_queue)
    layer.updateExtents()
    _bind_identities(layer_session, layer, identity_queue)
    return _finish_merged_layer(
        project_session, layer, layer_session, mdb_path, "line",
        display_field, codes, colors,
    )


def row_pk_value(feature, profile, columns):
    from .value_utils import to_python_value
    if profile is None:
        return None
    pk_field = profile.pk_field
    if not pk_field:
        return None
    if pk_field in columns:
        idx = columns.index(pk_field)
        return to_python_value(feature[idx])
    try:
        return to_python_value(feature[pk_field])
    except Exception:
        return None


def list_mdb_pipe_types(mdb_path, render_groups=None):
    """
    列出当前 MDB 中实际有表的管类及是否为空。
    空：点、线都无记录，或线有记录但点表无记录（无法构建线）。
    """
    conn = MdbConnection(mdb_path)
    try:
        tables = conn.list_user_tables()
        discovered = discover_pipe_layers(tables, render_groups=render_groups)
        items = []
        ordered = [code for code in PIPELINE_TYPES if code in discovered]
        extra = sorted(code for code in discovered if code not in PIPELINE_TYPES)
        for code in ordered + extra:
            info = discovered.get(code) or {}
            point_table = info.get("point")
            line_table = info.get("line")
            has_point = conn.has_rows(point_table) if point_table else False
            has_line = conn.has_rows(line_table) if line_table else False
            empty = not has_point
            if empty:
                if has_line:
                    reason = "线表有记录但点表无数据"
                else:
                    reason = "点、线表均无数据"
            else:
                reason = ""
            items.append({
                "code": code,
                "empty": empty,
                "has_point": has_point,
                "has_line": has_line,
                "reason": reason,
            })
        return items
    finally:
        conn.close()
