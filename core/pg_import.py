# -*- coding: utf-8 -*-
"""
MDB → PostgreSQL 入库。

按「结构映射 → 导入映射」写总库；井编号规则可选：
选了则按视图表续编并对照更新，未选则按原始井号导入。
FZ 井编号按行内管类字段（如 YS、WS）续编，不使用 FZ 前缀。
源表缺少管类字段时停止整次入库。
"""

from .mdb.mdb_connector import MdbConnection
from .mdb.geometry_builder import (
    build_point_lookup,
    line_geometry_from_row,
    point_geometry_from_row,
)
from .mdb.schema_detect import (
    discover_pipe_layers,
    resolve_existing_table,
    TableProfile,
)
from .mdb_decimals import apply_source_field_decimals
from .mdb.structure_convert import (
    mapping_has_field_rows,
    _group_by_id,
    _kind_mapping_rows,
    _row_get,
    _source_table_candidates,
)
from .pg_connection import PgConnectionInfo, test_pg_connection
from .mdb.fz_filter import (
    apply_fz_row_filter,
    normalize_type_code,
    resolve_fz_allowed,
    row_field_text,
)
from .pipe_catalog import pipeline_display_name
from .pipe_type_filter import FZ_PIPE_CODE
from .rule_apply import apply_rule_value
from .sql_ident import ident_name, quote_ident, quote_qualified, strip_ident_quotes
from .well_number import (
    WellNumberAllocator,
    mapping_uses_wellno,
    normalize_well_key,
)
from .xyz_mapping import is_xyz_rule, mapping_xyz_fields

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None


def _strip_ident(name):
    return strip_ident_quotes(name)


def _qualified_table(schema, table):
    return quote_qualified(schema, table)


def _split_schema_table(schema, table):
    schema = _strip_ident(schema) or "public"
    table = _strip_ident(table)
    if "." in table:
        left, right = table.split(".", 1)
        if _strip_ident(left) and _strip_ident(right):
            return _strip_ident(left), _strip_ident(right)
    return schema or "public", table


def _geom_udt(schemas, kind, geom_col):
    snap = (schemas or {}).get(kind) or {}
    target = (geom_col or "").strip().lower()
    for col in snap.get("columns") or []:
        if (col.get("name") or "").strip().lower() == target:
            return (col.get("udt_name") or "").strip().lower()
    return "geometry"


def _wellno_options(rule, target):
    kind = (rule or {}).get("kind") or ""
    rid = (rule or {}).get("id") or ""
    if kind == "wellno" or rid == "wellno" or target in ("assign", "follow"):
        mode = target if target in ("assign", "follow") else "assign"
        return mode, rule or {}
    return "", None


def _configured_mdb_type_field(render_group, kind):
    cfg = (render_group or {}).get("point" if kind == "point" else "line") or {}
    return (cfg.get("type_field") or "").strip()


def _ensure_mdb_type_field(src_table, profile, kind_label, pipe_code, render_group):
    """源表缺少管类字段时停止整次入库，不跳过、不部分写入。"""
    configured = _configured_mdb_type_field(render_group, profile.geom_kind)
    if profile.type_field:
        return
    if pipe_code != FZ_PIPE_CODE and not configured:
        return
    name = configured or "管类字段"
    raise RuntimeError(
        "%s表 %s 缺少管类字段「%s」，已停止入库。"
        % (kind_label, src_table, name)
    )


def _row_type_code(pipe_code, source_row, type_field):
    """FZ 按行内管类字段取值；其他管类用表对应管类。"""
    if pipe_code != FZ_PIPE_CODE:
        return (pipe_code or "").strip().upper()
    return normalize_type_code(row_field_text(source_row, type_field))


def _require_row_type_code(pipe_code, source_row, type_field, src_table, kind_label, index):
    code = _row_type_code(pipe_code, source_row, type_field)
    if pipe_code == FZ_PIPE_CODE and not code:
        raise RuntimeError(
            "%s表 %s 第 %s 条管类字段为空，已停止入库。"
            % (kind_label, src_table, index)
        )
    return code


