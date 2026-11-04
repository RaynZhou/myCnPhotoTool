"""偏移透传与旋转落位映射。旋转映射必须与旧转置在居中时逐像素等价。"""
import pytest

pytest.importorskip("PIL", reason="需要 Pillow")

from PIL import Image  # noqa: E402

from photoprint.core import modes, pack, render, specs  # noqa: E402

DPI = 25.4  # 1 像素 = 1 毫米，便于直接按 mm 取点


def _a4_id1_plan():
    a4, id1 = specs.find_spec("A4"), specs.find_spec("ID1")
    return a4, pack.pack(a4, id1, gap_mm=2.0, allow_rotate=False,
                         printable=specs.printable_rect(a4))


def test_place_rotated_dest_equals_transpose_when_centered():
    """居中回归锁：旋转前目标高 100、画面高 40 居中 → dy=30，
    真旋转映射给 x'=30，与旧转置 (dy,dx,dh,dw) 完全相同。"""
    got = render.place_rotated_dest((10.0, 30.0, 60.0, 40.0), 100.0)
    assert got == pytest.approx((30.0, 10.0, 40.0, 60.0))


def test_place_rotated_dest_flips_horizontal_when_off_center():
    """偏上落位（dy=10 < 居中值 30）在纸面上必须靠右，
    旧转置会给出 x'=10（靠左），方向整体反。"""
    got = render.place_rotated_dest((10.0, 10.0, 60.0, 40.0), 100.0)
    assert got[0] == pytest.approx(50.0)


def test_dy_offset_moves_picture_down_on_paper():
    a4, plan = _a4_id1_plan()
    photo = Image.new("RGB", (100, 100), (255, 0, 0))
    cell = plan.cells[0]
    ix, iy, iw, ih = cell.inner_mm()
    # 正方形照片进 25×32 的格：宽填满、上下各留白 (32-25)/2 = 3.5mm
    base = render.render_page(plan, [photo] * plan.count, a4, DPI,
                              modes.FIT_TO_PRINTABLE, show_mask=False)
    moved = render.render_page(plan, [photo] * plan.count, a4, DPI,
                               modes.FIT_TO_PRINTABLE, show_mask=False,
                               offset_pct=(0.0, 100.0 * 1.0 / ih))  # 纸面下移 1mm
    probe = (int(ix + iw / 2), int(iy + 4.0))
    assert base.getpixel(probe) == (255, 0, 0)      # 原画面覆盖
    assert moved.getpixel(probe) == (255, 255, 255)  # 下移 1mm 后露白
    tail = (int(ix + iw / 2), int(iy + 29.0))
    assert base.getpixel(tail) == (255, 255, 255)
    assert moved.getpixel(tail) == (255, 0, 0)


def test_dx_offset_moves_rotated_cell_picture_right_on_paper():
    """旋转格的纸面水平偏移必须真往右：旧转置写法会整体反号（终审 C1）。

    A4+4R 两格都是旋转格；正方形照片 FIT 进旋转前目标后是 102×102，
    在纸面格内左右各留白，起点 x = 格左沿 + (格宽 - 格高)/2。
    探针取起点内 1mm 与右沿外 1mm，偏移 3mm 后两者必须恰好互换。
    """
    a4, r4 = specs.find_spec("A4"), specs.find_spec("4R")
    plan = pack.pack(a4, r4, gap_mm=0.0, allow_rotate=True,
                     printable=specs.printable_rect(a4))
    assert [c.rotated for c in plan.cells] == [True, True]
    cx, cy, cw, ch = plan.cells[0].inner_mm()
    start = int(round(cx + (cw - ch) / 2.0))
    y_mid = int(round(cy + ch / 2.0))
    inside = (start + 1, y_mid)          # 原画面内、右移 3mm 后露白
    outside = (start + ch + 1, y_mid)    # 原留白、右移 3mm 后被覆盖
    photo = Image.new("RGB", (100, 100), (255, 0, 0))
    args = (plan, [photo] * plan.count, a4, DPI, modes.FIT_TO_PRINTABLE)
    pct = (100.0 * 3.0 / cw, 0.0)        # 纸面向右 3mm
    base = render.render_page(*args, show_mask=False)
    moved = render.render_page(*args, show_mask=False, offset_pct=pct)
    assert base.getpixel(inside) == (255, 0, 0), f"起点前提已破：{inside} 应为红"
    assert moved.getpixel(inside) == (255, 255, 255), (
        f"纸面向右 3mm 后 {inside} 应露白（仍为红 = 没动或反向）")
    assert base.getpixel(outside) == (255, 255, 255), f"起点前提已破：{outside} 应为白"
    assert moved.getpixel(outside) == (255, 0, 0), (
        f"纸面向右 3mm 后 {outside} 应转红（仍为白 = 方向反了）")


