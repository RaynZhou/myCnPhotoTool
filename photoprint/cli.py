"""命令行编排：探测 → 装箱 → 裁切 → 渲染 → 直打/PDF。

本文件不得包含任何 mm/像素或裁切几何计算，一律调用 core/。
"""
from __future__ import annotations

import argparse
import sys

from PIL import Image

from photoprint.core import modes, pack, render, specs, store


def load_photo(path):
    """读图并让 EXIF 方向生效，避免界面与打印各转一次。"""
    from PIL import ImageOps

    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


def build_plan_jobs(st, sheet_key, cell_key, gap_mm, bleed_mm, mode,
                    borderless_active):
    """返回 (排版方案, 生效模式)。mode 为 None 时按默认映射决定。"""
    sheet = st.resolve(sheet_key)
    cell = st.resolve(cell_key)
    printable = specs.printable_rect(sheet, borderless_active=borderless_active)
    probe_plan = pack.pack(sheet, cell, gap_mm=gap_mm, bleed_mm=0.0,
                           printable=printable)
    if mode is None:
        mode = modes.default_mode(sheet, cell, probe_plan.count, borderless_active)
    modes.assert_mode_legal(sheet, mode)
    bleed = bleed_mm if mode == modes.BLEED_TRIM else 0.0
    # 裁切模式在整张纸上装箱（无边距才容得下出血），其余在可打印区内装箱
    rect = specs.RectMM(0.0, 0.0, sheet.w_mm, sheet.h_mm) \
        if mode == modes.BLEED_TRIM else printable
    plan = pack.pack(sheet, cell, gap_mm=gap_mm, bleed_mm=bleed, printable=rect)
    if plan.count == 0 and mode != modes.BLEED_TRIM:
        # 退化情形：格子与纸张同尺寸（如 3R 纸打 3R 照片）。
        # 按可打印矩形装箱必然得 0 格，改为整纸装一格，
        # 画面收回可打印区由 render 层的交集负责。
        full = specs.RectMM(0.0, 0.0, sheet.w_mm, sheet.h_mm)
        plan = pack.pack(sheet, cell, gap_mm=gap_mm, bleed_mm=0.0, printable=full)
    if plan.count == 0:
        raise ValueError(f"{sheet.label} 放不下 {cell.label}，请换大纸或改小格子")
    return plan, mode


def _pages(plan, photos, sheet, dpi, mode, **kw):
    """按每页格子数切页。"""
    out = []
    for i in range(0, len(photos), plan.count):
        chunk = photos[i:i + plan.count]
        out.append(render.render_page(plan, chunk, sheet, dpi, mode, **kw))
    return out


def build_parser():
    ap = argparse.ArgumentParser(prog="photoprint", description="相片拼版打印")
    ap.add_argument("--photos", nargs="*", default=[])
    ap.add_argument("--printer", default=None)
    ap.add_argument("--sheet", default="A4")
    ap.add_argument("--cell", default="3R")
    ap.add_argument("--mode", default=None, choices=list(modes.MODES))
    ap.add_argument("--gap", type=float, default=0.0)
    ap.add_argument("--bleed", type=float, default=modes.DEFAULT_BLEED_MM)
    ap.add_argument("--dpi", type=float, default=300.0)
    ap.add_argument("--out", default=None, help="输出 PNG 路径（调试与验收用）")
    ap.add_argument("--pdf", default=None, help="兜底：输出等尺寸 PDF")
    ap.add_argument("--print", dest="do_print", action="store_true")
    ap.add_argument("--list-printers", action="store_true")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    st = store.Store()
    st.load()

    if args.list_printers:
        from photoprint.win import api as win_api

        for name in win_api.RealWinApi().enum_printers():
            print(name)
        return 0

    if not args.photos:
        print("没有照片：请用 --photos 指定至少一张", file=sys.stderr)
        return 2

    photos = [load_photo(p) for p in args.photos]
    sheet = st.resolve(args.sheet)
    plan, mode = build_plan_jobs(st, args.sheet, args.cell, args.gap,
                                args.bleed, args.mode, False)
    pages = _pages(plan, photos, sheet, args.dpi, mode)

    borderless = mode == modes.BLEED_TRIM
    note = ("需人工裁切：沿灰线切开后即为 "
            f"{plan.cells[0].inner_mm()[2]:.0f}×{plan.cells[0].inner_mm()[3]:.0f}mm 成品"
            if borderless else
            f"将保留白边：依规格约 上{sheet.margins.top}/下{sheet.margins.bottom}/"
            f"左{sheet.margins.left}/右{sheet.margins.right}mm（未经真机校准）")
    print(f"纸张 {sheet.label}，每页 {plan.count} 格，共 {len(pages)} 页。{note}")

    if args.out:
        pages[0].save(args.out)
        print(f"已输出 {args.out}")
    if args.pdf:
        from photoprint.win import pdf_export

        pdf_export.export_pdf(pages, sheet, args.pdf)
        print(f"已输出等尺寸 PDF {args.pdf}（打印时请选“实际大小/100%”）")
    if args.do_print:
        from photoprint.win import api as win_api
        from photoprint.win import gdi_print

        if not args.printer:
            print("--print 需要 --printer 指定打印机名", file=sys.stderr)
            return 2
        res = gdi_print.print_job(win_api.RealWinApi(), args.printer, None,
                                  pages, sheet, args.dpi)
        print(res["message"] or f"已发送 {res['pages']} 页")
        return 0 if res["ok"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
