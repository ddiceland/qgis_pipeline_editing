# -*- coding: utf-8 -*-
"""将 QGIS 图层编辑写回 MDB。"""

from qgis.core import NULL

from .coord_utils import map_xy_to_data_xy, session_swap_xy
from .layer_session import INTERNAL_PIPE_FIELD
from .value_utils import feature_attrs_to_python
from .mdb_connector import MdbConnection, python_to_odbc
from ..access_field_types import DEFAULT_DECIMAL_PLACES, field_decimal_places, round_mdb_number
from ..mdb_decimals import apply_save_decimals, structure_field


def _insert_values(columns, attrs):
    values = {}
    for col in columns:
        val = attrs.get(col)
        if _is_null(val) and col.upper() == "ID":
            continue
        values[col] = python_to_odbc(val)
    return values


def _is_null(value):
    return value is None or value == NULL


def _attrs_equal(old, new, columns):
    for col in columns:
        ov = old.get(col)
        nv = new.get(col)
        if _is_null(ov) and _is_null(nv):
            continue
        if str(ov) != str(nv):
            return False
    return True


def _feature_attrs(feature, columns):
    return feature_attrs_to_python(feature, columns)


def _xy_digits(project_session, pipe_code, profile):
    x_digits = DEFAULT_DECIMAL_PLACES
    y_digits = DEFAULT_DECIMAL_PLACES
    structure = getattr(project_session, "mdb_structure", None) if project_session else None
    if structure and profile:
        xp = field_decimal_places(
            structure_field(structure, pipe_code, "point", getattr(profile, "x_field", None))
        )
        yp = field_decimal_places(
            structure_field(structure, pipe_code, "point", getattr(profile, "y_field", None))
        )
        if xp is not None:
            x_digits = xp
        if yp is not None:
            y_digits = yp
    return x_digits, y_digits


def _round_data_xy(map_x, map_y, swap_xy=True, x_digits=DEFAULT_DECIMAL_PLACES,
                   y_digits=DEFAULT_DECIMAL_PLACES):
    data_x, data_y = map_xy_to_data_xy(map_x, map_y, swap=swap_xy)
    return round_mdb_number(data_x, x_digits), round_mdb_number(data_y, y_digits)


def _point_xy_from_geometry(geom, swap_xy=True, x_digits=DEFAULT_DECIMAL_PLACES,
                            y_digits=DEFAULT_DECIMAL_PLACES):
    if geom is None or geom.isEmpty():
        return None, None
    pt = geom.asPoint()
    return _round_data_xy(pt.x(), pt.y(), swap_xy=swap_xy, x_digits=x_digits, y_digits=y_digits)


def _round_write_values(values, project_session, pipe_code, kind, profile):
    structure = getattr(project_session, "mdb_structure", None) if project_session else None
    return apply_save_decimals(values, structure, pipe_code, kind, profile)


def _apply_xy_to_layer(layer, xy_by_fid):
    if not xy_by_fid or layer is None or not layer.isValid():
        return
    fields = layer.fields()
    started = False
    if not layer.isEditable():
        if not layer.startEditing():
            return
        started = True
    for fid, (profile, x, y) in xy_by_fid.items():
        x_idx = fields.indexFromName(profile.x_field) if profile.x_field else -1
        y_idx = fields.indexFromName(profile.y_field) if profile.y_field else -1
        if x_idx >= 0 and x is not None:
            layer.changeAttributeValue(fid, x_idx, x)
        if y_idx >= 0 and y is not None:
            layer.changeAttributeValue(fid, y_idx, y)
    if started:
        layer.commitChanges()


def _line_endpoints_from_geometry(geom):
    if geom is None or geom.isEmpty():
        return None, None
    poly = geom.asPolyline()
    if not poly:
        return None, None
    return poly[0], poly[-1]


class LayerEditDelta:
    __slots__ = ("added_fids", "deleted_fids", "changed_fids", "geom_changed_fids", "xy_changed_fids")

    def __init__(self):
        self.added_fids = []
        self.deleted_fids = []
        self.changed_fids = set()
        self.geom_changed_fids = set()
        self.xy_changed_fids = set()


