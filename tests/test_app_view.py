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


def test_to_thumbnail_scales_into_box_keeping_aspect(qapp):
    """横图 200×100 缩进 40×40：长边 40、短边等比 20。用非正方图才有牙
    （正方/纯色图缩放比不显方向，宽高比断言会恒真）。"""
    pm = view.to_thumbnail(Image.new("RGB", (200, 100), (10, 20, 30)), 40)
    assert (pm.width(), pm.height()) == (40, 20)


def test_to_thumbnail_does_not_mutate_source(qapp):
    """I-2 的底层保证：缩略图绝不动传入原图——改了会污染 self.photos 进而污染导出。"""
    img = Image.new("RGB", (200, 100), (10, 20, 30))
    view.to_thumbnail(img, 40)
    assert img.size == (200, 100)


def test_to_thumbnail_is_rgb_safe(qapp):
    """非 RGB 源（调色板图）也要能出缩略图：convert("RGB") 兜住 raw RGB 前提。"""
    pal = Image.new("P", (60, 60))
    pm = view.to_thumbnail(pal, 40)
    assert not pm.isNull()
    assert max(pm.width(), pm.height()) <= 40
