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


def to_thumbnail(img, px):
    """PIL 图等比缩到 px×px 方框内转 QPixmap；不改动传入的 img。

    先 convert("RGB") 兜住 to_pixmap 的 raw RGB 前提（调色板/灰度源不炸），
    再 copy() 保证 thumbnail 的原地缩落在副本上——原图是渲染共享对象，
    改了就污染导出。
    """
    small = img.convert("RGB").copy()
    small.thumbnail((px, px))
    return to_pixmap(small)
