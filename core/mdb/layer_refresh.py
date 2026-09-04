# -*- coding: utf-8 -*-
"""MDB 图层保存后的几何同步与快照更新。"""

from qgis.core import QgsFeatureRequest, QgsGeometry
from qgis.PyQt.QtWidgets import QApplication

from .geometry_builder import (
    build_point_lookup_from_layer,
    line_geometry_from_row,
    point_geometry_from_row,
)
from .layer_builder import row_pk_value
from .coord_utils import session_swap_xy
from .layer_session import INTERNAL_PIPE_FIELD
from .value_utils import feature_attrs_to_python


def update_project_session_snapshots(project_session, log=None, deltas=None):
    """保存后更新内存图层的变更基准快照，不从 MDB 重新读取。"""
    if not project_session or not project_session.layer_sessions:
        return

    for layer_session in project_session.layer_sessions.values():
        layer = layer_session.qgis_layer
        if layer is None or not layer.isValid():
            raise RuntimeError(
                "图层 %s 已失效，请重新加载后再保存" % (layer.name() if layer else "MDB")
            )
        delta = (deltas or {}).get(layer_session.geom_kind) if deltas else None
        if delta is not None:
            _patch_layer_session_registry(layer_session, layer, delta)
        else:
            _reset_layer_session_registry(layer_session, layer)
        if not layer.isEditable():
            layer.startEditing()

    if log:
        log("已更新编辑快照（未从 MDB 重读）")


def _patch_layer_session_registry(layer_session, layer, delta):
    columns = layer_session.columns
    for fid in delta.deleted_fids or []:
        layer_session.feature_pk.pop(fid, None)
        layer_session.feature_pipe.pop(fid, None)
        layer_session.original_attrs.pop(fid, None)
        layer_session.original_geom_wkt.pop(fid, None)
    for fid in delta.changed_fids or []:
        feat = layer.getFeature(fid)
        if feat is None or not feat.isValid():
            continue
        pipe = layer_session.pipe_for(fid)
        if not pipe and INTERNAL_PIPE_FIELD in columns:
            pipe = (feat[INTERNAL_PIPE_FIELD] or "").strip().upper()
        profile = layer_session.profile_for(pipe)
        pk = row_pk_value(feat, profile, columns) if profile else feat.id()
        attrs = feature_attrs_to_python(feat, columns)
        layer_session.register_feature(
            fid, pk, attrs, feat.geometry().asWkt(), pipe
        )


def _feature_geom_changed(layer_session, feat):
    orig = layer_session.original_geom_wkt.get(feat.id())
    if orig is None:
        return layer_session.is_new_feature(feat.id())
    geom = feat.geometry()
    if geom is None or geom.isEmpty():
        return False
    return geom.asWkt() != orig


def _layer_has_geom_changes(layer_session):
    layer = layer_session.qgis_layer
    if layer is None or not layer.isValid():
        return False
    return any(_feature_geom_changed(layer_session, f) for f in layer.getFeatures())


def _pipe_feature_request(pipe_code):
    expr = '"%s" = \'%s\'' % (
        INTERNAL_PIPE_FIELD.replace('"', '""'),
        str(pipe_code or "").replace("'", "''"),
    )
    return QgsFeatureRequest().setFilterExpression(expr)


