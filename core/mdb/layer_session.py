# -*- coding: utf-8 -*-
"""跟踪 MDB 图层与原始数据，用于保存时对比变更。"""

from .value_utils import attrs_to_python

INTERNAL_PIPE_FIELD = "_mdb_pipe"


class LayerSession:
    """一个合并图层（MDB管点或 MDB管线）对应多张管类表。"""

    def __init__(self, mdb_path, geom_kind, columns, display_type_field=""):
        self.mdb_path = mdb_path
        self.pipe_code = None
        self.geom_kind = geom_kind
        self.profile = None
        self.columns = list(columns)
        self.display_type_field = (display_type_field or "").strip()
        self.profiles = {}
        self.table_columns = {}
        self.feature_pk = {}
        self.feature_pipe = {}
        self.original_attrs = {}
        self.original_geom_wkt = {}
        self.qgis_layer = None
        self.deleted_pks = []

    def register_feature(self, qgis_fid, pk_value, attrs, geom_wkt, pipe_code):
        from .value_utils import to_python_value
        self.feature_pk[qgis_fid] = to_python_value(pk_value)
        self.feature_pipe[qgis_fid] = (pipe_code or "").strip().upper()
        self.original_attrs[qgis_fid] = attrs_to_python(attrs)
        self.original_geom_wkt[qgis_fid] = geom_wkt

    def register_identity(self, qgis_fid, pk_value, pipe_code, feature=None):
        """加载时把 Access 主键和管类绑到图层 fid，并记下当时的属性/几何快照。"""
        from .value_utils import to_python_value, feature_attrs_to_python
        self.feature_pk[qgis_fid] = to_python_value(pk_value)
        self.feature_pipe[qgis_fid] = (pipe_code or "").strip().upper()
        if feature is None:
            return
        self.original_attrs[qgis_fid] = feature_attrs_to_python(feature, self.columns)
        geom = feature.geometry()
        if geom is not None and not geom.isEmpty():
            self.original_geom_wkt[qgis_fid] = geom.asWkt()
        else:
            self.original_geom_wkt[qgis_fid] = ""

    def is_new_feature(self, qgis_fid):
        return qgis_fid not in self.feature_pk

    def pipe_for(self, qgis_fid):
        return (self.feature_pipe.get(qgis_fid) or "").strip().upper()

    def profile_for(self, pipe_code):
        return self.profiles.get((pipe_code or "").strip().upper())

    def table_columns_for(self, pipe_code):
        return list(self.table_columns.get((pipe_code or "").strip().upper()) or [])

    def skip_write_fields(self):
        """着色/路由用字段，保存时不写回 MDB。"""
        names = {INTERNAL_PIPE_FIELD.upper()}
        if self.display_type_field:
            names.add(self.display_type_field.upper())
        return names


class MdbProjectSession:
    def __init__(self, mdb_path, swap_xy=True):
        self.mdb_path = mdb_path
        self.layer_sessions = {}
        self.point_profiles = {}
        self.loaded_pipe_codes = []
        self.swap_xy = bool(swap_xy)
        self.render_group_id = None
        self.render_group_label = ""
        self.mdb_structure = None

    def add_layer_session(self, layer_id, session):
        self.layer_sessions[layer_id] = session
        if session.geom_kind == "point":
            self.point_profiles.update(session.profiles)

    def get_layer_session(self, layer):
        return self.layer_sessions.get(layer.id())

    def get_layer_session_by_id(self, layer_id):
        return self.layer_sessions.get(layer_id)

    def remove_layer(self, layer_id):
        self.layer_sessions.pop(layer_id, None)

    def layer_session_by_kind(self, geom_kind):
        for session in self.layer_sessions.values():
            if session.geom_kind == geom_kind:
                return session
        return None
