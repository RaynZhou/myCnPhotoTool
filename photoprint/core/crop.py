"""裁切与落位计算：预览层与打印层必须共用本函数（规格 6.4）。

模式语义（易错点，勿改）：
  FILL —— 铺满目标矩形，超出部分裁掉；zoom>=1，1.0 为恰好覆盖。
  FIT  —— 完整显示目标，画面缩小后居中留白；zoom<=1，1.0 为最大适配。
两者的"目标矩形"都可以是可打印区或整张纸，由调用方决定；
`fill_printable` 的目标是可打印区，**不是整张纸**，物理上铺不到纸边。
"""
from __future__ import annotations

from dataclasses import dataclass

from photoprint.core import units

FILL = "fill"
FIT = "fit"
_VALID_MODES = (FILL, FIT)


@dataclass
class Placement:
    """crop_px 为原图像素裁框，dest_mm 为相对目标区左上角的落位。"""

    crop_px: tuple
    dest_mm: tuple


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def cell_crop_box(photo_w_px, photo_h_px, target_w_mm, target_h_mm, mode,
                  zoom=1.0, dx_mm=0.0, dy_mm=0.0, ppmm=None):
    if mode not in _VALID_MODES:
        raise ValueError(f"未知 mode：{mode}，只允许 {FILL}/{FIT}")
    if ppmm is None:
        ppmm = units.ppmm(300)
    if photo_w_px <= 0 or photo_h_px <= 0 or target_w_mm <= 0 or target_h_mm <= 0:
        raise ValueError("照片与目标尺寸必须为正")

    tw_px = target_w_mm * ppmm
    th_px = target_h_mm * ppmm

    if mode == FILL:
        if not 1.0 <= zoom <= 4.0:
            raise ValueError(f"zoom 越界：{zoom}（fill 模式允许 1.0–4.0）")
        base = max(tw_px / photo_w_px, th_px / photo_h_px)
        scale = base * zoom
        crop_w = tw_px / scale
        crop_h = th_px / scale
        cx = photo_w_px / 2.0 + dx_mm * ppmm / scale
        cy = photo_h_px / 2.0 + dy_mm * ppmm / scale
        l = _clamp(cx - crop_w / 2.0, 0.0, photo_w_px - crop_w)
        t = _clamp(cy - crop_h / 2.0, 0.0, photo_h_px - crop_h)
        r, b = l + crop_w, t + crop_h
        return Placement((int(round(l)), int(round(t)),
                          int(round(r)), int(round(b))),
                         (0.0, 0.0, float(target_w_mm), float(target_h_mm)))

    if not 0.2 <= zoom <= 1.0:
        raise ValueError(f"zoom 越界：{zoom}（fit 模式允许 0.2–1.0）")
    base = min(tw_px / photo_w_px, th_px / photo_h_px) * zoom
    dest_w = photo_w_px * base / ppmm
    dest_h = photo_h_px * base / ppmm
    x = _clamp((target_w_mm - dest_w) / 2.0 + dx_mm, 0.0, target_w_mm - dest_w)
    y = _clamp((target_h_mm - dest_h) / 2.0 + dy_mm, 0.0, target_h_mm - dest_h)
    return Placement((0, 0, int(photo_w_px), int(photo_h_px)),
                     (x, y, dest_w, dest_h))
