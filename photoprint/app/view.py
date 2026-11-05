"""PIL → QPixmap 的唯一转换处；本层不得做尺寸换算（全局约束）。"""
from __future__ import annotations

from PySide6.QtGui import QImage, QPixmap


def to_pixmap(img):
    """RGB 位图转 QPixmap。

    `copy()` 不可省：QImage 只引用传入的 bytes，buf 一被回收就是野指针。
    """
    buf = img.tobytes("raw", "RGB")
    qimg = QImage(buf, img.width, img.height, img.width * 3,
                  QImage.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())
