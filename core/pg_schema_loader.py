# -*- coding: utf-8 -*-
"""从 PostgreSQL 读取表字段结构。"""

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

from .config_schema import _now_iso, normalize_pg_table_snapshot, order_pipe_codes


def fetch_table_columns(conn_info, schema, table):
    """
    返回 normalize 后的表快照 dict：
    {schema, table, loaded_at, columns:[{name,data_type,udt_name,is_nullable,ordinal_position}]}
    """
    if psycopg2 is None:
        raise RuntimeError(
            "未找到 psycopg2 模块，请在 QGIS 的 Python 环境安装：\n"
            "python3 -m pip install psycopg2-binary"
        )
    schema = (schema or "public").strip() or "public"
    table = (table or "").strip()
    if not table:
        raise ValueError("表名不能为空")

    conn = psycopg2.connect(
        host=conn_info.host,
        port=conn_info.port,
        dbname=conn_info.dbname,
        user=conn_info.user,
        password=conn_info.password,
    )
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT column_name, data_type, udt_name, is_nullable, ordinal_position
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            (schema, table),
        )
        rows = cur.fetchall()
        cur.close()
        if not rows:
            raise RuntimeError(f"未找到表 {schema}.{table}，或表没有任何列")
        columns = [
            {
                "name": r["column_name"],
                "data_type": r["data_type"] or "",
                "udt_name": r["udt_name"] or "",
                "is_nullable": r["is_nullable"] or "YES",
                "ordinal_position": int(r["ordinal_position"] or 0),
            }
            for r in rows
        ]
        return normalize_pg_table_snapshot({
            "schema": schema,
            "table": table,
            "loaded_at": _now_iso(),
            "columns": columns,
        })
    finally:
        conn.close()


def refresh_pg_pipe_types(
    shared_config,
    conn_info=None,
    persist=False,
    view_schema=None,
    view_table=None,
):
    """
    从「管线最大井编号」视图刷新总库管类占用。

    未配置、连不上或查询失败时清空 codes（不保留上一份），总数据库将全部禁用。
    仅应由「加载表结构」或插件打开时调用。
    """
    from .pg_connection import load_connection_info
    from .pg_import import fetch_view_pipe_type_codes

    info = conn_info
    if info is None:
        info, _ = load_connection_info()

    pg = shared_config.get_pg_config() if shared_config else {}
    view = pg.get("max_expno") or {}
    schema = (
        view_schema
        if view_schema is not None
        else (view.get("schema") or "public")
    )
    schema = (schema or "public").strip() or "public"
    table = (
        view_table if view_table is not None else (view.get("table") or "")
    )
    table = (table or "").strip()
    ptype_field = (view.get("ptype_field") or "ptype").strip() or "ptype"

    error = ""
    codes = []
    if not table:
        error = "未配置「管线最大井编号」视图表"
    elif not (info.host or "").strip() or not (info.dbname or "").strip() or not (info.user or "").strip():
        error = "未配置 PostgreSQL 连接"
    elif psycopg2 is None:
        error = "未找到 psycopg2 模块，无法读取视图表"
    else:
        try:
            conn = psycopg2.connect(
                host=info.host,
                port=info.port,
                dbname=info.dbname,
                user=info.user,
                password=info.password,
            )
            try:
                codes = order_pipe_codes(
                    fetch_view_pipe_type_codes(conn, schema, table, ptype_field)
                )
            finally:
                conn.close()
        except Exception as exc:
            codes = []
            error = str(exc)

    snapshot = {
        "schema": schema,
        "table": table,
        "loaded_at": _now_iso(),
        "codes": codes,
        "error": error,
    }
    schemas = shared_config.get_pg_table_schemas()
    schemas["pipe_types"] = snapshot
    shared_config.set_pg_table_schemas(schemas)
    if persist:
        try:
            shared_config.save()
        except OSError:
            pass
    return snapshot
