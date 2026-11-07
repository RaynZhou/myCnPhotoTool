"""Qt 测试统一走 offscreen：CI 与本机都不该弹真窗口。"""
import gc
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    """全测试会话共用一个 QApplication：多实例会撞 Qt 的单例约束。"""
    pytest.importorskip("PySide6", reason="需要 Qt 绑定")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def destroy_test_windows(windows, qapp):
    """就地销毁本轮用例建的窗口，而不是留给解释器退出时再析构。

    `close()` 只关不删，窗口对象（连同整棵控件树）仍由引用环吊着——窗口↔布局
    ↔子控件、信号 lambda 捕获 self——回收时机交给循环 GC 决定。一旦回收落在
    QApplication 销毁之后，就是一条没有 Python 栈的访问违例（0xC0000005 /
    0xC0000409）：pytest 已打印“N passed”，退出码却非零、CI 判失败。
    所以收尾必须显式 deleteLater 再 gc，让析构发生在 Qt 还活着的时候。
    """
    from PySide6.QtCore import QEventLoop

    for w in windows:
        w.close()
    qapp.processEvents(QEventLoop.AllEvents, 100)
    for w in windows:
        w.deleteLater()
    qapp.processEvents(QEventLoop.AllEvents, 100)
    gc.collect()


@pytest.fixture(scope="session")
def destroy_windows(qapp):
    """把 destroy_test_windows 包成夹具：界面用例的收尾夹具统一从这里取。"""
    return lambda windows: destroy_test_windows(windows, qapp)


@pytest.fixture(autouse=True)
def _reap_qt_windows(qapp):
    """每个用例收尾把它建的顶层窗口就地拆掉（无需各模块自己记得）。

    先 close（MainWindow.closeEvent 会 quit+wait 渲染线程）再 deleteLater，
    让 C++ 侧的窗口在 Qt 还活着时析构；Python 包装器晚一步释放也就无害了。
    没这步，窗口会拖到解释器退出、QApplication 已死之后才被回收 → 无 Python
    栈的访问违例，pytest 已打印“N passed”但退出码非零。
    """
    yield
    from PySide6.QtCore import QEventLoop

    wins = [w for w in qapp.topLevelWidgets() if w.isWindow()]
    if not wins:
        return
    for w in wins:
        w.close()
    qapp.processEvents(QEventLoop.AllEvents, 100)
    for w in wins:
        w.deleteLater()
    qapp.processEvents(QEventLoop.AllEvents, 100)


@pytest.fixture(scope="session", autouse=True)
def _flush_qt_on_session_end(qapp):
    """会话收尾时再强制一次全量 GC，把任何漏网窗口拆在 QApplication 之前。

    夹具声明在 qapp 之后，拆卸顺序自然先于它——此时 Qt 还活着。逐用例的
    `destroy_test_windows` 是主闸门，这里是给没装那套夹具的模块兜底。
    """
    yield
    gc.collect()
