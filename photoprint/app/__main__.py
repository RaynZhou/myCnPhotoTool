"""exe 与 `python -m photoprint.app` 的入口。

入口必须是真实 .py 文件：PyInstaller 不认 `python -m` 形式。
本文件不得 print：--windowed 下 sys.stdout 是 None。
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from photoprint.app import crashlog, main_window


def run(argv=None):
    crashlog.install()
    app = QApplication(argv if argv is not None else sys.argv[:1])
    win = main_window.MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
