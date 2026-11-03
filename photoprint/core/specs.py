"""相纸与格子尺寸规格表。

事实基线来自佳能中国 G3800 官方规格页：
  物理不可印边距 上3/下5/左右3.4mm（LTR、LGL 例外 左6.4/右6.3）
  自定义尺寸范围 宽55–215.9mm、长89–676mm
  无边距仅 A4/LTR/4"x6"/5"x7"/8"x10"/正方形5"x5"/卡片
  自定义尺寸不支持无边距 ⇒ 3R 必然留白边
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# G3800 自定义尺寸合法范围
MIN_FEED_W_MM, MAX_FEED_W_MM = 55.0, 215.9
MIN_FEED_L_MM, MAX_FEED_L_MM = 89.0, 676.0


@dataclass
class Margins:
    """物理不可印区，单位 mm。"""

    top: float = 3.0
    bottom: float = 5.0
    left: float = 3.4
    right: float = 3.4


@dataclass
class RectMM:
    x_mm: float
    y_mm: float
    w_mm: float
    h_mm: float


@dataclass
class SizeSpec:
    key: str
    label: str
    w_mm: float
    h_mm: float
    role: str  # paper=可当纸张 / cell=只能当拼版格子
    origin: str  # preset / custom / user / spec（spec = 只能当拼版格子，不对应任何驱动纸张）
    borderless: bool
    margins: Margins
    margin_source: str  # spec=依规格推定 / probed=驱动实测 / calibrated=真机校准
    # 驱动里的纸张名文本，用于运行时把预设匹配到实际驱动清单（地区命名不同）
    driver_paper_name: Optional[str] = None
    driver_paper_code: Optional[int] = None


def _m(key: str) -> Margins:
    if key in ("LTR", "LGL"):
        return Margins(top=3.0, bottom=5.0, left=6.4, right=6.3)
    return Margins(top=3.0, bottom=5.0, left=3.4, right=3.4)


def _paper(key, label, w, h, origin, borderless, driver_name=None, code=None):
    return SizeSpec(key, label, w, h, "paper", origin, borderless, _m(key),
                    "spec", driver_name, code)


PAPER_PRESETS = [
    # 驱动内置且官方无边距列表内有 ⇒ borderless=True
    _paper("A4", "A4", 210.0, 297.0, "preset", True, "A4", 9),
    _paper("LTR", "Letter", 215.9, 279.4, "preset", True, "Letter", 1),
    _paper("4R", "4R 6寸", 102.0, 152.0, "preset", True, "4x6"),
    _paper("5R", "5R 7寸", 127.0, 178.0, "preset", True, "5x7"),
    _paper("SQ55", "正方形 5x5", 127.0, 127.0, "preset", True, "5x5"),
    _paper("CARD", "卡片", 91.0, 55.0, "preset", True, "91x55"),
    # 官方无边距列表提到 8"x10"，但纸张列表未列 ⇒ 名字待运行时枚举确认
    _paper("7R", "7R 10寸", 203.0, 254.0, "preset", True, "8x10"),
    # 驱动内置但不在无边距列表
    _paper("A5", "A5", 148.0, 210.0, "preset", False, "A5", 11),
    _paper("B5", "B5", 176.0, 250.0, "preset", False, "B5", 13),
    _paper("LGL", "Legal", 215.9, 355.6, "preset", False, "Legal", 5),
    _paper("ENV_DL", "信封 DL", 110.0, 220.0, "preset", False, "DL", 27),
    # 只能走自定义尺寸 ⇒ 强制无边距不可用
    _paper("3R", "3R 5寸", 89.0, 127.0, "custom", False),
    _paper("6R", "6R 8寸", 152.0, 203.0, "custom", False),
]

CELL_PRESETS = [
    # 证件照规格：行业通行值，用户可在界面内直接改数值（各国签证不同）
    SizeSpec("ID1", "一寸", 25.0, 32.0, "cell", "spec", False, _m("X"), "spec"),
    SizeSpec("ID2", "二寸", 35.0, 49.0, "cell", "spec", False, _m("X"), "spec"),
    SizeSpec("IDS2", "小二寸", 35.0, 45.0, "cell", "spec", False, _m("X"), "spec"),
    SizeSpec("IDBIG1", "大一寸/护照", 33.0, 48.0, "cell", "spec", False, _m("X"), "spec"),
    SizeSpec("USVISA", "美国签证", 51.0, 51.0, "cell", "spec", False, _m("X"), "spec"),
]

ALL_PRESETS = PAPER_PRESETS + CELL_PRESETS
_INDEX = {s.key: s for s in ALL_PRESETS}


def find_spec(key: str) -> SizeSpec:
    try:
        return _INDEX[key]
    except KeyError:
        raise KeyError(f"未知尺寸：{key}") from None


def printable_rect(spec: SizeSpec, borderless_active: bool = False) -> RectMM:
    """可打印矩形。

    borderless_active 只有在驱动探测或真机校准实测到无边距已生效时才可为 True；
    margin_source == "spec" 时调用方不得凭空传 True（规格 7.4）。
    """
    if borderless_active:
        return RectMM(0.0, 0.0, spec.w_mm, spec.h_mm)
    m = spec.margins
    return RectMM(m.left, m.top, spec.w_mm - m.left - m.right,
                  spec.h_mm - m.top - m.bottom)


def custom_size_is_legal(w_mm: float, h_mm: float) -> tuple[bool, str]:
    """自定义尺寸范围校验，允许横竖交换判定。

    89×127 横放时长度恰为下限 89，因此必须两向都试。
    """
    for feed_w, feed_l in ((w_mm, h_mm), (h_mm, w_mm)):
        if (MIN_FEED_W_MM <= feed_w <= MAX_FEED_W_MM
                and MIN_FEED_L_MM <= feed_l <= MAX_FEED_L_MM):
            return True, ""
    return False, (f"G3800 自定义尺寸要求宽 {MIN_FEED_W_MM}–{MAX_FEED_W_MM}mm、"
                   f"长 {MIN_FEED_L_MM}–{MAX_FEED_L_MM}mm；"
                   f"{w_mm}×{h_mm}mm 两向都不满足")
