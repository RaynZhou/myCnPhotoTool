"""拼版装箱：三级搜索取张数最多。

第 1 级 单朝向均匀网格；第 2 级 一刀双带；第 3 级 两刀三带（深度上限 2）。
规模很小（张数 ≤ 30），穷举即可证明最优，不必上数值优化。

间隔只计在格子之间、不计外圈，故列数公式为 floor((W + gap) / (cw + gap))。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from photoprint.core import specs

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


@dataclass
class CutLine:
    """裁切参考线：axis 为 'v'（竖缝）或 'h'（横缝）。"""

    axis: str
    at_mm: float
    from_mm: float
    to_mm: float


@dataclass
class LayoutPlan:
    cells: list[Cell]
    cuts: list[CutLine]
    count: int
    waste_mm2: float
    strategy: str
    printable: specs.RectMM


def best_uniform(region_w, region_h, cell_w, cell_h, gap, bleed, allow_rotate):
    """两种朝向各自均匀排布，取张数多者；并列时外接框更接近正方形且更居中者优先。"""
    options = [False, True] if allow_rotate else [False]
    best: list[Cell] = []
    best_key = None
    for rot in options:
        cells = place_uniform(region_w, region_h, cell_w, cell_h, gap, bleed, rot)
        if not cells:
            continue
        key = _score(cells, region_w, region_h, 0)
        if best_key is None or key < best_key:
            best, best_key = cells, key
    return best


def _score(cells, region_w, region_h, strategy_rank):
    """决胜排序，越小越优：张数多 → 浪费小 → 策略简单 → 外接框方 → 居中 → 朝向统一。

    对应规格 5.2 的并列决胜①–⑤（首项是张数，它不算决胜而是前提）。
    “策略简单”必须排在外接框与居中之前：外接框只量跨度，量不出贴边解的不好看——
    A4+3R 的一刀双带解（左带宽恰好 89mm）外接框 194×254，比均匀网格的 178×254
    更接近正方形，张数与浪费全同，却不居中、列间隙一边 0mm 一边 16mm。把“简单”放
    在浪费之后、美观之前，混合带就只能在张数或浪费上真赢时才胜出（如 A4+4R 的 3 比 2）。
    """
    used = sum(c.w_mm * c.h_mm for c in cells)
    waste = region_w * region_h - used
    x1 = min(c.x_mm for c in cells)
    x2 = max(c.x_mm + c.w_mm for c in cells)
    y1 = min(c.y_mm for c in cells)
    y2 = max(c.y_mm + c.h_mm for c in cells)
    aspect = abs((x2 - x1) - (y2 - y1))
    # 外接框中心与区域中心的偏离（×2，免去除法）：居中为 0，越大越偏
    offcenter = abs((x1 + x2) - region_w) + abs((y1 + y2) - region_h)
    mixed = len({c.rotated for c in cells})
    return (-len(cells), waste, strategy_rank, aspect, offcenter, mixed)


def _cut_candidates(region_w, region_h, cell_w, cell_h, gap, bleed, allow_rotate):
    """候选切位 = 格子步进长度的整数倍，两向都取，横切与竖切分开。"""
    out = []
    rots = [False, True] if allow_rotate else [False]
    for rot in rots:
        bw, bh = cell_wh(cell_w, cell_h, rot)
        for step in (bw + 2 * bleed + gap, bh + 2 * bleed + gap):
            if step <= 0:
                continue
            k = 1
            while k * step < region_w - _EPS:
                out.append(("v", round(k * step, 6)))
                k += 1
            k = 1
            while k * step < region_h - _EPS:
                out.append(("h", round(k * step, 6)))
                k += 1
    return sorted(set(out))


def solve_region(region_w, region_h, cell_w, cell_h, gap, bleed, allow_rotate,
                 depth, memo):
    """返回 (格子列表, 策略名)。depth 为还可下的刀数。"""
    memo_key = (round(region_w, 6), round(region_h, 6), depth)
    if memo_key in memo:
        return memo[memo_key]

    uniform = best_uniform(region_w, region_h, cell_w, cell_h, gap, bleed,
                           allow_rotate)
    best_cells, best_strategy = uniform, "uniform"
    if uniform:
        best_key = _score(uniform, region_w, region_h, 0)
    else:
        # 空解的分值必须劣于任何非空解（首项 0 大于任何 -len）
        best_key = (0, region_w * region_h, 9, 0.0, 0.0, 9)

    if depth > 0:
        for axis, pos in _cut_candidates(region_w, region_h, cell_w, cell_h,
                                        gap, bleed, allow_rotate):
            if axis == "v":
                a_w, a_h, b_w, b_h = pos, region_h, region_w - pos, region_h
                off = (0.0, 0.0, pos, 0.0)
            else:
                a_w, a_h, b_w, b_h = region_w, pos, region_w, region_h - pos
                off = (0.0, 0.0, 0.0, pos)
            ca, _ = solve_region(a_w, a_h, cell_w, cell_h, gap, bleed,
                                 allow_rotate, depth - 1, memo)
            cb, _ = solve_region(b_w, b_h, cell_w, cell_h, gap, bleed,
                                 allow_rotate, depth - 1, memo)
            merged = list(ca) + [
                Cell(c.x_mm + off[2], c.y_mm + off[3], c.w_mm, c.h_mm,
                     c.rotated, c.bleed_mm) for c in cb]
            if not merged:
                continue
            key = _score(merged, region_w, region_h, 1)
            if key < best_key:
                best_cells, best_strategy, best_key = merged, "bands", key

    memo[memo_key] = (best_cells, best_strategy)
    return memo[memo_key]


def pack(sheet, cell, gap_mm: float = 0.0, bleed_mm: float = 0.0,
         allow_rotate: bool = True, printable=None) -> LayoutPlan:
    """装箱入口。sheet/cell 均为 specs.SizeSpec；printable 给定时按其尺寸装箱。"""
    rect = printable if printable is not None else _sheet_rect(sheet)
    cells, strategy = solve_region(rect.w_mm, rect.h_mm, cell.w_mm, cell.h_mm,
                                   gap_mm, bleed_mm, allow_rotate, depth=2,
                                   memo={})
    # 装箱在矩形局部坐标求解，再平移到可打印区原点
    cells = [Cell(c.x_mm + rect.x_mm, c.y_mm + rect.y_mm, c.w_mm, c.h_mm,
                  c.rotated, c.bleed_mm) for c in cells]
    used = sum(c.w_mm * c.h_mm for c in cells)
    return LayoutPlan(cells=cells, cuts=build_cuts(cells, rect),
                      count=len(cells),
                      waste_mm2=max(0.0, rect.w_mm * rect.h_mm - used),
                      strategy=strategy, printable=rect)


def _sheet_rect(sheet):
    """装箱默认区域 = 整张纸。

    规格 5.3 的手算基准全按整张纸算（`floor(210/89)` 而不是 `floor(203.2/89)`），
    默认值必须与基准同口径：A4+4R 在 210mm 宽里放得下两张 102mm（204 ≤ 210），
    扣掉物理边距后只剩 203.2mm，会因 0.8mm 之差让硬断言从 3 张掉到 2 张。
    代价就是打印路径必须显式传 printable，否则照片会吃进边距。
    """
    return specs.RectMM(0.0, 0.0, sheet.w_mm, sheet.h_mm)


def merge_spans(spans):
    """合并相接或重叠的一维区间。"""
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1] + _EPS:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def build_cuts(cells, rect):
    """由格子外框推导裁切缝（规格 5.2 的切缝取舍规则）。

    画：严格落在区域内的格子边界（左/右或上/下）；居中留白时两侧都要画，
    只画一侧会切不出成品尺寸。
    不画：与区域边界重合的边界（纸边就是基准，切了也无从下手）。
    线段取紧贴该缝的格子在另一轴上的范围之并集，让切纸刀有连续引导（见 6.4）。
    """
    if len(cells) < 2:
        return []
    cuts = []
    tol = 1e-3

    # 轴、属性名、区域都显式传参：不靠外层循环变量绑定闭包，
    # 那样写抽出一个函数就得连带重写调用点
    def seams(axis, pos_attrs, span_attrs, base, extent):
        lo_attr, len_attr = pos_attrs
        positions = set()
        for c in cells:
            lo = getattr(c, lo_attr)
            positions.add(round(lo, 6))
            positions.add(round(lo + getattr(c, len_attr), 6))
        for p in sorted(positions):
            if not (base + tol < p < base + extent - tol):
                continue
            spans = []
            for c in cells:
                lo = getattr(c, lo_attr)
                if abs(lo - p) > tol and abs(lo + getattr(c, len_attr) - p) > tol:
                    continue  # 不与该缝紧邻的格子不得拉长线段
                s0 = getattr(c, span_attrs[0])
                spans.append((s0, s0 + getattr(c, span_attrs[1])))
            for a, b in merge_spans(spans):
                cuts.append(CutLine(axis, p, a, b))

    seams("v", ("x_mm", "w_mm"), ("y_mm", "h_mm"), rect.x_mm, rect.w_mm)
    seams("h", ("y_mm", "h_mm"), ("x_mm", "w_mm"), rect.y_mm, rect.h_mm)

    # 每条缝 (axis, at_mm) 在 seams 内只生成一次，线段已按缝合并过，
    # 这里只需总排序
    return sorted(cuts, key=lambda c: (c.axis, c.at_mm, c.from_mm))


def needed_sheets(plan_count: int, photo_count: int) -> int:
    """按每页格子数算需要几张纸。"""
    if plan_count <= 0:
        return 0
    return -(-photo_count // plan_count)
