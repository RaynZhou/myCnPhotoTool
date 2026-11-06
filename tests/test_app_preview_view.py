"""PreviewView：显示 pixmap + 命中发 cellClicked + 描框高亮。offscreen。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6", reason="需要 Qt 绑定")
pytest.importorskip("PIL", reason="需要 Pillow")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from photoprint.app.preview_view import PreviewView  # noqa: E402


@pytest.fixture(autouse=True)
def _ensure_app(qapp):
    """会话级 QApplication 由 conftest 提供；autouse 依赖它保证每个用例都在 Qt 下。"""
    yield


def _two_cell_rects():
    return [(0, 0, 200, 200), (200, 0, 200, 200)]


def test_show_image_sets_non_null_pixmap():
    w = PreviewView()
    w.resize(400, 200)
    w.show_image(Image.new("RGB", (400, 200), (10, 20, 30)))
    assert not w.pixmap().isNull()


def test_clear_image_empties():
    w = PreviewView()
    w.show_image(Image.new("RGB", (40, 30), (0, 0, 0)))
    w.clear_image()
    assert w.pixmap() is None or w.pixmap().isNull()


def test_hit_position_uses_geometry():
    w = PreviewView()
    w.resize(400, 400)                      # 视图 400×400，图像 400×200 → 上下留白
    w.set_geometry(_two_cell_rects(), (400, 200))
    assert w.hit_position(100, 150) == 0
    assert w.hit_position(300, 150) == 1
    assert w.hit_position(100, 20) is None   # 信箱留白带


def test_no_geometry_no_hit():
    w = PreviewView()
    w.resize(300, 300)
    assert w.hit_position(10, 10) is None    # 未 set_geometry：不命中、不抛


def test_click_emits_cell_clicked():
    w = PreviewView()
    w.resize(400, 200)
    w.set_geometry(_two_cell_rects(), (400, 200))
    got = []
    w.cellClicked.connect(lambda i: got.append(i))
    w.show()
    QTest.mouseClick(w, Qt.LeftButton, Qt.NoModifier, QPoint(300, 100))
    assert got == [1]


def test_click_in_letterbox_emits_nothing():
    w = PreviewView()
    w.resize(400, 400)
    w.set_geometry(_two_cell_rects(), (400, 200))
    got = []
    w.cellClicked.connect(got.append)
    w.show()
    QTest.mouseClick(w, Qt.LeftButton, Qt.NoModifier, QPoint(100, 20))
    assert got == []