def _sync_lines_from_points(point_session, line_session, pipe_code, moved_pks=None):
    """根据同管类点位置更新线几何。"""
    point_layer = point_session.qgis_layer
    line_layer = line_session.qgis_layer
    if (
        point_layer is None or not point_layer.isValid()
        or line_layer is None or not line_layer.isValid()
    ):
        return 0

    point_profile = point_session.profile_for(pipe_code)
    line_profile = line_session.profile_for(pipe_code)
    if point_profile is None or line_profile is None:
        return 0
    key_field = point_profile.pk_field
    req = _pipe_feature_request(pipe_code)
    point_lookup = build_point_lookup_from_layer(
        point_layer, key_field, request=req,
    )
    if not point_lookup:
        return 0

    moved = None
    if moved_pks:
        moved = {str(item).strip() for item in moved_pks if item is not None}

    columns = line_session.columns
    updated = 0
    was_editing = line_layer.isEditable()
    if not was_editing:
        line_layer.startEditing()

    for feat in line_layer.getFeatures(req):
        if moved:
            start_key = feat[line_profile.start_field]
            end_key = feat[line_profile.end_field]
            start_ok = start_key is not None and str(start_key).strip() in moved
            end_ok = end_key is not None and str(end_key).strip() in moved
            if not start_ok and not end_ok:
                continue
        row = {col: feat[col] for col in columns}
        new_geom = line_geometry_from_row(
            line_profile.start_field, line_profile.end_field, row, point_lookup
        )
        if new_geom is None or new_geom.isEmpty():
            continue
        if feat.geometry().asWkt() != new_geom.asWkt():
            line_layer.changeGeometry(feat.id(), new_geom)
            updated += 1

    if not was_editing:
        line_layer.commitChanges()
        line_layer.startEditing()
    line_layer.updateExtents()
    line_layer.triggerRepaint()
    return updated


def _sync_points_from_lines(point_session, line_session, pipe_code):
    """根据同管类线端点更新点几何。"""
    point_layer = point_session.qgis_layer
    line_layer = line_session.qgis_layer
    if (
        point_layer is None or not point_layer.isValid()
        or line_layer is None or not line_layer.isValid()
    ):
        return 0

    point_profile = point_session.profile_for(pipe_code)
    line_profile = line_session.profile_for(pipe_code)
    if point_profile is None or line_profile is None:
        return 0
    pk_field = point_profile.pk_field

    endpoint_map = {}
    for feat in line_layer.getFeatures():
        if line_session.pipe_for(feat.id()) != pipe_code:
            continue
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            continue
        poly = geom.asPolyline()
        if len(poly) < 2:
            continue
        s_key = feat[line_profile.start_field]
        e_key = feat[line_profile.end_field]
        if s_key is not None:
            endpoint_map[str(s_key).strip()] = poly[0]
        if e_key is not None:
            endpoint_map[str(e_key).strip()] = poly[-1]

    if not endpoint_map:
        return 0

    updated = 0
    was_editing = point_layer.isEditable()
    if not was_editing:
        point_layer.startEditing()

    for feat in point_layer.getFeatures():
        if point_session.pipe_for(feat.id()) != pipe_code:
            continue
        key = feat[pk_field]
        if key is None:
            continue
        new_pt = endpoint_map.get(str(key).strip())
        if new_pt is None:
            continue
        new_geom = QgsGeometry.fromPointXY(new_pt)
        if feat.geometry().asWkt() != new_geom.asWkt():
            point_layer.changeGeometry(feat.id(), new_geom)
            updated += 1

    if not was_editing:
        point_layer.commitChanges()
        point_layer.startEditing()
    point_layer.updateExtents()
    point_layer.triggerRepaint()
    return updated


def _layer_has_xy_attr_changes(layer_session, pipe_code=None):
    """点图层 X/Y 属性相对快照是否有变化。"""
    layer = layer_session.qgis_layer
    if layer is None or not layer.isValid():
        return False
    for feat in layer.getFeatures():
        pipe = layer_session.pipe_for(feat.id())
        if pipe_code and pipe != pipe_code:
            continue
        profile = layer_session.profile_for(pipe)
        if profile is None or not profile.x_field or not profile.y_field:
            continue
        orig = layer_session.original_attrs.get(feat.id())
        if orig is None:
            continue
        attrs = feature_attrs_to_python(feat, layer_session.columns)
        for field in (profile.x_field, profile.y_field):
            ov = orig.get(field)
            nv = attrs.get(field)
            if ov is None and nv is None:
                continue
            if str(ov) != str(nv):
                return True
    return False


