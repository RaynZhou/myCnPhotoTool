"""线程边界：结果与异常都必须能回到主线程，不得静默死掉。"""
import pytest

pytest.importorskip("PySide6", reason="需要 Qt 绑定")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402

from photoprint.app import worker  # noqa: E402


def _run_and_drain(fn, timeout_ms=3000):
    """组装→连信号→启动→等停下来；返回 (结果列表, 错误列表)。"""
    thread, task = worker.start(fn)
    results, errors = [], []
    task.succeeded.connect(results.append)
    task.failed.connect(errors.append)
    thread.start()
    loop = QEventLoop()
    thread.finished.connect(loop.quit)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    thread.deleteLater()
    return results, errors


def test_start_returns_unstarted_thread_and_task(qapp):
    """start() 不得自己 start：否则调用方还来不及连信号，结果就丢了。"""
    thread, task = worker.start(lambda: 1)
    assert isinstance(task, worker.RenderTask)
    assert not thread.isRunning()


def test_task_emits_result_object(qapp):
    assert _run_and_drain(lambda: {"dpi": 300})[0] == [{"dpi": 300}]


def test_task_turns_exception_into_readable_text(qapp):
    def boom():
        raise ValueError("A4 放不下 5R，请换大纸或改小格子")

    errors = _run_and_drain(boom)[1]
    assert errors and "ValueError" in errors[0] and "换大纸" in errors[0]