def _xy_attr_indices(layer_session):
    layer = layer_session.qgis_layer
    if layer is None:
        return set()
    fields = layer.fields()
    indices = set()
    for profile in (layer_session.profiles or {}).values():
        for name in (getattr(profile, "x_field", None), getattr(profile, "y_field", None)):
            if not name:
                continue
            idx = fields.indexFromName(name)
            if idx >= 0:
                indices.add(idx)
    return indices


def capture_layer_edit_delta(layer_session):
    """在 commit 之前读取编辑缓冲，避免保存时全表扫描。"""
    delta = LayerEditDelta()
    layer = layer_session.qgis_layer
    if layer is None or not layer.isValid() or not layer.isEditable():
        return delta
    buf = layer.editBuffer()
    if buf is None:
        return delta
    added = buf.addedFeatures() or {}
    delta.added_fids = list(added.keys())
    delta.deleted_fids = list(buf.deletedFeatureIds() or [])
    changed_attrs = buf.changedAttributeValues() or {}
    changed_geoms = buf.changedGeometries() or {}
    delta.geom_changed_fids = set(changed_geoms.keys())
    delta.changed_fids = set(changed_attrs.keys()) | set(changed_geoms.keys())
    xy_indices = _xy_attr_indices(layer_session)
    if xy_indices:
        for fid, values in changed_attrs.items():
            if any(idx in xy_indices for idx in (values or {})):
                delta.xy_changed_fids.add(fid)
    return delta


def capture_project_edit_deltas(project_session):
    deltas = {}
    if not project_session:
        return deltas
    for session in (project_session.layer_sessions or {}).values():
        deltas[session.geom_kind] = capture_layer_edit_delta(session)
    return deltas


def change_flags_from_deltas(project_session, deltas):
    point_geom_changed = set()
    line_geom_changed = set()
    point_xy_changed = set()
    if not project_session or not deltas:
        return point_geom_changed, line_geom_changed, point_xy_changed
    point_session = project_session.layer_session_by_kind("point")
    line_session = project_session.layer_session_by_kind("line")
    point_delta = deltas.get("point")
    line_delta = deltas.get("line")
    if point_session and point_delta:
        for fid in point_delta.geom_changed_fids:
            pipe = point_session.pipe_for(fid)
            if pipe:
                point_geom_changed.add(pipe)
        for fid in point_delta.xy_changed_fids:
            pipe = point_session.pipe_for(fid)
            if pipe:
                point_xy_changed.add(pipe)
    if line_session and line_delta:
        for fid in line_delta.geom_changed_fids:
            pipe = line_session.pipe_for(fid)
            if pipe:
                line_geom_changed.add(pipe)
    return point_geom_changed, line_geom_changed, point_xy_changed


def _get_feature(layer, fid):
    feat = layer.getFeature(fid)
    if feat is None or not feat.isValid():
        return None
    return feat


def save_project_session(project_session, log=None, deltas=None):
    """把已加载图层的变更写回 MDB（只处理本次编辑过的要素）。"""
    def _log(msg):
        if log:
            log(msg)

    if not project_session or not project_session.layer_sessions:
        raise RuntimeError("没有可保存的 MDB 图层")

    if deltas is None:
        deltas = capture_project_edit_deltas(project_session)

    point_sessions = [
        s for s in project_session.layer_sessions.values() if s.geom_kind == "point"
    ]
    line_sessions = [
        s for s in project_session.layer_sessions.values() if s.geom_kind == "line"
    ]
    for layer_session in point_sessions + line_sessions:
        delta = deltas.get(layer_session.geom_kind) or LayerEditDelta()
        if delta.added_fids:
            layer = layer_session.qgis_layer
            name = layer.name() if layer is not None else "MDB"
            raise RuntimeError(
                "当前不支持向已有 MDB 新增要素（%s 中有 %d 条新要素）。"
                "请删除新画的要素后再保存。"
                % (name, len(delta.added_fids))
            )

    mdb_path = project_session.mdb_path
    conn = MdbConnection(mdb_path)

    stats = {"updated": 0, "inserted": 0, "deleted": 0, "point_geom_updates": 0}

    try:
        for layer_session in point_sessions + line_sessions:
            layer = layer_session.qgis_layer
            if layer is None:
                continue
            if layer.isEditable() and not layer.commitChanges():
                raise RuntimeError(f"图层 {layer.name()} 存在无效编辑，无法保存")

        for layer_session in point_sessions:
            _save_point_layer(
                conn, layer_session, stats, _log,
                swap_xy=session_swap_xy(project_session),
                delta=deltas.get("point") or LayerEditDelta(),
                project_session=project_session,
            )

        for layer_session in line_sessions:
            _save_line_layer(
                conn, layer_session, project_session, stats, _log,
                swap_xy=session_swap_xy(project_session),
                delta=deltas.get("line") or LayerEditDelta(),
            )

        conn.commit()
        _log(
            f"保存完成：更新 {stats['updated']}，删除 {stats['deleted']}，"
            f"同步点坐标 {stats['point_geom_updates']}"
        )
        return stats
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _attr_by_name(attrs, name):
    if not name:
        return None
    if name in attrs:
        return attrs.get(name)
    upper = name.upper()
    for key, value in attrs.items():
        if str(key).upper() == upper:
            return value
    return None