def check_import_ready(shared_config, conn_info, structure_id, mapping_block):
    """返回错误列表；空列表表示可以入库。"""
    errors = []
    info = conn_info or PgConnectionInfo()
    if not (info.host or "").strip() or not (info.dbname or "").strip() or not (info.user or "").strip():
        errors.append("请先在「配置管理 → 数据库连接」中填写并保存 PostgreSQL 主机、数据库和用户名。")
    pg = shared_config.get_pg_config() if shared_config else {}
    point = pg.get("point") or {}
    line = pg.get("line") or {}
    if not (point.get("table") or "").strip() or not (line.get("table") or "").strip():
        errors.append("请先在「配置管理 → 数据库连接」中设置管点表和管线表名称。")
    if not mapping_has_field_rows(mapping_block):
        label = structure_id or "当前结构"
        errors.append(
            "未在「结构映射 → 导入映射」中配置「%s」的字段映射。" % label
        )
    if mapping_uses_wellno(mapping_block, shared_config):
        view = pg.get("max_expno") or {}
        if not (view.get("table") or "").strip():
            errors.append(
                "导入映射使用了井编号规则，请先在「数据库连接」中填写「管线最大井编号」视图表。"
            )
    if not errors:
        ok, msg = test_pg_connection(info)
        if not ok:
            errors.append("PostgreSQL 连接失败：%s" % msg)
    return errors


def _resolve_pg_relation(conn, schema, table):
    """按名称大小写不敏感查找表/视图/物化视图，返回实际 schema、relname。"""
    schema, table = _split_schema_table(schema, table)
    if not table:
        return "", ""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT n.nspname, c.relname
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'v', 'm', 'f', 'p')
              AND lower(c.relname) = lower(%s)
              AND lower(n.nspname) = lower(%s)
            LIMIT 1
            """,
            (table, schema),
        )
        row = cur.fetchone()
        if row:
            return row[0], row[1]
        cur.execute(
            """
            SELECT n.nspname, c.relname
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'v', 'm', 'f', 'p')
              AND lower(c.relname) = lower(%s)
              AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
            ORDER BY CASE WHEN n.nspname = 'public' THEN 0 ELSE 1 END, n.nspname
            """,
            (table,),
        )
        rows = cur.fetchall() or []
        if rows:
            return rows[0][0], rows[0][1]
        cur.execute(
            """
            SELECT n.nspname || '.' || c.relname
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'v', 'm', 'f', 'p')
              AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
              AND c.relname ILIKE %s
            ORDER BY 1
            LIMIT 8
            """,
            ("%" + table + "%",),
        )
        hints = [item[0] for item in (cur.fetchall() or [])]
    finally:
        cur.close()
    hint_text = (" 当前库中名称相近的对象：%s。" % "、".join(hints)) if hints else ""
    raise RuntimeError(
        "当前连接的数据库中找不到「%s.%s」。%s"
        "请确认配置管理里的数据库名、schema 与视图表名，以及该连接用户能访问该对象。"
        % (schema, table, hint_text)
    )


def _resolve_pg_columns(conn, schema, table, wanted):
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT a.attname
            FROM pg_catalog.pg_attribute a
            JOIN pg_catalog.pg_class c ON a.attrelid = c.oid
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND c.relname = %s
              AND a.attnum > 0 AND NOT a.attisdropped
            ORDER BY a.attnum
            """,
            (schema, table),
        )
        names = [row[0] for row in (cur.fetchall() or [])]
    finally:
        cur.close()
    lower_map = {(item or "").lower(): item for item in names}
    resolved = []
    missing = []
    for item in wanted:
        key = (item or "").strip().lower()
        actual = lower_map.get(key)
        if actual:
            resolved.append(actual)
        else:
            missing.append(item)
    if missing:
        raise RuntimeError(
            "视图表 %s.%s 中找不到字段：%s。现有字段：%s"
            % (schema, table, "、".join(missing), "、".join(names) or "（无）")
        )
    return resolved


