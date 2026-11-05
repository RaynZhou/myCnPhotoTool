"""裁切线只在区域内部的格子边界上生成，且贯通整条缝；与纸边重合的不画。"""
import pytest

from photoprint.core import pack, specs


def _a4_3r():
    # 整纸装箱，坐标可手算：x0=16、y0=21.5，与断言里的值直接对得上
    return pack.pack(specs.find_spec("A4"), specs.find_spec("3R"),
                     printable=specs.RectMM(0.0, 0.0, 210.0, 297.0))


def test_a4_3r_grid_draws_two_side_borders_and_the_middle_seam():
    """居中 2×2：每轴 3 条（左边界 + 中间缝 + 右边界）。

    只画中间缝与一侧边界的话，切完左列仍是 105mm 宽带白边，
    得不到 89×127 的成品；成功判据 1.4 要的是“量得出 89×127”。
    """
    plan = _a4_3r()
    assert plan.count == 4
    v = sorted(round(c.at_mm, 3) for c in plan.cuts if c.axis == "v")
    h = sorted(round(c.at_mm, 3) for c in plan.cuts if c.axis == "h")
    x0 = (210.0 - 178.0) / 2
    y0 = (297.0 - 254.0) / 2
    assert v == [round(x0 + d, 3) for d in (0.0, 89.0, 178.0)]
    assert h == [round(y0 + d, 3) for d in (0.0, 127.0, 254.0)]
    assert len(plan.cuts) == 6


def test_cells_filling_region_leave_only_the_shared_seam():
    """格子恰好铺满区域时，与区域边界重合的边界不画：178×127 里两张 3R 只有一条竖缝。"""
    plan = pack.pack(specs.find_spec("A4"), specs.find_spec("3R"),
                     printable=specs.RectMM(0.0, 0.0, 178.0, 127.0))
    assert plan.count == 2
    assert [(c.axis, c.at_mm, c.from_mm, c.to_mm) for c in plan.cuts] == [
        ("v", 89.0, 0.0, 127.0)]


def test_cut_spans_full_used_extent():
    plan = _a4_3r()
    seam = next(c for c in plan.cuts
                if c.axis == "v" and round(c.at_mm, 3) == round((210.0 - 178.0) / 2 + 89.0, 3))
    assert seam.from_mm == pytest.approx((297.0 - 254.0) / 2)
    assert seam.to_mm == pytest.approx((297.0 - 254.0) / 2 + 254.0)


def test_single_cell_prints_no_seams():
    plan = pack.pack(specs.find_spec("4R"), specs.find_spec("3R"))
    assert plan.count == 1
    assert plan.cuts == []


def test_no_seam_on_paper_border():
    """满版单格（如 A4 打 A4）不得画任何线。"""
    plan = pack.pack(specs.find_spec("A4"), specs.find_spec("A4"),
                     printable=specs.RectMM(0, 0, 210, 297))
    assert plan.cuts == []


def test_merge_spans_joins_touching_intervals():
    got = pack.merge_spans([(0.0, 10.0), (10.0, 20.0), (30.0, 40.0)])
    assert got == [(0.0, 20.0), (30.0, 40.0)]


def test_no_cell_overlaps_and_stays_inside_region():
    """不变量：任何预设组合下格子不得越出装箱矩形，也不得互相重叠。

    T5 只校了 `used <= w*h`，那个断言既排除不了越界也排除不了重叠（两者
    的面积可以完全合法）。切缝的正确性建立在“格子不重叠”这个前提上，故与切缝
    测试同文件。已真跑 756 组（预设对 × (gap, bleed) 三种）确认 0 违规。
    """
    for sheet in specs.PAPER_PRESETS:
        for cell in specs.CELL_PRESETS + specs.PAPER_PRESETS:
            if cell.key == sheet.key and cell.role == "paper":
                continue
            for gap, bleed in ((0.0, 0.0), (2.0, 0.0), (0.0, 3.0)):
                plan = pack.pack(sheet, cell, gap_mm=gap, bleed_mm=bleed)
                rect = plan.printable
                tag = (sheet.key, cell.key, gap, bleed)
                for c in plan.cells:
                    assert c.x_mm >= rect.x_mm - 1e-6, tag
                    assert c.y_mm >= rect.y_mm - 1e-6, tag
                    assert c.x_mm + c.w_mm <= rect.x_mm + rect.w_mm + 1e-6, tag
                    assert c.y_mm + c.h_mm <= rect.y_mm + rect.h_mm + 1e-6, tag
                for i, a in enumerate(plan.cells):
                    for b in plan.cells[i + 1:]:
                        ox = min(a.x_mm + a.w_mm, b.x_mm + b.w_mm) - max(a.x_mm, b.x_mm)
                        oy = min(a.y_mm + a.h_mm, b.y_mm + b.h_mm) - max(a.y_mm, b.y_mm)
                        assert not (ox > 1e-6 and oy > 1e-6), (tag, a, b)


def test_needed_sheets():
    assert pack.needed_sheets(4, 4) == 1
    assert pack.needed_sheets(4, 5) == 2
    assert pack.needed_sheets(4, 8) == 2
    assert pack.needed_sheets(0, 3) == 0  # 无格子可打属异常，交由调用方提示


def test_bleed_seams_sit_on_the_outer_box_and_need_a_second_trim():
    """出血模式的切缝按格子外框（块=成品+2*bleed）出：沿缝切出 95×133 的块，
    裁到 89×127 是二道精裁，精裁线由渲染层按 inner_mm() 叠加（规格 5.2）。"""
    plan = pack.pack(specs.find_spec("A4"), specs.find_spec("3R"),
                     bleed_mm=3.0, printable=specs.RectMM(0.0, 0.0, 190.0, 133.0))
    assert plan.count == 2
    assert [(c.axis, c.at_mm, c.from_mm, c.to_mm) for c in plan.cuts] == [
        ("v", 95.0, 0.0, 133.0)]
    assert plan.cells[0].inner_mm() == (3.0, 3.0, 89.0, 127.0)
