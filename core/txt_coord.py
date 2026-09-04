# -*- coding: utf-8 -*-
"""解析、写回 TXT 坐标文档，并加载为 QGIS 线图层。"""

import os

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant

from .mdb.coord_utils import data_xy_to_map_xy
from .mdb.layer_style import apply_txt_coord_layer_style
from .pipe_catalog import pipeline_display_name


TXT_LAYER_GROUP = "TXT坐标"


def _read_text_lines(path):
    for encoding in ("utf-8-sig", "utf-8", "gbk", "gb2312"):
        try:
            with open(path, "r", encoding=encoding) as fp:
                return [ln.strip() for ln in fp.readlines() if ln.strip()], encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别文件编码：%s" % path)


def _parse_coord_triplet(text, line_no):
    parts = [p.strip() for p in text.split(",")]
    if len(parts) < 3:
        raise ValueError("第 %s 行坐标格式错误，应为 x,y,z：%s" % (line_no, text))
    try:
        return float(parts[0]), float(parts[1]), float(parts[2])
    except ValueError as exc:
        raise ValueError("第 %s 行坐标不是有效数字：%s" % (line_no, text)) from exc


def _fmt_num(value):
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "0"
    text = ("%.8f" % num).rstrip("0").rstrip(".")
    return text if text else "0"


def parse_txt_coord_file(path):
    """
    解析 TXT 坐标文件。

    第一行前两个字符为管类代码；其后每行：x1,y1,z1;x2,y2,z2;管径
    返回 dict：pipe_code / header / encoding / segments。
    """
    lines, encoding = _read_text_lines(path)
    if not lines:
        raise ValueError("TXT 文件为空")

    header = lines[0]
    if len(header) < 2:
        raise ValueError("首行无法识别管类代码：%s" % header)
    pipe_code = header[:2].upper()

    segments = []
    point_seq = 1
    for idx, line in enumerate(lines[1:], start=2):
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 3:
            raise ValueError(
                "第 %s 行格式错误，应为 x1,y1,z1;x2,y2,z2;管径：%s" % (idx, line)
            )
        x1, y1, z1 = _parse_coord_triplet(parts[0], idx)
        x2, y2, z2 = _parse_coord_triplet(parts[1], idx)
        diameter = parts[2]
        start_no = "S%s" % point_seq
        end_no = "S%s" % (point_seq + 1)
        point_seq += 1
        segments.append({
            "起点": start_no,
            "终点": end_no,
            "X": x1,
            "Y": y1,
            "Z": z1,
            "管径": diameter,
            "x1": x1,
            "y1": y1,
            "z1": z1,
            "x2": x2,
            "y2": y2,
            "z2": z2,
        })

    if not segments:
        raise ValueError("TXT 文件中没有有效的坐标行")
    return {
        "pipe_code": pipe_code,
        "header": header,
        "encoding": encoding,
        "segments": segments,
    }


def sync_segment_joints(segments):
    """下一行起点坐标与上一行终点坐标保持一致。"""
    segs = list(segments or [])
    for i in range(len(segs) - 1):
        prev = segs[i]
        nxt = segs[i + 1]
        x2 = prev.get("x2", prev.get("X"))
        y2 = prev.get("y2", prev.get("Y"))
        z2 = prev.get("z2", prev.get("Z"))
        nxt["x1"] = x2
        nxt["y1"] = y2
        nxt["z1"] = z2
        nxt["X"] = x2
        nxt["Y"] = y2
        nxt["Z"] = z2
    return segs


def write_txt_coord_file(path, pipe_code, segments, encoding="utf-8", header=None):
    """按打开时的格式写回 TXT（覆盖原文件）。"""
    segments = sync_segment_joints(segments)
    first = (header or "").strip() or (pipe_code or "")
    if first and len(first) >= 2:
        pass
    elif pipe_code:
        first = pipe_code
    lines = [first]
    for seg in segments or []:
        x1 = seg.get("x1", seg.get("X", 0))
        y1 = seg.get("y1", seg.get("Y", 0))
        z1 = seg.get("z1", seg.get("Z", 0))
        x2 = seg.get("x2", x1)
        y2 = seg.get("y2", y1)
        z2 = seg.get("z2", z1)
        diameter = "" if seg.get("管径") is None else str(seg.get("管径"))
        lines.append("%s,%s,%s;%s,%s,%s;%s" % (
            _fmt_num(x1), _fmt_num(y1), _fmt_num(z1),
            _fmt_num(x2), _fmt_num(y2), _fmt_num(z2),
            diameter,
        ))
    out_encoding = encoding or "utf-8"
    if out_encoding.lower() in ("utf-8-sig",):
        out_encoding = "utf-8-sig"
    with open(path, "w", encoding=out_encoding, newline="\n") as fp:
        fp.write("\n".join(lines))
        if lines:
            fp.write("\n")


