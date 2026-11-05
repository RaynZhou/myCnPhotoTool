"""Qt 测试统一走 offscreen：CI 与本机都不该弹真窗口。"""
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