def test_fill_mode_offset_moves_picture_toward_paper_direction():
    """FILL 的 dx/dy 在 crop 里挪的是取景窗，画面在纸面上反向；
    界面偏移是纸面语义，渲染层须按模式补一次反号。"""
    a4, plan = _a4_id1_plan()
    photo = Image.new("RGB", (200, 100), (255, 255, 255))
    photo.paste(Image.new("RGB", (40, 100), (255, 0, 0)), (80, 0))  # 中央红带
    ix, iy, iw, ih = plan.cells[0].inner_mm()
    y = int(iy + ih / 2)
    args = (plan, [photo] * plan.count, a4, DPI, modes.FILL_PRINTABLE)
    low = render.render_page(*args, show_mask=False,
                             offset_pct=(-100.0 * 3.0 / iw, 0.0))
    high = render.render_page(*args, show_mask=False,
                              offset_pct=(100.0 * 3.0 / iw, 0.0))

    def first_red(page):
        cols = [x for x in range(int(ix), int(ix + iw))
                if page.getpixel((x, y)) == (255, 0, 0)]
        assert cols, "红带不在首格内，测试前提已破"
        return min(cols)

    moved_by = first_red(high) - first_red(low)
    assert moved_by >= 1, f"dx 为正应使画面往纸面右边走，实际差 {moved_by}px"


def test_offset_pct_is_applied_per_cell_on_mixed_orientation_page():
    """混合朝向页（7R+3R 的 bands 装箱）：偏移必须逐格按本格尺寸换算。

    首格是转置格（纸面 127×89），第二格是竖格（89×127）。offset_pct=(0, 15)
    按第二格自己的高 127 算是 19.05mm（被留白夹到 19），画面顶沿落在 145；
    若按首格高 89 算只有 13.35mm，顶沿落在 139——探针 142 一个是白、一个是红。
    """
    sheet, cell = specs.find_spec("7R"), specs.find_spec("3R")
    plan = pack.pack(sheet, cell, gap_mm=0.0, allow_rotate=True,
                     printable=specs.printable_rect(sheet))
    assert [c.rotated for c in plan.cells] == [True, False, False]
    bx, by, bw, bh = plan.cells[1].inner_mm()
    photo = Image.new("RGB", (100, 100), (255, 0, 0))
    args = (plan, [photo] * plan.count, sheet, DPI, modes.FIT_TO_PRINTABLE)
    base = render.render_page(*args, show_mask=False)
    moved = render.render_page(*args, show_mask=False, offset_pct=(0.0, 15.0))
    probe = (int(bx + bw / 2), int(by + 35.0))     # 本格画面顶沿下方 16mm
    assert base.getpixel(probe) == (255, 0, 0), f"零偏移下第二格顶沿应经过探针 {probe}"
    assert moved.getpixel(probe) == (255, 255, 255), (
        f"偏移未按本格高 {bh:.0f}mm 换算（按首格算的话顶沿只到 139mm，"
        f"探针 {probe} 仍在画内）")


def test_offset_mm_for_cell_half_page_is_50_pct():
    """±50% 就是半格：ID1 内框 25×32 → 12.5 / 16.0mm。"""
    assert render.offset_mm_for_cell((50.0, -50.0), 25.0, 32.0) == (12.5, -16.0)


def test_offset_mm_for_cell_zero_is_zero():
    assert render.offset_mm_for_cell((0.0, 0.0), 89.0, 127.0) == (0.0, 0.0)
