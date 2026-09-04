# -*- coding: utf-8 -*-
"""按管类为图层设置符号颜色。"""

from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsDrawSourceEffect,
    QgsEffectStack,
    QgsInnerShadowEffect,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsOuterGlowEffect,
    QgsPaintEffect,
    QgsPalLayerSettings,
    QgsRendererCategory,
    QgsSimpleLineSymbolLayer,
    QgsSingleSymbolRenderer,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsUnitTypes,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtGui import QColor, QFont, QPainter

LINE_WIDTH = "0.35"
POINT_SIZE = "2.0"
TXT_LINE_COLOR = QColor(0, 255, 0)
TXT_LINE_WIDTH_MM = 1.0
TXT_LABEL_FONT = "SimSun"
TXT_LABEL_SIZE = 11
TXT_LABEL_BUFFER_MM = 1.0


def _normalize_hex(color):
    if not color:
        return "#808080"
    c = str(color).strip()
    if not c.startswith("#"):
        c = "#" + c
    return c


def _txt_line_draw_mode():
    if hasattr(QgsPaintEffect, "ModifyAndRender"):
        return QgsPaintEffect.ModifyAndRender
    return 2


def _create_txt_line_effect_stack():
    """TXT 线图层绘制效果。

    QGIS 属性面板按栈末项显示在上：先加入外发光、再源、再内部阴影，
    界面顺序即为「内部阴影、源、外发光」。
    """
    stack = QgsEffectStack()
    stack.setEnabled(True)

    outer_glow = QgsOuterGlowEffect()
    outer_glow.setEnabled(True)
    outer_glow.setSpread(2.0)
    outer_glow.setSpreadUnit(QgsUnitTypes.RenderMillimeters)
    outer_glow.setBlurLevel(0.7935)
    outer_glow.setBlurUnit(QgsUnitTypes.RenderMillimeters)
    outer_glow.setOpacity(0.5)
    outer_glow.setColor(QColor(255, 0, 0))
    outer_glow.setBlendMode(QPainter.CompositionMode_SourceOver)
    outer_glow.setDrawMode(_txt_line_draw_mode())
    stack.appendEffect(outer_glow)

    source = QgsDrawSourceEffect()
    source.setEnabled(True)
    stack.appendEffect(source)

    inner_shadow = QgsInnerShadowEffect()
    inner_shadow.setEnabled(True)
    inner_shadow.setOffsetAngle(135)
    inner_shadow.setOffsetDistance(2.0)
    inner_shadow.setOffsetUnit(QgsUnitTypes.RenderMillimeters)
    inner_shadow.setBlurLevel(2.645)
    inner_shadow.setBlurUnit(QgsUnitTypes.RenderMillimeters)
    inner_shadow.setOpacity(0.146)
    inner_shadow.setColor(QColor(0, 0, 0))
    inner_shadow.setBlendMode(QPainter.CompositionMode_Multiply)
    inner_shadow.setDrawMode(_txt_line_draw_mode())
    stack.appendEffect(inner_shadow)

    return stack


def _apply_txt_line_effects(symbol_layer):
    """
    将效果栈挂到「符号图层」上（对应图层属性中的「绘制效果」开关）。
    挂在 QgsSymbol / Renderer 上时，界面仍会显示为关闭。
    """
    stack = _create_txt_line_effect_stack()
    symbol_layer.setPaintEffect(stack)
    effect = symbol_layer.paintEffect()
    if effect is not None:
        effect.setEnabled(True)


def apply_txt_coord_layer_style(layer):
    """TXT 坐标线图层：绿色 neon 线 + 起点-终点标注。"""
    symbol = QgsLineSymbol()
    line_layer = QgsSimpleLineSymbolLayer()
    line_layer.setColor(TXT_LINE_COLOR)
    line_layer.setWidth(TXT_LINE_WIDTH_MM)
    line_layer.setWidthUnit(QgsUnitTypes.RenderMillimeters)
    symbol.changeSymbolLayer(0, line_layer)
    # 必须挂在符号图层上；挂在 Symbol 上时「绘制效果」仍显示关闭
    applied = symbol.symbolLayer(0)
    if applied is not None:
        _apply_txt_line_effects(applied)
    layer.setRenderer(QgsSingleSymbolRenderer(symbol.clone()))
    # setRenderer 会克隆符号，再对最终渲染器中的符号图层启用效果
    renderer = layer.renderer()
    if renderer is not None:
        final_symbol = renderer.symbol()
        if final_symbol is not None and final_symbol.symbolLayerCount() > 0:
            final_layer = final_symbol.symbolLayer(0)
            if final_layer is not None:
                if final_layer.paintEffect() is None:
                    _apply_txt_line_effects(final_layer)
                else:
                    final_layer.paintEffect().setEnabled(True)

    label_settings = QgsPalLayerSettings()
    label_settings.isExpression = True
    label_settings.fieldName = '"起点" || \'-\' || "终点"'

    text_format = QgsTextFormat()
    text_format.setColor(QColor(0, 0, 0))
    text_format.setFont(QFont(TXT_LABEL_FONT, TXT_LABEL_SIZE))
    text_format.setSize(TXT_LABEL_SIZE)
    text_format.setSizeUnit(QgsUnitTypes.RenderPoints)
    if hasattr(QgsTextFormat, "HorizontalOrientation"):
        text_format.setOrientation(QgsTextFormat.HorizontalOrientation)

    buffer_settings = QgsTextBufferSettings()
    buffer_settings.setEnabled(True)
    buffer_settings.setSize(TXT_LABEL_BUFFER_MM)
    buffer_settings.setSizeUnit(QgsUnitTypes.RenderMillimeters)
    buffer_settings.setColor(QColor(255, 255, 255))
    text_format.setBuffer(buffer_settings)

    label_settings.setFormat(text_format)
    label_settings.placement = QgsPalLayerSettings.Horizontal

    layer.setLabeling(QgsVectorLayerSimpleLabeling(label_settings))
    layer.setLabelsEnabled(True)
    layer.triggerRepaint()


def _pipe_symbol(geom_kind, color_hex):
    color = _normalize_hex(color_hex)
    if geom_kind == "point":
        return QgsMarkerSymbol.createSimple({
            "color": color,
            "outline_color": "#333333",
            "outline_width": "0.2",
            "size": POINT_SIZE,
        })
    return QgsLineSymbol.createSimple({
        "color": color,
        "width": LINE_WIDTH,
    })


def apply_pipe_symbology(layer, geom_kind, color_hex):
    layer.setRenderer(QgsSingleSymbolRenderer(_pipe_symbol(geom_kind, color_hex)))
    layer.triggerRepaint()


def apply_pipe_category_symbology(layer, geom_kind, type_field, codes, color_map):
    """按管类字段分类着色（合并后的 MDB管点 / MDB管线）。"""
    field_name = (type_field or "").strip()
    codes = [c for c in (codes or []) if c]
    if not field_name or not codes:
        color = (color_map or {}).get(codes[0], "#808080") if codes else "#808080"
        apply_pipe_symbology(layer, geom_kind, color)
        return
    categories = []
    for code in codes:
        symbol = _pipe_symbol(geom_kind, (color_map or {}).get(code, "#808080"))
        categories.append(QgsRendererCategory(code, symbol, code))
    layer.setRenderer(QgsCategorizedSymbolRenderer(field_name, categories))
    layer.triggerRepaint()
