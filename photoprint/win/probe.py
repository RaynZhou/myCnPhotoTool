"""驱动能力探测：不信任规格表，冲突时以驱动为准并出报告。

单位约定（易错）：
  DeviceCapabilities(DC_PAPERSIZE) → (w, h)，单位 0.1mm
  GetDeviceCaps(PHYSICAL*/PHYSICALOFFSET*/HORZRES/VERTRES) → 设备像素，
    换算 mm 需 / LOGPIXELSX(或 Y) * 25.4
"""
from __future__ import annotations

from dataclasses import dataclass, field

from photoprint.core import units

# DeviceCapabilities 字段（Windows 常量，此处自持以便脱机测试）
DC_PAPERS = 2
DC_PAPERNAMES = 16
DC_PAPERSIZE = 17

# GetDeviceCaps 字段
PHYSICALWIDTH = 110
PHYSICALHEIGHT = 111
PHYSICALOFFSETX = 112
PHYSICALOFFSETY = 113
HORZRES = 8
VERTRES = 10
LOGPIXELSX = 88
LOGPIXELSY = 90


@dataclass
class ProbeResult:
    printer: str
    paper_names: list = field(default_factory=list)
    paper_codes: list = field(default_factory=list)
    paper_sizes_mm: list = field(default_factory=list)
    physical_w_mm: float = 0.0
    physical_h_mm: float = 0.0
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0
    res_w_px: int = 0
    res_h_px: int = 0
    dpi_x: int = 0
    dpi_y: int = 0


def _px_to_mm(px, dpi):
    # 换算本体走 units.px_to_mm（全项目唯一入口，T10 派前核查：不得在 win
    # 层开第二套公式）；这里的 dpi=0 守卫是脱机回读缺省值时的真实需求，
    # 否则 units 会抛 ZeroDivisionError（T1 评审已裁决防御放调用侧）。
    if not dpi:
        return 0.0
    return units.px_to_mm(px, dpi)


def probe(api, printer, paper_code=None, dc=None):
    """探测一台打印机。dc 给定时用该设备上下文回读（直打时复用同一 hdc）。"""
    target = dc if dc is not None else api.open_printer(printer)
    own_handle = dc is None
    try:
        dpi_x = api.get_device_caps(target, LOGPIXELSX)
        dpi_y = api.get_device_caps(target, LOGPIXELSY)
        names = api.device_caps(printer, DC_PAPERNAMES) or []
        codes = api.device_caps(printer, DC_PAPERS) or []
        sizes = api.device_caps(printer, DC_PAPERSIZE) or []
        # 真机上 hdc 才是当前纸张的物理参数来源；脱机时用设备默认
        phys_w = api.get_device_caps(target, PHYSICALWIDTH)
        phys_h = api.get_device_caps(target, PHYSICALHEIGHT)
        off_x = api.get_device_caps(target, PHYSICALOFFSETX)
        off_y = api.get_device_caps(target, PHYSICALOFFSETY)
        hr = api.get_device_caps(target, HORZRES)
        vr = api.get_device_caps(target, VERTRES)
        dpi_x, dpi_y = dpi_x or 300, dpi_y or 300
    finally:
        if own_handle:
            api.close_printer(target)
    return ProbeResult(
        printer=printer,
        paper_names=list(names),
        paper_codes=list(codes),
        paper_sizes_mm=[(w / 10.0, h / 10.0) for w, h in sizes] if sizes else [],
        physical_w_mm=_px_to_mm(phys_w, dpi_x),
        physical_h_mm=_px_to_mm(phys_h, dpi_y),
        offset_x_mm=_px_to_mm(off_x, dpi_x),
        offset_y_mm=_px_to_mm(off_y, dpi_y),
        res_w_px=hr, res_h_px=vr, dpi_x=dpi_x, dpi_y=dpi_y,
    )


def _norm(name: str) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def match_driver_paper(names, want_name):
    """把 '4x6' 之类的期望名匹配到驱动实际叫法（'4 X 6'/'10x15'…）。"""
    want = _norm(want_name)
    codes = list(range(1, len(names) + 1))
    for code, name in zip(codes, names):
        if _norm(name) == want:
            return code, name
    for code, name in zip(codes, names):
        if want and want in _norm(name):
            return code, name
    return None, None


def borderless_active(result: ProbeResult) -> bool:
    """无边距是否生效：以驱动回报的物理偏移为零为唯一证据。

    绝不按"规格说支持无边距"就当成已生效——那是谎报的源头。
    """
    return abs(result.offset_x_mm) <= 0.05 and abs(result.offset_y_mm) <= 0.05


def diff_report(spec, result: ProbeResult) -> list:
    """规格值与驱动实测值的冲突清单，供 UI 同时显示两个数。"""
    out = []
    if result.physical_w_mm and abs(result.physical_w_mm - spec.w_mm) > 0.5:
        out.append(f"宽度：依规格 {spec.w_mm}mm，驱动实测 {result.physical_w_mm:.2f}mm")
    if result.physical_h_mm and abs(result.physical_h_mm - spec.h_mm) > 0.5:
        out.append(f"高度：依规格 {spec.h_mm}mm，驱动实测 {result.physical_h_mm:.2f}mm")
    if result.offset_x_mm and abs(result.offset_x_mm - spec.margins.left) > 0.2:
        out.append(f"左边距：依规格 {spec.margins.left}mm，驱动实测 "
                   f"{result.offset_x_mm:.2f}mm")
    if result.offset_y_mm and abs(result.offset_y_mm - spec.margins.top) > 0.2:
        out.append(f"上边距：依规格 {spec.margins.top}mm，驱动实测 "
                   f"{result.offset_y_mm:.2f}mm")
    return out