def fetch_view_pipe_type_codes(conn, schema, table, ptype_field="ptype"):
    """从管线最大井编号视图读取 DISTINCT ptype，供总数据库管类占用。"""
    schema, table = _split_schema_table(schema, table)
    if not table:
        raise RuntimeError("未配置「管线最大井编号」视图表。")
    real_schema, real_table = _resolve_pg_relation(conn, schema, table)
    ptype_col, = _resolve_pg_columns(
        conn, real_schema, real_table,
        [ptype_field or "ptype"],
    )
    sql = "SELECT DISTINCT %s AS ptype FROM %s WHERE %s IS NOT NULL" % (
        quote_ident(ptype_col),
        _qualified_table(real_schema, real_table),
        quote_ident(ptype_col),
    )
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute(sql)
        rows = cur.fetchall()
    except Exception as exc:
        raise RuntimeError(
            "读取管线最大井编号视图表 %s.%s 的管类失败：%s"
            % (real_schema, real_table, exc)
        )
    finally:
        cur.close()
    codes = []
    for row in rows or []:
        ptype = (row.get("ptype") or "").strip().upper()
        if ptype:
            codes.append(ptype)
    return codes


def fetch_max_expno_map(conn, schema, table, ptype_field="ptype", max_field="max_expno"):
    schema, table = _split_schema_table(schema, table)
    if not table:
        raise RuntimeError("未配置「管线最大井编号」视图表。")
    real_schema, real_table = _resolve_pg_relation(conn, schema, table)
    ptype_col, max_col = _resolve_pg_columns(
        conn, real_schema, real_table,
        [ptype_field or "ptype", max_field or "max_expno"],
    )
    sql = "SELECT %s AS ptype, %s AS max_expno FROM %s" % (
        quote_ident(ptype_col),
        quote_ident(max_col),
        _qualified_table(real_schema, real_table),
    )
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute(sql)
        rows = cur.fetchall()
    except Exception as exc:
        raise RuntimeError(
            "读取管线最大井编号视图表 %s.%s 失败：%s"
            % (real_schema, real_table, exc)
        )
    finally:
        cur.close()
    result = {}
    for row in rows or []:
        ptype = (row.get("ptype") or "").strip().upper()
        if ptype:
            result[ptype] = row.get("max_expno")
    return result


def _map_attributes(source_row, mapping_rows, shared_config, row_seq, allocator, pipe_code):
    values = {}
    for item in mapping_rows:
        raw = _row_get(source_row, item.get("src_field"))
        rule_set = item.get("rule_set") or ""
        rule_target = item.get("rule_target") or ""
        dst = ident_name(item.get("dst_field"))
        if not dst:
            continue
        rule = None
        if shared_config is not None and hasattr(shared_config, "get_rule_set"):
            rule = shared_config.get_rule_set(rule_set)
        mode, well_rule = _wellno_options(rule, rule_target)
        if mode and allocator is not None:
            if mode == "assign":
                values[dst] = allocator.assign(pipe_code, raw)
            else:
                values[dst] = allocator.follow(pipe_code, raw)
            continue
        if is_xyz_rule(rule_set, rule_target, shared_config):
            continue
        values[dst] = apply_rule_value(
            raw, rule_set, rule_target, shared_config, row_seq=row_seq
        )
    return values


INSERT_BATCH_SIZE = 5000


class ImportStopped(Exception):
    """用户点击「停止导入」。"""


def _import_cancelled(progress_dialog):
    return progress_dialog is not None and progress_dialog.was_cancelled()


def _check_import_stop(progress_dialog):
    if _import_cancelled(progress_dialog):
        raise ImportStopped()


def _progress_begin(progress_dialog, step, pipe_idx, pipe_total, pipe_code, detail):
    if progress_dialog is None:
        return
    progress_dialog.begin_pipe(
        step,
        pipeline_display_name(pipe_code),
        detail,
        display_index=pipe_idx,
        display_total=pipe_total,
    )


