# -*- coding: utf-8 -*-
"""各管类默认显示颜色（与导出插件一致）。"""

_PRESET = {
    "JS": "#0066CC",
    "XS": "#00AAFF",
    "YS": "#FF6600",
    "WS": "#8B4513",
    "HS": "#9932CC",
    "MQ": "#FF1493",
    "TR": "#FFD700",
    "GD": "#FF0000",
    "LD": "#9400D3",
    "DX": "#00CED1",
    "LT": "#32CD32",
    "YD": "#FFA500",
    "ZH": "#696969",
    "FZ": "#2F4F4F",
}

_EXTRA = [
    "#E6194B", "#3CB44B", "#4363D8", "#F58231", "#911EB4",
    "#42D4F4", "#F032E6", "#BFEF45", "#FABED4", "#469990",
    "#DCBEFF", "#9A6324", "#800000", "#AAFFC3", "#808000",
    "#FFD8B1", "#000075", "#A9A9A9",
]


def build_default_pipe_colors(pipeline_types):
    colors = {}
    extra_idx = 0
    for code in pipeline_types:
        if code in _PRESET:
            colors[code] = _PRESET[code]
        else:
            colors[code] = _EXTRA[extra_idx % len(_EXTRA)]
            extra_idx += 1
    return colors