def _changed_pipes_for_geom(layer_session):
    pipes = set()
    layer = layer_session.qgis_layer
    if layer is None or not layer.isValid():
        return pipes
    for feat in layer.getFeatures():
        if _feature_geom_changed(layer_session, feat):
            pipe = layer_session.pipe_for(feat.id())
            if pipe:
                pipes.add(pipe)
    return pipes


def _changed_pipes_for_xy(layer_session):
    pipes = set()
    layer = layer_session.qgis_layer
    if layer is None or not layer.isValid():
        return pipes
    for feat in layer.getFeatures():
        pipe = layer_session.pipe_for(feat.id())
        if not pipe or pipe in pipes:
            continue
        profile = layer_session.profile_for(pipe)
        if profile is None or not profile.x_field or not profile.y_field:
            continue
        orig = layer_session.original_attrs.get(feat.id())
        if orig is None:
            continue
        attrs = feature_attrs_to_python(feat, layer_session.columns)
        for field in (profile.x_field, profile.y_field):
            ov = orig.get(field)
            nv = attrs.get(field)
            if ov is None and nv is None:
                continue
            if str(ov) != str(nv):
                pipes.add(pipe)
                break
    return pipes


def collect_layer_change_flags(project_session):
    """保存前采集各管类点/线的几何或坐标属性变更。"""
    point_geom_changed = set()
    line_geom_changed = set()
    point_xy_changed = set()
    if not project_session:
        return point_geom_changed, line_geom_changed, point_xy_changed

    for layer_session in project_session.layer_sessions.values():
        if layer_session.geom_kind == "point":
            point_geom_changed.update(_changed_pipes_for_geom(layer_session))
            point_xy_changed.update(_changed_pipes_for_xy(layer_session))
        elif layer_session.geom_kind == "line":
            line_geom_changed.update(_changed_pipes_for_geom(layer_session))
    return point_geom_changed, line_geom_changed, point_xy_changed


def _apply_point_geometry_from_xy_attrs(point_session, pipe_code, swap_xy=True, fids=None):
    """根据 X/Y 属性字段重建指定管类的点几何。"""
    profile = point_session.profile_for(pipe_code)
    layer = point_session.qgis_layer
    if profile is None or layer is None or not layer.isValid():
        return 0

    columns = point_session.columns
    x_field = profile.x_field
    y_field = profile.y_field
    if not x_field or not y_field:
        return 0

    updated = 0
    was_editing = layer.isEditable()
    if not was_editing:
        layer.startEditing()

    if fids:
        iterator = []
        for fid in fids:
            feat = layer.getFeature(fid)
            if feat is not None and feat.isValid():
                iterator.append(feat)
    else:
        iterator = layer.getFeatures(_pipe_feature_request(pipe_code))

    for feat in iterator:
        if point_session.pipe_for(feat.id()) != pipe_code:
            continue
        row = {col: feat[col] for col in columns}
        new_geom = point_geometry_from_row(x_field, y_field, row, swap_xy=swap_xy)
        if new_geom is None or new_geom.isEmpty():
            continue
        if feat.geometry().asWkt() != new_geom.asWkt():
            layer.changeGeometry(feat.id(), new_geom)
            updated += 1

    if not was_editing:
        layer.commitChanges()
        layer.startEditing()
    layer.updateExtents()
    layer.triggerRepaint()
    return updated


