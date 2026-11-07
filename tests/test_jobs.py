"""编排层的格数、报错与文案全部钉死，且不含 print/GUI 依赖。"""
import inspect
import sys

import pytest

pytest.importorskip("PIL", reason="需要 Pillow")

from PIL import Image  # noqa: E402

from photoprint import jobs  # noqa: E402
from photoprint.core import modes, render, specs, store  # noqa: E402


@pytest.fixture
def st(tmp_path):
    s = store.Store(tmp_path / "papers.json")
    s.load()
    return s


def _photos(n, color=(200, 30, 30)):
    return [Image.new("RGB", (100, 100), color) for _ in range(n)]


# (纸张, 格子, gap, 出血, 指定模式, 无边距生效, 每页格数, 生效模式)
_CELL_COUNTS = [
    ("A4", "3R", 0.0, modes.DEFAULT_BLEED_MM, None, False, 4, modes.BLEED_TRIM),
    ("A4", "ID1", 2.0, modes.DEFAULT_BLEED_MM, None, False, 56,
     modes.FIT_TO_PRINTABLE),
    ("A4", "4R", 0.0, modes.DEFAULT_BLEED_MM, None, False, 2, modes.BLEED_TRIM),
    # 格与纸同尺寸：走“整纸一格”退化分支
    ("3R", "3R", 0.0, 0.0, modes.FILL_PRINTABLE, False, 1, modes.FILL_PRINTABLE),
    # 无边距生效时换的是可打印区，同一组合 2 格→ 3 格；不单独钉的话
    # 这一分支只能靠 Task 3 历史提交的对拍证明它当时确实与 cli 一致
    ("A4", "4R", 0.0, 0.0, modes.FIT_TO_PRINTABLE, True, 3, modes.FIT_TO_PRINTABLE),
]


@pytest.mark.parametrize("sheet,cell,gap,bleed,mode,borderless,want_count,"
                         "want_mode", _CELL_COUNTS)
def test_build_layout_cell_counts_are_frozen(st, sheet, cell, gap, bleed, mode,
                                             borderless, want_count, want_mode):
    """格数与生效模式全部钉死：数字漂了照样红，不需要另一个实现来参照。

    原方案是与重构前的 cli.build_plan_jobs 逐字段对拍；Task 4 把 cli 改成
    `jobs.build_layout` 的薄转发后，那两条就退化成自己比自己——永远绿，
    却不声明任何事。这里的绝对值是重构前实测抄下的。
    """
    plan, mode_eff = jobs.build_layout(st, sheet, cell, gap, bleed, mode,
                                       borderless_active=borderless)
    assert (plan.count, mode_eff) == (want_count, want_mode)


def test_cell_larger_than_sheet_raises_actionable_message(st):
    """报错文案是用户唯一能看见的出口，改成整句断言而不是与 cli 对拍。

    卡片纸（91×55）在出血档装不下带 3mm 出血的美国签证（57×57 > 55），
    且出血档不走“整纸一格”退化分支，是预设组合里真能走到的报错。
    """
    with pytest.raises(ValueError) as exc:
        jobs.build_layout(st, "CARD", "USVISA", 0.0, modes.DEFAULT_BLEED_MM,
                          modes.BLEED_TRIM, borderless_active=False)
    assert str(exc.value) == "卡片 放不下 美国签证，请换大纸或改小格子"


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


def test_photo_cell_takes_even_margins(st):
    """格子就是成品照片（role=paper）时白边取齐：上下/左右各自等宽。"""
    job = jobs.build_job(st, _photos(1), "3R", "3R")
    assert job.even_margins is True
    assert "上5.1/下5.1/左3.5/右3.5mm" in job.note


def test_id_grid_keeps_raw_margins_and_density(st):
    """证件照拼版不取齐：A4 一寸照保住 9 排 72 张，报数也用逐边原值。"""
    job = jobs.build_job(st, _photos(4), "A4", "ID1", gap_mm=2.0)
    assert job.even_margins is False
    assert "上3.0/下5.0/左3.4/右3.4mm" in job.note
    plan, _ = jobs.build_layout(st, "A4", "ID1", 0.0, 0.0,
                                modes.FILL_PRINTABLE)
    assert plan.count == 72


