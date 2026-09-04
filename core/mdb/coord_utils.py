# -*- coding: utf-8 -*-
"""
数据坐标与 QGIS 地图坐标互转。

测绘坐标（默认）：MDB 中 X 北、Y 东，与地图东向/北向相反，读写时交换 X、Y。
数学坐标：MDB 中 X 东、Y 北，与地图一致，不交换。
"""


def data_xy_to_map_xy(data_x, data_y, swap=True):
    """数据文件 X/Y -> QGIS 地图 (x, y)。"""
    if swap:
        return data_y, data_x
    return data_x, data_y


def map_xy_to_data_xy(map_x, map_y, swap=True):
    """QGIS 地图 (x, y) -> 数据文件 X/Y。"""
    if swap:
        return map_y, map_x
    return map_x, map_y


XY_WRITE_DECIMALS = 3


def round_xy(x, y, digits=XY_WRITE_DECIMALS):
    """写回 MDB 的 X/Y 默认保留 3 位小数。"""
    def _one(value):
        if value is None:
            return None
        try:
            return round(float(value), digits)
        except (TypeError, ValueError):
            return value
    return _one(x), _one(y)


def session_swap_xy(project_session, default=True):
    if project_session is None:
        return default
    return bool(getattr(project_session, "swap_xy", default))
