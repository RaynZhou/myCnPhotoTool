"""mm 与像素的唯一换算入口。"""
from __future__ import annotations

import math

MM_PER_INCH = 25.4


def round_px(value: float) -> int:
    """就近取整，.5 一律向上。全项目取整口径，渲染/裁切层都用它。

    不用内置 round()：它是银行家舍入，round(2.5) == 2、round(20.5) == 20，
    而本项目的几何断言（尤其 dpi=25.4 时 1 像素 = 1 毫米那批）需要的是
    直觉上的四舍五入，否则半像素落点会以一种看不出规律的方式偏移。
    """
    return int(math.floor(value + 0.5))


def ppmm(dpi: float) -> float:
    """每毫米对应多少像素。"""
    return dpi / MM_PER_INCH


def mm_to_px(mm: float, dpi: float) -> int:
    """mm 转像素，就近取整（.5 向上）。"""
    return round_px(mm * ppmm(dpi))


def px_to_mm(px: float, dpi: float) -> float:
    """像素回算 mm。"""
    return px / ppmm(dpi)


MM_TO_PT = 72.0 / 25.4  # PostScript 点/毫米换算因子


def mm_to_pt(mm: float) -> float:
    """毫米 → PostScript 点（1pt == 1/72 英寸），PDF 页面尺寸专用。"""
    return mm * MM_TO_PT


def win_mm(value_mm: float) -> int:
    """转 Windows DEVMODE 的 0.1mm 整数单位（1mm = 10 单位）。

    向下取整：纸张尺寸宁可小 0.1mm，也不要超出物理纸张导致驱动二次缩放。
    """
    return int(value_mm * 10)


def mm_to_scene(mm: float) -> int:
    """场景坐标：1 单位 = 0.1mm，整数以免累积误差。"""
    return round_px(mm * 10)
