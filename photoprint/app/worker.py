"""把渲染搬出主线程：主线程只做显示与输入。

异常必须转成信号，绝不让线程静默死掉——窗口化 exe 没有控制台，
静默失败等于用户完全无从得知。start() 只组装不启动：调用方先连信号
再 thread.start()，否则任务可能在连上之前就跑完了（信号丢失）。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal


class RenderTask(QObject):
    """在子线程里跑一个无参可调用，结果与异常都走信号。"""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            self.succeeded.emit(self._fn())
        except Exception as exc:  # 线程边界：任何异常都要变成可读消息
            self.failed.emit(f"{type(exc).__name__}: {exc}")


def start(fn):
    """组装 (thread, task)；调用方连信号后自己 thread.start()。"""
    thread = QThread()
    task = RenderTask(fn)
    task.moveToThread(thread)
    thread.started.connect(task.run)
    task.succeeded.connect(thread.quit)
    task.failed.connect(thread.quit)
    thread.finished.connect(task.deleteLater)
    return thread, task
