# -*- coding: utf-8 -*-


def classFactory(iface):
    from .pipeline_editing_plugin import PipelineEditingPlugin
    return PipelineEditingPlugin(iface)
