# -*- coding: utf-8 -*-
"""管类代码与显示名（界面占位数据）。"""

PIPELINE_TYPES = [
    "JS", "XS", "TS", "ZS", "YS", "WS", "HS", "MQ", "TR", "YH",
    "GY", "SY", "ZQ", "RS", "GD", "LD", "XH", "DX", "LT", "YD",
    "TT", "EX", "RX", "WT", "CX", "KX", "JY", "BX", "DS", "GB",
    "ZH", "BM", "FZ",
]

PIPELINE_TYPE_LABELS = {
    "JS": "给水",
    "XS": "原水",
    "TS": "退水",
    "ZS": "中水",
    "YS": "雨水",
    "WS": "污水",
    "HS": "雨污合流",
    "MQ": "煤气",
    "TR": "天然气",
    "YH": "液化气",
    "GY": "工业",
    "SY": "石油",
    "ZQ": "蒸汽",
    "RS": "热水",
    "GD": "供电",
    "LD": "路灯",
    "XH": "交通信号",
    "DX": "中国电信",
    "LT": "中国联通",
    "YD": "中国移动",
    "TT": "中国铁通",
    "EX": "电力通讯",
    "RX": "热力通讯",
    "WT": "中国网通",
    "CX": "长途传输局",
    "KX": "监控信号",
    "JY": "军用光缆",
    "BX": "保密及专用通讯",
    "DS": "有线电视",
    "GB": "广播",
    "ZH": "综合管沟/廊",
    "BM": "不明",
    "FZ": "辅助",
}


def pipeline_display_name(code):
    label = PIPELINE_TYPE_LABELS.get(code, "")
    if label:
        return f"{code} ({label})"
    return code
