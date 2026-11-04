"""CLI 与界面共用的编排层：探测 → 装箱 → 裁切 → 渲染。

本文件不得包含任何 mm/像素或裁切几何计算，一律调用 core/；
也不得输出到 stdout，不得引入 Qt 与 win32 模块——窗口化打包后
标准输出为 None，而无窗口无打印机可测是这一层存在的唯一理由。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image, ImageOps

from photoprint.core import modes, pack, render, specs

PREVIEW_DPI = 96.0
DEFAULT_OUTPUT_DPI = 300.0

# 状态栏的边距来源分档（规格 7.3：文案必须跟着证据走）。
# 未知来源一律按最保守口径写，绝不落进"实测"分支——凭空给用户一个
# 没有证据的承诺，比多写一句"未校准"严重得多。
_MARGIN_SOURCE_NOTE = {
    "spec": "依规格推定，未经真机校准",
    "probed": "驱动实测边距",
    "calibrated": "真机校准边距",
}
_UNKNOWN_MARGIN_SOURCE = _MARGIN_SOURCE_NOTE["spec"]


def load_photo(path):
    """读图并让 EXIF 方向生效，避免界面与打印各转一次。

    自 cli.py 搬来：界面也要读图，两处各写一遍会漂移。
    """
    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


def build_layout(st, sheet_key, cell_key, gap_mm, bleed_mm, mode,
                 borderless_active=False):
    """返回 (排版方案, 生效模式)。mode 为 None 时按默认映射决定。

    逻辑逐字来自 cli.build_plan_jobs；cli 改为本函数的薄转发是 Task 4 的事，
    因此本 commit 里两边仍是两份实现，等价测试是真对拍。
    """
    sheet = st.resolve(sheet_key)
    cell = st.resolve(cell_key)
    printable = specs.printable_rect(sheet, borderless_active=borderless_active)
    # 全局约束：证件照这类"格"（role="cell"）拼版不得旋转——横放会把
    # 一寸/二寸照排成横的；纸类（3R/4R）是照片本身，旋转是合法装箱策略
    allow_rotate = cell.role != "cell"
    probe_plan = pack.pack(sheet, cell, gap_mm=gap_mm, bleed_mm=0.0,
                           allow_rotate=allow_rotate, printable=printable)
    if mode is None:
        mode = modes.default_mode(sheet, cell, probe_plan.count, borderless_active)
    modes.assert_mode_legal(sheet, mode)
    bleed = bleed_mm if mode == modes.BLEED_TRIM else 0.0
    # 裁切模式在整张纸上装箱（无边距才容得下出血），其余在可打印区内装箱
    rect = specs.RectMM(0.0, 0.0, sheet.w_mm, sheet.h_mm) \
        if mode == modes.BLEED_TRIM else printable
    plan = pack.pack(sheet, cell, gap_mm=gap_mm, bleed_mm=bleed,
                     allow_rotate=allow_rotate, printable=rect)
    if plan.count == 0 and mode != modes.BLEED_TRIM:
        # 退化情形：格子与纸张同尺寸（如 3R 纸打 3R 照片）。
        # 按可打印矩形装箱必然得 0 格，改为整纸装一格，
        # 画面收回可打印区由 render 层的交集负责。
        full = specs.RectMM(0.0, 0.0, sheet.w_mm, sheet.h_mm)
        plan = pack.pack(sheet, cell, gap_mm=gap_mm, bleed_mm=0.0,
                         allow_rotate=allow_rotate, printable=full)
    if plan.count == 0:
        raise ValueError(f"{sheet.label} 放不下 {cell.label}，请换大纸或改小格子")
    return plan, mode


@dataclass
class Job:
    """一次排版的完整结果：照片 + 方案 + 偏移，按页渲染。"""

    plan: pack.LayoutPlan
    mode: str
    sheet: specs.SizeSpec
    photos: list = field(default_factory=list)
    offset_pct: tuple[float, float] = (0.0, 0.0)
    borderless_active: bool = False

    @property
    def count(self) -> int:
        return self.plan.count

    @property
    def page_count(self) -> int:
        """零照片也至少一页：界面要能预览空格。"""
        return max(1, pack.needed_sheets(self.plan.count, len(self.photos)))

    @property
    def note(self) -> str:
        """界面状态栏文案：边距那句按 margin_source 分档（规格 7.3）。

        cli 的 stdout 另有一套逐字冻结的文案（全局约束），两边共用同一份
        数字、不共用同一句话——界面要说清证据从哪来，cli 要保持历史输出不变。
        """
        if self.mode == modes.BLEED_TRIM:
            inner = self.plan.cells[0].inner_mm()
            return (f"需人工裁切：沿灰线切开后即为 {inner[2]:.0f}×{inner[3]:.0f}mm 成品")
        m = self.sheet.margins
        provenance = _MARGIN_SOURCE_NOTE.get(self.sheet.margin_source,
                                             _UNKNOWN_MARGIN_SOURCE)
        return (f"将保留白边：上{m.top}/下{m.bottom}/左{m.left}/右{m.right}mm"
                f"（{provenance}）")

    def render(self, page_index: int, dpi: float, show_mask: bool = False) -> Image.Image:
        """渲染单页。show_mask 只在预览开，导出必须关（否则灰边进相纸）。"""
        if not 0 <= page_index < self.page_count:
            raise IndexError(f"页码越界：{page_index}（共 {self.page_count} 页）")
        i = page_index * self.count
        chunk = self.photos[i:i + self.count]
        return render.render_page(self.plan, chunk, self.sheet, dpi, self.mode,
                                  show_mask=show_mask,
                                  borderless_active=self.borderless_active,
                                  offset_pct=self.offset_pct)


def build_job(st, photos, sheet_key, cell_key, *, gap_mm=0.0,
              bleed_mm=modes.DEFAULT_BLEED_MM, mode=None,
              offset_pct=(0.0, 0.0), borderless_active=False) -> Job:
    plan, mode_eff = build_layout(st, sheet_key, cell_key, gap_mm, bleed_mm,
                                  mode, borderless_active=borderless_active)
    # 百分比原样交给 core：同一页可能两种朝向混排，"按哪个尺寸换算"是逐格
    # 决策（T3 评审 I-1），本层若先按首格换算成 mm，其余格的 ±50% 就失真
    return Job(plan=plan, mode=mode_eff, sheet=st.resolve(sheet_key),
               photos=list(photos),
               offset_pct=tuple(float(v) for v in offset_pct),
               borderless_active=borderless_active)


def render_all(job: Job, dpi: float, show_mask: bool = False) -> list[Image.Image]:
    """CLI 用：等价于逐页调用 job.render，避免两边各写一套切页。"""
    return [job.render(i, dpi, show_mask) for i in range(job.page_count)]
