"""只读采证脚本：dump 指定打印机驱动自带的纸张表单清单（名称/表单码/尺寸）。

用途：真机定位"5 寸(89×127)"到底对应驱动哪个表单码、尺寸与方向如何，
供后续把界面尺寸映射到驱动真实表单（而非裸 DMPAPER_USER 自定义尺寸）。

绝不发送任何打印作业：只调用 DeviceCapabilities / GetDeviceCaps 回读。

用法（在连着 G3800 的机器上，仓库根目录）：
    python _lab/dump_driver_papers.py
    python _lab/dump_driver_papers.py "Canon G3800 series"
不带参数则用系统默认打印机；取不到默认就用枚举到的第一台。
"""
from __future__ import annotations

import sys

from photoprint.win import probe
from photoprint.win.api import RealWinApi


def _clean(name) -> str:
    """驱动返回的纸张名可能带尾随空白/内嵌 \\0，清掉才好读。"""
    s = str(name)
    return s.split("\x00", 1)[0].strip()


def _near(w, h, tw, th, tol=1.0) -> bool:
    return abs(w - tw) <= tol and abs(h - th) <= tol


def _mark(w, h):
    """标出我们关心的相片尺寸候选，方便一眼看出驱动有没有现成表单。"""
    targets = [
        ((89.0, 127.0), "≈5寸/3R(89×127)"),
        ((102.0, 152.0), "≈6寸/4R(102×152)"),
        ((127.0, 178.0), "≈7寸/5R(127×178)"),
    ]
    hits = []
    for (tw, th), label in targets:
        if _near(w, h, tw, th) or _near(w, h, th, tw):
            hits.append(label)
    return "  <== " + " / ".join(hits) if hits else ""


def main(argv):
    api = RealWinApi()
    printers = api.enum_printers()
    if not printers:
        print("未检测到任何打印机。")
        return 1

    if len(argv) > 1:
        printer = argv[1]
        if printer not in printers:
            print(f"指定名称不在清单里，改用第一台。可选：{printers}")
            printer = printers[0]
    else:
        try:
            printer = api.get_default_printer()
        except Exception as exc:  # 取默认失败不致命，退回第一台
            print(f"(取系统默认打印机失败：{exc})")
            printer = None
        if printer not in printers:
            printer = printers[0]

    print(f"当前探测打印机：{printer}")
    print(f"系统全部打印机：{printers}\n")

    r = probe.probe(api, printer)
    names, codes, sizes = r.paper_names, r.paper_codes, r.paper_sizes_mm

    print(f"驱动默认纸张实测物理尺寸：{r.physical_w_mm:.2f} × "
          f"{r.physical_h_mm:.2f} mm（dpi {r.dpi_x}×{r.dpi_y}）")
    print(f"表单条数：names={len(names)}  codes={len(codes)}  "
          f"sizes={len(sizes)}")
    if not sizes:
        print("\n[警告] DC_PAPERSIZE 没解析成 (宽,高) 对——这台驱动/pywin32 "
              "返回的形状不认识。请把下面原始三清单一起贴回，我再适配。")

    n = max(len(names), len(codes), len(sizes))
    print(f"\n{'序号':>4} {'码':>5}  {'宽mm':>7} {'高mm':>7}  名称")
    print("-" * 60)
    for i in range(n):
        code = codes[i] if i < len(codes) else "?"
        if i < len(sizes):
            w, h = sizes[i]
            ws, hs = f"{w:.1f}", f"{h:.1f}"
            tail = _mark(w, h)
        else:
            ws = hs = "-"
            tail = ""
        name = _clean(names[i]) if i < len(names) else "?"
        print(f"{i:>4} {str(code):>5}  {ws:>7} {hs:>7}  {name}{tail}")

    print("\n请把以上整段输出贴回来。重点看：")
    print("  1) 有没有哪一行的尺寸≈89×127（或 127×89）——那就是驱动自带的 5 寸表单；")
    print("  2) 它的“码”（DMPAPER_* 值）与“名称”分别是什么、方向是横还是竖。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
