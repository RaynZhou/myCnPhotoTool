"""命令行编排：探测 → 装箱 → 裁切 → 渲染 → 直打/PDF。

本文件不得包含任何 mm/像素或裁切几何计算，一律调用 core/。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from photoprint import jobs
from photoprint.core import modes, store  # pack/render/specs 不再由此层直接调用


def load_photo(path):
    """薄转发：读图实现已搬到 jobs，历史调用点不变。"""
    return jobs.load_photo(path)


def build_plan_jobs(st, sheet_key, cell_key, gap_mm, bleed_mm, mode,
                    borderless_active):
    """薄转发：保持 7 个位置参数与 (plan, mode) 返回的历史形状。"""
    return jobs.build_layout(st, sheet_key, cell_key, gap_mm, bleed_mm, mode,
                             borderless_active=borderless_active)


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
    ap.add_argument("--mask", action="store_true",
                    help="导出时保留不可印区灰遮罩（调试用，默认不导出）")
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
    job = jobs.build_job(st, photos, args.sheet, args.cell, gap_mm=args.gap,
                         bleed_mm=args.bleed, mode=args.mode)
    pages = jobs.render_all(job, args.dpi, show_mask=args.mask)

    # 文案逐字冻结（全局约束）：cli 沿用本层原有的两分支 note 表达式，
    # 不取 job.note——那条属性按 margin_source 分档，spec 档写的是
    # “依规格推定，未经真机校准”，与历史输出不同一句
    borderless = job.mode == modes.BLEED_TRIM
    note = ("需人工裁切：沿灰线切开后即为 "
            f"{job.plan.cells[0].inner_mm()[2]:.0f}×"
            f"{job.plan.cells[0].inner_mm()[3]:.0f}mm 成品"
            if borderless else
            f"将保留白边：依规格约 上{sheet.margins.top}/下{sheet.margins.bottom}/"
            f"左{sheet.margins.left}/右{sheet.margins.right}mm（未经真机校准）")
    print(f"纸张 {sheet.label}，每页 {job.count} 格，共 {len(pages)} 页。{note}")

    if args.out:
        # README 示例写 _lab/out/，而 git 不存空目录：父目录必须自建；
        # 多页时 --out 只落第一页（全部页面请用 --pdf），消息不得谎报全套（T14 评审 I-1）
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pages[0].save(out_path)
        extra = "（多页时仅第一页，全部页面请用 --pdf）" if len(pages) > 1 else ""
        print(f"已输出 {out_path}{extra}")
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