def sync_layers_after_save(project_session, log=None, change_flags=None, deltas=None):
    """保存后按变更方向同步点线几何，避免用旧线端点覆盖已移动的点。"""
    if not project_session:
        return

    if change_flags is None:
        change_flags = collect_layer_change_flags(project_session)
    point_geom_changed, line_geom_changed, point_xy_changed = change_flags

    point_session = project_session.layer_session_by_kind("point")
    line_session = project_session.layer_session_by_kind("line")
    if point_session and (not point_session.qgis_layer or not point_session.qgis_layer.isValid()):
        point_session = None
    if line_session and (not line_session.qgis_layer or not line_session.qgis_layer.isValid()):
        line_session = None

    pipes = set(point_geom_changed) | set(line_geom_changed) | set(point_xy_changed)
    point_delta = (deltas or {}).get("point") if deltas else None

    lines_updated = 0
    points_updated = 0
    for pipe_code in pipes:
        has_point = point_session is not None and pipe_code in point_session.profiles
        has_line = line_session is not None and pipe_code in line_session.profiles
        if not has_point or not has_line:
            continue
        points_moved = pipe_code in point_geom_changed
        points_xy_edited = pipe_code in point_xy_changed
        lines_moved = pipe_code in line_geom_changed

        moved_pks = None
        xy_fids = None
        if point_delta is not None and point_session is not None:
            moved_fids = set()
            if points_moved:
                moved_fids.update(
                    fid for fid in point_delta.geom_changed_fids
                    if point_session.pipe_for(fid) == pipe_code
                )
            if points_xy_edited:
                xy_fids = {
                    fid for fid in point_delta.xy_changed_fids
                    if point_session.pipe_for(fid) == pipe_code
                }
                moved_fids.update(xy_fids)
            if moved_fids:
                profile = point_session.profile_for(pipe_code)
                moved_pks = set()
                if profile and profile.pk_field:
                    for fid in moved_fids:
                        feat = point_session.qgis_layer.getFeature(fid)
                        if feat is None or not feat.isValid():
                            continue
                        key = feat[profile.pk_field]
                        if key is not None:
                            moved_pks.add(str(key).strip())

        if points_moved or points_xy_edited:
            if points_xy_edited:
                points_updated += _apply_point_geometry_from_xy_attrs(
                    point_session, pipe_code,
                    swap_xy=session_swap_xy(project_session),
                    fids=xy_fids,
                )
            lines_updated += _sync_lines_from_points(
                point_session, line_session, pipe_code, moved_pks=moved_pks
            )
        elif lines_moved:
            points_updated += _sync_points_from_lines(point_session, line_session, pipe_code)

    if log:
        if lines_updated:
            log(f"已同步 {lines_updated} 条线图层几何")
        if points_updated:
            log(f"已同步 {points_updated} 个点图层几何")


def redraw_project_layers(project_session, iface=None, log=None):
    """触发所有已加载图层的重绘。"""
    if project_session:
        for layer_session in project_session.layer_sessions.values():
            layer = layer_session.qgis_layer
            if layer is None or not layer.isValid():
                continue
            layer.updateExtents()
            layer.triggerRepaint()

    if iface is not None:
        canvas = iface.mapCanvas()
        if canvas.isFrozen():
            canvas.freeze(False)
        extent = canvas.extent()
        canvas.refreshAllLayers()
        canvas.setExtent(extent)
        canvas.refresh()

    QApplication.processEvents()
    if log:
        log("已重绘地图")


def _reset_layer_session_registry(layer_session, layer):
    columns = layer_session.columns
    old_pipe = dict(layer_session.feature_pipe)
    layer_session.feature_pk.clear()
    layer_session.feature_pipe.clear()
    layer_session.original_attrs.clear()
    layer_session.original_geom_wkt.clear()
    for feat in layer.getFeatures():
        pipe = old_pipe.get(feat.id()) or ""
        if not pipe and INTERNAL_PIPE_FIELD in columns:
            pipe = (feat[INTERNAL_PIPE_FIELD] or "").strip().upper()
        profile = layer_session.profile_for(pipe)
        pk = row_pk_value(feat, profile, columns) if profile else feat.id()
        attrs = feature_attrs_to_python(feat, columns)
        layer_session.register_feature(
            feat.id(), pk, attrs, feat.geometry().asWkt(), pipe
        )