def _remove_txt_layers_for_path(txt_path):
    project = QgsProject.instance()
    abs_path = os.path.normcase(os.path.abspath(txt_path)) if txt_path else ""
    remove_ids = []
    for layer in project.mapLayers().values():
        stored = layer.customProperty("txt_coord/source_path")
        if not stored:
            continue
        if os.path.normcase(os.path.abspath(str(stored))) == abs_path:
            remove_ids.append(layer.id())
    for layer_id in remove_ids:
        project.removeMapLayer(layer_id)
    root = project.layerTreeRoot()
    group = root.findGroup(TXT_LAYER_GROUP)
    if group is not None and not group.children():
        root.removeChildNode(group)


def load_txt_coord_layer(txt_path, pipe_code=None, segments=None, log=None, swap_xy=True):
    """解析 TXT（或使用已有分段）并加载为 QGIS 线图层。"""
    def _log(msg):
        if log:
            log(msg)

    txt_path = os.path.abspath(txt_path)
    if segments is None:
        parsed = parse_txt_coord_file(txt_path)
        pipe_code = parsed["pipe_code"]
        segments = parsed["segments"]
    if not pipe_code:
        raise ValueError("未能识别 TXT 管类")
    if not segments:
        raise ValueError("没有可加载的坐标行")

    _log("TXT 管类：%s，共 %s 段" % (pipe_code, len(segments)))
    _log("坐标约定：%s" % ("交换 X/Y" if swap_xy else "不交换 X/Y"))
    _remove_txt_layers_for_path(txt_path)

    project = QgsProject.instance()
    base_name = os.path.splitext(os.path.basename(txt_path))[0]
    layer_name = "%s-TXT(%s)" % (pipeline_display_name(pipe_code), base_name)
    layer = QgsVectorLayer("LineString", layer_name, "memory")
    if not layer.isValid():
        raise RuntimeError("创建 TXT 线图层失败")
    layer.setCrs(QgsCoordinateReferenceSystem(), False)

    fields = QgsFields()
    fields.append(QgsField("起点", QVariant.String, len=20))
    fields.append(QgsField("终点", QVariant.String, len=20))
    fields.append(QgsField("X1", QVariant.Double))
    fields.append(QgsField("Y1", QVariant.Double))
    fields.append(QgsField("Z1", QVariant.Double))
    fields.append(QgsField("X2", QVariant.Double))
    fields.append(QgsField("Y2", QVariant.Double))
    fields.append(QgsField("Z2", QVariant.Double))
    fields.append(QgsField("管径", QVariant.String, len=50))
    provider = layer.dataProvider()
    provider.addAttributes(fields)
    layer.updateFields()

    features = []
    for seg in segments:
        x1 = float(seg.get("x1", seg.get("X") or 0) or 0)
        y1 = float(seg.get("y1", seg.get("Y") or 0) or 0)
        z1 = float(seg.get("z1", seg.get("Z") or 0) or 0)
        x2 = float(seg.get("x2", x1) or 0)
        y2 = float(seg.get("y2", y1) or 0)
        z2 = float(seg.get("z2", z1) or 0)
        mx1, my1 = data_xy_to_map_xy(x1, y1, swap=swap_xy)
        mx2, my2 = data_xy_to_map_xy(x2, y2, swap=swap_xy)
        geom = QgsGeometry.fromPolylineXY([
            QgsPointXY(mx1, my1),
            QgsPointXY(mx2, my2),
        ])
        feat = QgsFeature(fields)
        feat.setGeometry(geom)
        feat.setAttributes([
            seg.get("起点") or "",
            seg.get("终点") or "",
            x1, y1, z1, x2, y2, z2,
            "" if seg.get("管径") is None else str(seg.get("管径")),
        ])
        features.append(feat)

    provider.addFeatures(features)
    layer.updateExtents()
    apply_txt_coord_layer_style(layer)

    root = project.layerTreeRoot()
    group = root.findGroup(TXT_LAYER_GROUP)
    if group is None:
        group = root.insertGroup(0, TXT_LAYER_GROUP)
    project.addMapLayer(layer, False)
    group.addLayer(layer)
    layer.setCustomProperty("txt_coord/source_path", txt_path)
    layer.setCustomProperty("txt_coord/pipe_code", pipe_code)
    layer.setCustomProperty("txt_coord/swap_xy", "1" if swap_xy else "0")
    _log("已加载 TXT 线图层：%s" % layer_name)
    return layer, pipe_code, len(segments)
