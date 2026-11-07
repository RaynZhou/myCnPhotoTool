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
    """四边白边，单位 mm。

    数值是「物理不可印区」的规格推定值（真机校准后会换成实测值），故允许
    逐边不等（本机 3R 实测：左3.39/右3.43/上2.96/下5.04）。排版用的白边不
    直接用它——那块必须同轴取齐，见 even_margins。
    """

    top: float = 3.0
    bottom: float = 5.0
    left: float = 3.4
    right: float = 3.4


# 取齐时统一多留的白边（mm）：规格值是 0.1mm 取整的估计，驱动实测可能
# 比它大不到 0.1mm（本机 3R：右 3.43 对规格 3.4、下 5.04 对 5.0）。不加
# 这点余量，照片最外一像素会被驱动边界吃掉。
EVEN_PAD_MM = 0.1


def even_margins(m: Margins) -> Margins:
    """同轴取大：上下相等、左右相等，且每边都不小于物理不可印区。

    为什么必须取齐：驱动给的不可印区天然不对称（本机底部比顶部多 2mm），
    直接拿四边原值排版，出片就是“上面窄、下面宽”，肉眼一眼看出歪。同轴
    取大＝把内容框往里收一点再居中：照片不会被裁（每边仍 ≥ 不可印区），
    上下、左右各自等宽。左右与上下之间仍可不同（纸张宽高比决定的自然结果，
    用户已确认可接受）。另加 EVEN_PAD_MM 余量，盖住规格取整与驱动实测差。
    """
    dy = round(max(m.top, m.bottom) + EVEN_PAD_MM, 2)
    dx = round(max(m.left, m.right) + EVEN_PAD_MM, 2)
    return Margins(top=dy, bottom=dy, left=dx, right=dx)


def used_margins(m: Margins, even: bool = False) -> Margins:
    """排版实际使用的一档白边：even=True 同轴取齐，否则沿用逐边原值。"""
    return even_margins(m) if even else m


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


# 注：LTR/LGL 的例外边距（左 6.4 / 右 6.3）绑在预设 key 上。用户自建尺寸即使用
# 同样的数值也不会自动拿到例外值，store 必须让调用方显式传 Margins（规格 4.5）。
# w_mm / h_mm 就是驱动里的宽/长，不约定大小关系（卡片 91×55 是宽大于高）。


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
    # B5 取向驱动实测：本机 G3800 的 B5 表单码 13 为 JIS 182×257（实测 181.99×256.96，官方规格同），不是 ISO 176×250。旧值差 6–7mm，足够让 verify_physical_size（0.5mm）每次判失败。
    _paper("B5", "B5", 182.0, 257.0, "preset", False, "B5", 13),
    _paper("LGL", "Legal", 215.9, 355.6, "preset", False, "Legal", 5),
    _paper("ENV_DL", "信封 DL", 110.0, 220.0, "preset", False, "DL", 27),
    _paper("ENV_10", "信封 COM10", 105.0, 241.0, "preset", False, "COM10", 20),
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


def printable_rect(spec: SizeSpec, borderless_active: bool = False,
                   even: bool = False) -> RectMM:
    """可打印矩形。

    borderless_active 只有在驱动探测或真机校准实测到无边距已生效时才可为 True；
    margin_source == "spec" 时调用方不得凭空传 True（规格 7.4）。

    even=True：白边同轴取齐（上下相等、左右相等），用于“照片本身就是成品”的
    场景（3R 纸打 3R 照片、4R 纸打 3R 照片）。证件照拼版不传：那类白边只是
    废料、要裁掉，换成取齐会把 A4 的一整排（一寸照 9 排→8 排）白丢。

    守卫：官方无边距清单之外的纸张（含一切自定义尺寸）传 True 直接报错。
    宁可当场报错也不能静默按整纸排版——后者就是规格 7.3 禁止的谎报。
    """
    if borderless_active and not spec.borderless:
        raise ValueError(f"{spec.key} 不支持无边距，borderless_active 不得为 True")
    if borderless_active:
        return RectMM(0.0, 0.0, spec.w_mm, spec.h_mm)
    m = used_margins(spec.margins, even)
    return RectMM(m.left, m.top, spec.w_mm - m.left - m.right,
                  spec.h_mm - m.top - m.bottom)


def custom_size_is_legal(w_mm: float, h_mm: float) -> tuple[bool, str]:
    """自定义尺寸范围校验，允许横竖交换判定。

    89×127 横放时长度恰为下限 89，因此必须两向都试。

    不合法时必须点出越界的那个具体数值与边界：只笼统报两个区间的话，
    调用方与测试都无法区分“宽超限”和“长不够”，断言会退化成永真。
    """
    for feed_w, feed_l in ((w_mm, h_mm), (h_mm, w_mm)):
        if (MIN_FEED_W_MM <= feed_w <= MAX_FEED_W_MM
                and MIN_FEED_L_MM <= feed_l <= MAX_FEED_L_MM):
            return True, ""
    limits = (f"宽 {MIN_FEED_W_MM}–{MAX_FEED_W_MM}mm、"
              f"长 {MIN_FEED_L_MM}–{MAX_FEED_L_MM}mm")
    long_side, short_side = max(w_mm, h_mm), min(w_mm, h_mm)
    if long_side > MAX_FEED_W_MM:
        why = f"{long_side}mm > {MAX_FEED_W_MM}mm（进纸宽度上限）"
    elif short_side < MIN_FEED_L_MM:
        why = f"{short_side}mm < {MIN_FEED_L_MM}mm（走纸长度下限）"
    elif short_side < MIN_FEED_W_MM:
        why = f"{short_side}mm < {MIN_FEED_W_MM}mm（进纸宽度下限）"
    else:
        why = f"{long_side}mm > {MAX_FEED_L_MM}mm（走纸长度上限）"
    return False, (f"G3800 自定义尺寸要求{limits}；"
                   f"{w_mm}×{h_mm}mm 两向都不满足：{why}")
