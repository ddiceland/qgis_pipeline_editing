# -*- coding: utf-8 -*-
"""表格单元格平时显示文字，点击后再弹出下拉。"""

from qgis.PyQt.QtCore import Qt, QTimer, QRect
from qgis.PyQt.QtGui import QPainter, QPen, QPalette
from qgis.PyQt.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QComboBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOption,
    QStyleOptionViewItem,
    QTableWidgetItem,
)


def enable_click_edit(table):
    table.setEditTriggers(
        QAbstractItemView.DoubleClicked
        | QAbstractItemView.EditKeyPressed
        | QAbstractItemView.AnyKeyPressed
        | QAbstractItemView.SelectedClicked
    )


def set_choice_item(table, row, column, label, data=""):
    item = QTableWidgetItem(label or "")
    item.setData(Qt.UserRole, "" if data is None else data)
    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
    table.setItem(row, column, item)


def choice_item_data(table, row, column):
    item = table.item(row, column)
    if item is None:
        return ""
    data = item.data(Qt.UserRole)
    return "" if data is None else data


class PopupComboDelegate(QStyledItemDelegate):
    """平时画成与 QGIS 下拉框接近的扁平选择框，点击后再弹出。"""

    def __init__(self, parent=None, choices=None, choice_provider=None):
        super().__init__(parent)
        self._choices = list(choices or [])
        self._choice_provider = choice_provider

    def _choices_for(self, index):
        if self._choice_provider is not None:
            return list(self._choice_provider(index) or [])
        return list(self._choices)

    def paint(self, painter, option, index):
        widget = option.widget
        style = widget.style() if widget is not None else QApplication.style()
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        bg_opt = QStyleOptionViewItem(opt)
        bg_opt.text = ""
        style.drawControl(QStyle.CE_ItemViewItem, bg_opt, painter, widget)

        palette = opt.palette
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        box = option.rect.adjusted(2, 2, -2, -2)

        # 与主面板 titledOptionBox 一致：窗口灰底 + palette(mid) 细边，不单独铺白底。
        fill = palette.color(QPalette.Window)
        border = palette.color(QPalette.Mid)
        if fill.lightness() > 245:
            fill = fill.darker(103)
        if hovered and not selected:
            fill = fill.darker(104)
        text_color = palette.color(
            QPalette.HighlightedText if selected else QPalette.WindowText
        )

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(border, 1))
        if selected:
            painter.setBrush(Qt.NoBrush)
        else:
            painter.setBrush(fill)
        painter.drawRoundedRect(box.adjusted(0, 0, -1, -1), 3, 3)

        arrow_w = 14
        text_rect = box.adjusted(6, 0, -arrow_w, 0)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setPen(text_color)
        painter.drawText(
            text_rect,
            int(Qt.AlignVCenter | Qt.AlignLeft),
            str(index.data(Qt.DisplayRole) or ""),
        )

        arrow_opt = QStyleOption()
        if widget is not None:
            arrow_opt.initFrom(widget)
        arrow_opt.rect = QRect(box.right() - arrow_w, box.top(), arrow_w, box.height())
        arrow_opt.palette = palette
        arrow_opt.state = QStyle.State_Enabled
        if selected:
            arrow_opt.palette.setColor(QPalette.WindowText, text_color)
            arrow_opt.palette.setColor(QPalette.ButtonText, text_color)
        style.drawPrimitive(QStyle.PE_IndicatorArrowDown, arrow_opt, painter, widget)
        painter.restore()

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        for label, data in self._choices_for(index):
            combo.addItem(label, data)
        combo.activated.connect(lambda *_args: self._commit_and_close(combo))
        QTimer.singleShot(0, combo.showPopup)
        return combo

    def _commit_and_close(self, editor):
        self.commitData.emit(editor)
        self.closeEditor.emit(editor, QAbstractItemDelegate.NoHint)

    def setEditorData(self, editor, index):
        data = index.data(Qt.UserRole)
        idx = -1
        if data is not None and data != "":
            idx = editor.findData(data)
        if idx < 0:
            text = index.data(Qt.EditRole) or index.data(Qt.DisplayRole) or ""
            idx = editor.findText(str(text))
        editor.blockSignals(True)
        editor.setCurrentIndex(idx if idx >= 0 else 0)
        editor.blockSignals(False)

    def setModelData(self, editor, model, index):
        label = editor.currentText()
        data = editor.currentData()
        if data is None:
            data = label
        model.setData(index, label, Qt.EditRole)
        model.setData(index, label, Qt.DisplayRole)
        model.setData(index, data, Qt.UserRole)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect.adjusted(2, 2, -2, -2))
