"""编排层必须与重构前的 cli 逐字段等价，且不含 print/GUI 依赖。"""
import inspect

import pytest

pytest.importorskip("PIL", reason="需要 Pillow")

from PIL import Image  # noqa: E402

from photoprint import cli, jobs  # noqa: E402
from photoprint.core import modes, store  # noqa: E402


@pytest.fixture
def st(tmp_path):
    s = store.Store(tmp_path / "papers.json")
    s.load()
    return s


def _photos(n, color=(200, 30, 30)):
    return [Image.new("RGB", (100, 100), color) for _ in range(n)]


@pytest.mark.parametrize("sheet,cell,gap,bleed,mode", [
    ("A4", "3R", 0.0, modes.DEFAULT_BLEED_MM, None),
    ("A4", "ID1", 2.0, modes.DEFAULT_BLEED_MM, None),
    ("A4", "4R", 0.0, modes.DEFAULT_BLEED_MM, None),
    ("3R", "3R", 0.0, 0.0, modes.FILL_PRINTABLE),
])
def test_build_layout_matches_legacy_cli(st, sheet, cell, gap, bleed, mode):
    plan_a, mode_a = cli.build_plan_jobs(st, sheet, cell, gap, bleed, mode, False)
    plan_b, mode_b = jobs.build_layout(st, sheet, cell, gap, bleed, mode,
                                       borderless_active=False)
    assert mode_a == mode_b
    assert plan_a == plan_b  # dataclass 逐字段相等


def test_build_job_counts_pages(st):
    job = jobs.build_job(st, _photos(5), "A4", "3R", bleed_mm=3.0)
    assert job.count == 4
    assert job.page_count == 2


def test_build_job_page_count_is_one_when_empty(st):
    """界面允许零照片：预览要有一张空格可看，不得除零或返回 0 页。"""
    job = jobs.build_job(st, [], "A4", "3R", bleed_mm=3.0)
    assert job.page_count == 1


def test_note_uses_legacy_wording_bleed(st):
    job = jobs.build_job(st, _photos(4), "A4", "3R", bleed_mm=3.0)
    assert job.note.startswith("需人工裁切：沿灰线切开后即为 89×127mm 成品")


def test_note_uses_legacy_wording_margins(st):
    job = jobs.build_job(st, _photos(4), "A4", "ID1", gap_mm=2.0)
    assert "未经真机校准" in job.note


def test_render_out_of_range_raises(st):
    job = jobs.build_job(st, _photos(4), "A4", "3R", bleed_mm=3.0)
    with pytest.raises(IndexError, match="页码越界"):
        job.render(1, 25.4)


def test_offset_changes_rendered_pixels(st):
    a = jobs.build_job(st, _photos(4), "A4", "ID1", gap_mm=2.0)
    b = jobs.build_job(st, _photos(4), "A4", "ID1", gap_mm=2.0,
                       offset_pct=(0.0, 50.0))
    assert a.render(0, 25.4).tobytes() != b.render(0, 25.4).tobytes()


def test_offset_pct_is_converted_by_cell_inner_size(st):
    """百分比按格子内框换算：ID1 内框 25×32，±50% → (12.5, 16.0)mm。"""
    job = jobs.build_job(st, _photos(4), "A4", "ID1", gap_mm=2.0,
                         offset_pct=(50.0, -50.0))
    assert job.offset_mm == pytest.approx((12.5, -16.0))
    assert job.offset_pct == (50.0, -50.0)


def test_render_all_covers_every_page(st):
    job = jobs.build_job(st, _photos(5), "A4", "3R", bleed_mm=3.0)
    pages = jobs.render_all(job, 25.4)
    assert len(pages) == 2


def test_jobs_module_has_no_print_and_no_gui():
    """窗口化打包后 sys.stdout 是 None；jobs 一旦被输出污染就会崩。

    注：这是“源码不含某字样”的守门断言，所以 jobs 的注释也不得写出
    被禁模块的名字，否则测试自己打自己。
    """
    src = inspect.getsource(jobs)
    assert "print(" not in src
    for banned in ("PySide6", "win32print", "win32ui", "win32con"):
        assert banned not in src