def _writable_changed(orig, attrs, table_columns, skip_names):
    changed = {}
    skip = {item.upper() for item in (skip_names or set())}
    for col in table_columns:
        if col.upper() in skip:
            continue
        old = _attr_by_name(orig, col)
        new = _attr_by_name(attrs, col)
        if not _attrs_equal({col: old}, {col: new}, [col]):
            changed[col] = python_to_odbc(new)
    return changed


def _point_xy_attrs_changed(feat, layer_session, profile):
    orig = layer_session.original_attrs.get(feat.id(), {})
    if not orig:
        return False
    attrs = _feature_attrs(feat, layer_session.columns)
    for field in (profile.x_field, profile.y_field):
        if not field:
            continue
        if not _attrs_equal({field: orig.get(field)}, {field: attrs.get(field)}, [field]):
            return True
    return False


def _save_point_layer(conn, layer_session, stats, log, swap_xy=True, delta=None,
                      project_session=None):
    layer = layer_session.qgis_layer
    columns = layer_session.columns
    skip_names = layer_session.skip_write_fields()
    delta = delta or LayerEditDelta()
    xy_by_fid = {}

    for fid in delta.changed_fids:
        feat = _get_feature(layer, fid)
        if feat is None:
            continue
        pipe = layer_session.pipe_for(fid)
        profile = layer_session.profile_for(pipe)
        if profile is None or layer_session.is_new_feature(fid):
            continue
        table_columns = layer_session.table_columns_for(pipe)
        attrs = _feature_attrs(feat, columns)
        geom_changed = fid in delta.geom_changed_fids or (
            feat.geometry().asWkt() != layer_session.original_geom_wkt.get(fid)
        )
        xy_attrs_changed = fid in delta.xy_changed_fids or _point_xy_attrs_changed(
            feat, layer_session, profile
        )
        x_digits, y_digits = _xy_digits(project_session, pipe, profile)

        x, y = None, None
        if geom_changed or not xy_attrs_changed:
            x, y = _point_xy_from_geometry(
                feat.geometry(), swap_xy=swap_xy, x_digits=x_digits, y_digits=y_digits
            )
            if x is not None and profile.x_field:
                attrs[profile.x_field] = x
            if y is not None and profile.y_field:
                attrs[profile.y_field] = y
            if x is not None or y is not None:
                xy_by_fid[fid] = (profile, x, y)
        elif profile.x_field or profile.y_field:
            x = round_mdb_number(_attr_by_name(attrs, profile.x_field), x_digits)
            y = round_mdb_number(_attr_by_name(attrs, profile.y_field), y_digits)
            if profile.x_field:
                attrs[profile.x_field] = x
            if profile.y_field:
                attrs[profile.y_field] = y
            xy_by_fid[fid] = (profile, x, y)

        orig = layer_session.original_attrs.get(fid, {})
        pk_value = layer_session.feature_pk.get(fid)
        if pk_value is None:
            continue

        changed = _writable_changed(orig, attrs, table_columns, skip_names)
        if geom_changed and profile.x_field and profile.y_field:
            if profile.x_field not in changed and x is not None:
                changed[profile.x_field] = x
            if profile.y_field not in changed and y is not None:
                changed[profile.y_field] = y
        changed = _round_write_values(
            changed, project_session, pipe, "point", profile
        )

        if changed:
            conn.update_row(profile.table_name, profile.pk_field, pk_value, changed)
            stats["updated"] += 1

    for fid in delta.deleted_fids:
        pk_value = layer_session.feature_pk.get(fid)
        pipe = layer_session.pipe_for(fid)
        profile = layer_session.profile_for(pipe)
        if pk_value is None or profile is None:
            continue
        conn.delete_row(profile.table_name, profile.pk_field, pk_value)
        stats["deleted"] += 1
    _apply_xy_to_layer(layer, xy_by_fid)


