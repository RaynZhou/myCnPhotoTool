"""混合带搜索的价值证明：A4 打 6寸必须靠一刀双带才能到 3 张。"""
import pytest

from photoprint.core import pack, specs


def _p(sheet_key, cell_key, gap=0.0, bleed=0.0, printable=None, allow_rotate=True):
    sheet = specs.find_spec(sheet_key)
    cell = specs.find_spec(cell_key)
    return pack.pack(sheet, cell, gap_mm=gap, bleed_mm=bleed,
                     allow_rotate=allow_rotate, printable=printable)


def test_a4_holds_four_3r():
    plan = _p("A4", "3R")
    assert plan.count == 4
    assert plan.strategy == "uniform"


def test_a4_holds_three_4r_only_via_band_split():
    """单网格最多 2；切位 y=152 分两带（上带 2 竖 + 下带 1 横）= 3。"""
    plan = _p("A4", "4R")
    assert plan.count == 3
    assert plan.strategy == "bands"
    orientations = {c.rotated for c in plan.cells}
    assert orientations == {False, True}  # 混合朝向，故必须混合带才解得出


def test_a4_holds_two_5r_and_area_bound_proves_three_impossible():
    plan = _p("A4", "5R")
    assert plan.count == 2
    assert 3 * 127.0 * 178.0 > 210.0 * 297.0  # 面积上界排除 3 张


def test_4r_paper_cannot_hold_two_3r():
    plan = _p("4R", "3R")
    assert plan.count == 1


def test_a4_with_bleed_still_four_3r():
    plan = _p("A4", "3R", bleed=3.0)
    assert plan.count == 4
    assert plan.cells[0].w_mm == pytest.approx(95.0)
    assert plan.cells[0].h_mm == pytest.approx(133.0)


def test_id_photo_counts_on_a4_with_gap():
    """证件照格子不得旋转：一寸 7×8=56、二寸 5×5=25（规格 5.3）。

    允许旋转时网格会取两种朝向的较大者，寸照张数只会虚高（一寸虚高到 66+），
    但横放的格子会让贴出来的证件照躺倒，所以界面层对 role=cell 必须传
    allow_rotate=False。这里同时断言“旋转不减反增”，把两种行为都钉住。
    """
    assert _p("A4", "ID1", gap=2.0, allow_rotate=False).count == 56
    assert _p("A4", "ID2", gap=2.0, allow_rotate=False).count == 25
    assert _p("A4", "ID1", gap=2.0).count > 56


def test_printable_area_shrink_keeps_four_3r():
    """A4 减去物理边距后仍应放得下 4 张 5寸（规格 5.3 末行）。"""
    plan = _p("A4", "3R")
    assert plan.count == 4
    shrunk = pack.pack(specs.find_spec("A4"), specs.find_spec("3R"),
                       printable=specs.printable_rect(specs.find_spec("A4")))
    assert shrunk.count == 4


def test_area_invariant_holds_for_every_preset_pair():
    for sheet in specs.PAPER_PRESETS:
        for cell in specs.CELL_PRESETS + specs.PAPER_PRESETS:
            if cell.key == sheet.key and cell.role == "paper":
                continue
            plan = pack.pack(sheet, cell)
            used = sum(c.w_mm * c.h_mm for c in plan.cells)
            assert used <= sheet.w_mm * sheet.h_mm + 1e-6


def test_waste_is_reported():
    plan = _p("A4", "3R")
    assert plan.waste_mm2 == pytest.approx(210 * 297 - 4 * 89 * 127)


def test_tie_break_prefers_uniform_over_edge_flush_bands():
    """张数与浪费全同时，贴边的双带解不得赢过居中的均匀网格。

    均匀网格解的外接框是 178×254（更方正），左带贴边、格子间距 89+0 的一刀双带解
    外接框 194×254（更接近正方形）。若决胜序里“策略简单”不排在“外接框方”
    之前，贴边解会靠更方正的外接框胜出，而它既不居中、列间隙也不均匀。
    规格 5.2 的决胜②就为了这条而存在。
    """
    plan = _p("A4", "3R")
    assert plan.strategy == "uniform"
    assert all(not c.rotated for c in plan.cells)  # 同向优先
    xs = [c.x_mm for c in plan.cells]
    assert min(xs) == pytest.approx((210.0 - 178.0) / 2)
    assert max(xs) == pytest.approx((210.0 - 178.0) / 2 + 89.0)
    # 列间隙全等（而不是 0mm 与 16mm 交替）：先取去重后的列坐标再比相邻差
    cols = sorted(set(xs))
    assert sorted({round(b - a, 6) for a, b in zip(cols, cols[1:])}) == [89.0]
