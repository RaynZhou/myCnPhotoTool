"""导入文件夹：枚举与批量入列，脱机、不碰目录对话框。"""
import os

import pytest

pytest.importorskip("PIL", reason="需要 Pillow")
pytest.importorskip("PySide6", reason="需要 Qt 绑定")

from PIL import Image  # noqa: E402

from photoprint.app.main_window import IMAGE_EXTS, IMAGE_FILTER, list_folder_images  # noqa: E402


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
