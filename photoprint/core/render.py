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

# 逐图旋转（M3-GUI 增量）：顺时针角度 → PIL transpose 操作。
# PIL 的 ROTATE_270 是顺时针 90°，与旋转格既有用法同口径。
_ANGLE_TRANSPOSE = {90: Image.ROTATE_270, 180: Image.ROTATE_180,
                    270: Image.ROTATE_90}


def _apply_rotation(photo, angle):
    """按顺时针 angle° 转照片。非法角度一律按 0（不转）降级：旋转是增强项，
    一次坏数据不得把整页渲染打死（与 store 的"任何损坏降级成没有"同口径）。
    归一必须是 90 的整数倍，45° 一类残余不得借 `% 360` 混进映射表。"""
    try:
        op = _ANGLE_TRANSPOSE.get(int(angle) % 360)
    except (TypeError, ValueError):
        return photo
    return photo if op is None else photo.transpose(op)


def intersect_mm(a, b):
    """两个 (x, y, w, h) 矩形求交，不相交返回 None。"""
    ax2, ay2 = a[0] + a[2], a[1] + a[3]
    bx2, by2 = b[0] + b[2], b[1] + b[3]
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(ax2, bx2), min(ay2, by2)
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2 - x1, y2 - y1)


def place_rotated_dest(dest_mm, target_h_mm):
    """旋转前落位 → 纸面落位：顺时针 90° 时 x' = H-(y+h)，y' = x。

    旧写法 `dx, dy, dw, dh = dy, dx, dh, dw` 是转置，只在落位居中时与真旋转
    等价；一旦有裁切偏移，水平方向会整体反号（终审对旋转落位的补充说明）。
    """
    dx, dy, dw, dh = dest_mm
    return ((target_h_mm - dh) - dy, dx, dh, dw)


def offset_mm_for_cell(offset_pct, w_mm, h_mm):
    """百分比偏移 → 该格的 mm 偏移：±50% 即最多挪半格。

    换算本体留在 core：界面层禁做几何，而「按哪个尺寸换算」本身就是几何决策。
    必须逐格调用（拿本格尺寸），同一页两种朝向的格子若不逐格算，±50% 就只对
    算出的那一格成立（T3 评审 I-1）。
    """
    return (offset_pct[0] / 100.0 * w_mm, offset_pct[1] / 100.0 * h_mm)


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
                show_cut_lines=True, borderless_active=False,
                offset_pct=(0.0, 0.0), rotations=()):
    """渲染一页。photos 与 plan.cells 一一对应，None 表示空格（留白）。

    rotations 是逐图顺时针角度（短于 photos 缺位按 0）：生效照片在取尺寸之前
    换好，其余几何一条规则不改——"渲染时转"与"读图时预转好"逐像素等价。"""
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
        # 逐图旋转必须早于任何 photo.width/height 取值：转完的才是生效照片
        photo = _apply_rotation(photo, rotations[idx] if idx < len(rotations) else 0)
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
        # 偏移是纸面语义且按本格尺寸逐格换算；旋转格还要再换算到旋转前坐标
        cell_dx, cell_dy = offset_mm_for_cell(offset_pct, ow, oh)
        in_dx, in_dy = crop.rotate_offset(cell_dx, cell_dy) if cell.rotated \
            else (cell_dx, cell_dy)
        if cm == crop.FILL:
            # FILL 的 dx/dy 挪的是取景窗，画面在纸面上会反向；fit 挪的是
            # 落位矩形，本身已是纸面语义，故只在 fill 档补一次反号
            in_dx, in_dy = -in_dx, -in_dy
        pl = crop.cell_crop_box(photo.width, photo.height, target_w, target_h,
                               cm, dx_mm=in_dx, dy_mm=in_dy,
                               ppmm=units.ppmm(dpi))
        piece = photo.crop(pl.crop_px)
        # 旋转格还要把落位换轴：照片转 90° 后宽高互换，若沿用旋转前的
        # (dx, dy)，尺寸检查会拿错轴、缩放补偿到错误的 (w, h)，画面会撑出
        # 格子并压到邻格（终审 C1 实测），映射见 place_rotated_dest
        if cell.rotated:
            piece = piece.transpose(Image.ROTATE_270)
            dx, dy, dw, dh = place_rotated_dest(pl.dest_mm, target_h)
        else:
            dx, dy, dw, dh = pl.dest_mm
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
