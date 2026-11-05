"""PIL → QPixmap 的唯一转换处。"""
import pytest

pytest.importorskip("PIL", reason="需要 Pillow")
pytest.importorskip("PySide6", reason="需要 Qt 绑定")

from PIL import Image  # noqa: E402

from photoprint.app import view  # noqa: E402


def test_to_pixmap_keeps_size_and_pixels(qapp):
    pm = view.to_pixmap(Image.new("RGB", (3, 2), (10, 20, 30)))
    assert (pm.width(), pm.height()) == (3, 2)
    got = pm.toImage().pixelColor(0, 0)
    assert (got.red(), got.green(), got.blue()) == (10, 20, 30)


def test_to_pixmap_survives_source_garbage_collection(qapp):
    """copy() 是必需的：原 buffer 被回收后 QPixmap 会变野指针。"""
    imgs = [view.to_pixmap(Image.new("RGB", (64, 64), (i, 0, 0))) for i in range(8)]
    assert all(not p.isNull() for p in imgs)
    assert imgs[-1].toImage().pixelColor(0, 0).red() == 7
