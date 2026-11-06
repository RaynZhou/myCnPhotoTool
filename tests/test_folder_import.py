"""导入文件夹：枚举与批量入列，脱机、不碰目录对话框。"""
import os

import pytest

pytest.importorskip("PIL", reason="需要 Pillow")
pytest.importorskip("PySide6", reason="需要 Qt 绑定")

from PIL import Image  # noqa: E402

from PySide6.QtCore import QElapsedTimer, QEventLoop  # noqa: E402
from PySide6.QtWidgets import QPushButton  # noqa: E402

from photoprint.app.main_window import (IMAGE_EXTS, IMAGE_FILTER, MainWindow,  # noqa: E402
                                         list_folder_images)
from photoprint.core import store  # noqa: E402


def _store(tmp_path):
    s = store.Store(tmp_path / "papers.json")
    s.load()
    return s


@pytest.fixture(autouse=True)
def _no_leaked_threads(qapp):
    """MainWindow.__init__ 会 _refresh() 起渲染线程；收尾必须泵停+关窗，
    否则进程退出时在跑的 QThread 被析构→硬崩（与 test_app_main_window 同口径）。"""
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
    for w in wins:
        w.close()
    qapp.processEvents(QEventLoop.AllEvents, 100)


def _mk(dirpath, name, size=(40, 30)):
    Image.new("RGB", size, (10, 20, 30)).save(str(dirpath / name))


def _basenames_sorted(paths):
    return sorted(os.path.basename(p).lower() for p in paths)


def test_list_folder_images_filters_and_sorts(tmp_path):
    _mk(tmp_path, "c.jpg")
    _mk(tmp_path, "b.png")
    _mk(tmp_path, "a.tif")
    (tmp_path / "notes.txt").write_text("hi")          # 非图片，忽略
    sub = tmp_path / "sub"
    sub.mkdir()
    _mk(sub, "z.jpg")                                   # 子目录，忽略
    assert _basenames_sorted(list_folder_images(str(tmp_path))) == \
        ["a.tif", "b.png", "c.jpg"]


def test_list_folder_images_case_insensitive_ext(tmp_path):
    _mk(tmp_path, "UPPER.JPG")                          # 大写扩展名要收
    got = list_folder_images(str(tmp_path))
    assert len(got) == 1 and got[0].lower().endswith(".jpg")


def test_list_folder_images_missing_dir_returns_empty(tmp_path):
    assert list_folder_images(str(tmp_path / "nope")) == []


def test_list_folder_images_skips_dir_named_like_image(tmp_path):
    """名为 fake.png 的子目录不是文件，必须排除（钉住 is_file 闸门）。"""
    _mk(tmp_path, "real.png")
    (tmp_path / "fake.png").mkdir()
    assert _basenames_sorted(list_folder_images(str(tmp_path))) == ["real.png"]


def test_image_exts_match_filter():
    """IMAGE_EXTS 与对话框 IMAGE_FILTER 的扩展名集合必须同源，否则能选不能列。"""
    filt = IMAGE_FILTER.split("(")[1].split(")")[0]
    from_filter = {t.lstrip("*").lower() for t in filt.split()}
    assert set(IMAGE_EXTS) == from_filter


def test_import_folder_adds_sorted(qapp, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _mk(src, "c.jpg")
    _mk(src, "b.png")
    _mk(src, "a.tif")
    w = MainWindow(st=_store(tmp_path))
    n = w.import_folder(str(src))
    assert n == 3
    assert w.photo_list.count() == 3
    assert len(w.pool) == 3
    texts = [w.photo_list.item(i).text() for i in range(3)]
    assert texts[0].startswith("a.tif") and texts[1].startswith("b.png") \
        and texts[2].startswith("c.jpg")


def test_import_folder_bad_image_flags_and_continues(qapp, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _mk(src, "good.jpg")
    (src / "broken.jpg").write_bytes(b"not an image")
    w = MainWindow(st=_store(tmp_path))
    n = w.import_folder(str(src))
    assert n == 2                                  # 两张都识别入列
    assert sum(1 for e in w.pool if e["img"] is None) == 1   # 坏图为 None 占位
    assert w.photo_list.item(0).text().startswith("broken")   # broken < good
    assert "读取失败" in w.photo_list.item(0).text()


def test_import_folder_empty_dir_no_change(qapp, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    w = MainWindow(st=_store(tmp_path))
    n = w.import_folder(str(src))
    assert n == 0
    assert w.photo_list.count() == 0
    assert "没有可导入的图片" in w.statusBar().currentMessage()


def test_import_folder_missing_dir_returns_zero(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    assert w.import_folder(str(tmp_path / "nope")) == 0
    assert w.photo_list.count() == 0


def test_import_button_exists(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    btns = w.findChildren(QPushButton)
    assert any(b.objectName() == "import_btn" for b in btns)
