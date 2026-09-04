# -*- coding: utf-8 -*-
"""将映射后的管点/管线写成 File Geodatabase 或 GeoPackage。

FileGDB / 可写 OpenFileGDB：要素类自带 OBJECTID（OID）和 Shape（几何）。
QGIS 3.18 自带的 OpenFileGDB 为只读 (rov)，不能 Create；若存在 ESRI FileGDB
驱动则用它写 .gdb，否则可退回 GeoPackage（FID=OBJECTID，几何列=Shape）。
"""

import os
import shutil

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant

from .access_field_types import normalize_access_type
from .sql_ident import ident_name


def _ogr_modules():
    try:
        from osgeo import gdal, ogr
        return gdal, ogr
    except ImportError:
        return None, None


def _unique_existing_dirs(paths):
    out = []
    seen = set()
    for path in paths or []:
        text = os.path.abspath(path) if path else ""
        if not text or text in seen or not os.path.isdir(text):
            continue
        seen.add(text)
        out.append(text)
    return out


def _gdal_plugin_dirs():
    gdal, _ogr = _ogr_modules()
    candidates = []
    env_path = os.environ.get("GDAL_DRIVER_PATH") or ""
    if env_path:
        candidates.extend(env_path.split(os.pathsep))
    prefix = os.environ.get("QGIS_PREFIX_PATH") or ""
    if prefix:
        candidates.extend([
            os.path.join(prefix, "bin", "gdalplugins"),
            os.path.join(prefix, "lib", "gdalplugins"),
            os.path.join(prefix, "..", "bin", "gdalplugins"),
        ])
    if gdal is not None:
        try:
            home = os.path.dirname(os.path.abspath(gdal.__file__))
            candidates.extend([
                os.path.join(home, "gdalplugins"),
                os.path.join(os.path.dirname(home), "gdalplugins"),
                os.path.join(os.path.dirname(home), "bin", "gdalplugins"),
            ])
        except Exception:
            pass
    return _unique_existing_dirs(candidates)


def _dir_has_filegdb_plugin(plugin_dir):
    try:
        names = os.listdir(plugin_dir)
    except OSError:
        return False
    for name in names:
        lower = name.lower()
        if "filegdb" in lower and (
            lower.endswith(".dll") or lower.endswith(".so") or lower.endswith(".dylib")
        ):
            return True
    return False


def _ensure_filegdb_registered():
    """若本机装了 ogr_FileGDB 插件但未注册，尝试加入 GDAL_DRIVER_PATH 并重新注册。"""
    gdal, ogr = _ogr_modules()
    if ogr is None:
        return
    if ogr.GetDriverByName("FileGDB") is not None:
        return
    for plugin_dir in _gdal_plugin_dirs():
        if not _dir_has_filegdb_plugin(plugin_dir):
            continue
        try:
            gdal.SetConfigOption("GDAL_DRIVER_PATH", plugin_dir)
            gdal.AllRegister()
        except Exception:
            continue
        if ogr.GetDriverByName("FileGDB") is not None:
            return


def _driver_can_create(ogr, name):
    driver = ogr.GetDriverByName(name)
    if driver is None:
        return False
    try:
        return bool(driver.TestCapability(ogr.ODrCCreateDataSource))
    except Exception:
        return False


def writable_gdb_drivers():
    """返回当前进程里真正能 Create 的 GDB 驱动，优先 FileGDB。"""
    _ensure_filegdb_registered()
    _gdal, ogr = _ogr_modules()
    if ogr is None:
        return []
    names = []
    for name in ("FileGDB", "OpenFileGDB"):
        if _driver_can_create(ogr, name):
            names.append(name)
    return names


def gdb_write_unavailable_message():
    present = []
    _gdal, ogr = _ogr_modules()
    if ogr is not None:
        for name in ("OpenFileGDB", "FileGDB"):
            if ogr.GetDriverByName(name) is not None:
                present.append(name)
    detail = "、".join(present) if present else "无"
    return (
        "当前 QGIS 的 GDAL 无法创建 File Geodatabase（.gdb）。\n"
        "已检测到的驱动：%s。\n\n"
        "ogr2ogr --formats 里的 OpenFileGDB (rov) 表示只读矢量："
        "可以打开已有 .gdb，但没有 Create 方法，因此会报 "
        "“no create method implemented for this format”。\n"
        "OpenFileGDB 写入从 GDAL 3.6 才提供；QGIS 3.18 自带版本不够。\n\n"
        "要写出 .gdb，请安装 ESRI FileGDB 驱动：\n"
        "OSGeo4W Setup → Advanced → Libs → gdal-filegdb。\n"
        "安装成功后，ogr2ogr --formats 应出现 FileGDB (rw+v)，然后重启 QGIS。"
        % detail
    )


