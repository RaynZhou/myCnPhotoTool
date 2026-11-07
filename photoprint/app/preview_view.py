"""交互式预览：整页 pixmap 之上描格框、高亮当前格，点击→格内序信号。

几何全部问 core（render.cell_index_at / cell_rects_view），本模块不写任何
mm/像素/裁切运算——守住 app 层红线。
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QLabel

from photoprint.app import theme, view
from photoprint.core import render

# 配色全部问 theme：格线与选中框是设计系统的一部分，不在这里另起一代码
_CELL_PEN = QColor(theme.LINE_STRONG)
_CURRENT_PEN = QColor(theme.ACCENT)
_EMPTY_TEXT = "（无预览）"


class PreviewView(QLabel):
    cellClicked = Signal(int)          # 格内序 [0, count)
    cellContextMenuRequested = Signal(int, QPoint)   # 页内序 + 菜单全局坐标

    def __init__(self, parent=None):
        super().__init__(_EMPTY_TEXT, parent)
        self.setObjectName("PreviewView")   # 空态字色/背景由全局 QSS 接管
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(360, 240)
        self._full_pm = None
        self._cell_rects_px = []
        self._image_wh = (1, 1)
        self._current_cell = None      # 格内序（页内），非全局槽位

    # ---------- 几何注入（main_window 每次 _rebuild_job 调） ----------

    def set_geometry(self, cell_rects_px, image_wh):
        self._cell_rects_px = [tuple(r) for r in cell_rects_px]
        self._image_wh = tuple(image_wh)
        self.update()

    def set_current_cell(self, position):
        self._current_cell = position
        self.update()

    # ---------- 图像 ----------

    def show_image(self, image):
        self._full_pm = view.to_pixmap(image)
        self._rescale()

    def clear_image(self):
        self._full_pm = None
        self.clear()

    def _rescale(self):
        if self._full_pm is None or self._full_pm.isNull():
            return
        self.setPixmap(self._full_pm.scaled(self.size(), Qt.KeepAspectRatio,
                                            Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()

    # ---------- 命中 / 点击 ----------

    def hit_position(self, x, y):
        if not self._cell_rects_px:
            return None
        return render.cell_index_at(self._cell_rects_px, self._image_wh,
                                    (self.width(), self.height()), (x, y))

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        idx = self.hit_position(event.position().x(), event.position().y())
        if idx is not None:
            self.cellClicked.emit(idx)

    def contextMenuEvent(self, event):
        """右键命中某格 → 发页内序 + 全局坐标；命中空白不发。放置语义交 MainWindow。"""
        idx = self.hit_position(event.pos().x(), event.pos().y())
        if idx is not None:
            self.cellContextMenuRequested.emit(idx, event.globalPos())

    # ---------- 绘制格框 ----------

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._cell_rects_px or self._full_pm is None:
            return
        painter = QPainter(self)
        rects = render.cell_rects_view(self._cell_rects_px, self._image_wh,
                                       (self.width(), self.height()))
        pen = QPen(_CELL_PEN)
        pen.setWidth(1)
        painter.setPen(pen)
        for (x, y, w, h) in rects:
            painter.drawRect(QRectF(x, y, w, h))
        if self._current_cell is not None and 0 <= self._current_cell < len(rects):
            cpen = QPen(_CURRENT_PEN)
            cpen.setWidth(2)          # 扁平风：2px 就够醒目，再粗压画面
            painter.setPen(cpen)
            cx, cy, cw, ch = rects[self._current_cell]
            painter.drawRect(QRectF(cx, cy, cw, ch))
        painter.end()
