"""只读采证脚本：dump 驱动自带纸张表单，并实测每张表的物理尺寸。

用途：真机核对"5 寸(89×127)"等相片尺寸到底落在驱动哪个表单上，以及
预设尺寸与驱动实测差多少（spec 2026-11-07）。

尺寸来源：逐表单码建 DEVMODE → CreateDC → GetDeviceCaps(PHYSICALWIDTH/HEIGHT)。
不走 DC_PAPERSIZE：本机 G3800 驱动对它返回 30 对全 0，形状不可信。

绝不发送任何打印作业：只建 DEVCONTEXT 回读，不调 StartDoc。

用法（在连着 G3800 的机器上，仓库根目录）：
    python _lab/dump_driver_papers.py
    python _lab/dump_driver_papers.py "Canon G3800 series"
不带参数则用系统默认打印机；取不到默认就用枚举到的第一台。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from photoprint.core import specs  # noqa: E402
from photoprint.win import forms, probe  # noqa: E402
from photoprint.win.api import RealWinApi  # noqa: E402


def _clean(name) -> str:
    """驱动返回的纸张名可能带尾随空白/内嵌 \\0，清掉才好读。"""
    s = str(name)
    return s.split("\x00", 1)[0].strip()


def _presets_hit_by(form):
    """这张表单命中哪些预设——用与打印路径同一个 find，结论才对得上。"""
    return [p.key for p in specs.PAPER_PRESETS
            if forms.find([form], p.w_mm, p.h_mm) is form]


def _pick_printer(api, argv):
    printers = api.enum_printers()
    if not printers:
        return None, printers
    if len(argv) > 1:
        printer = argv[1]
        if printer not in printers:
            print(f"指定名称不在清单里，改用第一台。可选：{printers}")
            printer = printers[0]
        return printer, printers
    try:
        printer = api.get_default_printer()
    except Exception as exc:  # 取默认失败不致命，退回第一台
        print(f"(取系统默认打印机失败：{exc})")
        printer = None
    if printer not in printers:
        printer = printers[0]
    return printer, printers


def main(argv):
    api = RealWinApi()
    printer, printers = _pick_printer(api, argv)
    if printer is None:
        print("未检测到任何打印机。")
        return 1

    print(f"当前探测打印机：{printer}")
    print(f"系统全部打印机：{printers}\n")

    r = probe.probe(api, printer)
    names = [_clean(n) for n in r.paper_names]
    codes = [int(c) for c in r.paper_codes]

    print(f"驱动默认纸张实测物理尺寸：{r.physical_w_mm:.2f} × "
          f"{r.physical_h_mm:.2f} mm（dpi {r.dpi_x}×{r.dpi_y}）")
    print(f"表单条数：names={len(names)}  codes={len(codes)}  "
          f"DC_PAPERSIZE sizes={len(r.paper_sizes_mm)}（不采用，见文件头）")
    if not codes:
        print("\n[中断] 拿不到表单码清单（DC_PAPERS），无法逐码实测。"
              "请把下面原始名称清单贴回。")
        for i, name in enumerate(names):
            print(f"{i:>4}  {name}")
        return 1

    measured = {f.code: f for f in forms.measure(api, printer, codes)}
    print(f"实测成功 {len(measured)}/{len(codes)} 张"
          f"（失败的码＝驱动不认，回读 PaperSize 被重置）\n")

    print(f"{'码':>5} {'宽mm':>8} {'高mm':>8}  名称   /   命中预设")
    print("-" * 78)
    for i, code in enumerate(codes):
        name = names[i] if i < len(names) else "?"
        form = measured.get(code)
        if form is None:
            print(f"{code:>5} {'-':>8} {'-':>8}  {name}   <== 驱动不认此码")
            continue
        keys = _presets_hit_by(form)
        tail = " / ".join(keys) if keys else "无匹配预设"
        print(f"{code:>5} {form.w_mm:>8.2f} {form.h_mm:>8.2f}  {name}   <== {tail}")

    print("\n预设反查（打印路径实际会下单哪张表；空＝无表单，退回自有纸张码）：")
    print("-" * 78)
    pool = list(measured.values())
    for p in specs.PAPER_PRESETS:
        hit = forms.find(pool, p.w_mm, p.h_mm)
        got = (f"码 {hit.code}  {hit.name}  实测 {hit.w_mm:.2f}×{hit.h_mm:.2f}"
               if hit is not None else "无匹配表单")
        print(f"{p.key:>6} {p.w_mm:>6.1f}×{p.h_mm:<6.1f} {got}")

    print("\n只读采证结束：全程未发送打印作业。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
