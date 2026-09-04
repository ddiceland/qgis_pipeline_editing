# -*- coding: utf-8 -*-
"""QVariant / Qt 类型与 Python 原生类型互转。"""

import datetime

from qgis.core import NULL
from qgis.PyQt.QtCore import QDate, QDateTime, QTime, QVariant


def to_python_value(value):
    """转为可安全 copy/pickle 的 Python 原生值。"""
    if value is None or value == NULL:
        return None

    if isinstance(value, QVariant):
        if value.isNull():
            return None
        return to_python_value(value.value())

    if isinstance(value, QDateTime):
        if not value.isValid():
            return None
        return value.toPyDateTime()

    if isinstance(value, QDate):
        if not value.isValid():
            return None
        return datetime.datetime.combine(
            value.toPyDate(), datetime.time.min
        )

    if isinstance(value, QTime):
        if not value.isValid():
            return None
        return value.toPyTime()

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    return str(value)


def attrs_to_python(attrs):
    return {key: to_python_value(val) for key, val in (attrs or {}).items()}


def feature_attrs_to_python(feature, columns):
    return {col: to_python_value(feature[col]) for col in columns}
