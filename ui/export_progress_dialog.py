# -*- coding: utf-8 -*-
"""总库导出进度对话框。"""

import time

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QApplication,
)


def _format_duration(seconds):
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "%s 秒" % seconds
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return "%s 分 %s 秒" % (minutes, secs)
    hours, minutes = divmod(minutes, 60)
    return "%s 小时 %s 分" % (hours, minutes)


class ExportProgressDialog(QDialog):
    """导出 / 导入进度：当前管类、百分比、预计剩余时间，可停止。"""

    def __init__(self, total_steps, parent=None, verb="导出"):
        super().__init__(parent)
        self._verb = (verb or "导出").strip() or "导出"
        self.setWindowTitle("正在%s..." % self._verb)
        self.setWindowModality(Qt.WindowModal)
        self.setMinimumWidth(420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._total = max(1, int(total_steps or 1))
        self._start_time = time.time()
        self._completed = 0
        self._cancelled = False
        self._allow_close = False

        layout = QVBoxLayout(self)

        self.status_label = QLabel("准备%s..." % self._verb)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, self._total)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        self.eta_label = QLabel("预计剩余时间：计算中...")
        layout.addWidget(self.eta_label)

        self.elapsed_label = QLabel("已用时间：0 秒")
        layout.addWidget(self.elapsed_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.stop_btn = QPushButton("停止%s" % self._verb)
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        btn_row.addWidget(self.stop_btn)
        layout.addLayout(btn_row)

        self.show()
        QApplication.processEvents()

    def was_cancelled(self):
        QApplication.processEvents()
        return self._cancelled

    def _on_stop_clicked(self):
        self._cancelled = True
        self.status_label.setText("正在停止%s，请稍候..." % self._verb)
        self.stop_btn.setEnabled(False)
        QApplication.processEvents()

    def closeEvent(self, event):
        # 不要走 QDialog.closeEvent：它会再调 reject()，而运行中的 reject
        # 只标记停止、不关窗，导致停止后进度框一直留着。
        if self._allow_close:
            event.accept()
            return
        self._on_stop_clicked()
        event.ignore()

    def reject(self):
        if self._allow_close:
            super().reject()
            return
        self._on_stop_clicked()

    def accept(self):
        self._allow_close = True
        super().accept()

    def finish_and_close(self):
        self._allow_close = True
        self.hide()
        super().reject()

    def set_status(self, text):
        self.status_label.setText(text or "")
        QApplication.processEvents()

    def begin_pipe(self, index, pipe_label, detail="", display_index=None, display_total=None):
        shown_i = display_index if display_index is not None else index
        shown_t = display_total if display_total is not None else self._total
        text = "正在%s [%s/%s] %s" % (self._verb, shown_i, shown_t, pipe_label)
        if detail:
            text += " — %s" % detail
        self.status_label.setText(text)
        self._refresh_time_labels(max(0, int(index) - 1))
        QApplication.processEvents()

    def finish_pipe(self, index, pipe_label, display_index=None, display_total=None):
        self._completed = index
        self.progress_bar.setValue(index)
        shown_i = display_index if display_index is not None else index
        shown_t = display_total if display_total is not None else self._total
        self.status_label.setText(
            "已完成 [%s/%s] %s" % (shown_i, shown_t, pipe_label)
        )
        self._refresh_time_labels(index)
        QApplication.processEvents()

    def set_finalizing(self):
        if self._verb == "导入":
            self.status_label.setText("正在提交入库事务...")
        else:
            self.status_label.setText("正在完成写入并关闭文件...")
        self.progress_bar.setValue(self._total)
        self.eta_label.setText("预计剩余时间：即将完成")
        QApplication.processEvents()

    def _refresh_time_labels(self, completed_count):
        elapsed = time.time() - self._start_time
        self.elapsed_label.setText("已用时间：%s" % _format_duration(elapsed))
        if completed_count <= 0:
            self.eta_label.setText("预计剩余时间：计算中...")
            return
        if completed_count >= self._total:
            self.eta_label.setText("预计剩余时间：即将完成")
            return
        remaining = (elapsed / completed_count) * (self._total - completed_count)
        self.eta_label.setText("预计剩余时间：约 %s" % _format_duration(remaining))
