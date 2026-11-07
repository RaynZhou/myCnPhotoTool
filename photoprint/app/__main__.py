"""exe 与 `python -m photoprint.app` 的入口。

入口必须是真实 .py 文件：PyInstaller 不认 `python -m` 形式。
本文件不得 print：--windowed 下 sys.stdout 是 None。
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from photoprint.app import branding, crashlog, main_window

# spec §9 要求崩溃落盘后在状态栏提示的逐字前缀（抽成常量供入口测钉）。
CRASH_HINT_PREFIX = "已记录错误日志："


def wire_crash_hint(win):
    """把崩溃落盘后的提示接到窗口状态栏（收一个日志 Path）。

    必须在窗口已建后调：启动早期（win 未成）`install()` 装的钩子只落盘、
    回调为空，接早了会误碰还不存在的 UI。
    """
    crashlog.set_ui_callback(
        lambda p: win._set_status(f"{CRASH_HINT_PREFIX}{p}", error=True))


def run(argv=None):
    crashlog.install()
    app = QApplication(argv if argv is not None else sys.argv[:1])
    # 应用图标要在第一个窗口创建前挂上去：任务栏/Alt-Tab 取的是 QApplication 的
    # 图标，窗口晚设只影响标题栏与任务栏缩略图。
    app.setWindowIcon(branding.app_icon())
    win = main_window.MainWindow()
    win.show()
    wire_crash_hint(win)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
