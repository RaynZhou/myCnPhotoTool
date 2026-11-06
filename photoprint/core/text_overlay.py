"""照片叠加文字（日期标签 / 文字水印）：纯几何 + PIL 绘制，无 Qt/win32。

字号以 mm 表达、渲染时 ×ppmm 换像素 → 预览与导出跨 dpi 物理字号一致。
几何全部在本模块，界面层只汇参数（守 app 不做几何的红线）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

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
    rotation: int = 0          # 文字顺时针角度，八档预设之一；0＝不旋转
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

ROTATION_PRESETS = (0, 45, 90, 135, 180, 225, 270, 315)


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


def _load_font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except (OSError, ValueError):
        return None


def draw_overlay(page, cell_rect_px, spec, text, dpi):
    """在 page(RGB) 的 cell_rect_px=(x,y,w,h) 格内画 text，逐格 clip 合成。

    前置不满足（未启用 / 空文字 / 格尺寸非法 / 字体缺失 / 缩到仍放不下）一律
    静默返回，绝不抛——一次坏叠加不得把整页渲染打死。"""
    if not spec.enabled or not text:
        return
    x, y, cw, ch = (int(v) for v in cell_rect_px)
    if cw <= 0 or ch <= 0:
        return
    paths = FONT_TABLE.get(spec.font_key)
    if not paths:
        return
    reg, bold = paths
    stroke = 0
    if spec.weight == "bold" and bold and os.path.isfile(bold):
        font_path = bold
    else:
        font_path = reg
        if spec.weight == "bold":
            stroke = max(1, size_px(spec.size_mm, dpi) // 12)
    if not font_path or not os.path.isfile(font_path):
        return
    size = size_px(spec.size_mm, dpi)
    font = _load_font(font_path, size)
    if font is None:
        return
    inset = inset_px(spec.margin_pct, (cw, ch))
    avail_w, avail_h = cw - 2 * inset, ch - 2 * inset
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    tw = th = 0
    l = t = 0
    for _ in range(3):                       # 超长降级：缩字号重算 ≤3 次
        l, t, tw, th = measure.textbbox((0, 0), text, font=font, stroke_width=stroke)
        if tw <= avail_w or size <= 1:
            break
        size = max(1, int(size * 0.8))
        font = _load_font(font_path, size)
        if font is None:
            return
    if tw > avail_w or th > avail_h:
        return
    fill = tuple(spec.rgb)[:3] + (int(spec.alpha),)
    if spec.rotation:
        text_img = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        ImageDraw.Draw(text_img).text((-l, -t), text, font=font, fill=fill,
                                      stroke_width=stroke, stroke_fill=fill)
        rot = text_img.rotate(-int(spec.rotation), expand=True,
                              resample=Image.BICUBIC)
        rw, rh = rot.size
        if rw > avail_w or rh > avail_h:                 # 旋转后放不下：降级不画
            return
        ax, ay = anchor_point(spec.corner, (cw, ch), (rw, rh), inset)
        layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        layer.alpha_composite(rot, (ax, ay))
    else:
        ax, ay = anchor_point(spec.corner, (cw, ch), (tw, th), inset)
        layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((ax - l, ay - t), text, font=font, fill=fill,
                                   stroke_width=stroke, stroke_fill=fill)
    region = page.crop((x, y, x + cw, y + ch)).convert("RGBA")
    region = Image.alpha_composite(region, layer)
    page.paste(region.convert("RGB"), (x, y))
