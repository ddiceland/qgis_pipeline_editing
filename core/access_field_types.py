# -*- coding: utf-8 -*-
"""Access 字段类型定义（与导出插件一致）。"""

ACCESS_FIELD_TYPES = [
    "TEXT", "MEMO", "BYTE", "INTEGER", "LONG", "SINGLE",
    "DOUBLE", "CURRENCY", "DATETIME", "YESNO", "GUID",
]

TEXT_SIZE_OPTIONS = ["10", "20", "50", "100", "255"]
TYPES_WITH_SIZE = {"TEXT"}
TYPE_DEFAULT_SIZE = {"TEXT": "50"}
TYPES_WITH_DECIMALS = {"SINGLE", "DOUBLE"}
DEFAULT_DECIMAL_PLACES = 3
DECIMAL_PLACES_MIN = 0
DECIMAL_PLACES_MAX = 8


def normalize_access_type(mdb_type):
    value = (mdb_type or "TEXT").strip().upper()
    if value in ACCESS_FIELD_TYPES:
        return value
    aliases = {
        "VARCHAR": "TEXT", "CHAR": "TEXT", "STRING": "TEXT",
        "INT": "LONG", "FLOAT": "DOUBLE", "NUMBER": "DOUBLE",
        "DECIMAL": "DOUBLE", "DATE": "DATETIME", "TIME": "DATETIME",
        "BOOLEAN": "YESNO", "BIT": "YESNO",
    }
    return aliases.get(value, "TEXT")


def type_needs_size(mdb_type):
    return normalize_access_type(mdb_type) in TYPES_WITH_SIZE


def type_needs_decimals(mdb_type):
    return normalize_access_type(mdb_type) in TYPES_WITH_DECIMALS


def default_size_for_type(mdb_type):
    normalized = normalize_access_type(mdb_type)
    if normalized in TYPES_WITH_SIZE:
        return TYPE_DEFAULT_SIZE.get(normalized, "50")
    return ""


def parse_decimal_places(raw, default=DEFAULT_DECIMAL_PLACES):
    if raw is None or raw == "" or str(raw).strip() == "-":
        return default
    try:
        places = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return max(DECIMAL_PLACES_MIN, min(DECIMAL_PLACES_MAX, places))


def field_decimal_places(field_def):
    """浮点字段返回小数位（空则 3）；非浮点或无定义返回 None。"""
    if not field_def:
        return None
    if not type_needs_decimals(field_def.get("mdb_type")):
        return None
    return parse_decimal_places(field_def.get("decimal_places"))


def default_decimals_for_type(mdb_type):
    if type_needs_decimals(mdb_type):
        return str(DEFAULT_DECIMAL_PLACES)
    return ""


def round_mdb_number(value, places):
    if value is None or value == "":
        return value
    try:
        return round(float(value), int(places))
    except (TypeError, ValueError):
        return value


def access_column_ddl(item):
    """根据字段定义生成 Access CREATE TABLE 类型片段。"""
    mdb_type = normalize_access_type(item.get("mdb_type"))
    mdb_size = (item.get("mdb_size") or "").strip()

    if mdb_type == "TEXT":
        size = mdb_size or default_size_for_type("TEXT")
        return f"TEXT({size or '50'})"
    if mdb_type == "MEMO":
        return "MEMO"
    if mdb_type == "BYTE":
        return "BYTE"
    if mdb_type == "INTEGER":
        return "INTEGER"
    if mdb_type == "LONG":
        return "LONG"
    if mdb_type == "SINGLE":
        return "SINGLE"
    if mdb_type == "DOUBLE":
        return "DOUBLE"
    if mdb_type == "CURRENCY":
        return "CURRENCY"
    if mdb_type == "DATETIME":
        return "DATETIME"
    if mdb_type == "YESNO":
        return "YESNO"
    if mdb_type == "GUID":
        return "GUID"
    return "TEXT(50)"


def odbc_type_to_mdb_type(type_name):
    """把 ODBC 列类型名转成 Access 字段类型。"""
    value = (type_name or "").strip().upper()
    mapping = {
        "VARCHAR": "TEXT",
        "CHAR": "TEXT",
        "WCHAR": "TEXT",
        "LONGCHAR": "MEMO",
        "MEMO": "MEMO",
        "INTEGER": "LONG",
        "INT": "LONG",
        "COUNTER": "LONG",
        "AUTOINCREMENT": "LONG",
        "SMALLINT": "INTEGER",
        "TINYINT": "BYTE",
        "BYTE": "BYTE",
        "DOUBLE": "DOUBLE",
        "FLOAT": "DOUBLE",
        "REAL": "SINGLE",
        "SINGLE": "SINGLE",
        "DECIMAL": "DOUBLE",
        "NUMERIC": "DOUBLE",
        "CURRENCY": "CURRENCY",
        "DATETIME": "DATETIME",
        "DATE": "DATETIME",
        "TIME": "DATETIME",
        "BIT": "YESNO",
        "YESNO": "YESNO",
        "BOOLEAN": "YESNO",
        "GUID": "GUID",
        "UNIQUEIDENTIFIER": "GUID",
    }
    return mapping.get(value, "TEXT")
