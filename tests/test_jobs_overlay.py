"""jobs：photo_date_text 取 EXIF→回退 mtime→坏值 None；Job 透传叠加参不改变无叠加渲染。"""
import os

import pytest

pytest.importorskip("PIL", reason="需要 Pillow")

from PIL import Image  # noqa: E402

from photoprint import jobs  # noqa: E402
from photoprint.core import store, text_overlay  # noqa: E402
from photoprint.core.text_overlay import TextSpec  # noqa: E402


def _store(tmp_path):
    s = store.Store(tmp_path / "papers.json")
    s.load()
    return s


def test_photo_date_text_falls_back_to_mtime(tmp_path):
    p = tmp_path / "n.jpg"
    Image.new("RGB", (40, 40), (0, 0, 0)).save(p)      # 无 EXIF
    got = jobs.photo_date_text(str(p))
    import time
    want = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(str(p))))
    assert got == want


def test_photo_date_text_missing_file_returns_none(tmp_path):
    assert jobs.photo_date_text(str(tmp_path / "nope.jpg")) is None


def test_job_without_overlay_equals_legacy_render(tmp_path):
    st = _store(tmp_path)
    ph = Image.new("RGB", (200, 100), (10, 20, 30))
    photos = [ph]
    legacy = jobs.build_job(st, photos, "A4", "ID1")
    withfield = jobs.build_job(st, photos, "A4", "ID1", date_texts=["2025-01-02"])
    assert legacy.render(0, 96.0).tobytes() == withfield.render(0, 96.0).tobytes()


def test_build_job_accepts_specs(tmp_path):
    st = _store(tmp_path)
    spec = TextSpec(enabled=True, font_key="arial", corner="tl")
    job = jobs.build_job(st, [Image.new("RGB", (200, 100))], "A4", "ID1",
                         date_overlay=spec,
                         date_texts=["2025-01-02"])
    assert job.date_overlay is spec and job.date_texts == ("2025-01-02",)
