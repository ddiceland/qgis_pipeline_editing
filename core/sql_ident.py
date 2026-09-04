# -*- coding: utf-8 -*-
"""映射调用时的标识符。

PostgreSQL 用双引号并区分大小写；Access/MDB 必须用方括号
（驱动会把双引号中的名称当成参数，报「参数不足」）。
"""


def strip_ident_quotes(name):
    text = (name or "").strip()
    if len(text) >= 2 and text.startswith("[") and text.endswith("]"):
        return text[1:-1].replace("]]", "]").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'", "`"):
        inner = text[1:-1]
        if text[0] == '"':
            inner = inner.replace('""', '"')
        return inner.strip()
    return text


def ident_name(name):
    """去掉用户可能手写的引号，保留原文大小写。"""
    return strip_ident_quotes(name)


def quote_ident(name):
    """PostgreSQL 标识符：双引号，保留配置中的大小写。"""
    text = strip_ident_quotes(name)
    if not text:
        return '""'
    return '"' + text.replace('"', '""') + '"'


def quote_access_ident(name):
    """Access 标识符：方括号。驱动会把双引号里的未知名称当成参数，不能用双引号。"""
    text = strip_ident_quotes(name)
    if not text:
        return "[]"
    return "[" + text.replace("]", "]]") + "]"


def quote_qualified(schema, table):
    """schema.table，两段都加双引号。"""
    schema = strip_ident_quotes(schema) or "public"
    table = strip_ident_quotes(table)
    if not table:
        return ""
    if "." in table:
        left, right = table.split(".", 1)
        left = strip_ident_quotes(left)
        right = strip_ident_quotes(right)
        if left and right:
            return "%s.%s" % (quote_ident(left), quote_ident(right))
    return "%s.%s" % (quote_ident(schema), quote_ident(table))