def _mdb_type_to_qvariant(mdb_type):
    kind = normalize_access_type(mdb_type)
    mapping = {
        "BYTE": QVariant.Int,
        "INTEGER": QVariant.Int,
        "LONG": QVariant.LongLong,
        "SINGLE": QVariant.Double,
        "DOUBLE": QVariant.Double,
        "CURRENCY": QVariant.Double,
        "DATETIME": QVariant.DateTime,
        "YESNO": QVariant.Bool,
        "GUID": QVariant.String,
        "MEMO": QVariant.String,
        "TEXT": QVariant.String,
    }
    return mapping.get(kind, QVariant.String)


def _layer_uri(kind, crs=None):
    geom = "PointZ" if kind == "point" else "LineStringZ"
    if crs is not None and crs.isValid() and crs.authid():
        return "%s?crs=%s" % (geom, crs.authid())
    return geom


class GdbWriter:
    def __init__(self, output_path, crs=None, driver_names=None):
        self.output_path = os.path.abspath(output_path)
        # GDB 默认不写坐标系；仅在调用方显式传入有效 CRS 时才带上（如 GPKG）。
        self.crs = crs if crs is not None and crs.isValid() else QgsCoordinateReferenceSystem()
        if driver_names:
            self.driver_names = list(driver_names)
        else:
            self.driver_names = writable_gdb_drivers()
        if not self.driver_names:
            raise RuntimeError(gdb_write_unavailable_message())
        self._created = False
        parent = os.path.dirname(self.output_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if os.path.isdir(self.output_path):
            shutil.rmtree(self.output_path)
        elif os.path.isfile(self.output_path):
            os.remove(self.output_path)

    def write_feature_class(self, table_name, kind, field_defs, mapped_rows, geom_wkts):
        name = ident_name(table_name)
        if not name:
            raise ValueError("GDB 要素类名称不能为空")
        uri = _layer_uri(kind, self.crs)
        layer = QgsVectorLayer(uri, name, "memory")
        if not layer.isValid():
            raise RuntimeError("无法创建内存图层：%s" % name)
        if not self.crs.isValid():
            layer.setCrs(QgsCoordinateReferenceSystem(), False)
        provider = layer.dataProvider()
        fields = QgsFields()
        # OBJECTID / Shape 由驱动生成，不要再写成普通属性字段。
        seen = {"OBJECTID", "SHAPE", "Shape", "shape", "FID", "fid"}
        attr_names = []
        for item in field_defs or []:
            fname = ident_name(item.get("name"))
            if not fname or fname in seen:
                continue
            seen.add(fname)
            fields.append(QgsField(fname, _mdb_type_to_qvariant(item.get("mdb_type"))))
            attr_names.append(fname)
        if fields.count():
            provider.addAttributes([fields.at(i) for i in range(fields.count())])
            layer.updateFields()

        features = []
        for index, mapped in enumerate(mapped_rows or [], start=1):
            feat = QgsFeature(layer.fields())
            wkt = ""
            if index <= len(geom_wkts or []):
                wkt = geom_wkts[index - 1] or ""
            geom = QgsGeometry.fromWkt(wkt) if wkt else QgsGeometry()
            if geom is None or geom.isEmpty():
                continue
            feat.setGeometry(geom)
            for fname in attr_names:
                feat.setAttribute(fname, mapped.get(fname))
            features.append(feat)
        if features:
            provider.addFeatures(features)
        layer.updateExtents()
        self._flush_layer(layer, name)
        return len(features)

    def _flush_layer(self, layer, layer_name):
        last_error = ""
        for driver in self.driver_names:
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = driver
            options.layerName = layer_name
            options.fileEncoding = "UTF-8"
            options.overrideGeometryType = (
                QgsWkbTypes.PointZ if layer.wkbType() in (
                    QgsWkbTypes.Point, QgsWkbTypes.PointZ, QgsWkbTypes.Point25D
                ) else QgsWkbTypes.LineStringZ
            )
            options.forceMulti = False
            options.includeZ = True
            if driver == "GPKG":
                options.layerOptions = ["FID=OBJECTID", "GEOMETRY_NAME=Shape"]
            if self._created:
                options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
            else:
                options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile
            result = QgsVectorFileWriter.writeAsVectorFormatV2(
                layer, self.output_path, QgsCoordinateTransformContext(), options
            )
            if isinstance(result, tuple):
                err = result[0]
                msg = result[1] if len(result) > 1 else ""
            else:
                err = result
                msg = ""
            if err == QgsVectorFileWriter.NoError:
                self._created = True
                return
            last_error = "%s（驱动 %s）" % (msg or err, driver)
        if "GPKG" in self.driver_names:
            raise RuntimeError("写入 GeoPackage 失败：%s" % (last_error or "未知错误"))
        raise RuntimeError(
            "写入 File Geodatabase 失败：%s\n\n%s"
            % (last_error or "未知错误", gdb_write_unavailable_message())
        )
