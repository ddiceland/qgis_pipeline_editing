# -*- coding: utf-8 -*-
"""按管类为 PostgreSQL 总管点/总管线图层设置符号颜色。"""
from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsRendererCategory,
    QgsRuleBasedRenderer,
    QgsSingleSymbolRenderer,
)

from .pipe_type_filter import FZ_PIPE_CODE

LINE_WIDTH = "0.3"
POINT_SIZE = "1.8"


def _normalize_hex(color):
    if not color:
        return "#808080"
    c = str(color).strip()
    if not c.startswith("#"):
        c = "#" + c
    return c


def _line_symbol(color_hex):
    return QgsLineSymbol.createSimple({
        "color": _normalize_hex(color_hex),
        "width": LINE_WIDTH,
    })


def _point_symbol(color_hex):
    return QgsMarkerSymbol.createSimple({
        "color": _normalize_hex(color_hex),
        "outline_color": "#333333",
        "outline_width": "0.2",
        "size": POINT_SIZE,
    })


def _escape_expr(value):
    return str(value).replace("'", "''")


def _apply_rule_based_symbology(
    layer, geom_kind, type_field, gtype_field, codes, color_map
):
    """含 FZ：非 FZ 按 ptype 分类着色，FZ 辅助数据统一使用 FZ 配置色。"""
    make_symbol = _point_symbol if geom_kind == "point" else _line_symbol
    type_field = (type_field or "ptype").strip()
    gtype_field = (gtype_field or "gtype").strip()
    root = QgsRuleBasedRenderer.Rule(None)

    for code in codes:
        if code == FZ_PIPE_CODE:
            continue
        symbol = make_symbol(color_map.get(code, "#808080"))
        filt = (
            f'"{type_field}" = \'{_escape_expr(code)}\' '
            f'AND "{gtype_field}" IS NULL'
        )
        root.appendChild(
            QgsRuleBasedRenderer.Rule(symbol, 0, 0, filt, label=str(code))
        )

    fz_symbol = make_symbol(color_map.get(FZ_PIPE_CODE, "#808080"))
    root.appendChild(
        QgsRuleBasedRenderer.Rule(
            fz_symbol, 0, 0, f'"{gtype_field}" IS NOT NULL', label=FZ_PIPE_CODE
        )
    )
    layer.setRenderer(QgsRuleBasedRenderer(root))


def _apply_categorized_symbology(layer, geom_kind, type_field, codes, color_map):
    """仅非 FZ 管类：按 ptype 字段分类着色。"""
    make_symbol = _point_symbol if geom_kind == "point" else _line_symbol
    type_field = (type_field or "").strip()
    codes = [c for c in codes if c != FZ_PIPE_CODE]
    if not codes:
        return

    if len(codes) > 1 and type_field:
        categories = []
        for code in codes:
            symbol = make_symbol(color_map.get(code, "#808080"))
            categories.append(QgsRendererCategory(code, symbol, str(code)))
        if categories:
            layer.setRenderer(QgsCategorizedSymbolRenderer(type_field, categories))
    else:
        code = codes[0]
        symbol = make_symbol(color_map.get(code, "#808080"))
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))


def apply_pipeline_symbology(
    layer,
    geom_kind,
    type_field,
    gtype_field,
    pipeline_types,
    color_map,
    include_fz=False,
):
    """
    - 非 FZ：按 ptype 字段分类着色
    - 含 FZ：非 FZ 数据 ptype 分类 + gtype IS NULL；FZ 数据 gtype IS NOT NULL，统一 FZ 配置色
    """
    codes = [c for c in (pipeline_types or []) if c != FZ_PIPE_CODE]
    if include_fz:
        _apply_rule_based_symbology(
            layer, geom_kind, type_field, gtype_field, codes, color_map
        )
    else:
        _apply_categorized_symbology(layer, geom_kind, type_field, codes, color_map)

    layer.triggerRepaint()