def test_photo_grid_on_a4_uses_even_box(st):
    """A4 排 3R 照片（4 格）也走取齐：内容框上下各 5.1mm，不丢格数。"""
    plan, _ = jobs.build_layout(st, "A4", "3R", 0.0, 0.0,
                                modes.FILL_PRINTABLE)
    assert plan.count == 4
    assert plan.printable.y_mm == pytest.approx(5.1)
    assert plan.printable.h_mm == pytest.approx(286.8)


def test_uniform_margin_makes_four_sides_equal_on_single_photo(st):
    """单张（3R 纸 + 3R 照片）勾「四周等宽白边」：报数是四边同一档。

    不加这一档时是“同轴取齐”（上5.1/下5.1/左3.5/右3.5）；用户 2026-11-07
    要的是“四周一样宽”。多格不生效：内框是所有照片共享的，拿它当边距
    会把整页拖小。
    """
    job = jobs.build_job(st, _photos(1), "3R", "3R",
                         mode=modes.FILL_PRINTABLE, uniform_mm=5.1)
    assert job.count == 1
    assert job.uniform_mm == 5.1
    assert "上5.1/下5.1/左5.1/右5.1mm" in job.note

    # 多格时 uniform_mm 必须失效，格数不能因此少（A4 一寸仍是 72）
    mult = jobs.build_job(st, _photos(1), "A4", "ID1", uniform_mm=5.1)
    assert mult.count == 72
    assert mult.uniform_mm is None
    assert "左3.4/右3.4mm" in mult.note


def test_uniform_margin_is_lifted_to_physical_floor(st):
    """要 4mm 会被抬到物理下限 5.1mm：下边 5.04mm 打不到，不是可以商量的。

    纸与格子同尺寸时（3R/3R）等宽内框装不下原尺寸照片，build_layout 退成
    “整纸一格”，实际落位交给 render 用同一个内框求交缩小（见
    test_render_geometry.test_uniform_border_is_equal_on_all_four_sides）。
    这里钉两件事：格数不丢，报数是四边 5.1 而不是逐边原值。
    """
    job = jobs.build_job(st, _photos(1), "3R", "3R",
                         mode=modes.FILL_PRINTABLE, uniform_mm=4.0)
    assert job.count == 1
    assert job.uniform_mm == 5.1          # 4.0 被抬到物理下限
    assert "上5.1/下5.1/左5.1/右5.1mm" in job.note


def test_uniform_margin_never_enlarges_the_photo(st):
    """4R 纸打 3R 照片：等宽框比照片大，勾等宽会把 3R 放大成 92×142。

    那是默默改了成品尺寸，所以这一档直接不生效（`uniform_applies` 一处判定），
    照片保持标称 89×127、由装箱居中（左右相等、上下相等）。
    """
    job = jobs.build_job(st, _photos(1), "4R", "3R",
                         mode=modes.FILL_PRINTABLE, uniform_mm=5.1)
    assert job.count == 1
    assert job.uniform_mm is None
    assert job.plan.cells[0].w_mm == pytest.approx(89.0)
    assert job.plan.cells[0].h_mm == pytest.approx(127.0)
    assert "左3.5/右3.5mm" in job.note      # 退回取齐档，不谎报四边 5.1

    # 纸与照片同规格时才成立：框比照片小，只能缩不能放
    assert jobs.uniform_applies(st.resolve("3R"), st.resolve("3R"), 5.1)
    assert not jobs.uniform_applies(st.resolve("4R"), st.resolve("3R"), 5.1)
    # 出血档与无边距生效时也不成立
    assert not jobs.uniform_applies(st.resolve("3R"), st.resolve("3R"), 5.1,
                                    mode=modes.BLEED_TRIM)
    assert not jobs.uniform_applies(st.resolve("3R"), st.resolve("3R"), 5.1,
                                    borderless_active=True)


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
