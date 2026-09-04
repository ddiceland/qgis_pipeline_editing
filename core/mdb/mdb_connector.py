# -*- coding: utf-8 -*-
"""Access(MDB) 连接与读写。"""

import datetime
import os

try:
    import pyodbc
except ImportError:
    pyodbc = None

from ..sql_ident import ident_name, quote_access_ident


class AccessRow:
    """按列下标取值，避免把整行先转成 dict。"""

    __slots__ = ("_record", "_index")

    def __init__(self, record, index):
        self._record = record
        self._index = index

    def get(self, key, default=None):
        if not key:
            return default
        idx = self._index.get(key)
        if idx is None:
            idx = self._index.get(str(key).upper())
        if idx is None:
            return default
        return self._record[idx]

    def __contains__(self, key):
        if not key:
            return False
        return key in self._index or str(key).upper() in self._index

    def items(self):
        inverse = {}
        for key, idx in self._index.items():
            if idx not in inverse:
                inverse[idx] = key
        return [
            (inverse[idx], self._record[idx])
            for idx in range(len(self._record))
            if idx in inverse
        ]


def column_index_map(columns):
    index = {}
    for i, name in enumerate(columns or []):
        index[name] = i
        index[str(name).upper()] = i
    return index


def wrap_records(columns, records):
    index = column_index_map(columns)
    return [AccessRow(record, index) for record in records or []]


def check_pyodbc_available():
    if pyodbc is None:
        raise RuntimeError(
            "未找到 pyodbc 模块，请在 QGIS Python 环境中安装：\n"
            "python3 -m pip install pyodbc"
        )
    drivers = [d for d in pyodbc.drivers() if "Access Driver" in d]
    if not drivers:
        raise RuntimeError(
            "系统未检测到 Access ODBC 驱动。\n"
            "请安装 Microsoft Access Database Engine Redistributable。"
        )


def _connection_string(mdb_path):
    return (
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={os.path.abspath(mdb_path)};"
    )


def _access_2003_create_strings(output_path):
    return [
        (
            f"Provider=Microsoft.Jet.OLEDB.4.0;"
            f"Data Source={output_path};"
            f"Jet OLEDB:Engine Type=5;"
        ),
        (
            f"Provider=Microsoft.ACE.OLEDB.12.0;"
            f"Data Source={output_path};"
            f"Jet OLEDB:Engine Type=5;"
        ),
        f"Provider=Microsoft.ACE.OLEDB.12.0;Data Source={output_path};",
    ]


def create_empty_mdb(output_path):
    """创建空的 Access MDB 文件（Access 2002-2003 / Jet 4.0 格式）。"""
    output_path = os.path.abspath(output_path)
    if os.path.exists(output_path):
        os.remove(output_path)
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    try:
        import win32com.client
        cat = win32com.client.Dispatch("ADOX.Catalog")
        errors = []
        for conn_str in _access_2003_create_strings(output_path):
            try:
                cat.Create(conn_str)
                return output_path
            except Exception as exc:
                errors.append(str(exc))
    except ImportError:
        errors = ["未安装 pywin32（pip install pywin32）"]
    except Exception as exc:
        errors = [str(exc)]

    detail = "\n".join(f"- {msg}" for msg in errors[:3])
    raise RuntimeError(
        "无法创建空的 Access MDB 文件。\n"
        "请确认已安装 Microsoft Access Database Engine（32/64 位需与 QGIS 匹配），"
        "且 QGIS Python 环境可用 pywin32（pip install pywin32）。\n"
        f"尝试详情：\n{detail}"
    )


