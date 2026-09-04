# -*- coding: utf-8 -*-
"""PostgreSQL 连接信息（本插件独立 QSettings，首次可从导出插件迁移）。"""

from qgis.PyQt.QtCore import QSettings

SETTINGS_GROUP = "PipelineEditingPlugin/pg_connection"
LEGACY_SETTINGS_GROUP = "PipeExportPlugin/pg_connection"


class PgConnectionInfo:
    def __init__(self, host="", port=5432, dbname="", user="", password=""):
        self.host = host
        self.port = int(port or 5432)
        self.dbname = dbname
        self.user = user
        self.password = password


def _profile_key(group, mode_id, field):
    return f"{group}/profiles/{mode_id}/{field}"


def _read_info(group, mode_id):
    s = QSettings()
    return PgConnectionInfo(
        host=s.value(_profile_key(group, mode_id, "host"), ""),
        port=int(s.value(_profile_key(group, mode_id, "port"), 5432) or 5432),
        dbname=s.value(_profile_key(group, mode_id, "dbname"), ""),
        user=s.value(_profile_key(group, mode_id, "user"), ""),
        password=s.value(_profile_key(group, mode_id, "password"), ""),
    )


def _has_connection_data(info):
    return bool((info.host or "").strip() or (info.dbname or "").strip())


def _migrate_from_legacy_if_needed(mode_id):
    """本插件尚无连接配置时，一次性从导出插件 QSettings 复制。"""
    own = _read_info(SETTINGS_GROUP, mode_id)
    if _has_connection_data(own):
        return own
    legacy = _read_info(LEGACY_SETTINGS_GROUP, mode_id)
    if not _has_connection_data(legacy):
        # 兼容默认空 host 时仍尝试 default 模式
        if mode_id != "default":
            legacy = _read_info(LEGACY_SETTINGS_GROUP, "default")
        if not _has_connection_data(legacy):
            return PgConnectionInfo(host="localhost", port=5432)
    save_connection_info(legacy, mode_id=mode_id)
    return legacy


def load_connection_info(mode_id=None):
    s = QSettings()
    if mode_id is None:
        mode_id = s.value(f"{SETTINGS_GROUP}/last_mode", None)
        if not mode_id:
            mode_id = s.value(f"{LEGACY_SETTINGS_GROUP}/last_mode", "default")
    info = _migrate_from_legacy_if_needed(mode_id)
    if not _has_connection_data(info) and not (info.host or "").strip():
        info.host = "localhost"
    return info, mode_id


def save_connection_info(info, mode_id="default"):
    s = QSettings()
    s.setValue(_profile_key(SETTINGS_GROUP, mode_id, "host"), info.host)
    s.setValue(_profile_key(SETTINGS_GROUP, mode_id, "port"), info.port)
    s.setValue(_profile_key(SETTINGS_GROUP, mode_id, "dbname"), info.dbname)
    s.setValue(_profile_key(SETTINGS_GROUP, mode_id, "user"), info.user)
    s.setValue(_profile_key(SETTINGS_GROUP, mode_id, "password"), info.password)
    s.setValue(f"{SETTINGS_GROUP}/last_mode", mode_id)
    s.sync()


def test_pg_connection(info):
    try:
        import psycopg2
    except ImportError:
        return False, (
            "未找到 psycopg2 模块，请在 QGIS 的 Python 环境安装：\n"
            "python3 -m pip install psycopg2-binary"
        )
    try:
        conn = psycopg2.connect(
            host=info.host,
            port=info.port,
            dbname=info.dbname,
            user=info.user,
            password=info.password,
        )
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        return True, "连接成功"
    except Exception as exc:
        return False, str(exc)
