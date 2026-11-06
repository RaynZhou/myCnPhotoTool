"""照片叠加文字（日期标签 / 文字水印）：纯几何 + PIL 绘制，无 Qt/win32。

字号以 mm 表达、渲染时 ×ppmm 换像素 → 预览与导出跨 dpi 物理字号一致。
几何全部在本模块，界面层只汇参数（守 app 不做几何的红线）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from PIL import ImageFont

from photoprint.core import units

_FONTS_DIR = r"C:\Windows\Fonts"


class Corner:
    TL, TR, BL, BR = "tl", "tr", "bl", "br"


@dataclass(frozen=True)
class TextSpec:
    enabled: bool = False
    text: str = ""                 # 水印用；日期渲染时按格注入，忽略此字段
    font_key: str = "yahei"
    size_mm: float = 4.0
    weight: str = "normal"         # "normal" | "bold"
    corner: str = Corner.BR
    rgb: tuple = (255, 255, 255)
    alpha: int = 255               # 0–255；日期恒 255，水印按不透明度
    margin_pct: float = 4.0


def _p(name):
    return os.path.join(_FONTS_DIR, name)


# font_key → (常规字体路径, 粗体字体路径或 None)
FONT_TABLE = {
    "yahei": (_p("msyh.ttc"), _p("msyhbd.ttc")),
    "heiti": (_p("simhei.ttf"), None),
    "songti": (_p("simsun.ttc"), None),
    "arial": (_p("arial.ttf"), _p("arialbd.ttf")),
}


def size_px(size_mm, dpi):
    """文字名义高度 mm → 像素（随 dpi 线性；下限 1 防 0 高字体崩）。"""
    return max(1, units.mm_to_px(float(size_mm), dpi))


def inset_px(margin_pct, cell_wh):
    """内缩边距：占格短边的百分比。"""
    short = min(cell_wh)
    return units.round_px(float(margin_pct) / 100.0 * short)


def anchor_point(corner, cell_wh, text_wh, inset):
    """四角锚点（格局部坐标，文字左上落点）。"""
    cw, ch = cell_wh
    tw, th = text_wh
    if corner == Corner.TL:
        return (inset, inset)
    if corner == Corner.TR:
        return (cw - tw - inset, inset)
    if corner == Corner.BL:
        return (inset, ch - th - inset)
    return (cw - tw - inset, ch - th - inset)   # BR
