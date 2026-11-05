"""三档打印模式与默认映射。

诚实性约束：
  BLEED_TRIM 的 UI 标签必须写"需人工裁切"，不得写"无边距打印"——
  结果是无边距，但那个动作不是打印能自己完成的。
  FILL_PRINTABLE 的 UI 文案不得写"铺满整张纸"，除非实测无边距已生效。
"""
from __future__ import annotations

from photoprint.core import crop, specs

FIT_TO_PRINTABLE = "fit_to_printable"
FILL_PRINTABLE = "fill_printable"
BLEED_TRIM = "bleed_trim"

MODES = (FIT_TO_PRINTABLE, FILL_PRINTABLE, BLEED_TRIM)
DEFAULT_BLEED_MM = 3.0


def crop_mode(mode: str) -> str:
    if mode == FIT_TO_PRINTABLE:
        return crop.FIT
    if mode in (FILL_PRINTABLE, BLEED_TRIM):
        return crop.FILL
    raise ValueError(f"未知 mode：{mode}")


def default_mode(sheet, cell, cell_count, borderless_active=False) -> str:
    """按规格 7.2 给默认档。"""
    if cell.role == "cell":
        return FIT_TO_PRINTABLE
    if sheet.borderless and cell_count >= 2 and sheet.origin != "custom":
        return BLEED_TRIM
    return FILL_PRINTABLE


def assert_mode_legal(sheet, mode: str) -> None:
    """裁切模式依赖大纸能无边距，否则出血区打不出来，属非法组合。"""
    if mode == BLEED_TRIM and not sheet.borderless:
        raise ValueError(f"{sheet.key} 不支持无边距，无法使用需裁切的出血模式")


def target_rect(sheet, cell, mode, printable, borderless_active=False):
    """照片放置的目标矩形。

    FIT/FILL 用可打印矩形；BLEED 用整张纸（无边距已生效才合法）。
    """
    if mode == BLEED_TRIM:
        assert_mode_legal(sheet, mode)
        return specs.RectMM(0.0, 0.0, sheet.w_mm, sheet.h_mm)
    if borderless_active:
        return specs.RectMM(0.0, 0.0, sheet.w_mm, sheet.h_mm)
    return printable
