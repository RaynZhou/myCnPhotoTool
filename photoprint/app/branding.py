"""应用标识：窗口图标、任务栏图标与标题 logo 的唯一出处。

资源放在 photoprint/app/assets/，由 build_exe.ps1 的 --add-data 打进 onefile
（_MEIPASS 下按原相对路径展开，`Path(__file__).parent` 在开发态与打包态都成立）。
文件缺失时只退化成空图标，绝不抛异常——窗口化 exe 没有控制台，抛出去就是闪退。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
LOGO_PNG = ASSETS_DIR / "logo.png"


def app_icon():
    """窗口/任务栏图标；资源缺失返回空 QIcon（Qt 自己会退化成默认图标）。"""
    if not LOGO_PNG.is_file():
        return QIcon()
    return QIcon(str(LOGO_PNG))


def logo_pixmap(size=34):
    """标题旁的方形 logo；缺失返回空 QPixmap，由调用方跳过 setPixmap。"""
    pixmap = QPixmap(str(LOGO_PNG))
    if pixmap.isNull():
        return pixmap
    return pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
