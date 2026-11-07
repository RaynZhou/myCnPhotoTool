"""CLI 与界面共用的编排层：探测 → 装箱 → 裁切 → 渲染。

本文件不得包含任何 mm/像素或裁切几何计算，一律调用 core/；
也不得输出到 stdout，不得引入 Qt 与 win32 模块——窗口化打包后
标准输出为 None，而无窗口无打印机可测是这一层存在的唯一理由。
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from PIL import Image, ImageOps

from photoprint.core import modes, pack, render, specs

PREVIEW_DPI = 96.0
DEFAULT_OUTPUT_DPI = 300.0

# 状态栏的边距来源分档（规格 7.3：文案必须跟着证据走）。
# 未知来源一律按最保守口径写，绝不落进"实测"分支——凭空给用户一个
# 没有证据的承诺，比多写一句"未校准"严重得多。
# 取值前面统一接「边距」二字，两档文案共用同一个前缀；spec 档那句是全局
# 约束点名要逐字出现的，故只有它可以不带动词。
_MARGIN_SOURCE_NOTE = {
    "spec": "依规格推定，未经真机校准",
    "probed": "已由驱动实测",
    "calibrated": "已经真机校准",
}
_UNKNOWN_MARGIN_SOURCE = _MARGIN_SOURCE_NOTE["spec"]


def load_photo(path):
    """读图并让 EXIF 方向生效，避免界面与打印各转一次。

    自 cli.py 搬来：界面也要读图，两处各写一遍会漂移。
    """
    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


def even_margins(sheet):
    """成品照片档的白边（上下相等、左右相等）。

    转发 core 的同轴取齐，供状态栏与 cli 共用一个数字来源：cli 不得直接调
    core.specs（分层约束），而两边报的数绝不能比排版自己那套多一个版本。
    """
    return specs.even_margins(sheet.margins)


def margins_for(sheet, even, uniform_mm=None):
    """本作业实际使用的白边：等宽档优先，其次取齐，否则沿用逐边原值。"""
    return specs.used_margins(sheet.margins, even, uniform_mm)


def wants_even_margins(cell):
    """格子就是成品照片（role=paper，如 3R 纸打 3R 照片）时才取齐白边。

    证件照格（role=cell）的白边是要裁掉的废料：那里换成取齐只会把 A4 的
    一整排容量白丢（一寸照 9 排→8 排），四边差 2mm 也无人看。
    """
    return cell.role == "paper"


def uniform_applies(sheet, cell, mm, borderless_active=False, mode=None):
    """单张能不能真的“四周等宽”：只有在**不会把照片放大**时才成立。

    为什么：等宽是纸边上的框，照片铺满框。框比标称照片小 → 等比缩小（3R 纸
    打 3R 照片：89×127 → 78.8×116.8，裁掉极窄一圈）；框比照片大 → 只能把照片
    放大（4R 纸打 3R 照片会变成 92×142），那是默默改了成品尺寸，不干。
    框比照片大时保持标称尺寸、由装箱居中：左右相等、上下相等（取齐档）。

    判定只能有这一个出处：GUI 靠它决定文案/可用性，build_job 靠它决定
    Job.uniform_mm，render 靠它决定落位——三处各算一次就会报一套写另一套。
    """
    if cell.role != "paper" or borderless_active or mode == modes.BLEED_TRIM:
        return False
    box = specs.printable_rect(sheet, uniform_mm=mm)
    return box.w_mm <= cell.w_mm + 0.01 and box.h_mm <= cell.h_mm + 0.01


def build_layout(st, sheet_key, cell_key, gap_mm, bleed_mm, mode,
                 borderless_active=False, uniform_mm=None):
    """返回 (排版方案, 生效模式)。mode 为 None 时按默认映射决定。

    本函数是唯一真相源，cli.build_plan_jobs 只是它的薄转发（Task 4）。
    与旧 cli 实现的等价性已在历史提交上逐字段对拍过一次，此后不再靠
    两份实现互比——那只会退化成自己比自己，改由绝对格数与报错整句钉住。
    """
    sheet = st.resolve(sheet_key)
    cell = st.resolve(cell_key)
    even = wants_even_margins(cell)
    printable = specs.printable_rect(sheet, borderless_active=borderless_active,
                                     even=even)
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
    # 单张成品照片要“四周一样宽”：格子与整纸同尺寸时，按原内框装箱会退化
    # 成同轴取齐（左右窄、上下宽）。改按等宽内框重排；仍然装不下就是整纸
    # 一格，最终由 render 用同一个内框求交缩小。只对 1 格生效：多格时内框
    # 尺寸是所有照片共享的，拿它当“边距”会把整页拖小。
    if (uniform_mm is not None and plan.count == 1
            and uniform_applies(sheet, cell, uniform_mm,
                               borderless_active=borderless_active, mode=mode)):
        box = specs.printable_rect(sheet, uniform_mm=uniform_mm)
        plan = pack.pack(sheet, cell, gap_mm=0.0, bleed_mm=0.0,
                         allow_rotate=allow_rotate, printable=box)
        if plan.count == 0:
            full = specs.RectMM(0.0, 0.0, sheet.w_mm, sheet.h_mm)
            plan = pack.pack(sheet, cell, gap_mm=0.0, bleed_mm=0.0,
                             allow_rotate=allow_rotate, printable=full)
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
    rotations: tuple = ()   # 逐图顺时针角度，原样交 core 归一；短于 photos 缺位按 0
    date_overlay: object = None
    watermark_overlay: object = None
    date_texts: tuple = ()
    date_overrides: tuple = ()
    wm_overrides: tuple = ()
    even_margins: bool = False   # 成品照片档：白边同轴取齐（见 wants_even_margins）
    uniform_mm: float | None = None   # 单张成品照片：四边等宽的留白（见 build_layout）

    @property
    def count(self) -> int:
        return self.plan.count

    @property
    def page_count(self) -> int:
        """零照片也至少一页：界面要能预览空格。"""
        return max(1, pack.needed_sheets(self.plan.count, len(self.photos)))

    @property
    def note(self) -> str:
        """界面状态栏文案：边距来源那句按 margin_source 分档（规格 7.3）。

        两档都带来源：全局约束是无条件的——只要 `margin_source == "spec"` 就得
        说明“未经真机校准”。而出血档的预览偏偏仍在按规格边距画不可印遮罩带
        （render 层的 `_mask_bands`），界面正在用一组没证据的数字。

        cli 的 stdout 另有一套逐字冻结的文案（全局约束），两边共用同一份
        数字、不共用同一句话——界面要说清证据从哪来，cli 要保持历史输出不变。
        """
        provenance = _MARGIN_SOURCE_NOTE.get(self.sheet.margin_source,
                                             _UNKNOWN_MARGIN_SOURCE)
        if self.mode == modes.BLEED_TRIM:
            inner = self.plan.cells[0].inner_mm()
            return (f"需人工裁切：沿灰线切开后即为 {inner[2]:.0f}×{inner[3]:.0f}mm 成品"
                    f"（边距{provenance}）")
        # 文案里的数字必须与排版用的一致（同一档白边，含取齐与否）：
        # 照逐边原值写，界面就是在报另一套数字。
        m = margins_for(self.sheet, self.even_margins, self.uniform_mm)
        return (f"将保留白边：上{m.top}/下{m.bottom}/左{m.left}/右{m.right}mm"
                f"（边距{provenance}）")

    def render(self, page_index: int, dpi: float, show_mask: bool = False) -> Image.Image:
        """渲染单页。show_mask 只在预览开，导出必须关（否则灰边进相纸）。"""
        if not 0 <= page_index < self.page_count:
            raise IndexError(f"页码越界：{page_index}（共 {self.page_count} 页）")
        i = page_index * self.count
        chunk = self.photos[i:i + self.count]
        # 角度与照片共用一个下标空间（第 i 张照片配 rotations[i]）：photos 按页
        # 切片后 rotations 必须同样切片，否则第 2 页起角度会错位到别的照片上
        rot_chunk = self.rotations[i:i + self.count]
        dt_chunk = self.date_texts[i:i + self.count]
        do_chunk = self.date_overrides[i:i + self.count]
        wo_chunk = self.wm_overrides[i:i + self.count]
        return render.render_page(self.plan, chunk, self.sheet, dpi, self.mode,
                                  show_mask=show_mask,
                                  borderless_active=self.borderless_active,
                                  offset_pct=self.offset_pct,
                                  rotations=rot_chunk,
                                  date_overlay=self.date_overlay,
                                  watermark_overlay=self.watermark_overlay,
                                  date_texts=dt_chunk,
                                  date_overrides=do_chunk,
                                  wm_overrides=wo_chunk,
                                  even_margins=self.even_margins,
                                  uniform_mm=self.uniform_mm)


def build_job(st, photos, sheet_key, cell_key, *, gap_mm=0.0,
              bleed_mm=modes.DEFAULT_BLEED_MM, mode=None,
              offset_pct=(0.0, 0.0), borderless_active=False,
              rotations=(), date_overlay=None, watermark_overlay=None,
              date_texts=(), date_overrides=(), wm_overrides=(),
              uniform_mm=None) -> Job:
    plan, mode_eff = build_layout(st, sheet_key, cell_key, gap_mm, bleed_mm,
                                  mode, borderless_active=borderless_active,
                                  uniform_mm=uniform_mm)
    cell = st.resolve(cell_key)
    # 只在真正生效的那一种组合下把值交给 Job：多格、证件照拼版、出血档
    # 都不算“单张四周等宽”，否则状态栏会报一套根本没用的数字。
    uniform = (uniform_mm if (uniform_mm is not None
                              and plan.count == 1
                              and uniform_applies(st.resolve(sheet_key), cell,
                                                 uniform_mm,
                                                 borderless_active=borderless_active,
                                                 mode=mode_eff)) else None)
    # 存生效值而不是用户填的值：不足物理下限时（如要 4mm）要被抬到 5.1。
    # 抬的值只能有一个出处，否则 Job.uniform_mm 与 note/render 各算各的。
    if uniform is not None:
        uniform = specs.uniform_margins(st.resolve(sheet_key).margins,
                                        uniform).top
    # 百分比原样交给 core：同一页可能两种朝向混排，“按哪个尺寸换算”是逐格
    # 决策（T3 评审 I-1），本层若先按首格换算成 mm，其余格的 ±50% 就失真
    return Job(plan=plan, mode=mode_eff, sheet=st.resolve(sheet_key),
               photos=list(photos),
               offset_pct=tuple(float(v) for v in offset_pct),
               borderless_active=borderless_active,
               rotations=tuple(rotations),
               date_overlay=date_overlay, watermark_overlay=watermark_overlay,
               date_texts=tuple(date_texts),
               date_overrides=tuple(date_overrides),
               wm_overrides=tuple(wm_overrides),
               even_margins=wants_even_margins(cell),
               uniform_mm=uniform)


def render_all(job: Job, dpi: float, show_mask: bool = False) -> list[Image.Image]:
    """CLI 用：等价于逐页调用 job.render，避免两边各写一套切页。"""
    return [job.render(i, dpi, show_mask) for i in range(job.page_count)]


def _fmt_exif_dt(value):
    """EXIF 'YYYY:MM:DD HH:MM:SS' → 'YYYY-MM-DD'；取不到日期段返回 None。"""
    s = str(value).strip()
    date_part = s.split(" ")[0].split("T")[0]
    ymd = date_part.replace(":", "-").split("-")
    if len(ymd) >= 3 and all(x.isdigit() for x in ymd[:3]):
        return f"{int(ymd[0]):04d}-{int(ymd[1]):02d}-{int(ymd[2]):02d}"
    return None


def photo_date_text(path):
    """逐张日期文本：EXIF DateTimeOriginal→DateTime→文件 mtime→None。绝不抛。"""
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            raw = None
            try:
                ifd = exif.get_ifd(0x8769)             # ExifIFD
                raw = ifd.get(36867) or ifd.get(306)   # DateTimeOriginal / DateTime
            except Exception:
                raw = None
            raw = raw or exif.get(306)
            if raw:
                d = _fmt_exif_dt(raw)
                if d:
                    return d
    except Exception:
        pass
    try:
        return time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(path)))
    except OSError:
        return None
