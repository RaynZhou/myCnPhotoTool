"""编排层必须与重构前的 cli 逐字段等价，且不含 print/GUI 依赖。"""
import inspect
import sys

import pytest

pytest.importorskip("PIL", reason="需要 Pillow")

from PIL import Image  # noqa: E402

from photoprint import cli, jobs  # noqa: E402
from photoprint.core import modes, render, specs, store  # noqa: E402


@pytest.fixture
def st(tmp_path):
    s = store.Store(tmp_path / "papers.json")
    s.load()
    return s


def _photos(n, color=(200, 30, 30)):
    return [Image.new("RGB", (100, 100), color) for _ in range(n)]


@pytest.mark.parametrize("sheet,cell,gap,bleed,mode,borderless", [
    ("A4", "3R", 0.0, modes.DEFAULT_BLEED_MM, None, False),
    ("A4", "ID1", 2.0, modes.DEFAULT_BLEED_MM, None, False),
    ("A4", "4R", 0.0, modes.DEFAULT_BLEED_MM, None, False),
    ("3R", "3R", 0.0, 0.0, modes.FILL_PRINTABLE, False),
    # 无边距实测生效是另一条排版分支（可打印区换成整张纸），也得对拍
    ("A4", "4R", 0.0, modes.DEFAULT_BLEED_MM, None, True),
])
def test_build_layout_matches_legacy_cli(st, sheet, cell, gap, bleed, mode,
                                         borderless):
    """与重构前的 cli 逐字段对拍：这一层是搬过来的，必须证明没搬坏。

    Task 4 把 cli 改成薄转发之后，这里会退化成自己比自己，届时换成绝对格数
    断言（见计划 Task 4 Step 4）；本 commit 里两边仍是两份实现，对拍是真对拍。
    """
    plan_a, mode_a = cli.build_plan_jobs(st, sheet, cell, gap, bleed, mode,
                                         borderless)
    plan_b, mode_b = jobs.build_layout(st, sheet, cell, gap, bleed, mode,
                                       borderless_active=borderless)
    assert mode_a == mode_b
    assert plan_a == plan_b  # dataclass 逐字段相等


def test_build_layout_rejects_cell_larger_than_sheet_with_same_message(st):
    """报错分支也要对拍：文案是用户唯一能看见的出口，漂了就没人知道为何失败。

    卡片纸（91×55）在出血档装不下带 3mm 出血的美国签证（57×57 > 55），
    且出血档不走“整纸一格”退化分支，是预设组合里真能走到的报错。

    与 `test_build_layout_matches_legacy_cli` 同一命运：Task 4 后换成整句断言。
    """
    with pytest.raises(ValueError) as ea:
        cli.build_plan_jobs(st, "CARD", "USVISA", 0.0,
                            modes.DEFAULT_BLEED_MM, modes.BLEED_TRIM, False)
    with pytest.raises(ValueError) as eb:
        jobs.build_layout(st, "CARD", "USVISA", 0.0, modes.DEFAULT_BLEED_MM,
                          modes.BLEED_TRIM, borderless_active=False)
    assert str(ea.value) == str(eb.value)
    assert "放不下" in str(eb.value)


def test_build_job_counts_pages(st):
    job = jobs.build_job(st, _photos(5), "A4", "3R", bleed_mm=3.0)
    assert job.count == 4
    assert job.page_count == 2


def test_build_job_page_count_is_one_when_empty(st):
    """界面允许零照片：预览要有一张空格可看，不得除零或返回 0 页。"""
    job = jobs.build_job(st, [], "A4", "3R", bleed_mm=3.0)
    assert job.page_count == 1


def test_note_bleed_states_cut_action_and_provenance(st):
    """出血档也得说清边距从哪来：全局约束对 margin_source 的点名是无条件的，
    而出血档的预览仍在按规格边距画不可印遮罩——界面正在用一组没证据的数字。"""
    job = jobs.build_job(st, _photos(4), "A4", "3R", bleed_mm=3.0)
    assert job.mode == modes.BLEED_TRIM  # 前提：默认映射确实落到裁切档
    assert job.note.startswith("需人工裁切：沿灰线切开后即为 89×127mm 成品")
    assert job.note.endswith("（边距依规格推定，未经真机校准）")


def test_note_bleed_provenance_follows_margin_source(st):
    """来源换了出血档文案也得跟着换，否则分档表成了只对白边档生效的摆设。"""
    st.override_margins("A4", specs.Margins(3.0, 5.0, 3.4, 3.4), "calibrated")
    job = jobs.build_job(st, _photos(4), "A4", "3R", bleed_mm=3.0)
    # 钉整括号而不是“真机校准”四个字：spec 档那句也含这四个字
    assert job.note.endswith("（边距已经真机校准）")
    assert "依规格推定" not in job.note


