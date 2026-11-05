"""几何像素断言：dpi=25.4 时 1 像素 = 1 毫米，可直接量坐标。"""
import pytest

Image = pytest.importorskip("PIL.Image", reason="需要 Pillow")
from PIL import Image as PILImage  # noqa: E402

from photoprint.core import modes, pack, render, specs, units  # noqa: E402

DPI = 25.4  # 1px == 1mm


def _photos(n, color):
    return [PILImage.new("RGB", (200, 100), color) for _ in range(n)]


def _a4_3r(mode=modes.FILL_PRINTABLE, bleed=0.0, photos=None, cut_lines=True):
    # 固定用整张纸作为装箱矩形，坐标可手算：x0=(210-178)/2=16、y0=(297-254)/2=21.5
    # （默认的可打印内缩矩形由 T5 的测试覆盖，本文件只验裁切线几何）
    full = specs.RectMM(0.0, 0.0, 210.0, 297.0)
    plan = pack.pack(specs.find_spec("A4"), specs.find_spec("3R"), bleed_mm=bleed,
                     printable=full)
    imgs = photos or _photos(plan.count, (255, 0, 0))
    return plan, render.render_page(plan, imgs, specs.find_spec("A4"), DPI, mode,
                                   show_cut_lines=cut_lines)


def test_page_size_matches_sheet_in_pixels():
    plan, img = _a4_3r()
    assert img.size == (210, 297)


def test_photo_pixels_present_and_bounded():
    plan, img = _a4_3r(photos=_photos(4, (255, 0, 0)))
    c = plan.cells[0]
    x0 = units.round_px(c.x_mm)
    y0 = units.round_px(c.y_mm)
    assert img.getpixel((x0 + 40, y0 + 60)) == (255, 0, 0)
    # 纸外角落必须是白（A4 无边距未启用时角落在遮罩内，仍非照片色）
    assert img.getpixel((0, 0)) != (255, 0, 0)


def test_fill_mode_crops_to_cell_exactly():
    """横向 200×100 的照片铺满 89×127 的格：宽被裁，高铺满。
    只放一张照片（其余格留白），否则同行邻格的同色绿会连进扫描区间；
    关切缝叠加：居中装箱的缝在 x=16/105 的格子边界上（T6 裁决两侧都画），
    会盖掉照片首列——那是画线预期行为，与本条的几何断言无关，
    缝自身的像素位置由后面的裁切线测试钉住。"""
    green = PILImage.new("RGB", (200, 100), (0, 255, 0))
    plan, img = _a4_3r(photos=[green], cut_lines=False)
    c = plan.cells[0]
    x0, y0 = units.round_px(c.x_mm), units.round_px(c.y_mm)
    col = [x for x in range(210) if img.getpixel((x, y0 + 60)) == (0, 255, 0)]
    assert min(col) == x0
    assert max(col) - min(col) + 1 == 89


def test_bleed_mode_overlays_inner_trim_guides():
    """BLEED_TRIM 的两道切线：外框缝（粗切）由 build_cuts 给出并被切缝测试钉住，
    本条钉第二道：按 inner_mm() 画的精裁线（T6 裁决，规格 5.2）。
    内框比块边内缩 3px（dpi=25.4），线压在照片出血区上，精裁后正好消失。"""
    green = PILImage.new("RGB", (200, 100), (0, 255, 0))
    plan, img = _a4_3r(mode=modes.BLEED_TRIM, bleed=3.0, photos=[green])
    c = plan.cells[0]
    ix, iy = c.x_mm + c.bleed_mm, c.y_mm + c.bleed_mm   # 内框左上 (13.0, 18.5)
    # 竖精裁线：x=13 像素列非绿，右移一列回绿
    assert img.getpixel((int(ix), int(iy) + 40)) != (0, 255, 0)
    assert img.getpixel((int(ix) + 1, int(iy) + 40)) == (0, 255, 0)
    # 横精裁线：y=18.5 经 round_px 落像素 19，上方出血带仍是绿
    x_mid = int(c.x_mm + c.w_mm / 2.0)                  # 57
    assert img.getpixel((x_mid, int(iy + 0.5))) != (0, 255, 0)
    assert img.getpixel((x_mid, int(iy + 0.5) + 1)) == (0, 255, 0)
    assert img.getpixel((x_mid, int(iy) - 1)) == (0, 255, 0)


def test_mask_covers_physical_margin_band():
    plan, img = _a4_3r(photos=_photos(4, (0, 0, 255)))
    a4 = specs.find_spec("A4")
    # 左边缘 3.4mm 内属不可印区，应被遮罩压暗，不得是纯白也不是照片色
    px = img.getpixel((1, 150))
    assert px != (255, 255, 255)
    assert px != (0, 0, 255)


def test_cut_lines_are_drawn_and_light_gray():
    plan, img = _a4_3r(photos=_photos(4, (255, 0, 0)))
    # 取竖缝：它的 x 落在 at_mm 上，线段沿 y 走（取 cuts[0] 会拿成横缝，
    # 坐标当像素用时会把 x/y 写反，采样点落在照片上而不是线上）
    seam = next(c for c in plan.cuts if c.axis == "v")
    x = units.round_px(seam.at_mm)
    y = units.round_px(seam.from_mm) + 30  # 沿线段方向取一点，避开横缝
    px = img.getpixel((x, y))
    assert abs(px[0] - render.CUT_LINE_GRAY) <= 3
    assert abs(px[1] - render.CUT_LINE_GRAY) <= 3