def _save_line_layer(conn, layer_session, project_session, stats, log, swap_xy=True, delta=None):
    layer = layer_session.qgis_layer
    columns = layer_session.columns
    skip_names = layer_session.skip_write_fields()
    point_session = project_session.layer_session_by_kind("point")
    delta = delta or LayerEditDelta()

    for fid in delta.changed_fids:
        feat = _get_feature(layer, fid)
        if feat is None:
            continue
        pipe = layer_session.pipe_for(fid)
        profile = layer_session.profile_for(pipe)
        if profile is None or layer_session.is_new_feature(fid):
            continue
        table_columns = layer_session.table_columns_for(pipe)
        attrs = _feature_attrs(feat, columns)
        orig = layer_session.original_attrs.get(fid, {})
        pk_value = layer_session.feature_pk.get(fid)
        if pk_value is None:
            continue

        changed = _writable_changed(orig, attrs, table_columns, skip_names)
        changed = _round_write_values(
            changed, project_session, pipe, "line", profile
        )
        geom_changed = fid in delta.geom_changed_fids or (
            feat.geometry().asWkt() != layer_session.original_geom_wkt.get(fid)
        )
        if changed:
            conn.update_row(profile.table_name, profile.pk_field, pk_value, changed)
            stats["updated"] += 1
        if geom_changed:
            _sync_line_geometry_to_points(
                conn, feat, profile, point_session, pipe, stats, swap_xy=swap_xy,
                project_session=project_session,
            )

    for fid in delta.deleted_fids:
        pk_value = layer_session.feature_pk.get(fid)
        pipe = layer_session.pipe_for(fid)
        profile = layer_session.profile_for(pipe)
        if pk_value is None or profile is None:
            continue
        conn.delete_row(profile.table_name, profile.pk_field, pk_value)
        stats["deleted"] += 1


def _sync_line_geometry_to_points(conn, line_feature, line_profile, point_session, pipe_code,
                                  stats, swap_xy=True, project_session=None):
    if point_session is None:
        return
    point_profile = point_session.profile_for(pipe_code)
    if point_profile is None:
        return
    start_key = line_feature[line_profile.start_field]
    end_key = line_feature[line_profile.end_field]
    if start_key is None or end_key is None:
        return

    sp, ep = _line_endpoints_from_geometry(line_feature.geometry())
    if sp is None or ep is None:
        return

    x_digits, y_digits = _xy_digits(project_session, pipe_code, point_profile)
    data_x1, data_y1 = _round_data_xy(
        sp.x(), sp.y(), swap_xy=swap_xy, x_digits=x_digits, y_digits=y_digits
    )
    data_x2, data_y2 = _round_data_xy(
        ep.x(), ep.y(), swap_xy=swap_xy, x_digits=x_digits, y_digits=y_digits
    )
    conn.update_row(
        point_profile.table_name,
        point_profile.pk_field,
        start_key,
        {
            point_profile.x_field: data_x1,
            point_profile.y_field: data_y1,
        },
    )
    conn.update_row(
        point_profile.table_name,
        point_profile.pk_field,
        end_key,
        {
            point_profile.x_field: data_x2,
            point_profile.y_field: data_y2,
        },
    )
    stats["point_geom_updates"] += 2