def test_note_spec_source_says_unproven(st):
    """全局约束点名的一句：margin_source=spec 时必须逐字出现该文案。"""
    job = jobs.build_job(st, _photos(4), "A4", "ID1", gap_mm=2.0)
    assert job.sheet.margin_source == "spec"  # 前提：开发期常态
    assert "（边距依规格推定，未经真机校准）" in job.note
    assert "上3.0/下5.0/左3.4/右3.4mm" in job.note  # 数字不得丢


def test_note_probed_source_says_driver_measured(st):
    st.override_margins("A4", specs.Margins(3.0, 5.0, 3.4, 3.4), "probed")
    job = jobs.build_job(st, _photos(4), "A4", "ID1", gap_mm=2.0)
    assert "边距已由驱动实测" in job.note
    assert "未经真机校准" not in job.note  # 已实测就不许再说不确定


def test_note_calibrated_source_says_machine_calibrated(st):
    st.override_margins("A4", specs.Margins(3.0, 5.0, 3.4, 3.4), "calibrated")
    job = jobs.build_job(st, _photos(4), "A4", "ID1", gap_mm=2.0)
    # 钉整括号而不是"真机校准"四个字：光说“未经真机校准”也含这四个字
    assert "（边距已经真机校准）" in job.note
    assert "未经" not in job.note and "依规格推定" not in job.note


def test_note_unknown_margin_source_falls_back_to_most_conservative(st):
    """手改的 papers.json 可能交来历不明的来源；凭空说"实测"就是谎报。"""
    st.raw["overrides"]["A4"] = {
        "margins_mm": {"top": 3.0, "bottom": 5.0, "left": 3.4, "right": 3.4},
        "margin_source": "guessed",
    }
    job = jobs.build_job(st, _photos(4), "A4", "ID1", gap_mm=2.0)
    assert "依规格推定，未经真机校准" in job.note


def test_render_out_of_range_raises(st):
    job = jobs.build_job(st, _photos(4), "A4", "3R", bleed_mm=3.0)
    with pytest.raises(IndexError, match="页码越界"):
        job.render(1, 25.4)


def test_offset_changes_rendered_pixels(st):
    a = jobs.build_job(st, _photos(4), "A4", "ID1", gap_mm=2.0)
    b = jobs.build_job(st, _photos(4), "A4", "ID1", gap_mm=2.0,
                       offset_pct=(0.0, 50.0))
    assert a.render(0, 25.4).tobytes() != b.render(0, 25.4).tobytes()


def test_build_job_passes_percentage_through_without_converting(st, monkeypatch):
    """编排层不得自己换算成 mm：±50% 必须原样送到 core，逐格按本格尺寸换算。

    本层只按首格换算的话，混合朝向页上其余格的偏移会失真（T3 评审 I-1），
    而界面交来的百分比本身是与格子无关的量。 spy 只拦一层，真渲染照跑。
    """
    seen = {}
    real = render.render_page

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(render, "render_page", spy)
    job = jobs.build_job(st, _photos(4), "A4", "ID1", gap_mm=2.0,
                         offset_pct=(50.0, -50.0))
    job.render(0, 25.4)
    assert job.offset_pct == (50.0, -50.0)
    assert seen["offset_pct"] == (50.0, -50.0)


def test_render_all_covers_every_page(st):
    job = jobs.build_job(st, _photos(5), "A4", "3R", bleed_mm=3.0)
    pages = jobs.render_all(job, 25.4)
    assert len(pages) == 2


def test_jobs_module_has_no_print_and_no_gui():
    """窗口化打包后 sys.stdout 是 None；jobs 一旦被输出污染就会崩。

    注：这是“源码不含某字样”的守门断言，所以 jobs 的注释也不得写出
    被禁模块的名字，否则测试自己打自己。字样拦不住别名与 logging，
    真正兜住它的是下面那条把 sys.stdout 设为 None 的行为断言。
    """
    src = inspect.getsource(jobs)
    assert "print(" not in src
    for banned in ("PySide6", "win32print", "win32ui", "win32con"):
        assert banned not in src


def test_jobs_stay_silent_when_stdout_is_unavailable(st, monkeypatch):
    """--windowed 下 sys.stdout 真的是 None：编排层写一句就 AttributeError。

    行为断言而不是文本扫描：logging/traceback.print_exc/别名转发都绕得过扫描。
    """
    monkeypatch.setattr(sys, "stdout", None)
    job = jobs.build_job(st, _photos(5), "A4", "3R", bleed_mm=3.0)
    assert job.note
    assert len(jobs.render_all(job, 25.4)) == 2