class MdbConnection:
    def __init__(self, mdb_path):
        check_pyodbc_available()
        self.mdb_path = os.path.abspath(mdb_path)
        if not os.path.isfile(self.mdb_path):
            raise FileNotFoundError(f"MDB 文件不存在：{self.mdb_path}")
        self.conn = pyodbc.connect(_connection_string(self.mdb_path), autocommit=False)
        self.cursor = self.conn.cursor()
        self._columns_cache = {}

    def list_user_tables(self):
        """列出用户表。正元等 MDB 里点/线有时是查询(VIEW)而不是物理表。"""
        tables = []
        for row in self.cursor.tables():
            name = (row.table_name or "").strip()
            ttype = (row.table_type or "").upper()
            if not name or name.startswith("MSys") or name.startswith("~"):
                continue
            if ttype in ("TABLE", "VIEW", "SYNONYM", "LINK", "PASS-THROUGH"):
                tables.append(name)
        return sorted(set(tables))

    def get_columns(self, table_name):
        key = (table_name or "").strip().upper()
        if not key:
            return []
        cached = self._columns_cache.get(key)
        if cached is not None:
            return cached
        cols = []
        for row in self.cursor.columns(table=table_name):
            cols.append({
                "name": row.column_name,
                "type": (row.type_name or "").upper(),
                "nullable": row.nullable == 1,
            })
        self._columns_cache[key] = cols
        return cols

    def read_records(self, table_name, where=None):
        """读取整表为元组列表。Access 必须 SELECT *。"""
        sql = "SELECT * FROM %s" % quote_access_ident(table_name)
        if where:
            sql += " WHERE %s" % where
        self.cursor.execute(sql)
        columns = [ident_name(desc[0]) for desc in self.cursor.description]
        return columns, self.cursor.fetchall()

    def read_all_rows(self, table_name, field_names=None, where=None):
        """读取整表为 dict 列表（入库/转换等仍用此接口）。"""
        columns, records = self.read_records(table_name, where=where)
        rows = [dict(zip(columns, record)) for record in records]
        return columns, rows

    def has_rows(self, table_name):
        """是否至少有一行。用 TOP 1，避免大表 COUNT(*)。"""
        if not table_name:
            return False
        try:
            self.cursor.execute(
                "SELECT TOP 1 1 FROM %s" % quote_access_ident(table_name)
            )
            return self.cursor.fetchone() is not None
        except Exception:
            return True

    def create_table(self, table_name, fields):
        """按字段定义新建表。fields: [{name, mdb_type, mdb_size}, ...]"""
        from ..access_field_types import access_column_ddl
        cols = []
        seen = set()
        for item in fields or []:
            name = (item.get("name") or "").strip()
            if not name or name.upper() in seen:
                continue
            seen.add(name.upper())
            cols.append("%s %s" % (quote_access_ident(name), access_column_ddl(item)))
        if not cols:
            raise ValueError(f"表 {table_name} 没有有效字段，无法建表")
        self.cursor.execute(
            "CREATE TABLE %s (%s)" % (quote_access_ident(table_name), ", ".join(cols))
        )

    def insert_row(self, table_name, values_by_column):
        if not values_by_column:
            return
        cols = list(values_by_column.keys())
        placeholders = ",".join(["?"] * len(cols))
        col_sql = ",".join(quote_access_ident(c) for c in cols)
        sql = "INSERT INTO %s (%s) VALUES (%s)" % (
            quote_access_ident(table_name), col_sql, placeholders
        )
        self.cursor.execute(sql, [python_to_odbc(values_by_column[c]) for c in cols])

    def update_row(self, table_name, pk_field, pk_value, values_by_column):
        if not values_by_column:
            return
        set_sql = ", ".join("%s = ?" % quote_access_ident(c) for c in values_by_column.keys())
        sql = "UPDATE %s SET %s WHERE %s = ?" % (
            quote_access_ident(table_name), set_sql, quote_access_ident(pk_field)
        )
        params = list(values_by_column.values()) + [pk_value]
        self.cursor.execute(sql, params)

    def delete_row(self, table_name, pk_field, pk_value):
        sql = "DELETE FROM %s WHERE %s = ?" % (
            quote_access_ident(table_name), quote_access_ident(pk_field)
        )
        self.cursor.execute(sql, [pk_value])

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        try:
            self.cursor.close()
        except Exception:
            pass
        try:
            self.conn.close()
        except Exception:
            pass


def python_to_odbc(value):
    if value is None:
        return None
    if hasattr(value, "toPyDateTime"):
        value = value.toPyDateTime()
    if isinstance(value, datetime.datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, datetime.date):
        return datetime.datetime.combine(value, datetime.time.min)
    try:
        from decimal import Decimal
        if isinstance(value, Decimal):
            return float(value)
    except Exception:
        pass
    return value
