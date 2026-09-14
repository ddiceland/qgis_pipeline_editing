# -*- coding: utf-8 -*-
"""按规则集转换字段值：对照表（名称/代码）、角度换算、顺序号、时间。"""

import datetime
import math
import re

from .access_field_types import normalize_access_type


def convert_angle_value(value, target, decimal_places=6):
    """
    target=radians：源值按角度制转为弧度。
    target=degrees：源值按弧度制转为角度。
    """
    if value is None or value == "":
        return value
    try:
        num = float(value)
    except (TypeError, ValueError):
        return value
    if target == "radians":
        out = num * math.pi / 180.0
    elif target == "degrees":
        out = num * 180.0 / math.pi
    else:
        return value
    try:
        places = int(decimal_places)
    except (TypeError, ValueError):
        places = 6
    if places < 0:
        return out
    return round(out, places)


def _apply_lookup_rule(value, rows, rule_target):
    text = "" if value is None else str(value).strip()
    if not text:
        return value
    if rule_target == "code":
        for item in rows or []:
            if (item.get("name") or "").strip() == text:
                return item.get("code") or value
            if (item.get("code") or "").strip() == text:
                return item.get("code") or value
    elif rule_target == "name":
        for item in rows or []:
            if (item.get("code") or "").strip() == text:
                return item.get("name") or value
            if (item.get("name") or "").strip() == text:
                return item.get("name") or value
    return value


def next_sequence_value(rule, row_seq):
    """按表内行号生成从 start_from 起的整数顺序号（默认从 1 开始）。"""
    try:
        start = int((rule or {}).get("start_from", 1))
    except (TypeError, ValueError):
        start = 1
    if start < 1:
        start = 1
    try:
        seq = int(row_seq)
    except (TypeError, ValueError):
        seq = 1
    if seq < 1:
        seq = 1
    return start + seq - 1


def parse_date_value(value):
    """把文本、日期对象解析成 date；无法识别则返回 None。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if hasattr(value, "toPyDateTime"):
        try:
            parsed = value.toPyDateTime()
            if parsed is not None:
                return parsed.date()
        except Exception:
            pass
    if hasattr(value, "toPyDate"):
        try:
            parsed = value.toPyDate()
            if parsed is not None:
                return parsed
        except Exception:
            pass
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("T", " ").split()[0]
    text = text.replace("/", "-").replace(".", "-")
    match = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", text)
    if match:
        try:
            return datetime.date(
                int(match.group(1)), int(match.group(2)), int(match.group(3))
            )
        except ValueError:
            return None
    match = re.match(r"^(\d{4})年(\d{1,2})月(\d{1,2})日?$", text)
    if match:
        try:
            return datetime.date(
                int(match.group(1)), int(match.group(2)), int(match.group(3))
            )
        except ValueError:
            return None
    if re.fullmatch(r"\d{8}", text):
        try:
            return datetime.date(int(text[0:4]), int(text[4:6]), int(text[6:8]))
        except ValueError:
            return None
    return None


def convert_date_value(value, target, mdb_type=None):
    """
    把源日期转成目标格式。
    target=compact：20260822；target=dashed：2026-08-22。
    目标库结构为 DATETIME 时写出日期时间，否则写出文本。
    """
    parsed = parse_date_value(value)
    if parsed is None:
        return value
    kind = normalize_access_type(mdb_type) if mdb_type else ""
    if kind == "DATETIME":
        return datetime.datetime.combine(parsed, datetime.time.min)
    if target in ("compact", "yyyymmdd"):
        return parsed.strftime("%Y%m%d")
    return parsed.strftime("%Y-%m-%d")


def apply_rule_value(value, rule_set_id, rule_target, shared_config, row_seq=None,
                     mdb_type=None):
    if not rule_set_id:
        return value
    rule = None
    if shared_config is not None and hasattr(shared_config, "get_rule_set"):
        rule = shared_config.get_rule_set(rule_set_id)
    kind = (rule or {}).get("kind") or ""
    if not kind and rule_set_id == "angle":
        kind = "angle"
    elif not kind and rule_set_id == "sequence":
        kind = "sequence"
    elif not kind and rule_set_id == "wellno":
        kind = "wellno"
    elif not kind and rule_set_id == "xyz":
        kind = "xyz"
    elif not kind and rule_set_id == "date":
        kind = "date"
    if kind == "sequence" or rule_target == "seq":
        return next_sequence_value(rule, row_seq)
    if kind == "wellno" or rule_set_id == "wellno" or rule_target in ("assign", "follow"):
        return value
    if kind == "xyz" or rule_set_id == "xyz" or rule_target in ("x", "y", "z"):
        return value
    if kind == "date" or rule_set_id == "date" or rule_target in ("dashed", "compact", "yyyymmdd"):
        return convert_date_value(value, rule_target or "dashed", mdb_type)
    if not rule_target:
        return value
    if kind == "angle" or rule_target in ("radians", "degrees"):
        places = (rule or {}).get("decimal_places", 6)
        return convert_angle_value(value, rule_target, places)
    rows = []
    if rule is not None:
        rows = rule.get("rows") or []
    elif shared_config is not None and hasattr(shared_config, "get_rule_set_rows"):
        rows = shared_config.get_rule_set_rows(rule_set_id)
    return _apply_lookup_rule(value, rows, rule_target)
