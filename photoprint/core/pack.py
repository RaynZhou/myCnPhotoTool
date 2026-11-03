"""拼版装箱：三级搜索取张数最多。

第 1 级 单朝向均匀网格；第 2 级 一刀双带；第 3 级 两刀三带（深度上限 2）。
规模很小（张数 ≤ 30），穷举即可证明最优，不必上数值优化。

间隔只计在格子之间、不计外圈，故列数公式为 floor((W + gap) / (cw + gap))。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

_EPS = 1e-6


@dataclass
class Cell:
    """一个格子的外框（含出血）。"""

    x_mm: float
    y_mm: float
    w_mm: float
    h_mm: float
    rotated: bool
    bleed_mm: float

    def inner_mm(self) -> tuple[float, float, float, float]:
        """照片实际区域：外框四边内缩出血。"""
        return (self.x_mm + self.bleed_mm, self.y_mm + self.bleed_mm,
                self.w_mm - 2 * self.bleed_mm, self.h_mm - 2 * self.bleed_mm)


def cell_wh(w: float, h: float, rotated: bool) -> tuple[float, float]:
    """格子外框尺寸（不含出血与间隔），旋转时交换长短边。"""
    return (h, w) if rotated else (w, h)


def grid_counts(region_w: float, region_h: float, cw: float, ch: float,
                gap: float) -> tuple[int, int]:
    """给定区域内可放的列数与行数。"""
    if cw <= 0 or ch <= 0:
        return 0, 0
    cols = math.floor((region_w + gap) / (cw + gap) + _EPS)
    rows = math.floor((region_h + gap) / (ch + gap) + _EPS)
    return max(cols, 0), max(rows, 0)


def place_uniform(region_w: float, region_h: float, cell_w: float, cell_h: float,
                  gap: float, bleed: float, rotated: bool) -> list[Cell]:
    """单一朝向均匀排布，在区域内居中。"""
    base_w, base_h = cell_wh(cell_w, cell_h, rotated)
    cw, ch = base_w + 2 * bleed, base_h + 2 * bleed
    cols, rows = grid_counts(region_w, region_h, cw, ch, gap)
    if cols == 0 or rows == 0:
        return []
    used_w = cols * cw + (cols - 1) * gap
    used_h = rows * ch + (rows - 1) * gap
    x0 = (region_w - used_w) / 2.0
    y0 = (region_h - used_h) / 2.0
    out: list[Cell] = []
    for j in range(rows):
        for i in range(cols):
            out.append(Cell(x0 + i * (cw + gap), y0 + j * (ch + gap),
                            cw, ch, rotated, bleed))
    return out