def _progress_finish(progress_dialog, step, pipe_idx, pipe_total, pipe_code):
    if progress_dialog is None:
        return
    progress_dialog.finish_pipe(
        step,
        pipeline_display_name(pipe_code),
        display_index=pipe_idx,
        display_total=pipe_total,
    )


def _wkt_from_geom(geom):
    if geom is None or geom.isEmpty():
        return None
    return geom.asWkt()


def _insert_batch(cur, qualified, rows, geom_col, srid, geom_udt):
    """同一事务内按批写入；rows 为空则忽略。"""
    if not rows:
        return
    geom_name = ident_name(geom_col)
    columns = []
    seen = set()
    geom_key = ""
    for row in rows:
        for name in row.keys():
            key = ident_name(name)
            if not key or key in seen:
                continue
            seen.add(key)
            columns.append(name)
            if geom_name and key.lower() == geom_name.lower():
                geom_key = name
    if not columns:
        return
    placeholders = []
    for name in columns:
        if geom_key and name == geom_key:
            if geom_udt == "geography":
                placeholders.append("geography(ST_Force3DZ(ST_GeomFromText(%s)))")
            else:
                placeholders.append(
                    "ST_SetSRID(ST_Force3DZ(ST_GeomFromText(%%s)), %d)" % int(srid or 0)
                )
        else:
            placeholders.append("%s")
    template = "(" + ", ".join(placeholders) + ")"
    sql = "INSERT INTO %s (%s) VALUES %%s" % (
        qualified,
        ", ".join(quote_ident(c) for c in columns),
    )
    tuples = [tuple(row.get(c) for c in columns) for row in rows]
    psycopg2.extras.execute_values(
        cur, sql, tuples, template=template, page_size=len(tuples)
    )


def _flush_insert_buffer(cur, qualified, buffer, geom_col, srid, geom_udt):
    if not buffer:
        return
    _insert_batch(cur, qualified, buffer, geom_col, srid, geom_udt)
    del buffer[:]


