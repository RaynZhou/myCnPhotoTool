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
                               dy_mm=1.0)
    probe = (int(ix + iw / 2), int(iy + 4.0))
    assert base.getpixel(probe) == (255, 0, 0)      # 原画面覆盖
    assert moved.getpixel(probe) == (255, 255, 255)  # 下移 1mm 后露白
    tail = (int(ix + iw / 2), int(iy + 29.0))
    assert base.getpixel(tail) == (255, 255, 255)
    assert moved.getpixel(tail) == (255, 0, 0)


def test_dx_offset_moves_rotated_cell_picture_right_on_paper():
    """旋转格的纸面水平偏移必须真往右：旧转置写法会整体反号（终审 C1）。

    A4+4R 两格都是旋转格，纸面格子 152×102，旋转前目标 102×152；
    正方形照片 FIT 后为 102×102，纸面起点 x = 29+25 = 54（占 54..155）。
    dx_mm=+3 → 旋转前 dy=-3 → 纸面起点 x=57（占 57..158）。
    """
    a4, r4 = specs.find_spec("A4"), specs.find_spec("4R")
    plan = pack.pack(a4, r4, gap_mm=0.0, allow_rotate=True,
                     printable=specs.printable_rect(a4))
    assert [c.rotated for c in plan.cells] == [True, True]
    photo = Image.new("RGB", (100, 100), (255, 0, 0))
    args = (plan, [photo] * plan.count, a4, DPI, modes.FIT_TO_PRINTABLE)
    base = render.render_page(*args, show_mask=False)
    moved = render.render_page(*args, show_mask=False, dx_mm=3.0)
    assert base.getpixel((55, 95)) == (255, 0, 0)       # 起点左侧 1mm 仍在画内
    assert moved.getpixel((55, 95)) == (255, 255, 255)  # 右移 3mm 后露白
    assert base.getpixel((157, 95)) == (255, 255, 255)  # 原本右侧留白 25mm
    assert moved.getpixel((157, 95)) == (255, 0, 0)     # 移进来才见红


def test_fill_mode_offset_moves_picture_toward_paper_direction():
    """FILL 的 dx/dy 在 crop 里挪的是取景窗，画面在纸面上反向；
    界面偏移是纸面语义，渲染层须按模式补一次反号。"""
    a4, plan = _a4_id1_plan()
    photo = Image.new("RGB", (200, 100), (255, 255, 255))
    photo.paste(Image.new("RGB", (40, 100), (255, 0, 0)), (80, 0))  # 中央红带
    ix, iy, iw, ih = plan.cells[0].inner_mm()
    y = int(iy + ih / 2)
    args = (plan, [photo] * plan.count, a4, DPI, modes.FILL_PRINTABLE)
    low = render.render_page(*args, show_mask=False, dx_mm=-3.0)
    high = render.render_page(*args, show_mask=False, dx_mm=3.0)

    def first_red(page):
        return min(x for x in range(int(ix), int(ix + iw))
                   if page.getpixel((x, y)) == (255, 0, 0))

    assert first_red(high) > first_red(low)  # dx 为正 → 画面往纸面右边走


def test_offset_mm_for_cell_half_page_is_50_pct():
    """±50% 就是半格：ID1 内框 25×32 → 12.5 / 16.0mm。"""
    assert render.offset_mm_for_cell((50.0, -50.0), 25.0, 32.0) == (12.5, -16.0)


def test_offset_mm_for_cell_zero_is_zero():
    assert render.offset_mm_for_cell((0.0, 0.0), 89.0, 127.0) == (0.0, 0.0)
