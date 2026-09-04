# -*- coding: utf-8 -*-
"""从 MDB 属性构建 QGIS 几何。"""

from qgis.core import QgsGeometry, QgsPoint, QgsPointXY

from .coord_utils import data_xy_to_map_xy


def _to_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _row_value(row, field_name):
    if not field_name or row is None:
        return None
    getter = getattr(row, "get", None)
    if getter is None:
        return None
    if isinstance(row, dict):
        if field_name in row:
            return row.get(field_name)
        upper = str(field_name).upper()
        for key, value in row.items():
            if str(key).upper() == upper:
                return value
        return None
    return getter(field_name)


def _fmt(num):
    return "%.12g" % float(num)


def _as_xyz_point(pt):
    if pt is None:
        return None
    x = pt.x()
    y = pt.y()
    z = 0.0
    if hasattr(pt, "z"):
        try:
            raw = pt.z()
            if raw == raw:
                z = float(raw)
        except (TypeError, ValueError):
            z = 0.0
    return QgsPoint(x, y, z)


def point_geometry_from_row(x_field, y_field, row, z_field=None, with_z=False, swap_xy=True):
    x = _to_float(_row_value(row, x_field))
    y = _to_float(_row_value(row, y_field))
    if x is None or y is None:
        return None
    map_x, map_y = data_xy_to_map_xy(x, y, swap=swap_xy)
    if with_z or z_field:
        z = _to_float(_row_value(row, z_field))
        if z is None:
            z = 0.0
        return QgsGeometry.fromWkt(
            "POINT Z (%s %s %s)" % (_fmt(map_x), _fmt(map_y), _fmt(z))
        )
    return QgsGeometry.fromPointXY(QgsPointXY(map_x, map_y))


def build_point_lookup(point_rows, key_field, x_field, y_field, z_field=None,
                       with_z=False, swap_xy=True):
    lookup = {}
    for row in point_rows:
        key = _row_value(row, key_field)
        if key is None:
            continue
        x = _to_float(_row_value(row, x_field))
        y = _to_float(_row_value(row, y_field))
        if x is None or y is None:
            continue
        map_x, map_y = data_xy_to_map_xy(x, y, swap=swap_xy)
        token = str(key).strip()
        if with_z or z_field:
            z = _to_float(_row_value(row, z_field))
            if z is None:
                z = 0.0
            lookup[token] = QgsPoint(map_x, map_y, z)
        else:
            lookup[token] = QgsPointXY(map_x, map_y)
    return lookup


def build_point_lookup_from_layer(layer, key_field, accept_feat=None, request=None):
    """从已加载点图层的地图几何构建起终点查找表（不再做坐标交换）。"""
    lookup = {}
    iterator = layer.getFeatures(request) if request is not None else layer.getFeatures()
    for feat in iterator:
        if accept_feat is not None and not accept_feat(feat):
            continue
        key = feat[key_field]
        if key is None:
            continue
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            continue
        pt = geom.constGet() if hasattr(geom, "constGet") else None
        if pt is not None and hasattr(pt, "x") and hasattr(pt, "y"):
            lookup[str(key).strip()] = _as_xyz_point(pt)
            continue
        pt = geom.asPoint()
        lookup[str(key).strip()] = QgsPointXY(pt.x(), pt.y())
    return lookup


def line_geometry_from_row(start_field, end_field, row, point_lookup):
    s_key = _row_value(row, start_field)
    e_key = _row_value(row, end_field)
    if s_key is None or e_key is None:
        return None
    sp = point_lookup.get(str(s_key).strip())
    ep = point_lookup.get(str(e_key).strip())
    if sp is None or ep is None:
        return None
    use_z = hasattr(sp, "z") or hasattr(ep, "z")
    if use_z:
        p1 = _as_xyz_point(sp)
        p2 = _as_xyz_point(ep)
        return QgsGeometry.fromWkt(
            "LINESTRING Z (%s %s %s, %s %s %s)" % (
                _fmt(p1.x()), _fmt(p1.y()), _fmt(p1.z()),
                _fmt(p2.x()), _fmt(p2.y()), _fmt(p2.z()),
            )
        )
    return QgsGeometry.fromPolylineXY([sp, ep])