def import_mdb_to_pg(mdb_path, pipe_codes, structure_id, shared_config, conn_info,
                     swap_xy=True, load_all_fz=False, log=None, progress_dialog=None):
    if psycopg2 is None:
        raise RuntimeError(
            "未找到 psycopg2 模块，请在 QGIS 的 Python 环境安装：\n"
            "python3 -m pip install psycopg2-binary"
        )
    pipe_codes = [c for c in (pipe_codes or []) if c]
    if not pipe_codes:
        raise RuntimeError("请至少勾选一个管类后再入库。")
    fz_allowed, base_types, include_fz = resolve_fz_allowed(
        pipe_codes, load_all_fz=load_all_fz, action="入库"
    )

    def _log(msg):
        if log:
            log(msg)

    mapping_block = shared_config.get_mapping_block("import", structure_id)
    errors = check_import_ready(shared_config, conn_info, structure_id, mapping_block)
    if errors:
        raise RuntimeError("\n".join(errors))

    pg = shared_config.get_pg_config()
    schemas = shared_config.get_pg_table_schemas()
    render_groups = shared_config.get_mdb_render_groups()
    render_group = _group_by_id(render_groups, structure_id)
    structure = shared_config.get_mdb_structure(structure_id) or {}
    point_mapping = _kind_mapping_rows(mapping_block, "point")
    line_mapping = _kind_mapping_rows(mapping_block, "line")
    if not point_mapping and not line_mapping:
        raise RuntimeError("导入映射没有有效的点表或线表字段。")
    xyz_point = mapping_xyz_fields(mapping_block, "point", shared_config)

    uses_wellno = mapping_uses_wellno(mapping_block, shared_config)
    well_rule = shared_config.get_rule_set("wellno") if uses_wellno else None

    point_table = _qualified_table(pg["point"].get("schema"), pg["point"].get("table"))
    line_table = _qualified_table(pg["line"].get("schema"), pg["line"].get("table"))
    point_geom = ident_name(pg["point"].get("geom_col") or "geom") or "geom"
    line_geom = ident_name(pg["line"].get("geom_col") or "geom") or "geom"
    point_type_field = ident_name(pg["point"].get("type_field") or "")
    line_type_field = ident_name(pg["line"].get("type_field") or "")
    point_gtype_field = ident_name(pg["point"].get("gtype_field") or "")
    line_gtype_field = ident_name(pg["line"].get("gtype_field") or "")
    srid = 0
    point_udt = _geom_udt(schemas, "point", point_geom)
    line_udt = _geom_udt(schemas, "line", line_geom)

    stats = {
        "structure_id": structure_id,
        "point_rows": 0,
        "line_rows": 0,
        "skipped": [],
        "wellno": uses_wellno,
        "pipes": [],
        "cancelled": False,
    }

    src_conn = None
    pg_conn = None
    try:
        src_conn = MdbConnection(mdb_path)
        tables = src_conn.list_user_tables()
        discovered = discover_pipe_layers(tables, render_groups=render_groups)
        pg_conn = psycopg2.connect(
            host=conn_info.host,
            port=conn_info.port,
            dbname=conn_info.dbname,
            user=conn_info.user,
            password=conn_info.password,
        )
        pg_conn.autocommit = False
        pg_cur = pg_conn.cursor()

        allocator = None
        if uses_wellno:
            view = pg.get("max_expno") or {}
            max_map = fetch_max_expno_map(
                pg_conn,
                view.get("schema") or "public",
                view.get("table"),
                view.get("ptype_field") or "ptype",
                view.get("max_field") or "max_expno",
            )
            allocator = WellNumberAllocator(max_map, rule=well_rule)

        if include_fz:
            if load_all_fz:
                _log("[FZ] 已全选可用管类，辅助数据全部入库")
            else:
                _log(
                    "[FZ] 辅助数据按勾选管类筛选入库：%s"
                    % "、".join(pipeline_display_name(c) for c in base_types)
                )

        point_cache = {}
        pipe_total = max(1, len(pipe_codes))
        for idx, pipe_code in enumerate(pipe_codes, start=1):
            _check_import_stop(progress_dialog)
            if progress_dialog is not None:
                progress_dialog.set_status(
                    "正在导入 [%s/%s] %s — 读取点表"
                    % (idx, pipe_total, pipeline_display_name(pipe_code))
                )
            src_table = resolve_existing_table(
                tables,
                _source_table_candidates(
                    pipe_code, "point", structure, render_group, discovered
                ),
            )
            if not src_table:
                _log("%s 点表不存在，未入库" % pipeline_display_name(pipe_code))
                continue
            columns, rows = src_conn.read_all_rows(src_table)
            profile = TableProfile(src_table, "point", columns, render_group=render_group)
            _ensure_mdb_type_field(
                src_table, profile, "点", pipe_code, render_group
            )
            raw_count = len(rows or [])
            rows = apply_fz_row_filter(
                pipe_code, rows, profile.type_field, fz_allowed, "点", _log
            )
            if not rows:
                if raw_count == 0:
                    _log("%s 点表无数据，未入库" % pipeline_display_name(pipe_code))
                continue
            x_field = xyz_point.get("x") or profile.x_field
            y_field = xyz_point.get("y") or profile.y_field
            z_field = xyz_point.get("z") or ""
            lookup = build_point_lookup(
                rows, profile.pk_field, x_field, y_field,
                z_field=z_field, with_z=True, swap_xy=swap_xy,
            )
            point_cache[pipe_code] = {
                "src_table": src_table,
                "rows": rows,
                "profile": profile,
                "lookup": lookup,
                "x_field": x_field,
                "y_field": y_field,
                "z_field": z_field,
            }

        if allocator is not None:
            for pipe_code, cached in point_cache.items():
                for item in point_mapping:
                    rule = None
                    if hasattr(shared_config, "get_rule_set"):
                        rule = shared_config.get_rule_set(item.get("rule_set"))
                    mode, _well_rule = _wellno_options(
                        rule, item.get("rule_target") or ""
                    )
                    if mode != "assign":
                        continue
                    type_field = cached["profile"].type_field
                    src_table = cached.get("src_table") or pipe_code
                    for index, source_row in enumerate(cached["rows"], start=1):
                        if index == 1 or index % 25 == 0:
                            _check_import_stop(progress_dialog)
                        raw = _row_get(source_row, item.get("src_field"))
                        if not normalize_well_key(raw):
                            continue
                        well_code = _require_row_type_code(
                            pipe_code, source_row, type_field,
                            src_table, "点", index,
                        )
                        allocator.assign(well_code, raw)

        point_buffer = []
        for idx, pipe_code in enumerate(pipe_codes, start=1):
            _check_import_stop(progress_dialog)
            cached = point_cache.get(pipe_code)
            if not cached or not point_mapping:
                _progress_finish(progress_dialog, idx, idx, pipe_total, pipe_code)
                continue
            count = 0
            type_field = cached["profile"].type_field
            src_table = cached.get("src_table") or pipe_code
            _progress_begin(
                progress_dialog, idx, idx, pipe_total, pipe_code,
                "写入管点 (%s 条)" % len(cached["rows"] or []),
            )
            for index, source_row in enumerate(cached["rows"], start=1):
                if index == 1 or index % 25 == 0:
                    _check_import_stop(progress_dialog)
                well_code = _require_row_type_code(
                    pipe_code, source_row, type_field, src_table, "点", index
                )
                mapped = _map_attributes(
                    source_row, point_mapping, shared_config, index, allocator, well_code
                )
                mapped = apply_source_field_decimals(
                    mapped, point_mapping, structure, pipe_code, "point"
                )
                if point_type_field and point_type_field not in mapped:
                    mapped[point_type_field] = well_code
                if (
                    pipe_code == FZ_PIPE_CODE
                    and point_gtype_field
                    and point_gtype_field not in mapped
                ):
                    mapped[point_gtype_field] = FZ_PIPE_CODE
                geom = point_geometry_from_row(
                    cached.get("x_field") or cached["profile"].x_field,
                    cached.get("y_field") or cached["profile"].y_field,
                    source_row,
                    z_field=cached.get("z_field") or "",
                    with_z=True,
                    swap_xy=swap_xy,
                )
                wkt = _wkt_from_geom(geom)
                if wkt:
                    mapped[point_geom] = wkt
                elif point_geom not in mapped:
                    stats["skipped"].append(
                        "%s 点表第 %s 条无坐标，已跳过" % (
                            pipeline_display_name(pipe_code), index
                        )
                    )
                    continue
                point_buffer.append(mapped)
                count += 1
                if len(point_buffer) >= INSERT_BATCH_SIZE:
                    _check_import_stop(progress_dialog)
                    _flush_insert_buffer(
                        pg_cur, point_table, point_buffer,
                        point_geom, srid, point_udt,
                    )
            stats["point_rows"] += count
            stats["pipes"].append({"pipe": pipe_code, "kind": "point", "rows": count})
            _progress_finish(progress_dialog, idx, idx, pipe_total, pipe_code)
        _check_import_stop(progress_dialog)
        _flush_insert_buffer(
            pg_cur, point_table, point_buffer, point_geom, srid, point_udt
        )

        line_buffer = []
        for idx, pipe_code in enumerate(pipe_codes, start=1):
            _check_import_stop(progress_dialog)
            if not line_mapping:
                _progress_finish(
                    progress_dialog, pipe_total + idx, idx, pipe_total, pipe_code
                )
                continue
            src_table = resolve_existing_table(
                tables,
                _source_table_candidates(
                    pipe_code, "line", structure, render_group, discovered
                ),
            )
            if not src_table:
                _log("%s 线表不存在，未入库" % pipeline_display_name(pipe_code))
                _progress_finish(
                    progress_dialog, pipe_total + idx, idx, pipe_total, pipe_code
                )
                continue
            columns, rows = src_conn.read_all_rows(src_table)
            profile = TableProfile(src_table, "line", columns, render_group=render_group)
            _ensure_mdb_type_field(
                src_table, profile, "线", pipe_code, render_group
            )
            lookup = (point_cache.get(pipe_code) or {}).get("lookup") or {}
            if not lookup:
                _log("%s 无线点对照，线表未入库" % pipeline_display_name(pipe_code))
                _progress_finish(
                    progress_dialog, pipe_total + idx, idx, pipe_total, pipe_code
                )
                continue
            raw_count = len(rows or [])
            rows = apply_fz_row_filter(
                pipe_code, rows, profile.type_field, fz_allowed, "线", _log
            )
            if not rows:
                if raw_count == 0:
                    _log("%s 线表无数据，未入库" % pipeline_display_name(pipe_code))
                _progress_finish(
                    progress_dialog, pipe_total + idx, idx, pipe_total, pipe_code
                )
                continue
            count = 0
            _progress_begin(
                progress_dialog, pipe_total + idx, idx, pipe_total, pipe_code,
                "写入管线 (%s 条)" % len(rows),
            )
            for index, source_row in enumerate(rows, start=1):
                if index == 1 or index % 25 == 0:
                    _check_import_stop(progress_dialog)
                well_code = _require_row_type_code(
                    pipe_code, source_row, profile.type_field,
                    src_table, "线", index,
                )
                mapped = _map_attributes(
                    source_row, line_mapping, shared_config, index, allocator, well_code
                )
                mapped = apply_source_field_decimals(
                    mapped, line_mapping, structure, pipe_code, "line"
                )
                if line_type_field and line_type_field not in mapped:
                    mapped[line_type_field] = well_code
                if (
                    pipe_code == FZ_PIPE_CODE
                    and line_gtype_field
                    and line_gtype_field not in mapped
                ):
                    mapped[line_gtype_field] = FZ_PIPE_CODE
                geom = line_geometry_from_row(
                    profile.start_field, profile.end_field, source_row, lookup
                )
                wkt = _wkt_from_geom(geom)
                if wkt:
                    mapped[line_geom] = wkt
                elif line_geom not in mapped:
                    stats["skipped"].append(
                        "%s 线表第 %s 条无法构建几何，已跳过" % (
                            pipeline_display_name(pipe_code), index
                        )
                    )
                    continue
                line_buffer.append(mapped)
                count += 1
                if len(line_buffer) >= INSERT_BATCH_SIZE:
                    _check_import_stop(progress_dialog)
                    _flush_insert_buffer(
                        pg_cur, line_table, line_buffer,
                        line_geom, srid, line_udt,
                    )
            stats["line_rows"] += count
            stats["pipes"].append({"pipe": pipe_code, "kind": "line", "rows": count})
            _progress_finish(
                progress_dialog, pipe_total + idx, idx, pipe_total, pipe_code
            )
        _check_import_stop(progress_dialog)
        _flush_insert_buffer(
            pg_cur, line_table, line_buffer, line_geom, srid, line_udt
        )

        if stats["point_rows"] == 0 and stats["line_rows"] == 0:
            pg_conn.rollback()
            raise RuntimeError("没有写入任何管点或管线，请检查导入映射与源表数据。")
        if progress_dialog is not None:
            progress_dialog.set_finalizing()
        _check_import_stop(progress_dialog)
        pg_conn.commit()
        return stats
    except ImportStopped:
        if pg_conn is not None:
            try:
                pg_conn.rollback()
            except Exception:
                pass
        _log("入库已由用户停止，事务已回滚，未写入 PostgreSQL")
        stats["cancelled"] = True
        stats["point_rows"] = 0
        stats["line_rows"] = 0
        stats["pipes"] = []
        return stats
    except Exception:
        if pg_conn is not None:
            try:
                pg_conn.rollback()
            except Exception:
                pass
        raise
    finally:
        if src_conn is not None:
            src_conn.close()
        if pg_conn is not None:
            pg_conn.close()
