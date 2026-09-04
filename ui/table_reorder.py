# -*- coding: utf-8 -*-
"""配置表格行顺序：上移 / 下移 / 移到指定行 / 拖动行号。"""

from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QInputDialog, QMessageBox, QPushButton,
)


def install_row_reorder(table):
    """
    为表格启用行号拖动排序。
    表格需实现 snapshot_rows() / restore_rows(rows)。
    """
    if getattr(table, "_reorder_header_hooked", False):
        return
    table._reorder_header_hooked = True
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    header = table.verticalHeader()
    header.setVisible(True)
    header.setSectionsMovable(True)
    header.setToolTip("拖动行号可调整顺序")
    header.sectionMoved.connect(
        lambda _logical, old, new, t=table: _on_header_moved(t, old, new)
    )


def add_row_reorder_buttons(parent, layout, table):
    up_btn = QPushButton("上移")
    down_btn = QPushButton("下移")
    jump_btn = QPushButton("移到...")
    up_btn.setToolTip("将选中行向上移动一行")
    down_btn.setToolTip("将选中行向下移动一行")
    jump_btn.setToolTip("将选中行移到指定行号，例如从第 7 行移到第 2 行")
    up_btn.clicked.connect(lambda: move_selected(table, -1))
    down_btn.clicked.connect(lambda: move_selected(table, 1))
    jump_btn.clicked.connect(lambda: prompt_move_to(parent, table))
    layout.addWidget(up_btn)
    layout.addWidget(down_btn)
    layout.addWidget(jump_btn)


def current_row(table):
    row = table.currentRow()
    if row >= 0:
        return row
    selected = sorted({idx.row() for idx in table.selectedIndexes()})
    return selected[0] if selected else -1


def move_selected(table, delta):
    src = current_row(table)
    if src < 0:
        return
    dest = src + delta
    if dest < 0 or dest >= table.rowCount():
        return
    _move_row(table, src, dest)


def prompt_move_to(parent, table):
    src = current_row(table)
    if src < 0 or table.rowCount() <= 0:
        QMessageBox.warning(parent, "提示", "请先选中要移动的行。")
        return
    dest, ok = QInputDialog.getInt(
        parent,
        "移动行",
        "将第 %d 行移到第几行：" % (src + 1),
        src + 1,
        1,
        table.rowCount(),
    )
    if not ok:
        return
    _move_row(table, src, dest - 1)


def _on_header_moved(table, old_visual, new_visual):
    if getattr(table, "_reordering", False):
        return
    if old_visual == new_visual:
        return
    _move_row(table, old_visual, new_visual)


def _move_row(table, src, dest):
    if src == dest:
        return
    if not hasattr(table, "snapshot_rows") or not hasattr(table, "restore_rows"):
        return
    data = table.snapshot_rows()
    if src < 0 or dest < 0 or src >= len(data) or dest >= len(data):
        return
    table._reordering = True
    header = table.verticalHeader()
    header.blockSignals(True)
    try:
        item = data.pop(src)
        data.insert(dest, item)
        table.restore_rows(data)
        table.selectRow(dest)
        table.setCurrentCell(dest, 0)
    finally:
        header.blockSignals(False)
        table._reordering = False
