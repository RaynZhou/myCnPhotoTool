"""左区布局的三条硬约束：一次看全、两列并排、字段名对齐。

这些不是「好看就行」的主观项：默认开窗必须把左区三张卡片全露出来（不然用户
第一眼就看到被裁掉的表单），照片列与设置列必须并排（单列堆叠要 1200px 以上），
同一张卡片里的字段名必须共用一条左边线（旧版右对齐时左沿参差，看着像没对齐）。
窗口尺寸/图标另有两组用例，避免资源缺失时静默退化成默认图标。
"""
import pytest

pytest.importorskip("PIL", reason="需要 Pillow")
pytest.importorskip("PySide6", reason="需要 Qt 绑定")

from PySide6.QtCore import QEventLoop, QPoint, QRect  # noqa: E402
from PySide6.QtWidgets import QLabel, QScrollArea, QWidget  # noqa: E402

from photoprint.app import branding, main_window, theme  # noqa: E402
from photoprint.app.main_window import MainWindow  # noqa: E402
from photoprint.core import store  # noqa: E402


def _store(tmp_path):
    s = store.Store(tmp_path / "papers.json")
    s.load()
    return s


def _window(qapp, tmp_path, size=(1400, 960)):
    """建窗、按默认尺寸开局并让布局真正算一遍（不 show 时几何还是初始值）。"""
    w = MainWindow(st=_store(tmp_path))
    w.resize(*size)
    w.show()
    qapp.processEvents(QEventLoop.AllEvents, 200)
    return w


def test_left_region_fits_without_scrolling(qapp, tmp_path):
    """默认窗（1400×960，1080p 上的开窗尺寸）里左区内容应一次全露、不出滚动条。

    牙在「两列并排 + 紧凑字段网格」：退回单列堆叠后内容高 1200px 以上，这条
    断言立刻转红——那正是用户抱怨的「默认打开看不全」。
    """
    w = _window(qapp, tmp_path)
    scroll = w.findChild(QScrollArea, "Sidebar")
    assert scroll is not None
    assert scroll.widget().height() <= scroll.viewport().height()
    assert not scroll.verticalScrollBar().isVisible()


def test_photo_column_and_panel_column_side_by_side(qapp, tmp_path):
    """照片网格在左、纸张与布局在右，且同处一条水平带（并排而非上下堆）。"""
    w = _window(qapp, tmp_path)
    photo = w.photo_list.mapTo(w, QPoint(0, 0))
    panel = w.sheet_box.mapTo(w, QPoint(0, 0))
    assert photo.x() + w.photo_list.width() <= panel.x()
    assert panel.y() < photo.y() + w.photo_list.height()


def test_field_labels_share_one_left_edge_per_card(qapp, tmp_path):
    """每张卡片里的字段名共用固定列宽：同宽、最多两列、每列各自对齐。"""
    w = _window(qapp, tmp_path)
    labels = [lb for lb in w.findChildren(QLabel)
              if lb.objectName() == "FieldLabel"]
    assert labels
    per_card = {}
    for lb in labels:
        per_card.setdefault(id(lb.parentWidget()), []).append(lb)
    for group in per_card.values():
        widths = {lb.width() for lb in group}
        assert len(widths) == 1, f"同卡片字段名宽度不一：{widths}"
        assert widths <= {theme.LABEL_W, theme.LABEL_W_SMALL}
        edges = {lb.mapTo(lb.window(), QPoint(0, 0)).x() for lb in group}
        assert len(edges) <= 2, f"字段名超出两列：{sorted(edges)}"


def test_initial_window_size_follows_screen(qapp):
    """开窗尺寸：够大时用默认 1400×960，小屏向可用区收，但不低于最小值。"""
    class _Screen:
        def __init__(self, width, height):
            self._rect = QRect(0, 0, width, height)

        def availableGeometry(self):
            return self._rect

    assert main_window.initial_window_size(_Screen(1920, 1040)) == (1400, 960)
    assert main_window.initial_window_size(_Screen(1366, 728)) == (1326, 700)
    # 小到不能再小时仍保底，避免把操作条与状态栏推出屏幕
    assert main_window.initial_window_size(_Screen(800, 600)) == (
        main_window.MIN_WIN_W, main_window.MIN_WIN_H)


def test_logo_assets_are_wired(qapp, tmp_path):
    """窗口与标题 logo 都取自 branding：资源缺失会静默退化成空图标，必须钉住。"""
    assert branding.LOGO_PNG.is_file()
    assert not branding.app_icon().isNull()
    assert not branding.logo_pixmap(34).isNull()
    w = _window(qapp, tmp_path)
    assert not w.windowIcon().isNull()
    header = [lb for lb in w.findChildren(QLabel) if lb.objectName() == "BrandLogo"]
    assert header and not header[0].pixmap().isNull()
    assert isinstance(header[0].parentWidget(), QWidget)