def test_no_cut_lines_when_single_cell():
    plan = pack.pack(specs.find_spec("4R"), specs.find_spec("3R"))
    img = render.render_page(plan, _photos(1, (255, 0, 0)),
                             specs.find_spec("4R"), DPI, modes.FILL_PRINTABLE)
    assert img.size == (102, 152)
    assert plan.count == 1


def test_cut_lines_can_be_hidden():
    plan, shown = _a4_3r(photos=_photos(4, (255, 0, 0)))
    hidden = render.render_page(plan, _photos(4, (255, 0, 0)),
                                specs.find_spec("A4"), DPI, modes.FILL_PRINTABLE,
                                show_cut_lines=False)
    # 同一个采样点：画时是灰线，关掉后必须变回照片色（1px=1mm）
    seam = next(c for c in plan.cuts if c.axis == "v")
    x = units.round_px(seam.at_mm)
    y = units.round_px(seam.from_mm) + 30
    assert shown.getpixel((x, y)) != (255, 0, 0)
    assert hidden.getpixel((x, y)) == (255, 0, 0)


def test_bleed_cells_extend_beyond_inner_photo():
    plan, img = _a4_3r(mode=modes.BLEED_TRIM, bleed=3.0, photos=_photos(4, (9, 9, 9)))
    c = plan.cells[0]
    # 出血格的外框 95×133，内缩 3mm 后才是 89×127 成品；画面应铺到外框
    assert img.getpixel((units.round_px(c.x_mm) + 1, units.round_px(c.y_mm) + 1)) == (9, 9, 9)


def test_photo_count_mismatch_leaves_remaining_cells_white():
    plan = pack.pack(specs.find_spec("A4"), specs.find_spec("3R"),
                     printable=specs.RectMM(0.0, 0.0, 210.0, 297.0))
    assert plan.count == 4
    img = render.render_page(plan, _photos(2, (255, 0, 0)), specs.find_spec("A4"),
                             DPI, modes.FILL_PRINTABLE)
    assert img.size == (210, 297)
    # 第 4 格没有照片，必须保持纸白，不能被上一张残留内容污染
    c3 = plan.cells[3]
    assert img.getpixel((units.round_px(c3.x_mm) + 40, units.round_px(c3.y_mm) + 60)) == (255, 255, 255)


def test_rotated_cell_places_rotated_photo():
    """A4 打 4R 需要横放：照片转 90° 后必须正好落在格内（C1 回归）。

    旧版用 [None] * count 渲染——整页全白也能通过，等于什么都没测。
    旋转格的 dest_mm 是旋转前的 (w, h)，若不交换轴就按 (102, 152) 缩放，
    实际宽度会被撑到 152mm 冲进邻格并越过纸边（终审 C1 实测）。
    """
    a4 = specs.find_spec("A4")
    plan = pack.pack(a4, specs.find_spec("4R"), printable=specs.printable_rect(a4))
    assert plan.count == 2 and all(c.rotated for c in plan.cells)
    img = render.render_page(plan, _photos(plan.count, (255, 0, 0)), a4, DPI,
                             modes.FILL_PRINTABLE, show_cut_lines=False,
                             show_mask=False)
    assert img.size == (210, 297)
    for c in plan.cells:
        x0, y0 = units.round_px(c.x_mm), units.round_px(c.y_mm)
        w, h = units.round_px(c.w_mm), units.round_px(c.h_mm)
        for pt in ((x0 + 1, y0 + 1), (x0 + w - 2, y0 + 1),
                   (x0 + 1, y0 + h - 2), (x0 + w - 2, y0 + h - 2)):
            assert img.getpixel(pt) == (255, 0, 0), (c, pt)
    # 溢出的画面会越过格子边界：格间留白必须仍是纸白
    assert img.getpixel((0, 0)) == (255, 255, 255)


def test_single_cell_on_same_size_paper_stays_inside_printable():
    """退化情形：3R 纸只放一格，画面必须收进可打印区而不是被边距吃掉。"""
    r3 = specs.find_spec("3R")
    plan = pack.pack(r3, r3, printable=specs.RectMM(0, 0, 89.0, 127.0))
    assert plan.count == 1
    img = render.render_page(plan, _photos(1, (255, 0, 0)), r3, DPI,
                             modes.FILL_PRINTABLE, show_mask=False)
    assert img.size == (89, 127)
    assert img.getpixel((1, 63)) != (255, 0, 0)   # 左边 3.4mm 内是物理不可印区
    assert img.getpixel((45, 63)) == (255, 0, 0)  # 可打印区中心有画面


def test_intersect_mm():
    a = (0.0, 0.0, 89.0, 127.0)
    b = (3.4, 3.0, 82.2, 119.0)
    x, y, w, h = render.intersect_mm(a, b)
    assert (round(x, 3), round(y, 3)) == (3.4, 3.0)
    assert (round(w, 3), round(h, 3)) == (82.2, 119.0)
    assert render.intersect_mm((0, 0, 1, 1), (5, 5, 1, 1)) is None
