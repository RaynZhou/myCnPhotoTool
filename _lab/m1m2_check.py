"""M1/M2 验收：不连打印机也能把几何做实。中文注释。

跑法：python _lab/m1m2_check.py
产出：_lab/out/ 下的 PNG 与 PDF，可用尺子和 Acrobat 逐项核对。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw  # noqa: E402

from photoprint.core import modes, pack, render, specs, units  # noqa: E402
from photoprint.win import pdf_export  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(parents=True, exist_ok=True)
DPI = 25.4  # 1px = 1mm，量得动


def synth(n, seed):
    """生成带网格的假照片，便于肉眼检查缩放与裁切是否变形。"""
    img = Image.new("RGB", (600, 300), (240, 240, 255))
    d = ImageDraw.Draw(img)
    for x in range(0, 600, 25):
        d.line([(x, 0), (x, 300)], fill=(200, 60, 60), width=2)
    for y in range(0, 300, 25):
        d.line([(0, y), (600, y)], fill=(60, 60, 200), width=2)
    d.rectangle([seed * 10, 10, seed * 10 + 120, 60], fill=(0, 0, 0))
    return img


def check(name, got, want, tol=1e-6):
    ok = abs(got - want) <= tol
    print(f"{'OK ' if ok else 'BAD'} {name}: {got} (期望 {want})")
    return ok


def main():
    allok = True
    a4, r3 = specs.find_spec("A4"), specs.find_spec("3R")

    # 1) A4 + 3R 出血 3mm：4 格，裁切后每格 89×127
    plan = pack.pack(a4, r3, bleed_mm=modes.DEFAULT_BLEED_MM,
                     printable=specs.RectMM(0, 0, a4.w_mm, a4.h_mm))
    allok &= check("A4+3R(bleed3) 格数", plan.count, 4)
    allok &= check("裁切线数", len(plan.cuts), 6)  # 居中 2×2：每轴 3 条（两侧边界 + 中间缝）
    page = render.render_page(plan, [synth(4, i) for i in range(4)], a4, DPI,
                              modes.BLEED_TRIM)
    allok &= check("页面宽 mm=px", page.width, 210)
    allok &= check("页面高 mm=px", page.height, 297)
    png = OUT / "a4_3r_bleed.png"
    page.save(png)
    print(f"→ 用尺子量 {png}：灰线间距应为 89.0 与 127.0 mm（屏幕 100% 显示）")

    # 2) A4 + 4R 混合带：3 格（含旋转格）
    p2 = pack.pack(a4, specs.find_spec("4R"))
    allok &= check("A4+4R 格数", p2.count, 3)
    # 旋转格落位（终审 C1）：按可打印区装箱后逐格校验四角内侧像素都是照片色。
    # 照片按未旋转的轴缩放会撑出格子压到邻格，这一条会在画面上当场抓住。
    p2p = pack.pack(a4, specs.find_spec("4R"),
                    printable=specs.printable_rect(a4))
    allok &= check("A4+4R(可打印区) 旋转格数",
                   sum(1 for c in p2p.cells if c.rotated), 2)
    red = Image.new("RGB", (600, 400), (255, 0, 0))
    page2 = render.render_page(p2p, [red] * p2p.count, a4, DPI,
                               modes.FILL_PRINTABLE, show_cut_lines=False,
                               show_mask=False)
    bad = []
    for c in p2p.cells:
        x0, y0 = units.round_px(c.x_mm), units.round_px(c.y_mm)
        w, h = units.round_px(c.w_mm), units.round_px(c.h_mm)
        for pt in ((x0 + 1, y0 + 1), (x0 + w - 2, y0 + 1),
                   (x0 + 1, y0 + h - 2), (x0 + w - 2, y0 + h - 2)):
            if page2.getpixel(pt) != (255, 0, 0):
                bad.append((pt, page2.getpixel(pt)))
    allok &= check("A4+4R 每格四角都在格内（越界点数）", len(bad), 0)
    page2.save(OUT / "a4_4r_rotated.png")
    print(f"→ 看一眼 {OUT / 'a4_4r_rotated.png'}：旋转格里的照片不得压到邻格")

    # 3) 3R 直打：可打印区 82.2×119.0（换算唯一入口 specs.printable_rect）
    pr = specs.printable_rect(r3)
    allok &= check("3R 可打印宽", pr.w_mm, 82.2, 1e-3)
    allok &= check("3R 可打印高", pr.h_mm, 119.0, 1e-3)
    # pack 默认区域是整张纸，拿不到可打印矩形；退化直打仍整纸装一格，
    # 画面收回可打印区由 render 层的交集负责。
    p3 = pack.pack(r3, r3)
    page3 = render.render_page(p3, [synth(1, 0)], r3, DPI, modes.FILL_PRINTABLE)
    allok &= check("3R 页面宽", page3.width, 89)

    # 4) 等尺寸 PDF：MediaBox 点数
    pdf = OUT / "single_3r.pdf"
    pdf_export.export_pdf([page3], r3, pdf)
    m = re.search(rb"MediaBox\s*\[([\d.\s]+)\]", pdf.read_bytes())
    vals = [float(x) for x in m.group(1).split()]
    allok &= check("3R PDF 宽(pt)", vals[2], 252.283, 1.0)
    allok &= check("3R PDF 高(pt)", vals[3], 360.0, 1.0)

    print("\n结论：", "全部通过" if allok else "存在失败项，见上面 BAD 行")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
