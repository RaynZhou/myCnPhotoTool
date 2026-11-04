"""把排版结果渲染成物理尺寸精确的位图。

约定：1 像素 = 1/dpi 毫米，页面像素 = round(sheet_mm * ppmm)。
预览层不走这里——预览用同一个 crop.cell_crop_box，但目标换成屏幕像素，
这样"所见即所得"是构造出来的，而不是靠两边各写一套再祈祷一致。
"""
from __future__ import annotations

from PIL import Image, ImageDraw

from photoprint.core import crop, modes, specs, units

CUT_LINE_GRAY = 217  # 15% 灰：不抢画面，又能在照片上看见
CUT_LINE_MM = 0.35
MASK_RGB = (150, 150, 150)
_MASK_ALPHA = 110


def intersect_mm(a, b):
    """两个 (x, y, w, h) 矩形求交，不相交返回 None。"""
    ax2, ay2 = a[0] + a[2], a[1] + a[3]
    bx2, by2 = b[0] + b[2], b[1] + b[3]
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(ax2, bx2), min(ay2, by2)
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2 - x1, y2 - y1)


def _mask_bands(sheet, rect):
    """返回物理不可印区的四个矩形（mm），仅在未启用无边距时给出。"""
    m = sheet.margins
    w, h = sheet.w_mm, sheet.h_mm
    return [
        (0.0, 0.0, w, m.top),
        (0.0, h - m.bottom, w, m.bottom),
        (0.0, 0.0, m.left, h),
        (w - m.right, 0.0, m.right, h),
    ]


def render_page(plan, photos, sheet, dpi, mode, show_mask=True,
                show_cut_lines=True, borderless_active=False):
    """渲染一页。photos 与 plan.cells 一一对应，None 表示空格（留白）。"""
    px_w = units.mm_to_px(sheet.w_mm, dpi)
    px_h = units.mm_to_px(sheet.h_mm, dpi)
    page = Image.new("RGB", (px_w, px_h), (255, 255, 255))
    draw = ImageDraw.Draw(page, "RGBA")
    cm = modes.crop_mode(mode)
    # 可打印矩形与装箱无关，始终由规格边距推出；无边距实测生效时它就是整张纸
    printable = specs.printable_rect(sheet, borderless_active=borderless_active)

    for idx, cell in enumerate(plan.cells):
        photo = photos[idx] if idx < len(photos) else None
        if photo is None:
            continue
        # BLEED 用外框（出血就故意外伸到纸边，裁掉后正好得到成品尺寸）；
        # 其余用内框并与可打印矩形求交，处理“整纸只放一格”的退化情形
        if mode == modes.BLEED_TRIM:
            ox, oy, ow, oh = cell.x_mm, cell.y_mm, cell.w_mm, cell.h_mm
        else:
            got = intersect_mm(cell.inner_mm(),
                               (printable.x_mm, printable.y_mm,
                                printable.w_mm, printable.h_mm))
            if got is None:
                continue
            ox, oy, ow, oh = got
        # 旋转格：先把原图按未旋转的目标比例裁，再转 90°，尺寸正好对上外框
        target_w, target_h = (oh, ow) if cell.rotated else (ow, oh)
        pl = crop.cell_crop_box(photo.width, photo.height, target_w, target_h,
                               cm, ppmm=units.ppmm(dpi))
        piece = photo.crop(pl.crop_px)
        # dest_mm 是旋转前的目标矩形（宽高按未旋转的格子算）：照片转 90° 后
        # 宽高互换，落位偏移也须互换，否则尺寸检查拿错轴、缩放补偿到错误的
        # (w, h)，画面会撑出格子并压到邻格（终审 C1 实测）
        dx, dy, dw, dh = pl.dest_mm
        if cell.rotated:
            piece = piece.transpose(Image.ROTATE_270)
            dx, dy, dw, dh = dy, dx, dh, dw
        if dw and (abs(dw - piece.width / units.ppmm(dpi)) > 0.6
                   or abs(dh - piece.height / units.ppmm(dpi)) > 0.6):
            piece = piece.resize((max(1, units.round_px(dw * units.ppmm(dpi))),
                                  max(1, units.round_px(dh * units.ppmm(dpi)))),
                                 Image.LANCZOS)
        paste_x = units.mm_to_px(ox + dx, dpi)
        paste_y = units.mm_to_px(oy + dy, dpi)
        page.paste(piece, (paste_x, paste_y))

    # 遮罩在照片之后绘制，使“这条边打不出来”的警告始终可见；
    # 正常拼版下照片都在可打印区内，不会被遮罩压到
    if show_mask and not borderless_active:
        for bx, by, bw, bh in _mask_bands(sheet, plan.printable):
            draw.rectangle(
                [units.mm_to_px(bx, dpi), units.mm_to_px(by, dpi),
                 units.mm_to_px(bx + bw, dpi) - 1, units.mm_to_px(by + bh, dpi) - 1],
                fill=MASK_RGB + (_MASK_ALPHA,))

    if show_cut_lines and len(plan.cells) >= 2:
        lw = max(1, units.mm_to_px(CUT_LINE_MM, dpi))
        for cut in plan.cuts:
            if cut.axis == "v":
                x = units.mm_to_px(cut.at_mm, dpi)
                draw.line([(x, units.mm_to_px(cut.from_mm, dpi)),
                           (x, units.mm_to_px(cut.to_mm, dpi))],
                          fill=(CUT_LINE_GRAY, CUT_LINE_GRAY, CUT_LINE_GRAY), width=lw)
            else:
                y = units.mm_to_px(cut.at_mm, dpi)
                draw.line([(units.mm_to_px(cut.from_mm, dpi), y),
                           (units.mm_to_px(cut.to_mm, dpi), y)],
                          fill=(CUT_LINE_GRAY, CUT_LINE_GRAY, CUT_LINE_GRAY), width=lw)

    # 出血模式的切缝是两道（T6 裁决，规格 5.2）：build_cuts 给的是外框缝
    # = 粗切落刀位；精裁的第二道线由内框 inner_mm() 推出，在这里压在照片
    # 出血区上，精裁后正好随成品边缘消失。单格也要画精裁线（外框缝没有，
    # 出血仍需精裁）
    if show_cut_lines and mode == modes.BLEED_TRIM:
        lw = max(1, units.mm_to_px(CUT_LINE_MM, dpi))
        for cell in plan.cells:
            ix, iy, iw, ih = cell.inner_mm()
            x2, y2 = ix + iw, iy + ih
            for x0, y0, x1, y1 in ((ix, iy, ix, y2), (x2, iy, x2, y2),
                                   (ix, iy, x2, iy), (ix, y2, x2, y2)):
                draw.line([(units.mm_to_px(x0, dpi), units.mm_to_px(y0, dpi)),
                           (units.mm_to_px(x1, dpi), units.mm_to_px(y1, dpi))],
                          fill=(CUT_LINE_GRAY, CUT_LINE_GRAY, CUT_LINE_GRAY),
                          width=lw)
    return page
