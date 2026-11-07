"""极简扁平主题：样式单一出处与页面指示器的守护。

行为类断言（排版/打印/持久化）留在各自模块的用例里；这里只钉两件容易被
“顺手改样式”改坏的事：窗口吃到的是 theme.APP_QSS 这一份样式，以及预览格线
/选中框的配色确实来自主题令牌而不是另一套写死的 RGB。
"""
import pytest

pytest.importorskip("PIL", reason="需要 Pillow")
pytest.importorskip("PySide6", reason="需要 Qt 绑定")

from PySide6.QtCore import QElapsedTimer, QEventLoop  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402

from PIL import Image  # noqa: E402

from photoprint.app import preview_view, theme  # noqa: E402
from photoprint.app.main_window import MainWindow  # noqa: E402
from photoprint.core import store  # noqa: E402


def _store(tmp_path):
    s = store.Store(tmp_path / "papers.json")
    s.load()
    return s


def _fill(window, tmp_path, n=4):
    """入库 n 张纯色图并顺序摆到槽 0..n-1（与 test_app_main_window 同构）。"""
    for i in range(n):
        p = tmp_path / f"{i}.jpg"
        Image.new("RGB", (400, 200), (200 - 30 * i, 30, 40)).save(p)
        window.append_photo(str(p))
        window.place(i, i)
    window._refresh()


@pytest.fixture(autouse=True)
def _no_leaked_threads(qapp, destroy_windows):
    """与其余界面用例同构：先停 debounce，泵停渲染线程，再关窗并就地销毁。

    否则窗口随进程退出被析构时线程还在跑（或在 QApplication 拆了之后才被
    循环 GC 回收）→ 解释器硬崩（0xC0000409 / 0xC0000005），pytest 已打印
    “passed”但退出码非零。
    """
    yield
    wins = [w for w in qapp.topLevelWidgets() if isinstance(w, MainWindow)]
    for w in wins:
        w._debounce.stop()
    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < 3000:
        qapp.processEvents(QEventLoop.AllEvents, 50)
        if not any(w._thread is not None and w._thread.isRunning() for w in wins):
            break
    destroy_windows(wins)


def test_window_applies_global_stylesheet(qapp, tmp_path):
    """窗口样式必须是 theme 那一份：另写一份内联样式就等于有了第二套设计系统。"""
    w = MainWindow(st=_store(tmp_path))
    assert w.styleSheet() == theme.APP_QSS
    assert theme.ACCENT in w.styleSheet()
    assert "border-radius" in w.styleSheet()
    # 主按钮靠 objectName 拿到强调色实心样式
    assert "QPushButton#print_btn" in w.styleSheet()
    assert w.print_btn.objectName() == "print_btn"


def test_page_label_tracks_pages(qapp, tmp_path):
    """预览头的页码跟随实际页数：5 张 3R 在 A4 上是 2 页。"""
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path, n=5)
    assert w.job.page_count == 2
    assert w.page_label.text() == "第 1 / 2 页"
    w._go_page(1)
    assert w.page_label.text() == "第 2 / 2 页"


def test_preview_colors_come_from_theme(qapp, tmp_path):
    """预览格线/选中框取自主题令牌，换色只改一处。"""
    assert preview_view._CELL_PEN == QColor(theme.LINE_STRONG)
    assert preview_view._CURRENT_PEN == QColor(theme.ACCENT)
    assert preview_view._CURRENT_PEN != QColor(theme.LINE_STRONG)


def test_overlay_color_swatch_uses_theme(qapp, tmp_path):
    """颜色按钮是实心色块：内联样式由 theme.swatch_style 生成（含圆角与细边）。"""
    w = MainWindow(st=_store(tmp_path))
    style = w.date_color_btn.styleSheet()
    assert style == theme.swatch_style(w._date_rgb)
    assert "border-radius" in style
