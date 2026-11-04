# 相片打印助手 · 核心几何与打印链路（M1+M2）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现一个无界面的相片拼版与打印内核：能把照片按任意相纸尺寸（含 3R 89×127mm）排版、渲染成物理尺寸精确的位图，并通过 Windows GDI 直打或等尺寸 PDF 导出送进打印机。

**Architecture:** 三层单向依赖。`core/` 是纯函数层（尺寸表、装箱、裁切、渲染、模式映射），不得 import 任何 GUI 或 win32 模块，因此可在无窗口无打印机环境下全量测试；`win/` 封装驱动探测、DEVMODE 构造、GDI 送页与 PDF 导出；`photoprint/cli.py` 把两层串成一条可手工验收的流水线。界面（M3）与校准页（M4）在第二份计划中实现，只调用本计划产出的 `core/` 接口。

**Tech Stack:** Python 3.13、Pillow 12.x、pywin32、img2pdf、pytest。Windows 平台。

规格来源：`docs/superpowers/specs/2026-11-03-photo-print-app-design.md`（已提交 d6781cd）。本计划覆盖规格第 2、4、5、6、7、9、10 节与第 17 节的 M1、M2 两批。

## Global Constraints

- 代码注释一律用中文。自动化测试放 `tests/`（pytest）；需要真机或手工比对的一次性验证脚本放 `_lab/`，其输出进 `_lab/out/`。
- 直接 `import` 的包必须在 `requirements.txt` 显式声明（`Pillow`、`pywin32`、`img2pdf`、`pytest`、`PySide6`），不得依赖传递依赖；README 同步一份依赖说明。
- `photoprint/core/**` 禁止 import `PySide6`、`win32print`、`win32ui`、`win32con`；违反即视为架构缺陷。
- mm↔px 的唯一换算：`ppmm = dpi / 25.4`。渲染层内不得出现第二套换算公式。
- G3800 官方物理边距：上 3mm、下 5mm、左 3.4mm、右 3.4mm；LTR/LGL 例外为左 6.4mm、右 6.3mm。
- G3800 自定义尺寸合法范围：宽 55–215.9mm、长 89–676mm，判定允许横竖交换。
- 无边距仅 A4/LTR/4"x6"/5"x7"/8"x10"/正方形5"x5"/卡片；**自定义尺寸不支持无边距**（含 3R）。
- `margins_mm = 0` 只能在探测或校准实测到无边距生效时成立；`margin_source == "spec"` 时不得假设边距为 0。
- DEVMODE 四条不可变语义：按驱动回报的 size 分配 buffer、继承驱动私有扩展区、不改 `cbSize`、只改纸张相关字段。禁止 new 空 DEVMODE。
- GDI 回读物理尺寸与请求值的容差为 **0.5mm**，超限即判定驱动忽略自定义尺寸并中止直打。
- 用户可见文案禁则：`borderless=False` 时不得出现"无边距"；`fill_printable` 时不得出现"铺满整张纸"；未校准时不得给出 0.1mm 级白边承诺。
- 装箱基准为硬断言，数值取自规格 5.3：`A4+3R=4`、`A4+4R=3`、`A4+5R=2`、`4R+3R=1`、`A4+3R(bleed3)=4`、`A4+ID1(gap2, 禁旋转)=56`、`A4+ID2(gap2, 禁旋转)=25`、`A4 去边距后+3R=4`。
- 证件照（`role=cell`）拼版必须传 `allow_rotate=False`：旋转会把格子横放，贴出来的证件照是躺倒的；允许旋转只会让张数虚高，不作为基准值。
- `pack.pack` 的默认装箱区域是**整张纸**（与规格 5.3 手算基准同口径）；任何要真送打的排版必须显式传 `printable=specs.printable_rect(...)`（无边距生效时它返回整张纸）——T9 渲染与 T14 CLI 都属此列，不自愿传就会把照片切进物理边距。

## 文件结构（本计划范围内）

| 文件 | 职责 | 建立于 |
|---|---|---|
| `requirements.txt` | 显式依赖清单 | T1 |
| `pytest.ini` | 测试发现规则，排除 `_lab/` | T1 |
| `photoprint/__init__.py` | 包标记 | T1 |
| `photoprint/core/__init__.py` | 层标记 + 禁则注释 | T1 |
| `photoprint/core/units.py` | mm↔px 唯一换算入口 | T1 |
| `tests/test_units.py` | 换算断言 | T1 |
| `photoprint/core/specs.py` | 尺寸数据模型、预设表、可打印矩形、自定义尺寸校验 | T2 |
| `tests/test_specs.py` | 3R 可打印矩形、无边距归零、12寸阻断 | T2 |
| `photoprint/core/store.py` | `papers.json` 覆盖与用户自建尺寸读写 | T3 |
| `tests/test_store.py` | 只存差异、写盘失败降级内存 | T3 |
| `photoprint/core/pack.py` | 装箱第 1 级：均匀网格 | T4 |
| `tests/test_pack_grid.py` | 网格基准断言 | T4 |
| `photoprint/core/pack.py` | 装箱第 2、3 级：一刀双带、两刀三带、决胜排序 | T5 |
| `tests/test_pack_bands.py` | `A4+4R=3` 等混合带断言、变异测试 | T5 |
| `photoprint/core/pack.py` | 裁切缝 `cuts` 生成、`needed_sheets` | T6 |
| `tests/test_pack_cuts.py` | 缝坐标断言与分页数 | T6 |
| `photoprint/core/crop.py` | `cell_crop_box` 预览与打印共用裁切放置 | T7 |
| `tests/test_crop.py` | 覆盖性、钳制、锚点缩放 | T7 |
| `photoprint/core/modes.py` | 三档模式与默认映射、出血默认值 | T8 |
| `tests/test_modes.py` | 映射表逐条断言 | T8 |
| `photoprint/core/render.py` | `render_page` 出物理精确位图（照片/遮罩/裁切线） | T9 |
| `tests/test_render_geometry.py` | 1px=1mm 技巧下的像素级几何断言 | T9 |
| `photoprint/win/api.py` | win32 调用的可注入薄封装 | T10 |
| `photoprint/win/probe.py` | 驱动能力探测与比对报告 | T10 |
| `tests/test_probe.py` | monkeypatch 断言 mm 换算与冲突报告 | T10 |
| `photoprint/win/devmode.py` | DEVMODE 继承与改写 | T11 |
| `tests/test_devmode.py` | buffer 不截断、dmFields 位、0.1mm 单位 | T11 |
| `photoprint/win/gdi_print.py` | CreateDC/StretchBlt 送页 + 0.5mm 回读校验 | T12 |
| `tests/test_gdi_verify.py` | 纯函数容差判定 | T12 |
| `photoprint/win/pdf_export.py` | 等尺寸 PDF 导出 | T13 |
| `tests/test_pdf_export.py` | MediaBox 点数断言 | T13 |
| `photoprint/cli.py` | 串起 probe→pack→crop→render→print/pdf | T14 |
| `_lab/m1m2_check.py` | 端到端手工验收脚本与证据输出 | T14 |
| `README.md` | 用法、真机待验证清单、驱动建表单指引 | T14 |

---

### Task 1: 项目骨架与唯一换算入口

**Files:**
- Create: `requirements.txt`
- Create: `pytest.ini`
- Create: `photoprint/__init__.py`
- Create: `photoprint/core/__init__.py`
- Create: `photoprint/core/units.py`
- Create: `photoprint/win/__init__.py`
- Test: `tests/test_units.py`

**Interfaces:**
- Consumes: 无
- Produces: `units.ppmm(dpi: float) -> float`（每毫米像素数）；`units.mm_to_px(mm: float, dpi: float) -> int`；`units.px_to_mm(px: float, dpi: float) -> float`；`units.win_mm(value_mm: float) -> int`（Windows DEVMODE 用的 0.1mm 整数）；`units.mm_to_scene(mm: float) -> int`（场景坐标，1 单位=0.1mm，供 M3 界面复用）

- [ ] **Step 1: 建依赖清单与 pytest 配置**

`requirements.txt`：

```
# 直接 import 的包一律显式声明，不依赖传递依赖
Pillow>=12.0
pywin32>=306 ; sys_platform == "win32"
img2pdf>=0.5
pytest>=8.0
PySide6>=6.7
```

`pytest.ini`：

```ini
[pytest]
testpaths = tests
python_files = test_*.py
addopts = -q
```

- [ ] **Step 2: 写失败测试**

`tests/test_units.py`：

```python
"""mm 与像素换算的断言：全项目只允许这一套换算。"""
from photoprint.core import units


def test_ppmm_300dpi():
    assert units.ppmm(300) == 300 / 25.4


def test_mm_to_px_rounds_half_up():
    # 89mm @300dpi = 1051.181 像素 → 1051；0.35mm 线宽 @300dpi = 4.134 → 4
    assert units.mm_to_px(89, 300) == 1051
    assert units.mm_to_px(0.35, 300) == 4
    # 恰好 .5 时必须向上：round() 是银行家舍入（round(2.5)==2），
    # 用它会让“dpi=25.4 下 1mm=1px”的像素断言反直觉，Task 9 的几何测试依赖这点
    assert units.mm_to_px(2.5, 25.4) == 3


def test_mm_to_px_at_one_pixel_per_mm():
    # dpi=25.4 时 1 像素 = 1 毫米，几何测试靠这个技巧做像素级断言
    assert units.mm_to_px(210, 25.4) == 210


def test_px_mm_roundtrip_within_half_pixel():
    for dpi in (25.4, 150, 300, 600):
        for mm in (89.0, 127.0, 210.0, 297.0, 3.4):
            back = units.px_to_mm(units.mm_to_px(mm, dpi), dpi)
            assert abs(back - mm) <= 0.5 / units.ppmm(dpi) + 1e-9


def test_win_mm_uses_tenth_of_mm():
    assert units.win_mm(89.0) == 890
    assert units.win_mm(127.0) == 1270
    assert units.win_mm(82.25) == 822  # 0.1mm 向下取整，宁小勿大避免溢出纸张


def test_mm_to_scene_is_tenth_mm():
    assert units.mm_to_scene(89.0) == 890
    assert units.mm_to_scene(3.4) == 34
    assert units.mm_to_scene(0.25) == 3  # 2.5 个 0.1mm 单位，同样 .5 向上


def test_round_px_is_half_up():
    # 全项目取整口径的公共入口（T7 评审 I-1：crop 层也必须走它）
    assert units.round_px(2.5) == 3
    assert units.round_px(20.5) == 21
    assert units.round_px(-0.5) == 0  # floor(v+0.5)，负半同样向大数一侧
```

- [ ] **Step 3: 运行确认失败**

Run: `python -m pytest tests/test_units.py -v`
Expected: FAIL —`ModuleNotFoundError: No module named 'photoprint'`

- [ ] **Step 4: 实现 units 与包标记**

`photoprint/__init__.py`（空文件，仅注释）：

```python
"""相片打印助手：core（纯函数）/ win（Windows 打印）/ app（界面）。"""
```

`photoprint/core/__init__.py`：

```python
"""纯函数层。

禁则：本包内禁止 import PySide6、win32print、win32ui、win32con，
否则 core 无法在无窗口无打印机环境下测试，而本机没有连接 G3800。
"""
```

`photoprint/win/__init__.py`：

```python
"""Windows 打印链路层：驱动探测、DEVMODE、GDI 送页、PDF 导出。"""
```

`photoprint/core/units.py`：

```python
"""mm 与像素的唯一换算入口。"""
from __future__ import annotations

import math

MM_PER_INCH = 25.4


def round_px(value: float) -> int:
    """就近取整，.5 一律向上。全项目取整口径，渲染/裁切层都用它。

    不用内置 round()：它是银行家舍入，round(2.5) == 2、round(20.5) == 20，
    而本项目的几何断言（尤其 dpi=25.4 时 1 像素 = 1 毫米那批）需要的是
    直觉上的四舍五入，否则半像素落点会以一种看不出规律的方式偏移。
    """
    return int(math.floor(value + 0.5))


def ppmm(dpi: float) -> float:
    """每毫米对应多少像素。"""
    return dpi / MM_PER_INCH


def mm_to_px(mm: float, dpi: float) -> int:
    """mm 转像素，就近取整（.5 向上）。"""
    return round_px(mm * ppmm(dpi))


def px_to_mm(px: float, dpi: float) -> float:
    """像素回算 mm。"""
    return px / ppmm(dpi)


def win_mm(value_mm: float) -> int:
    """转 Windows DEVMODE 的 0.1mm 整数单位（1mm = 10 单位）。

    向下取整：纸张尺寸宁可小 0.1mm，也不要超出物理纸张导致驱动二次缩放。
    """
    return int(value_mm * 10)


def mm_to_scene(mm: float) -> int:
    """场景坐标：1 单位 = 0.1mm，整数以免累积误差。"""
    return round_px(mm * 10)
```

- [ ] **Step 5: 运行确认通过**

Run: `python -m pytest tests/test_units.py -v`
Expected: PASS（7 passed）

- [ ] **Step 6: 提交**

```bash
git add requirements.txt pytest.ini photoprint tests
git commit -m "feat: 项目骨架与 mm/像素唯一换算入口"
```

---

### Task 2: 尺寸规格表与可打印矩形

**Files:**
- Create: `photoprint/core/specs.py`
- Test: `tests/test_specs.py`

**Interfaces:**
- Consumes: `units.ppmm`
- Produces:
  - `specs.Margins(top: float, bottom: float, left: float, right: float)`
  - `specs.SizeSpec(key, label, w_mm, h_mm, role, origin, borderless, margins, margin_source, driver_paper_name, driver_paper_code)`（字段顺序以此为准，数据类定义与 T3 的位置构造均按此序）
  - `specs.RectMM(x_mm, y_mm, w_mm, h_mm)`
  - `specs.PAPER_PRESETS: list[SizeSpec]`、`specs.CELL_PRESETS: list[SizeSpec]`、`specs.ALL_PRESETS: list[SizeSpec]`
  - `specs.find_spec(key: str) -> SizeSpec`
  - `specs.printable_rect(spec: SizeSpec, borderless_active: bool = False) -> RectMM`
  - `specs.custom_size_is_legal(w_mm: float, h_mm: float) -> tuple[bool, str]`

- [ ] **Step 1: 写失败测试**

`tests/test_specs.py`：

```python
"""尺寸表与可打印矩形：数值取自佳能中国 G3800 官方规格页。"""
import pytest

from photoprint.core import specs


def test_3r_exists_and_is_custom_no_borderless():
    s = specs.find_spec("3R")
    assert (s.w_mm, s.h_mm) == (89.0, 127.0)
    assert s.role == "paper"
    assert s.origin == "custom"
    assert s.borderless is False
    assert s.margin_source == "spec"


def test_3r_printable_rect_subtracts_physical_margins():
    s = specs.find_spec("3R")
    r = specs.printable_rect(s)
    assert r.w_mm == pytest.approx(82.2, abs=1e-6)   # 89 - 3.4 - 3.4
    assert r.h_mm == pytest.approx(119.0, abs=1e-6)  # 127 - 3 - 5
    assert (r.x_mm, r.y_mm) == (3.4, 3.0)


def test_a4_borderless_active_zeroes_margins():
    """规格 7.4：实测无边距生效时目标矩形等于整张纸。"""
    s = specs.find_spec("A4")
    assert s.borderless is True
    off = specs.printable_rect(s, borderless_active=False)
    on = specs.printable_rect(s, borderless_active=True)
    assert off.w_mm == pytest.approx(203.2)
    assert on.w_mm == pytest.approx(210.0)
    assert on.h_mm == pytest.approx(297.0)
    assert (on.x_mm, on.y_mm) == (0.0, 0.0)


def test_borderless_active_rejected_on_non_borderless_sheet():
    """规格第 2 节硬事实：自定义尺寸（含 3R）不支持无边距。

    守卫放在这里而不是每个调用点：printable_rect 是唯一能同时看到
    `spec.borderless` 与 `borderless_active` 的地方，调用侧把关意味着
    T8/T9/T12/T14 都要各自记住这条。
    """
    s = specs.find_spec("3R")
    assert s.borderless is False
    with pytest.raises(ValueError, match="无边距"):
        specs.printable_rect(s, borderless_active=True)


def test_source_spec_never_assumes_zero_margins():
    """margin_source=spec 时，即使尺寸有边框能力也必须按规格边距处理。"""
    s = specs.find_spec("4R")
    assert s.borderless is True
    assert s.margin_source == "spec"
    r = specs.printable_rect(s)  # 未声明 borderless_active
    assert r.w_mm == pytest.approx(95.2)  # 102 - 3.4 - 3.4，钉死而非只判“小于”


def test_ltr_uses_exception_margins():
    s = specs.find_spec("LTR")
    assert (s.margins.left, s.margins.right) == (6.4, 6.3)


def test_cell_presets_cannot_be_used_as_paper():
    for s in specs.CELL_PRESETS:
        assert s.role == "cell"
    for s in specs.PAPER_PRESETS:
        assert s.role == "paper"


def test_id_photo_sizes_are_unchanged():
    assert specs.find_spec("ID1").w_mm == 25.0
    assert specs.find_spec("ID1").h_mm == 32.0
    assert specs.find_spec("ID2").w_mm == 35.0
    assert specs.find_spec("ID2").h_mm == 49.0


def test_custom_legal_accepts_3r_both_orientations():
    ok, _ = specs.custom_size_is_legal(89.0, 127.0)
    assert ok
    ok, _ = specs.custom_size_is_legal(127.0, 89.0)
    assert ok


def test_custom_illegal_12inch_is_blocked():
    """12寸 254×305：宽 254 > 215.9，两向都不合法 —— 必须阻断。"""
    ok, msg = specs.custom_size_is_legal(254.0, 305.0)
    assert ok is False
    assert "305.0mm > 215.9mm" in msg  # 必须点出越界的具体数值与边界


def test_custom_illegal_below_length_floor():
    """80×70：两个方向当宽度都 ∈ 55–215.9，但当长度都 < 89 ⇒ 只违反长度下限。

    不得用 100×80 做这个用例：允许横竖交换后 80 当宽、100 当长完全合法，
    而卡片 91×55 结构同形（只能靠交换才合法），任何“让 100×80 不合法”的改法都会误判死卡片。
    """
    ok, msg = specs.custom_size_is_legal(80.0, 70.0)
    assert ok is False
    assert "70.0mm < 89.0mm" in msg  # 精确到违反的那条边界


def test_12inch_is_not_a_preset():
    keys = {s.key for s in specs.ALL_PRESETS}
    assert not any(s.w_mm >= 254 for s in specs.ALL_PRESETS if s.role == "paper")
    assert "12INCH" not in keys
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_specs.py -v`
Expected: FAIL —`ModuleNotFoundError: No module named 'photoprint.core.specs'`

- [ ] **Step 3: 实现 specs**

`photoprint/core/specs.py`：

```python
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
    _paper("B5", "B5", 176.0, 250.0, "preset", False, "B5", 13),
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


def printable_rect(spec: SizeSpec, borderless_active: bool = False) -> RectMM:
    """可打印矩形。

    borderless_active 只有在驱动探测或真机校准实测到无边距已生效时才可为 True；
    margin_source == "spec" 时调用方不得凭空传 True（规格 7.4）。

    守卫：官方无边距清单之外的纸张（含一切自定义尺寸）传 True 直接报错。
    宁可当场报错也不能静默按整纸排版——后者就是规格 7.3 禁止的谎报。
    """
    if borderless_active and not spec.borderless:
        raise ValueError(f"{spec.key} 不支持无边距，borderless_active 不得为 True")
    if borderless_active:
        return RectMM(0.0, 0.0, spec.w_mm, spec.h_mm)
    m = spec.margins
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
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_specs.py -v`
Expected: PASS（12 passed）

- [ ] **Step 5: 提交**

```bash
git add photoprint/core/specs.py tests/test_specs.py
git commit -m "feat: G3800 相纸与证件照尺寸规格表及可打印矩形"
```

---

### Task 3: 用户尺寸与标定值的持久化

**Files:**
- Create: `photoprint/core/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `specs.SizeSpec`、`specs.Margins`、`specs.custom_size_is_legal`
- Produces:
  - `store.Store(path: Path)`
  - `Store.load() -> None`
  - `Store.override_margins(key: str, margins: Margins, source: str) -> None`
  - `Store.add_user_size(spec: SizeSpec) -> None`
  - `Store.resolve(key: str) -> SizeSpec`（预设 + 覆盖 + 自建，返回生效规格）
  - `Store.save() -> bool`（写盘失败返回 False，但内存修改仍生效）
  - `Store.raw: dict`（`overrides` / `user_sizes` / `last_job` 三段）
  - `store.DEFAULT_PATH: Path`（依 `%APPDATA%` 推导）
- 真相源规则（M3 界面与后续任务都依此行事）：`resolve` 对自建 key 只看 `_users`，
  `raw["user_sizes"]` 每次变更后由 `_users` 重新序列化；自建 key 的边距更新写它
  自己的记录，不写 `overrides`。

- [ ] **Step 1: 写失败测试**

`tests/test_store.py`：

```python
"""papers.json 只存差异，升级预设不得冲掉用户标定。"""
import json
from pathlib import Path

import pytest

from photoprint.core import specs, store


@pytest.fixture
def tmp_store(tmp_path):
    return store.Store(tmp_path / "papers.json")


def test_resolve_without_override_returns_preset(tmp_store):
    tmp_store.load()
    s = tmp_store.resolve("3R")
    assert s.margins.top == 3.0
    assert s.margin_source == "spec"


def test_override_margins_upgrades_source_and_persists(tmp_store):
    tmp_store.load()
    tmp_store.override_margins("3R", specs.Margins(2.8, 5.2, 3.5, 3.5), "calibrated")
    assert tmp_store.save() is True
    disk = json.loads(Path(tmp_store.path).read_text(encoding="utf-8"))
    assert disk["overrides"]["3R"]["margin_source"] == "calibrated"
    assert disk["overrides"]["3R"]["margins_mm"]["bottom"] == 5.2

    again = store.Store(tmp_store.path)
    again.load()
    s = again.resolve("3R")
    assert s.margin_source == "calibrated"
    assert s.margins.left == 3.5


def test_file_only_stores_difference_not_whole_preset(tmp_store):
    tmp_store.load()
    tmp_store.override_margins("3R", specs.Margins(3.0, 5.0, 3.4, 3.4), "probed")
    tmp_store.save()
    disk = json.loads(Path(tmp_store.path).read_text(encoding="utf-8"))
    assert set(disk["overrides"]["3R"]) == {"margins_mm", "margin_source", "updated_at"}
    assert "w_mm" not in disk["overrides"]["3R"]


def test_user_size_rejects_illegal(tmp_store):
    tmp_store.load()
    bad = specs.SizeSpec("user-12", "12寸", 254.0, 305.0, "paper", "user",
                         False, specs.Margins(), "spec")
    with pytest.raises(ValueError, match="215.9"):
        tmp_store.add_user_size(bad)


def test_user_size_forces_borderless_false(tmp_store):
    tmp_store.load()
    s = specs.SizeSpec("user-4d", "4D 自建", 100.0, 148.0, "paper", "user",
                       True, specs.Margins(), "spec")
    tmp_store.add_user_size(s)
    got = tmp_store.resolve("user-4d")
    assert got.origin == "user"
    assert got.borderless is False  # 自定义尺寸不可能无边距，用户意愿不予采纳
    assert s.borderless is True     # 不得就地改调用方交进来的对象

    # 自建尺寸必须走完 save → load → resolve 的往返。只测内存里那条断言，
    # 磁盘少写一个字段也照样是绿的。
    assert tmp_store.save() is True
    again = store.Store(tmp_store.path)
    again.load()
    back = again.resolve("user-4d")
    assert (back.key, back.label) == ("user-4d", "4D 自建")
    assert (back.w_mm, back.h_mm) == (100.0, 148.0)
    assert back.origin == "user"
    assert back.role == "paper"
    assert back.borderless is False
    assert back.margins.bottom == 5.0

    # 磁盘上谎称无边距 / 当格子用也不采信：这条边界由代码守，不由文件守
    disk = json.loads(Path(tmp_store.path).read_text(encoding="utf-8"))
    disk["user_sizes"][0]["borderless"] = True
    disk["user_sizes"][0]["role"] = "cell"
    Path(tmp_store.path).write_text(json.dumps(disk, ensure_ascii=False),
                                    encoding="utf-8")
    liar = store.Store(tmp_store.path)
    liar.load()
    assert liar.resolve("user-4d").borderless is False
    assert liar.resolve("user-4d").role == "paper"


def test_save_failure_keeps_memory_effect(tmp_path):
    blocked = tmp_path / "dir.json"
    blocked.mkdir()  # 目录占位，写文件必然失败
    st = store.Store(blocked)
    st.load()
    st.override_margins("3R", specs.Margins(1, 2, 3, 4), "calibrated")
    assert st.save() is False
    assert st.resolve("3R").margin_source == "calibrated"


def test_corrupt_file_falls_back_to_empty(tmp_store):
    Path(tmp_store.path).write_text("{ not json", encoding="utf-8")
    tmp_store.load()
    assert tmp_store.resolve("3R").margin_source == "spec"


def test_override_margins_on_user_size_reaches_back(tmp_store):
    """自建尺寸的边距只能落在它自己的记录上。

    resolve() 里 `_users` 短路在前，`overrides[key]` 对自建 key 是死数据：
    标定值看着存下了，实际每次都被磁盘上的旧记录盖掉。
    """
    tmp_store.load()
    tmp_store.add_user_size(specs.SizeSpec(
        "user-4d", "4D 自建", 100.0, 148.0, "paper", "user",
        False, specs.Margins(), "spec"))
    tmp_store.override_margins("user-4d", specs.Margins(1.5, 2.5, 3.5, 4.5),
                               "calibrated")
    assert tmp_store.resolve("user-4d").margins.left == 3.5
    assert "user-4d" not in tmp_store.raw["overrides"]
    assert tmp_store.save() is True
    again = store.Store(tmp_store.path)
    again.load()
    back = again.resolve("user-4d")
    assert back.margin_source == "calibrated"
    assert (back.margins.top, back.margins.bottom, back.margins.right) == (
        1.5, 2.5, 4.5)


@pytest.mark.parametrize("text", [
    "null",
    "[1, 2]",
    '{"user_sizes": ["abc"]}',
    '{"user_sizes": [{"key": "u1"}]}',
    '{"overrides": 3, "user_sizes": {"key": "u1"}}',
])
def test_structured_json_corruption_is_contained(tmp_store, text):
    """语法能过但形状错：不能抛，也不能带出半条记录。

    这些是用户手工编辑 papers.json 或旧版本写坏文件后最常见的形状。load()
    抛异常会让程序卡在启动，比丢掉这份配置更糟。
    """
    Path(tmp_store.path).write_text(text, encoding="utf-8")
    tmp_store.load()  # 不得抛
    assert isinstance(tmp_store.raw["overrides"], dict)
    assert isinstance(tmp_store.raw["user_sizes"], list)
    with pytest.raises(KeyError):
        tmp_store.resolve("u1")
    assert tmp_store.resolve("3R").margin_source == "spec"


def test_good_user_sizes_survive_a_bad_sibling(tmp_store):
    Path(tmp_store.path).write_text(json.dumps({"user_sizes": [
        {"key": "u-ok", "label": "ok", "w_mm": 100.0, "h_mm": 148.0},
        {"key": "u-bad"},
    ]}), encoding="utf-8")
    tmp_store.load()
    assert tmp_store.resolve("u-ok").label == "ok"
    # 坏条目已被剔除，下次存盘就写不回磁盘了
    assert [d["key"] for d in tmp_store.raw["user_sizes"]] == ["u-ok"]


def test_user_size_rejects_bad_key(tmp_store):
    """空 key 或与预设重名：重名会让 `_users` 静默遮蔽预设。"""
    tmp_store.load()
    for bad_key in ("", "A4"):
        s = specs.SizeSpec(bad_key, "x", 100.0, 148.0, "paper", "user",
                           False, specs.Margins(), "spec")
        with pytest.raises(ValueError, match="key"):
            tmp_store.add_user_size(s)
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_store.py -v`
Expected: FAIL —`ModuleNotFoundError: No module named 'photoprint.core.store'`

- [ ] **Step 3: 实现 store**

`photoprint/core/store.py`：

```python
"""用户配置读写：预设 + 覆盖差异 + 自建尺寸三者的合成。

真相源规则（后续任务与 M3 界面都依此行事）：
- 预设：specs.PAPER_PRESETS，papers.json 只存覆盖差异 overrides[key]；
- 自建尺寸：self._users 是唯一定本，raw["user_sizes"] 每次变更后由它重新序列化；
- 自建 key 的边距走 _users 记录本身，不写 overrides —— overrides 对自建 key
  永不生效（resolve 里 _users 短路在前），写进去就是死数据。

写盘失败（权限、被占用）时内存修改依然生效并返回 False，
调用方必须在状态栏提示"本次设置未持久化"，不得静默丢弃。
"""
from __future__ import annotations

import copy
import json
import os
from datetime import date
from pathlib import Path
from typing import Optional

from photoprint.core import specs

# 自建尺寸不得用这些 key：_users 在 resolve 里短路在前，重名会静默遮蔽预设
PRESET_KEYS = frozenset(s.key for s in specs.PAPER_PRESETS + specs.CELL_PRESETS)


def default_path() -> Path:
    """`%APPDATA%\\PhotoPrint\\papers.json`。

    用环境变量而不是 `Path.home() / "AppData" / "Roaming"`：前者尊重重定向与
    非系统盘部署，后者只在系统盘就是 C: 时才对；取不到 APPDATA 才退回家目录推算。
    """
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    return root / "PhotoPrint" / "papers.json"


DEFAULT_PATH = default_path()


def _empty_raw() -> dict:
    return {"overrides": {}, "user_sizes": [], "last_job": {}}


def _norm_margins(m: specs.Margins) -> specs.Margins:
    """归一为 float：SpinBox 常交来 int，混进去会让同一份配置里出现 3 与 3.0 两种形状。"""
    return specs.Margins(float(m.top), float(m.bottom), float(m.left), float(m.right))


def _margins_from_dict(m: dict) -> specs.Margins:
    """缺字段按规格默认补齐，与 _from_dict 走同一条路径。"""
    return specs.Margins(float(m.get("top", 3.0)), float(m.get("bottom", 5.0)),
                         float(m.get("left", 3.4)), float(m.get("right", 3.4)))


class Store:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else DEFAULT_PATH
        self.raw: dict = _empty_raw()
        self._users: dict[str, specs.SizeSpec] = {}

    def load(self) -> None:
        """读盘。任何损坏都降级成"这份没有"，结对不抛。

        只挡语法错不够：用户手改过的 papers.json 多半是语法对、形状错
        （顶层是 list、user_sizes 里混进字符串、条目缺 label），那些必须在
        这里一次性围住，否则坏配置会把启动流程整个卡死。
        """
        try:
            disk = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            disk = None
        if not isinstance(disk, dict):
            disk = {}
        self.raw = _empty_raw()
        overrides = disk.get("overrides")
        if isinstance(overrides, dict):
            # 逐条也要形状对，否则 resolve 会在后面某次调用里招
            self.raw["overrides"] = {
                k: v for k, v in overrides.items()
                if isinstance(v, dict) and isinstance(v.get("margins_mm"), dict)}
        last_job = disk.get("last_job")
        self.raw["last_job"] = last_job if isinstance(last_job, dict) else {}
        items = disk.get("user_sizes")
        self._users = {}
        for item in items if isinstance(items, list) else []:
            try:
                spec = _from_dict(item)
            except (KeyError, TypeError, ValueError):
                continue  # 单条坏记录不牵连其余
            self._users[spec.key] = spec
        self._sync_user_sizes()

    def resolve(self, key: str) -> specs.SizeSpec:
        if key in self._users:
            return copy.deepcopy(self._users[key])
        base = specs.find_spec(key)
        ov = self.raw["overrides"].get(key)
        if not ov:
            return copy.deepcopy(base)
        return specs.SizeSpec(
            base.key, base.label, base.w_mm, base.h_mm, base.role, base.origin,
            base.borderless,
            _margins_from_dict(ov["margins_mm"]),
            ov.get("margin_source", "spec"),
            base.driver_paper_name, base.driver_paper_code,
        )

    def override_margins(self, key: str, margins: specs.Margins, source: str) -> None:
        m = _norm_margins(margins)
        user = self._users.get(key)
        if user is not None:
            # 自建尺寸的真相源只有一份：直接改它自己的记录
            user.margins = m
            user.margin_source = source
            self._sync_user_sizes()
            return
        self.resolve(key)  # 未知 key 在这里抛错，避免写入无效覆盖
        self.raw["overrides"][key] = {
            "margins_mm": {"top": m.top, "bottom": m.bottom,
                           "left": m.left, "right": m.right},
            "margin_source": source,
            "updated_at": date.today().isoformat(),
        }

    def add_user_size(self, spec: specs.SizeSpec) -> None:
        if not spec.key or spec.key in PRESET_KEYS:
            raise ValueError(f"自建尺寸 key 非法：{spec.key!r}（不得为空，不得与预设重名）")
        ok, msg = specs.custom_size_is_legal(spec.w_mm, spec.h_mm)
        if not ok:
            raise ValueError(msg)
        # 存副本而不是改入参：就地改 spec 会让调用方手里的对象和 _users 里的
        # 副本各自演化（双真相源），下一次 save() 写的是谁的看见都不一定
        stored = copy.deepcopy(spec)
        stored.w_mm, stored.h_mm = float(spec.w_mm), float(spec.h_mm)
        stored.margins = _norm_margins(spec.margins)
        # 自建尺寸一律走自定义送纸，无边距能力强制关闭
        stored.origin = "user"
        stored.borderless = False
        stored.role = "paper"
        stored.margin_source = "spec"
        self._users[stored.key] = stored
        self._sync_user_sizes()

    def _sync_user_sizes(self) -> None:
        self.raw["user_sizes"] = [_to_dict(s) for s in self._users.values()]

    def save(self) -> bool:
        """先写同目录 .tmp 再 os.replace：不让写入中途被杀留下一半 papers.json。

        TypeError/ValueError 也归入失败：不序列化得了的值（NaN 以外的对象、
        手滑传进来的路径对象）归调用方错，但对用户而言现象与写盘失败相同。
        """
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(
                json.dumps(self.raw, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except (OSError, TypeError, ValueError):
            return False
        return True


def _to_dict(s: specs.SizeSpec) -> dict:
    # driver_paper_* 不落盘：自建尺寸没有驱动纸张名，那个字段只对预设有意义
    return {
        "key": s.key, "label": s.label, "w_mm": s.w_mm, "h_mm": s.h_mm,
        "role": s.role, "origin": s.origin, "borderless": s.borderless,
        "margins_mm": {"top": s.margins.top, "bottom": s.margins.bottom,
                       "left": s.margins.left, "right": s.margins.right},
        "margin_source": s.margin_source,
    }


def _from_dict(d: dict) -> specs.SizeSpec:
    """磁盘记录 → 规格。缺字段补默认，类型错就抛（由 load() 逐条兜住）。

    role / origin / borderless 三个字段不采信磁盘值：本项目里自建尺寸只能当
    纸，且自定义送纸必然留白边（规格第 2 节硬事实）。
    """
    return specs.SizeSpec(
        d["key"], d["label"], float(d["w_mm"]), float(d["h_mm"]),
        "paper", "user", False,
        _margins_from_dict(d.get("margins_mm") or {}),
        d.get("margin_source", "spec"),
    )
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_store.py -v`
Expected: PASS（15 passed）

Run: `python -m pytest -q`
Expected: PASS（33 passed，无 warning）

- [ ] **Step 5: 提交**

```bash
git add photoprint/core/store.py tests/test_store.py
git commit -m "feat: 尺寸覆盖与自建相纸的持久化"
```

---

### Task 4: 装箱第 1 级——单朝向均匀网格

**Files:**
- Create: `photoprint/core/pack.py`
- Test: `tests/test_pack_grid.py`

**Interfaces:**
- Consumes: `specs.SizeSpec`、`specs.RectMM`、`specs.printable_rect`
- Produces:
  - `pack.Cell(x_mm, y_mm, w_mm, h_mm, rotated, bleed_mm)`，方法 `inner_mm() -> tuple[float, float, float, float]`
  - `pack.cell_wh(w: float, h: float, rotated: bool) -> tuple[float, float]`
  - `pack.grid_counts(region_w: float, region_h: float, cw: float, ch: float, gap: float) -> tuple[int, int]`
  - `pack.place_uniform(region_w, region_h, cell_w, cell_h, gap, bleed, rotated) -> list[Cell]`
- 说明：`Cell.w_mm/h_mm` 含出血（外框），`inner_mm()` 给照片实际区域

- [ ] **Step 1: 写失败测试**

`tests/test_pack_grid.py`：

```python
"""均匀网格：公式 n = floor((W + gap) / (cw + gap))，间隔不计外圈。"""
from photoprint.core import pack, specs


def test_counts_3r_on_a4_no_gap():
    assert pack.grid_counts(210.0, 297.0, 89.0, 127.0, 0.0) == (2, 2)
    # 横向放：127 宽 × 89 高 → 1 列 3 行，少于竖放的 4
    assert pack.grid_counts(210.0, 297.0, 127.0, 89.0, 0.0) == (1, 3)


def test_counts_with_gap_uses_plus_gap_formula():
    # 1寸 25×32 gap=2：floor(212/27)=7、floor(299/34)=8 ⇒ 56
    assert pack.grid_counts(210.0, 297.0, 25.0, 32.0, 2.0) == (7, 8)
    # 2寸 35×49 gap=2：floor(212/37)=5、floor(299/51)=5 ⇒ 25
    assert pack.grid_counts(210.0, 297.0, 35.0, 49.0, 2.0) == (5, 5)
    # 上面两例的尾量（21、25、25、42mm）都大于 gap，去掉分子的 +gap 也不改变
    # 结果，杀不掉变异；只有尾量不足 gap 的临界排版能区分两种公式。180 与 256
    # 恰好等于两张加一个间隔（89×2+2、127×2+2），间隔不计外圈 ⇒ 两维都必须是 2。
    assert pack.grid_counts(180.0, 256.0, 89.0, 127.0, 2.0) == (2, 2)


def test_counts_zero_when_cell_bigger_than_region():
    # 两个方向都放不下：127×200 的格子对 102×152 的区域两向都超
    assert pack.grid_counts(102.0, 152.0, 127.0, 200.0, 0.0) == (0, 0)
    # 列与行各自独立算：宽放不下不代表高也放不下（89 在 152 里能竖下一张）。
    # 总数为零靠的是 place_uniform“任一维为 0 就不放”，不是靠 grid_counts 返回 (0, 0)。
    assert pack.grid_counts(102.0, 152.0, 127.0, 89.0, 0.0) == (0, 1)


def test_bleed_enlarges_cell_effectively():
    # 3mm 出血把 89×127 抬到 95×133：仍为 2×2 ⇒ 出血不损失 A4 产能
    cw, ch = pack.cell_wh(89.0, 127.0, False)
    cw += 2 * 3.0
    ch += 2 * 3.0
    assert pack.grid_counts(210.0, 297.0, cw, ch, 0.0) == (2, 2)


def test_place_uniform_is_centered_and_counted():
    cells = pack.place_uniform(210.0, 297.0, 89.0, 127.0, 0.0, 0.0, False)
    assert len(cells) == 4
    xs = sorted({c.x_mm for c in cells})
    ys = sorted({c.y_mm for c in cells})
    assert xs == [(210.0 - 178.0) / 2, (210.0 - 178.0) / 2 + 89.0]
    assert ys == [(297.0 - 254.0) / 2, (297.0 - 254.0) / 2 + 127.0]


def test_place_uniform_inner_shrinks_by_bleed():
    cells = pack.place_uniform(210.0, 297.0, 89.0, 127.0, 0.0, 3.0, False)
    c = cells[0]
    assert (c.w_mm, c.h_mm) == (95.0, 133.0)
    x, y, w, h = c.inner_mm()
    assert (round(x - c.x_mm, 6), round(y - c.y_mm, 6)) == (3.0, 3.0)
    assert (w, h) == (89.0, 127.0)


def test_place_uniform_empty_when_no_fit():
    assert pack.place_uniform(89.0, 127.0, 102.0, 152.0, 0.0, 0.0, False) == []
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_pack_grid.py -v`
Expected: FAIL —`ModuleNotFoundError: No module named 'photoprint.core.pack'`

- [ ] **Step 3: 实现 pack 的第 1 级**

`photoprint/core/pack.py`：

```python
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
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_pack_grid.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: 变异测试（证明断言有效）**

临时把 `grid_counts` 分子的 `+ gap` 去掉（改成 `region_w / (cw + gap)`），运行：

Run: `python -m pytest tests/test_pack_grid.py -v`
Expected: FAIL —`test_counts_with_gap_uses_plus_gap_formula` 的临界断言失败（`(2, 2)` 变 `(1, 1)`）。注意 210×297 那两条删掉 `+ gap` 后仍是 `(7, 8)` 与 `(5, 5)`（`210//27=7`、`297//34=8`），单靠它们杀不掉变异，必须有 180×256 这条。改回原实现后再跑必须全绿。若仍全绿说明断言没管事，需补强测试。

- [ ] **Step 6: 提交**

```bash
git add photoprint/core/pack.py tests/test_pack_grid.py
git commit -m "feat: 拼版均匀网格装箱与格子放置计算"
```

---

### Task 5: 装箱第 2、3 级——混合带搜索与决胜排序

**Files:**
- Modify: `photoprint/core/pack.py`（追加，不改动第 1 级函数签名）
- Test: `tests/test_pack_bands.py`

**Interfaces:**
- Consumes: `pack.Cell`、`pack.cell_wh`、`pack.grid_counts`、`pack.place_uniform`
- Produces:
  - `pack.CutLine(axis, at_mm, from_mm, to_mm)`
  - `pack.LayoutPlan(cells, cuts, count, waste_mm2, strategy, printable)`
  - `pack.best_uniform(region_w, region_h, cell_w, cell_h, gap, bleed, allow_rotate) -> list[Cell]`
  - `pack.solve_region(region_w, region_h, cell_w, cell_h, gap, bleed, allow_rotate, depth, memo) -> tuple[list[Cell], str]`
  - `pack.pack(sheet, cell, gap_mm=0.0, bleed_mm=0.0, allow_rotate=True, printable=None) -> LayoutPlan`
    （`printable=None` 时按整张纸装箱，与规格 5.3 基准同口径）

- [ ] **Step 1: 写失败测试**

`tests/test_pack_bands.py`：

```python
"""混合带搜索的价值证明：A4 打 6寸必须靠一刀双带才能到 3 张。"""
import pytest

from photoprint.core import pack, specs


def _p(sheet_key, cell_key, gap=0.0, bleed=0.0, printable=None, allow_rotate=True):
    sheet = specs.find_spec(sheet_key)
    cell = specs.find_spec(cell_key)
    return pack.pack(sheet, cell, gap_mm=gap, bleed_mm=bleed,
                     allow_rotate=allow_rotate, printable=printable)


def test_a4_holds_four_3r():
    plan = _p("A4", "3R")
    assert plan.count == 4
    assert plan.strategy == "uniform"


def test_a4_holds_three_4r_only_via_band_split():
    """单网格最多 2；切位 y=152 分两带（上带 2 竖 + 下带 1 横）= 3。"""
    plan = _p("A4", "4R")
    assert plan.count == 3
    assert plan.strategy == "bands"
    orientations = {c.rotated for c in plan.cells}
    assert orientations == {False, True}  # 混合朝向，故必须混合带才解得出


def test_a4_holds_two_5r_and_area_bound_proves_three_impossible():
    plan = _p("A4", "5R")
    assert plan.count == 2
    assert 3 * 127.0 * 178.0 > 210.0 * 297.0  # 面积上界排除 3 张


def test_4r_paper_cannot_hold_two_3r():
    plan = _p("4R", "3R")
    assert plan.count == 1


def test_a4_with_bleed_still_four_3r():
    plan = _p("A4", "3R", bleed=3.0)
    assert plan.count == 4
    assert plan.cells[0].w_mm == pytest.approx(95.0)
    assert plan.cells[0].h_mm == pytest.approx(133.0)


def test_id_photo_counts_on_a4_with_gap():
    """证件照格子不得旋转：一寸 7×8=56、二寸 5×5=25（规格 5.3）。

    允许旋转时网格会取两种朝向的较大者，寸照张数只会虚高（一寸虚高到 66+），
    但横放的格子会让贴出来的证件照躺倒，所以界面层对 role=cell 必须传
    allow_rotate=False。这里同时断言“旋转不减反增”，把两种行为都钉住。
    """
    assert _p("A4", "ID1", gap=2.0, allow_rotate=False).count == 56
    assert _p("A4", "ID2", gap=2.0, allow_rotate=False).count == 25
    assert _p("A4", "ID1", gap=2.0).count > 56


def test_printable_area_shrink_keeps_four_3r():
    """A4 减去物理边距后仍应放得下 4 张 5寸（规格 5.3 末行）。"""
    plan = _p("A4", "3R")
    assert plan.count == 4
    shrunk = pack.pack(specs.find_spec("A4"), specs.find_spec("3R"),
                       printable=specs.printable_rect(specs.find_spec("A4")))
    assert shrunk.count == 4


def test_area_invariant_holds_for_every_preset_pair():
    for sheet in specs.PAPER_PRESETS:
        for cell in specs.CELL_PRESETS + specs.PAPER_PRESETS:
            if cell.key == sheet.key and cell.role == "paper":
                continue
            plan = pack.pack(sheet, cell)
            used = sum(c.w_mm * c.h_mm for c in plan.cells)
            assert used <= sheet.w_mm * sheet.h_mm + 1e-6


def test_waste_is_reported():
    plan = _p("A4", "3R")
    assert plan.waste_mm2 == pytest.approx(210 * 297 - 4 * 89 * 127)


def test_tie_break_prefers_uniform_over_edge_flush_bands():
    """张数与浪费全同时，贴边的双带解不得赢过居中的均匀网格。

    均匀网格解的外接框是 178×254（更方正），左带贴边、格子间距 89+0 的一刀双带解
    外接框 194×254（更接近正方形）。若决胜序里“策略简单”不排在“外接框方”
    之前，贴边解会靠更方正的外接框胜出，而它既不居中、列间隙也不均匀。
    规格 5.2 的决胜②就为了这条而存在。
    """
    plan = _p("A4", "3R")
    assert plan.strategy == "uniform"
    assert all(not c.rotated for c in plan.cells)  # 同向优先
    xs = [c.x_mm for c in plan.cells]
    assert min(xs) == pytest.approx((210.0 - 178.0) / 2)
    assert max(xs) == pytest.approx((210.0 - 178.0) / 2 + 89.0)
    # 列间隙全等（而不是 0mm 与 16mm 交替）：先取去重后的列坐标再比相邻差
    cols = sorted(set(xs))
    assert sorted({round(b - a, 6) for a, b in zip(cols, cols[1:])}) == [89.0]
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_pack_bands.py -v`
Expected: FAIL —`AttributeError: module 'photoprint.core.pack' has no attribute 'pack'`

- [ ] **Step 3: 追加第 2、3 级与 pack 入口**

在 `photoprint/core/pack.py` 末尾追加（并在文件顶部已有的 import 区补上
`from photoprint.core import specs`：`_sheet_rect` 要用 `specs.RectMM`，specs 不
反向依赖 pack，不构成循环导入）：

```python
@dataclass
class CutLine:
    """裁切参考线：axis 为 'v'（竖缝）或 'h'（横缝）。"""

    axis: str
    at_mm: float
    from_mm: float
    to_mm: float


@dataclass
class LayoutPlan:
    cells: list
    cuts: list
    count: int
    waste_mm2: float
    strategy: str
    printable: object


def best_uniform(region_w, region_h, cell_w, cell_h, gap, bleed, allow_rotate):
    """两种朝向各自均匀排布，取张数多者；并列时外接框更接近正方形者优先。"""
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
```

`_sheet_rect` 与 `build_cuts` 是本任务需要的两个辅助函数（后者在下一个 Task
被真实现替换）：

```python
def _sheet_rect(sheet):
    """装箱默认区域 = 整张纸。

    规格 5.3 的手算基准全按整张纸算（`floor(210/89)` 而不是 `floor(203.2/89)`），
    默认值必须与基准同口径：A4+4R 在 210mm 宽里放得下两张 102mm（204 ≤ 210），
    扣掉物理边距后只剩 203.2mm，会因 0.8mm 之差让硬断言从 3 张掉到 2 张。
    代价就是打印路径必须显式传 printable，否则照片会吃进边距。
    """
    return specs.RectMM(0.0, 0.0, sheet.w_mm, sheet.h_mm)


def build_cuts(cells, rect):
    """占位：T6 用贯通切缝的真实现替换它。本任务的测试不断言 cuts 内容。"""
    return []
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_pack_bands.py tests/test_pack_grid.py -v`
Expected: PASS（bands 10 passed，grid 仍 7 passed）

- [ ] **Step 5: 变异测试**

把 `solve_region` 里 `depth > 0` 改为 `False`（即禁用混合带），运行：

Run: `python -m pytest tests/test_pack_bands.py -v`
Expected: FAIL —`test_a4_holds_three_4r_only_via_band_split` 断言失败（得 2 而非 3），证明混合带搜索真的在被检验。改回后必须全绿。

- [ ] **Step 6: 提交**

```bash
git add photoprint/core/pack.py tests/test_pack_bands.py
git commit -m "feat: 拼版混合带三级搜索与决胜排序"
```

---

### Task 6: 裁切参考线生成与分页计算

**Files:**
- Modify: `photoprint/core/pack.py`（用真实现替换 `build_cuts`，追加 `needed_sheets`，收紧 `LayoutPlan` 字段类型）
- Test: `tests/test_pack_cuts.py`

**Interfaces:**
- Consumes: `pack.Cell`、`pack.LayoutPlan`、`specs.RectMM`
- Produces:
  - `pack.build_cuts(cells: list[Cell], rect: RectMM) -> list[CutLine]`
  - `pack.merge_spans(spans: list[tuple[float, float]]) -> list[tuple[float, float]]`
  - `pack.needed_sheets(plan_count: int, photo_count: int) -> int`

- [ ] **Step 1: 写失败测试**

`tests/test_pack_cuts.py`：

```python
"""裁切线只在区域内部的格子边界上生成，且贯通整条缝；与纸边重合的不画。"""
import pytest

from photoprint.core import pack, specs


def _a4_3r():
    # 整纸装箱，坐标可手算：x0=16、y0=21.5，与断言里的值直接对得上
    return pack.pack(specs.find_spec("A4"), specs.find_spec("3R"),
                     printable=specs.RectMM(0.0, 0.0, 210.0, 297.0))


def test_a4_3r_grid_draws_two_side_borders_and_the_middle_seam():
    """居中 2×2：每轴 3 条（左边界 + 中间缝 + 右边界）。

    只画中间缝与一侧边界的话，切完左列仍是 105mm 宽带白边，
    得不到 89×127 的成品；成功判据 1.4 要的是“量得出 89×127”。
    """
    plan = _a4_3r()
    assert plan.count == 4
    v = sorted(round(c.at_mm, 3) for c in plan.cuts if c.axis == "v")
    h = sorted(round(c.at_mm, 3) for c in plan.cuts if c.axis == "h")
    x0 = (210.0 - 178.0) / 2
    y0 = (297.0 - 254.0) / 2
    assert v == [round(x0 + d, 3) for d in (0.0, 89.0, 178.0)]
    assert h == [round(y0 + d, 3) for d in (0.0, 127.0, 254.0)]
    assert len(plan.cuts) == 6


def test_cells_filling_region_leave_only_the_shared_seam():
    """格子恰好铺满区域时，与区域边界重合的边界不画：178×127 里两张 3R 只有一条竖缝。"""
    plan = pack.pack(specs.find_spec("A4"), specs.find_spec("3R"),
                     printable=specs.RectMM(0.0, 0.0, 178.0, 127.0))
    assert plan.count == 2
    assert [(c.axis, c.at_mm, c.from_mm, c.to_mm) for c in plan.cuts] == [
        ("v", 89.0, 0.0, 127.0)]


def test_cut_spans_full_used_extent():
    plan = _a4_3r()
    seam = next(c for c in plan.cuts
                if c.axis == "v" and round(c.at_mm, 3) == round((210.0 - 178.0) / 2 + 89.0, 3))
    assert seam.from_mm == pytest.approx((297.0 - 254.0) / 2)
    assert seam.to_mm == pytest.approx((297.0 - 254.0) / 2 + 254.0)


def test_single_cell_prints_no_seams():
    plan = pack.pack(specs.find_spec("4R"), specs.find_spec("3R"))
    assert plan.count == 1
    assert plan.cuts == []


def test_no_seam_on_paper_border():
    """满版单格（如 A4 打 A4）不得画任何线。"""
    plan = pack.pack(specs.find_spec("A4"), specs.find_spec("A4"),
                     printable=specs.RectMM(0, 0, 210, 297))
    assert plan.cuts == []


def test_merge_spans_joins_touching_intervals():
    got = pack.merge_spans([(0.0, 10.0), (10.0, 20.0), (30.0, 40.0)])
    assert got == [(0.0, 20.0), (30.0, 40.0)]


def test_no_cell_overlaps_and_stays_inside_region():
    """不变量：任何预设组合下格子不得越出装箱矩形，也不得互相重叠。

    T5 只校了 `used <= w*h`，那个断言既排除不了越界也排除不了重叠（两者
    的面积可以完全合法）。切缝的正确性建立在“格子不重叠”这个前提上，故与切缝
    测试同文件。已真跑 756 组（预设对 × (gap, bleed) 三种）确认 0 违规。
    """
    for sheet in specs.PAPER_PRESETS:
        for cell in specs.CELL_PRESETS + specs.PAPER_PRESETS:
            if cell.key == sheet.key and cell.role == "paper":
                continue
            for gap, bleed in ((0.0, 0.0), (2.0, 0.0), (0.0, 3.0)):
                plan = pack.pack(sheet, cell, gap_mm=gap, bleed_mm=bleed)
                rect = plan.printable
                tag = (sheet.key, cell.key, gap, bleed)
                for c in plan.cells:
                    assert c.x_mm >= rect.x_mm - 1e-6, tag
                    assert c.y_mm >= rect.y_mm - 1e-6, tag
                    assert c.x_mm + c.w_mm <= rect.x_mm + rect.w_mm + 1e-6, tag
                    assert c.y_mm + c.h_mm <= rect.y_mm + rect.h_mm + 1e-6, tag
                for i, a in enumerate(plan.cells):
                    for b in plan.cells[i + 1:]:
                        ox = min(a.x_mm + a.w_mm, b.x_mm + b.w_mm) - max(a.x_mm, b.x_mm)
                        oy = min(a.y_mm + a.h_mm, b.y_mm + b.h_mm) - max(a.y_mm, b.y_mm)
                        assert not (ox > 1e-6 and oy > 1e-6), (tag, a, b)


def test_needed_sheets():
    assert pack.needed_sheets(4, 4) == 1
    assert pack.needed_sheets(4, 5) == 2
    assert pack.needed_sheets(4, 8) == 2
    assert pack.needed_sheets(0, 3) == 0  # 无格子可打属异常，交由调用方提示


def test_bleed_seams_sit_on_the_outer_box_and_need_a_second_trim():
    """出血模式的切缝按格子外框（块=成品+2*bleed）出：沿缝切出 95×133 的块，
    裁到 89×127 是二道精裁，精裁线由渲染层按 inner_mm() 叠加（规格 5.2）。"""
    plan = pack.pack(specs.find_spec("A4"), specs.find_spec("3R"),
                     bleed_mm=3.0, printable=specs.RectMM(0.0, 0.0, 190.0, 133.0))
    assert plan.count == 2
    assert [(c.axis, c.at_mm, c.from_mm, c.to_mm) for c in plan.cuts] == [
        ("v", 95.0, 0.0, 133.0)]
    assert plan.cells[0].inner_mm() == (3.0, 3.0, 89.0, 127.0)
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_pack_cuts.py -v`
Expected: FAIL —`AssertionError` （当前 `build_cuts` 返回空列表）

- [ ] **Step 3: 实现 build_cuts 与 needed_sheets**

用下面内容替换 `pack.py` 中的占位 `build_cuts`，并追加 `needed_sheets`：

```python
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
    # 这里只需总排序（评审 Important #2：曾有第二趟 merged 再合并，
    # 作 756 组/4245 个缝桶验证全部为恒等操作，属死代码，已删）
    return sorted(cuts, key=lambda c: (c.axis, c.at_mm, c.from_mm))


def needed_sheets(plan_count: int, photo_count: int) -> int:
    """按每页格子数算需要几张纸。"""
    if plan_count <= 0:
        return 0
    return -(-photo_count // plan_count)
```

两个轴的坐标属性名不同（竖缝的位置读 `x_mm`，线段的范围读 `y_mm`），用
元组传名字而不是写四份 `if axis == "v"` 的分支，是为了让两轴共用同一段
推导代码；分支写到一起会漏改其中一轴。

- [ ] **Step 4: 顺带订正 T5 评审留下的三处（不改行为）**

T5 复审 Approved，但留了三条 Minor，都是只碰 `pack.py` / T5 测试文件的极小改动，归入本任务一并清：

1. 收紧 `LayoutPlan` 的字段类型（现在 `cells: list` / `cuts: list` / `printable: object` 丢了类型信号，T6 开始 `cuts` 真产 `CutLine`、T9 要消费 `printable`）：

```python
@dataclass
class LayoutPlan:
    cells: list[Cell]
    cuts: list[CutLine]
    count: int
    waste_mm2: float
    strategy: str
    printable: specs.RectMM
```

`from __future__ import annotations` 已在文件顶部，这些注解不会在运行期求值，`specs` 也已真实 import，不构成循环。

2. `best_uniform` 的 docstring 只写了“外接框更接近正方形者优先”，但 `_score` 的元组里还有居中偏差与朝向两项生效。补成：“两种朝向各自均匀排布，取张数多者；并列时外接框更接近正方形且更居中者优先。”

3. `tests/test_pack_bands.py::test_a4_holds_three_4r_only_via_band_split` 的 docstring 写“切位 y=152 分两带”，而实现报出的是同分的对称解 y=102（两支 `_score` 元组逐位相等，`_cut_candidates` 排序后取前者）。把这句话改成：“单网格最多 2；横切一刀分两带（一支为切位 y=152：上 2 竖 + 下 1 横，另一支 y=102 与之对称）得 3。两支同分，实际报出哪支取决于候选切位的排序，本测试只钉张数与混合朝向。”不得动断言本身。

- [ ] **Step 5: 运行确认通过**

Run: `python -m pytest tests/test_pack_cuts.py -v`
Expected: PASS（9 passed）

- [ ] **Step 6: 全量回归**

Run: `python -m pytest -v`
Expected: 全绿（59 passed：units 6 + specs 12 + store 15 + pack 三组 26）

- [ ] **Step 7: 提交**

```bash
git add photoprint/core/pack.py tests/test_pack_cuts.py tests/test_pack_bands.py
git commit -m "feat: 裁切参考线推导与分页计算"
```

---

### Task 7: cell_crop_box——预览与打印共用的裁切放置

**Files:**
- Create: `photoprint/core/crop.py`
- Test: `tests/test_crop.py`

**Interfaces:**
- Consumes: `units.ppmm`、`units.round_px`
- Produces:
  - `crop.Placement(crop_px: tuple[int, int, int, int], dest_mm: tuple[float, float, float, float])`
  - `crop.cell_crop_box(photo_w_px, photo_h_px, target_w_mm, target_h_mm, mode, zoom=1.0, dx_mm=0.0, dy_mm=0.0, ppmm=None) -> Placement`
  - `crop.FILL = "fill"`、`crop.FIT = "fit"`
- 接口说明：规格 6.1 把返回写成 `(l,t,r,b)` 是简化表述。`fit` 模式需要表达"缩小的画面落在目标区哪个位置"，单靠 crop box 无法表达，故返回 `Placement`，其中 `.crop_px` 就是规格里那个四元组，`.dest_mm` 是粘贴落位。预览与打印两侧都消费同一个 `Placement`。

- [ ] **Step 1: 写失败测试**

`tests/test_crop.py`：

```python
"""裁放置：用 dpi=25.4 让 1 像素 = 1 毫米，便于逐位核对。"""
import pytest

from photoprint.core import crop, units

PPMM = 1.0  # dpi 25.4


def test_fill_minimal_cover_crops_sides():
    p = crop.cell_crop_box(200, 100, 100, 100, crop.FILL, ppmm=PPMM)
    assert p.crop_px == (50, 0, 150, 100)
    assert p.dest_mm == (0.0, 0.0, 100.0, 100.0)


def test_fill_zoom_2_shrinks_crop():
    p = crop.cell_crop_box(200, 100, 100, 100, crop.FILL, zoom=2.0, ppmm=PPMM)
    assert p.crop_px == (75, 25, 125, 75)


def test_fill_dx_moves_crop_and_clamps_inside_photo():
    p = crop.cell_crop_box(200, 100, 100, 100, crop.FILL, zoom=2.0, dx_mm=10.0,
                           ppmm=PPMM)
    assert p.crop_px == (80, 25, 130, 75)
    far = crop.cell_crop_box(200, 100, 100, 100, crop.FILL, zoom=2.0, dx_mm=500.0,
                             ppmm=PPMM)
    # 钳制在原图内 ⇒ 绝不出现白边
    assert far.crop_px[2] == 200
    assert far.crop_px[0] == 150


def test_fill_never_exceeds_photo_bounds_at_min_zoom():
    p = crop.cell_crop_box(200, 100, 100, 100, crop.FILL, zoom=1.0, dx_mm=-999,
                           dy_mm=-999, ppmm=PPMM)
    l, t, r, b = p.crop_px
    assert l == 0 and t == 0
    assert r <= 200 and b <= 100


def test_fit_keeps_whole_image_and_letterboxes():
    p = crop.cell_crop_box(200, 100, 100, 100, crop.FIT, ppmm=PPMM)
    assert p.crop_px == (0, 0, 200, 100)
    x, y, w, h = p.dest_mm
    assert (w, h) == pytest.approx((100.0, 50.0))
    assert x == pytest.approx(0.0)
    assert y == pytest.approx(25.0)  # 上下各留 25mm 白边


def test_fit_zoom_half_shrinks_dest():
    p = crop.cell_crop_box(200, 100, 100, 100, crop.FIT, zoom=0.5, ppmm=PPMM)
    x, y, w, h = p.dest_mm
    assert (w, h) == pytest.approx((50.0, 25.0))
    assert (x, y) == pytest.approx((25.0, 37.5))


def test_fit_dx_clamped_inside_target():
    p = crop.cell_crop_box(200, 100, 100, 100, crop.FIT, zoom=0.5, dx_mm=999,
                           ppmm=PPMM)
    assert p.dest_mm[0] == pytest.approx(50.0)  # 100 - 50，不得越出目标区


def test_zoom_bounds_are_enforced():
    with pytest.raises(ValueError, match="zoom"):
        crop.cell_crop_box(200, 100, 100, 100, crop.FILL, zoom=0.5, ppmm=PPMM)
    with pytest.raises(ValueError, match="zoom"):
        crop.cell_crop_box(200, 100, 100, 100, crop.FIT, zoom=1.5, ppmm=PPMM)


def test_default_ppmm_accepted():
    """解析结果对 ppmm 不变（分子分母同现被约掉），本条钉不住「默认=300dpi」；
    它钉的是默认值不为 None 也能算完、不触守卫（评审 I-3，原名
    test_default_ppmm_is_300dpi 名不副实）。"""
    p = crop.cell_crop_box(200, 100, 100, 100, crop.FILL)
    assert p.crop_px == (50, 0, 150, 100)


def test_unknown_mode_rejected():
    with pytest.raises(ValueError, match="mode"):
        crop.cell_crop_box(200, 100, 100, 100, "stretch", ppmm=PPMM)


def test_fill_zoom_upper_bound_enforced():
    # 评审 I-2：原 test_zoom_bounds_are_enforced 只钉了 FILL 下界与 FIT 上界
    with pytest.raises(ValueError, match="zoom"):
        crop.cell_crop_box(200, 100, 100, 100, crop.FILL, zoom=4.5, ppmm=PPMM)


def test_fit_zoom_lower_bound_enforced():
    with pytest.raises(ValueError, match="zoom"):
        crop.cell_crop_box(200, 100, 100, 100, crop.FIT, zoom=0.1, ppmm=PPMM)


def test_fit_aspect_ratio_preserved_on_non_square_target():
    """评审 I-2：正方形目标下 min() 两支数值相等，钉不住退化为只按宽缩放。"""
    p = crop.cell_crop_box(200, 100, 400, 50, crop.FIT, ppmm=PPMM)
    x, y, w, h = p.dest_mm
    assert (w, h) == pytest.approx((100.0, 50.0))  # 按宽缩放会得 400×200 越格
    assert (x, y) == pytest.approx((150.0, 0.0))


def test_fill_crop_box_uses_half_up_rounding():
    """评审 I-1：未取整的 l 恰为 36.5，必须按全项目 round_px 口径得 37，
    而非银行家舍入的 36。"""
    p = crop.cell_crop_box(100, 80, 100, 152, crop.FILL, zoom=2,
                           dx_mm=-1.3, ppmm=units.ppmm(300))
    assert p.crop_px == (37, 20, 63, 60)
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_crop.py -v`
Expected: FAIL —`ModuleNotFoundError: No module named 'photoprint.core.crop'`

- [ ] **Step 3: 实现 crop**

`photoprint/core/crop.py`：

```python
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

    crop_px: tuple[int, int, int, int]
    dest_mm: tuple[float, float, float, float]


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
        # 取整走 units.round_px（全项目口径，.5 向上）：内置 round 是银行家
        # 舍入，300dpi 下约 4.8% 的裁框边会恰落 .5，偏移方向不可预测（T7 评审 I-1）
        return Placement((units.round_px(l), units.round_px(t),
                          units.round_px(r), units.round_px(b)),
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
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_crop.py -v`
Expected: PASS（14 passed）

- [ ] **Step 5: 提交**

```bash
git add photoprint/core/crop.py tests/test_crop.py
git commit -m "feat: 预览与打印共用的裁切落位纯函数"
```

---

### Task 8: 三档打印模式与默认映射

**Files:**
- Create: `photoprint/core/modes.py`
- Test: `tests/test_modes.py`

**Interfaces:**
- Consumes: `specs.SizeSpec`、`specs.printable_rect`、`crop.FILL`、`crop.FIT`
- Produces:
  - `modes.FIT_TO_PRINTABLE = "fit_to_printable"`、`modes.FILL_PRINTABLE = "fill_printable"`、`modes.BLEED_TRIM = "bleed_trim"`
  - `modes.DEFAULT_BLEED_MM = 3.0`
  - `modes.default_mode(sheet, cell, cell_count, borderless_active=False) -> str`
  - `modes.crop_mode(mode: str) -> str`（映射到 `crop.FILL`/`crop.FIT`）
  - `modes.target_rect(sheet_spec, cell_spec, mode, printable_rect, borderless_active)`

- [ ] **Step 1: 写失败测试**

`tests/test_modes.py`：

```python
"""默认映射逐条对应规格 7.2；文案禁则对应 7.3。"""
import pytest

from photoprint.core import crop, modes, specs


def test_id_photo_always_fit():
    """证件照丢头即废片，无论纸张如何都用 fit。"""
    m = modes.default_mode(specs.find_spec("A4"), specs.find_spec("ID1"), 56)
    assert m == modes.FIT_TO_PRINTABLE
    assert modes.crop_mode(m) == crop.FIT


def test_custom_sheet_falls_back_to_fill_printable():
    """3R 只能自定义送纸 ⇒ 无法无边距，默认铺满可打印区。"""
    m = modes.default_mode(specs.find_spec("3R"), specs.find_spec("3R"), 1)
    assert m == modes.FILL_PRINTABLE


def test_borderless_sheet_multi_cell_uses_bleed_trim():
    m = modes.default_mode(specs.find_spec("A4"), specs.find_spec("3R"), 4)
    assert m == modes.BLEED_TRIM
    assert modes.crop_mode(m) == crop.FILL


def test_borderless_sheet_single_cell_no_trim_needed():
    """单格满版本身就铺满可打印区，不必裁切。"""
    m = modes.default_mode(specs.find_spec("A4"), specs.find_spec("A4"), 1)
    assert m == modes.FILL_PRINTABLE


def test_non_borderless_multi_cell_never_bleed_trim():
    """A5 无边距能力 ⇒ 不得推荐需要无边距的裁切模式。"""
    m = modes.default_mode(specs.find_spec("A5"), specs.find_spec("ID1"), 20)
    assert m != modes.BLEED_TRIM


def test_bleed_trim_target_is_full_sheet_and_others_are_printable():
    a4 = specs.find_spec("A4")
    p = specs.printable_rect(a4, borderless_active=True)
    t_bleed = modes.target_rect(a4, specs.find_spec("3R"), modes.BLEED_TRIM,
                                specs.RectMM(0, 0, 210, 297), True)
    t_fill = modes.target_rect(a4, specs.find_spec("3R"), modes.FILL_PRINTABLE,
                               p, True)
    assert (t_bleed.w_mm, t_bleed.h_mm) == (210.0, 297.0)
    assert (t_fill.w_mm, t_fill.h_mm) == (210.0, 297.0)  # 无边距生效时同为整纸


def test_bleed_trim_requires_borderless_capable_sheet():
    with pytest.raises(ValueError, match="无边距"):
        modes.assert_mode_legal(specs.find_spec("3R"), modes.BLEED_TRIM)


def test_default_bleed_is_three_mm():
    assert modes.DEFAULT_BLEED_MM == 3.0


def test_unknown_mode_rejected():
    with pytest.raises(ValueError, match="mode"):
        modes.crop_mode("fit_page")
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_modes.py -v`
Expected: FAIL —`ModuleNotFoundError: No module named 'photoprint.core.modes'`

- [ ] **Step 3: 实现 modes**

`photoprint/core/modes.py`：

```python
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
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_modes.py -v`
Expected: PASS（9 passed）

- [ ] **Step 5: 提交**

```bash
git add photoprint/core/modes.py tests/test_modes.py
git commit -m "feat: 三档打印模式与默认映射及合法性校验"
```

---

### Task 9: render_page——物理精确位图渲染

**Files:**
- Create: `photoprint/core/render.py`
- Test: `tests/test_render_geometry.py`

**Interfaces:**
- Consumes: `pack.LayoutPlan`、`pack.Cell`、`pack.CutLine`、`crop.cell_crop_box`、`modes.crop_mode`、`units.mm_to_px`、`specs.printable_rect`
- Produces:
  - `render.render_page(plan, photos, sheet, dpi, mode, show_mask=True, show_cut_lines=True, borderless_active=False) -> PIL.Image.Image`
  - `render.intersect_mm(a: tuple, b: tuple) -> tuple | None`（两个 mm 矩形求交）
  - `render.CUT_LINE_GRAY = 217`（15% 灰）、`render.CUT_LINE_MM = 0.35`
  - `render.MASK_RGB = (150, 150, 150)`
- 目标矩形规则：非 `BLEED_TRIM` 模式下，照片落位的目标 = 格子内框 ∩ 可打印矩形。正常拼版下格子本就在可打印区内，交集等于原框；而“整张纸只放一格”（如 3R 纸打 3R 照片）时，交集把画面收回可打印区，避免内容被物理边距吃掉。`BLEED_TRIM` 恰恰要让画面伸进边距区，故用外框不求交。

- [ ] **Step 1: 写失败测试**

`tests/test_render_geometry.py`：

```python
"""几何像素断言：dpi=25.4 时 1 像素 = 1 毫米，可直接量坐标。"""
import pytest

Image = pytest.importorskip("PIL.Image", reason="需要 Pillow")
from PIL import Image as PILImage  # noqa: E402

from photoprint.core import modes, pack, render, specs, units  # noqa: E402

DPI = 25.4  # 1px == 1mm


def _photos(n, color):
    return [PILImage.new("RGB", (200, 100), color) for _ in range(n)]


def _a4_3r(mode=modes.FILL_PRINTABLE, bleed=0.0, photos=None, cut_lines=True):
    # 固定用整张纸作为装箱矩形，坐标可手算：x0=(210-178)/2=16、y0=(297-254)/2=21.5
    # （默认的可打印内缩矩形由 T5 的测试覆盖，本文件只验裁切线几何）
    full = specs.RectMM(0.0, 0.0, 210.0, 297.0)
    plan = pack.pack(specs.find_spec("A4"), specs.find_spec("3R"), bleed_mm=bleed,
                     printable=full)
    imgs = photos or _photos(plan.count, (255, 0, 0))
    return plan, render.render_page(plan, imgs, specs.find_spec("A4"), DPI, mode,
                                   show_cut_lines=cut_lines)


def test_page_size_matches_sheet_in_pixels():
    plan, img = _a4_3r()
    assert img.size == (210, 297)


def test_photo_pixels_present_and_bounded():
    plan, img = _a4_3r(photos=_photos(4, (255, 0, 0)))
    c = plan.cells[0]
    x0 = units.round_px(c.x_mm)
    y0 = units.round_px(c.y_mm)
    assert img.getpixel((x0 + 40, y0 + 60)) == (255, 0, 0)
    # 纸外角落必须是白（A4 无边距未启用时角落在遮罩内，仍非照片色）
    assert img.getpixel((0, 0)) != (255, 0, 0)


def test_fill_mode_crops_to_cell_exactly():
    """横向 200×100 的照片铺满 89×127 的格：宽被裁，高铺满。
    只放一张照片（其余格留白），否则同行邻格的同色绿会连进扫描区间；
    关切缝叠加：居中装箱的缝在 x=16/105 的格子边界上（T6 裁决两侧都画），
    会盖掉照片首列——那是画线预期行为，与本条的几何断言无关，
    缝自身的像素位置由后面的裁切线测试钉住。"""
    green = PILImage.new("RGB", (200, 100), (0, 255, 0))
    plan, img = _a4_3r(photos=[green], cut_lines=False)
    c = plan.cells[0]
    x0, y0 = units.round_px(c.x_mm), units.round_px(c.y_mm)
    col = [x for x in range(210) if img.getpixel((x, y0 + 60)) == (0, 255, 0)]
    assert min(col) == x0
    assert max(col) - min(col) + 1 == 89


def test_bleed_mode_overlays_inner_trim_guides():
    """BLEED_TRIM 的两道切线：外框缝（粗切）由 build_cuts 给出并被切缝测试钉住，
    本条钉第二道：按 inner_mm() 画的精裁线（T6 裁决，规格 5.2）。
    内框比块边内缩 3px（dpi=25.4），线压在照片出血区上，精裁后正好消失。"""
    green = PILImage.new("RGB", (200, 100), (0, 255, 0))
    plan, img = _a4_3r(mode=modes.BLEED_TRIM, bleed=3.0, photos=[green])
    c = plan.cells[0]
    ix, iy = c.x_mm + c.bleed_mm, c.y_mm + c.bleed_mm   # 内框左上 (13.0, 18.5)
    # 竖精裁线：x=13 像素列非绿，右移一列回绿
    assert img.getpixel((int(ix), int(iy) + 40)) != (0, 255, 0)
    assert img.getpixel((int(ix) + 1, int(iy) + 40)) == (0, 255, 0)
    # 横精裁线：y=18.5 经 round_px 落像素 19，上方出血带仍是绿
    x_mid = int(c.x_mm + c.w_mm / 2.0)                  # 57
    assert img.getpixel((x_mid, int(iy + 0.5))) != (0, 255, 0)
    assert img.getpixel((x_mid, int(iy + 0.5) + 1)) == (0, 255, 0)
    assert img.getpixel((x_mid, int(iy) - 1)) == (0, 255, 0)


def test_mask_covers_physical_margin_band():
    plan, img = _a4_3r(photos=_photos(4, (0, 0, 255)))
    a4 = specs.find_spec("A4")
    # 左边缘 3.4mm 内属不可印区，应被遮罩压暗，不得是纯白也不是照片色
    px = img.getpixel((1, 150))
    assert px != (255, 255, 255)
    assert px != (0, 0, 255)


def test_cut_lines_are_drawn_and_light_gray():
    plan, img = _a4_3r(photos=_photos(4, (255, 0, 0)))
    # 取竖缝：它的 x 落在 at_mm 上，线段沿 y 走（取 cuts[0] 会拿成横缝，
    # 坐标当像素用时会把 x/y 写反，采样点落在照片上而不是线上）
    seam = next(c for c in plan.cuts if c.axis == "v")
    x = units.round_px(seam.at_mm)
    y = units.round_px(seam.from_mm) + 30  # 沿线段方向取一点，避开横缝
    px = img.getpixel((x, y))
    assert abs(px[0] - render.CUT_LINE_GRAY) <= 3
    assert abs(px[1] - render.CUT_LINE_GRAY) <= 3


def test_no_cut_lines_when_single_cell():
    plan = pack.pack(specs.find_spec("4R"), specs.find_spec("3R"))
    img = render.render_page(plan, _photos(1, (255, 0, 0)),
                             specs.find_spec("4R"), DPI, modes.FILL_PRINTABLE)
    assert img.size == (102, 152)
    assert plan.count == 1


def test_cut_lines_can_be_hidden():
    plan, shown = _a4_3r(photos=_photos(4, (255, 0, 0)))
    hidden = render.render_page(plan, _photos(4, (255, 0, 0)),
                                specs.find_spec("A4"), DPI, modes.FILL_PRINTABLE,
                                show_cut_lines=False)
    # 同一个采样点：画时是灰线，关掉后必须变回照片色（1px=1mm）
    seam = next(c for c in plan.cuts if c.axis == "v")
    x = units.round_px(seam.at_mm)
    y = units.round_px(seam.from_mm) + 30
    assert shown.getpixel((x, y)) != (255, 0, 0)
    assert hidden.getpixel((x, y)) == (255, 0, 0)


def test_bleed_cells_extend_beyond_inner_photo():
    plan, img = _a4_3r(mode=modes.BLEED_TRIM, bleed=3.0, photos=_photos(4, (9, 9, 9)))
    c = plan.cells[0]
    # 出血格的外框 95×133，内缩 3mm 后才是 89×127 成品；画面应铺到外框
    assert img.getpixel((units.round_px(c.x_mm) + 1, units.round_px(c.y_mm) + 1)) == (9, 9, 9)


def test_photo_count_mismatch_leaves_remaining_cells_white():
    plan = pack.pack(specs.find_spec("A4"), specs.find_spec("3R"),
                     printable=specs.RectMM(0.0, 0.0, 210.0, 297.0))
    assert plan.count == 4
    img = render.render_page(plan, _photos(2, (255, 0, 0)), specs.find_spec("A4"),
                             DPI, modes.FILL_PRINTABLE)
    assert img.size == (210, 297)
    # 第 4 格没有照片，必须保持纸白，不能被上一张残留内容污染
    c3 = plan.cells[3]
    assert img.getpixel((units.round_px(c3.x_mm) + 40, units.round_px(c3.y_mm) + 60)) == (255, 255, 255)


def test_rotated_cell_places_rotated_photo():
    """A4 打 5R 需要横放：外框 w>h 时照片必须转 90° 后落入。"""
    plan = pack.pack(specs.find_spec("A4"), specs.find_spec("5R"))
    cell = next(c for c in plan.cells if c.rotated)
    img = render.render_page(plan, [None] * plan.count, specs.find_spec("A4"), DPI,
                             modes.FILL_PRINTABLE)
    assert cell.w_mm == 178.0 and cell.h_mm == 127.0
    assert img.size == (210, 297)


def test_single_cell_on_same_size_paper_stays_inside_printable():
    """退化情形：3R 纸只放一格，画面必须收进可打印区而不是被边距吃掉。"""
    r3 = specs.find_spec("3R")
    plan = pack.pack(r3, r3, printable=specs.RectMM(0, 0, 89.0, 127.0))
    assert plan.count == 1
    img = render.render_page(plan, _photos(1, (255, 0, 0)), r3, DPI,
                             modes.FILL_PRINTABLE, show_mask=False)
    assert img.size == (89, 127)
    assert img.getpixel((1, 63)) != (255, 0, 0)   # 左边 3.4mm 内是物理不可印区
    assert img.getpixel((45, 63)) == (255, 0, 0)  # 可打印区中心有画面


def test_intersect_mm():
    a = (0.0, 0.0, 89.0, 127.0)
    b = (3.4, 3.0, 82.2, 119.0)
    x, y, w, h = render.intersect_mm(a, b)
    assert (round(x, 3), round(y, 3)) == (3.4, 3.0)
    assert (round(w, 3), round(h, 3)) == (82.2, 119.0)
    assert render.intersect_mm((0, 0, 1, 1), (5, 5, 1, 1)) is None
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_render_geometry.py -v`
Expected: FAIL —`ModuleNotFoundError: No module named 'photoprint.core.render'`

- [ ] **Step 3: 实现 render**

`photoprint/core/render.py`：

```python
"""把排版结果渲染成物理尺寸精确的位图。

约定：1 像素 = 1/dpi 毫米，页面像素 = round(sheet_mm * ppmm)。
预览层不走这里——预览用同一个 crop.cell_crop_box，但目标换成屏幕像素，
这样"所见即所得"是构造出来的，而不是靠两边各写一套再祈祷一致。
"""
from __future__ import annotations

from PIL import Image, ImageDraw

from photoprint.core import crop, modes, specs, units

CUT_LINE_GRAY = 217  # 15% 灰：不抢画面，又能在照片上看见
CUT_LINE_MM = 0.35
MASK_RGB = (150, 150, 150)
_MASK_ALPHA = 110


def intersect_mm(a, b):
    """两个 (x, y, w, h) 矩形求交，不相交返回 None。"""
    ax2, ay2 = a[0] + a[2], a[1] + a[3]
    bx2, by2 = b[0] + b[2], b[1] + b[3]
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(ax2, bx2), min(ay2, by2)
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2 - x1, y2 - y1)


def _mask_bands(sheet, rect):
    """返回物理不可印区的四个矩形（mm），仅在未启用无边距时给出。"""
    m = sheet.margins
    w, h = sheet.w_mm, sheet.h_mm
    return [
        (0.0, 0.0, w, m.top),
        (0.0, h - m.bottom, w, m.bottom),
        (0.0, 0.0, m.left, h),
        (w - m.right, 0.0, m.right, h),
    ]


def render_page(plan, photos, sheet, dpi, mode, show_mask=True,
                show_cut_lines=True, borderless_active=False):
    """渲染一页。photos 与 plan.cells 一一对应，None 表示空格（留白）。"""
    px_w = units.mm_to_px(sheet.w_mm, dpi)
    px_h = units.mm_to_px(sheet.h_mm, dpi)
    page = Image.new("RGB", (px_w, px_h), (255, 255, 255))
    draw = ImageDraw.Draw(page, "RGBA")
    cm = modes.crop_mode(mode)
    # 可打印矩形与装箱无关，始终由规格边距推出；无边距实测生效时它就是整张纸
    printable = specs.printable_rect(sheet, borderless_active=borderless_active)

    for idx, cell in enumerate(plan.cells):
        photo = photos[idx] if idx < len(photos) else None
        if photo is None:
            continue
        # BLEED 用外框（出血就故意外伸到纸边，裁掉后正好得到成品尺寸）；
        # 其余用内框并与可打印矩形求交，处理“整纸只放一格”的退化情形
        if mode == modes.BLEED_TRIM:
            ox, oy, ow, oh = cell.x_mm, cell.y_mm, cell.w_mm, cell.h_mm
        else:
            got = intersect_mm(cell.inner_mm(),
                               (printable.x_mm, printable.y_mm,
                                printable.w_mm, printable.h_mm))
            if got is None:
                continue
            ox, oy, ow, oh = got
        # 旋转格：先把原图按未旋转的目标比例裁，再转 90°，尺寸正好对上外框
        target_w, target_h = (oh, ow) if cell.rotated else (ow, oh)
        pl = crop.cell_crop_box(photo.width, photo.height, target_w, target_h,
                               cm, ppmm=units.ppmm(dpi))
        piece = photo.crop(pl.crop_px)
        if cell.rotated:
            piece = piece.transpose(Image.ROTATE_270)
        if pl.dest_mm[2] != 0 and (abs(pl.dest_mm[2] - piece.width / units.ppmm(dpi)) > 0.6
                                   or abs(pl.dest_mm[3] - piece.height / units.ppmm(dpi)) > 0.6):
            piece = piece.resize((max(1, units.round_px(pl.dest_mm[2] * units.ppmm(dpi))),
                                  max(1, units.round_px(pl.dest_mm[3] * units.ppmm(dpi)))),
                                 Image.LANCZOS)
        paste_x = units.mm_to_px(ox + pl.dest_mm[0], dpi)
        paste_y = units.mm_to_px(oy + pl.dest_mm[1], dpi)
        page.paste(piece, (paste_x, paste_y))

    # 遮罩在照片之后绘制，使“这条边打不出来”的警告始终可见；
    # 正常拼版下照片都在可打印区内，不会被遮罩压到
    if show_mask and not borderless_active:
        for bx, by, bw, bh in _mask_bands(sheet, plan.printable):
            draw.rectangle(
                [units.mm_to_px(bx, dpi), units.mm_to_px(by, dpi),
                 units.mm_to_px(bx + bw, dpi) - 1, units.mm_to_px(by + bh, dpi) - 1],
                fill=MASK_RGB + (_MASK_ALPHA,))

    if show_cut_lines and len(plan.cells) >= 2:
        lw = max(1, units.mm_to_px(CUT_LINE_MM, dpi))
        for cut in plan.cuts:
            if cut.axis == "v":
                x = units.mm_to_px(cut.at_mm, dpi)
                draw.line([(x, units.mm_to_px(cut.from_mm, dpi)),
                           (x, units.mm_to_px(cut.to_mm, dpi))],
                          fill=(CUT_LINE_GRAY, CUT_LINE_GRAY, CUT_LINE_GRAY), width=lw)
            else:
                y = units.mm_to_px(cut.at_mm, dpi)
                draw.line([(units.mm_to_px(cut.from_mm, dpi), y),
                           (units.mm_to_px(cut.to_mm, dpi), y)],
                          fill=(CUT_LINE_GRAY, CUT_LINE_GRAY, CUT_LINE_GRAY), width=lw)

    # 出血模式的切缝是两道（T6 裁决，规格 5.2）：build_cuts 给的是外框缝
    # = 粗切落刀位；精裁的第二道线由内框 inner_mm() 推出，在这里压在照片
    # 出血区上，精裁后正好随成品边缘消失。单格也要画精裁线（外框缝没有，
    # 出血仍需精裁）
    if show_cut_lines and mode == modes.BLEED_TRIM:
        lw = max(1, units.mm_to_px(CUT_LINE_MM, dpi))
        for cell in plan.cells:
            ix, iy, iw, ih = cell.inner_mm()
            x2, y2 = ix + iw, iy + ih
            for x0, y0, x1, y1 in ((ix, iy, ix, y2), (x2, iy, x2, y2),
                                   (ix, iy, x2, iy), (ix, y2, x2, y2)):
                draw.line([(units.mm_to_px(x0, dpi), units.mm_to_px(y0, dpi)),
                           (units.mm_to_px(x1, dpi), units.mm_to_px(y1, dpi))],
                          fill=(CUT_LINE_GRAY, CUT_LINE_GRAY, CUT_LINE_GRAY),
                          width=lw)
    return page
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_render_geometry.py -v`
Expected: PASS（13 passed）

- [ ] **Step 5: 变异测试**

把 `units.mm_to_px(cell 坐标)` 改成 int 截断（`int(...)`）：

Run: `python -m pytest tests/test_render_geometry.py -v`
Expected: `test_fill_mode_crops_to_cell_exactly` 失败（宽度得 88 而非 89）。改回后全绿。

- [ ] **Step 6: 提交**

```bash
git add photoprint/core/render.py tests/test_render_geometry.py
git commit -m "feat: 物理精确位图渲染与遮罩裁切线绘制"
```

---

### Task 10: 驱动能力探测（可注入 API）

**Files:**
- Create: `photoprint/win/api.py`
- Create: `photoprint/win/probe.py`
- Test: `tests/test_probe.py`

**Interfaces:**
- Consumes: `specs.SizeSpec`、`specs.PAPER_PRESETS`、`units.px_to_mm`
- Produces:
  - `api.WinApi`（协议类）与 `api.RealWinApi`（真实实现，内部才 import win32）
  - `probe.DC_PAPERS`、`probe.DC_PAPERNAMES`、`probe.DC_PAPERSIZE`、`probe.PHYSICALWIDTH`、`probe.PHYSICALHEIGHT`、`probe.PHYSICALOFFSETX`、`probe.PHYSICALOFFSETY`、`probe.HORZRES`、`probe.VERTRES`、`probe.LOGPIXELSX`
  - `probe.ProbeResult(printer, paper_names, paper_codes, paper_sizes_mm, physical_w_mm, physical_h_mm, offset_x_mm, offset_y_mm, res_w_px, res_h_px, dpi_x, dpi_y)`
  - `probe.probe(api, printer, paper_code=None, dc=None) -> ProbeResult`
  - `probe.match_driver_paper(paper_names, want_name) -> tuple[int | None, str | None]`
  - `probe.borderless_active(result) -> bool`
  - `probe.diff_report(spec: SizeSpec, result: ProbeResult) -> list[str]`

- [ ] **Step 1: 写失败测试**

`tests/test_probe.py`：

```python
"""探测逻辑必须能在没有打印机的开发机上测：win32 调用全部经 api 注入。"""
import pytest

pytest.importorskip("PIL", reason="需要 Pillow")

from photoprint.core import specs  # noqa: E402
from photoprint.win import probe  # noqa: E402


class FakeApi:
    """按 key 返回预设值，记录调用顺序。"""

    def __init__(self, caps=None, dc_caps=None, papers=None, sizes=None):
        self.caps = caps or {}
        self.dc_caps = dc_caps or {}
        self.papers = papers or []
        self.sizes = sizes or []
        self.calls = []

    def device_caps(self, printer, field):
        self.calls.append(("device_caps", field))
        if field == probe.DC_PAPERNAMES:
            return self.papers
        if field == probe.DC_PAPERS:
            return list(range(1, len(self.papers) + 1))
        if field == probe.DC_PAPERSIZE:
            return self.sizes
        return self.caps.get(field, 0)

    def open_printer(self, name):
        self.calls.append(("open", name))
        return f"hdc:{name}"

    def close_printer(self, handle):
        self.calls.append(("close", handle))

    def get_device_caps(self, handle, field):
        self.calls.append(("dc", field))
        return self.dc_caps.get(field, 0)


def test_probe_reads_paper_table_in_tenth_mm_and_device_in_px():
    api = FakeApi(
        papers=["A4", "4x6"],
        sizes=[(2100, 2970), (1020, 1520)],  # DeviceCapabilities 单位 0.1mm
        dc_caps={probe.PHYSICALWIDTH: 2480, probe.PHYSICALHEIGHT: 3508,
                 probe.PHYSICALOFFSETX: 34, probe.PHYSICALOFFSETY: 30,
                 probe.HORZRES: 2412, probe.VERTRES: 3448,
                 probe.LOGPIXELSX: 300, probe.LOGPIXELSY: 300})
    r = probe.probe(api, "Canon G3800 series")
    # 纸张表按 0.1mm 换算 ⇒ A4 为 210×297mm
    assert r.paper_sizes_mm[0] == (210.0, 297.0)
    assert r.paper_sizes_mm[1] == (102.0, 152.0)
    assert r.paper_codes == [1, 2]
    # 设备物理尺寸是像素 ⇒ 2480 / 300 * 25.4 = 210.13mm
    assert r.physical_w_mm == pytest.approx(210.13, abs=0.05)
    assert r.dpi_x == 300


def test_probe_unit_conventions_are_isolated():
    """GetDeviceCaps 返回的是设备像素，需除以 LOGPIXELS 乘 25.4 得 mm。"""
    api = FakeApi(dc_caps={probe.PHYSICALWIDTH: 2480, probe.PHYSICALHEIGHT: 3508,
                           probe.PHYSICALOFFSETX: 34, probe.PHYSICALOFFSETY: 30,
                           probe.HORZRES: 2412, probe.VERTRES: 3448,
                           probe.LOGPIXELSX: 300, probe.LOGPIXELSY: 300})
    r = probe.probe(api, "P")
    assert r.physical_w_mm == pytest.approx(210.13, abs=0.05)
    assert r.offset_x_mm == pytest.approx(2.88, abs=0.01)   # 34/300*25.4
    assert r.offset_y_mm == pytest.approx(2.54, abs=0.01)   # 30/300*25.4
    assert r.res_w_px == 2412


def test_borderless_active_only_when_offsets_zero():
    zero = FakeApi(dc_caps={probe.PHYSICALOFFSETX: 0, probe.PHYSICALOFFSETY: 0,
                             probe.PHYSICALWIDTH: 2480, probe.PHYSICALHEIGHT: 3508,
                             probe.HORZRES: 2480, probe.VERTRES: 3508,
                             probe.LOGPIXELSX: 300, probe.LOGPIXELSY: 300})
    assert probe.borderless_active(probe.probe(zero, "P")) is True
    nonzero = FakeApi(dc_caps={probe.PHYSICALOFFSETX: 34, probe.PHYSICALOFFSETY: 30,
                               probe.PHYSICALWIDTH: 2480, probe.PHYSICALHEIGHT: 3508,
                               probe.HORZRES: 2412, probe.VERTRES: 3448,
                               probe.LOGPIXELSX: 300, probe.LOGPIXELSY: 300})
    assert probe.borderless_active(probe.probe(nonzero, "P")) is False


def test_match_driver_paper_is_case_and_space_insensitive():
    names = ["ISO A4", "Letter", "4 X 6", "5 x 7"]
    code, hit = probe.match_driver_paper(names, "4x6")
    assert hit == "4 X 6"
    assert code == 3
    missing_code, missing = probe.match_driver_paper(names, "8x10")
    assert missing is None and missing_code is None


def test_diff_report_surfaces_driver_vs_spec_conflict():
    r = probe.ProbeResult(printer="P", paper_names=["4x6"], paper_codes=[1],
                          paper_sizes_mm=[(102.0, 152.0)], physical_w_mm=102.0,
                          physical_h_mm=152.0, offset_x_mm=5.0, offset_y_mm=6.0,
                          res_w_px=1200, res_h_px=1800, dpi_x=300, dpi_y=300)
    lines = probe.diff_report(specs.find_spec("4R"), r)
    assert any("3.4" in ln and "5.0" in ln for ln in lines), lines
    assert any("左边距" in ln for ln in lines)


def test_diff_report_empty_when_consistent():
    r = probe.ProbeResult(printer="P", paper_names=["4x6"], paper_codes=[1],
                          paper_sizes_mm=[(102.0, 152.0)], physical_w_mm=102.0,
                          physical_h_mm=152.0, offset_x_mm=3.4, offset_y_mm=3.0,
                          res_w_px=1204, res_h_px=1785, dpi_x=300, dpi_y=300)
    assert probe.diff_report(specs.find_spec("4R"), r) == []


def test_probe_closes_printer_handle():
    api = FakeApi(dc_caps={probe.LOGPIXELSX: 300, probe.LOGPIXELSY: 300})
    probe.probe(api, "P")
    assert ("close", "hdc:P") in api.calls
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_probe.py -v`
Expected: FAIL —`ModuleNotFoundError: No module named 'photoprint.win.api'`

- [ ] **Step 3: 实现 api 与 probe**

`photoprint/win/api.py`：

```python
"""win32 调用的薄封装层。

真实实现在方法内部才 import win32，这样 tests 可以完全脱机跑 FakeApi；
本机没有连接 G3800，任何在 import 期就拉 win32 的设计都会让测试假死。
"""
from __future__ import annotations


class RealWinApi:
    def enum_printers(self):
        import win32print
        return [p[2] for p in win32print.EnumPrinters(
            win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)]

    def device_caps(self, printer, field):
        import win32print
        return win32print.DeviceCapabilities(printer, None, field, None)

    def open_printer(self, name):
        import win32print
        return win32print.OpenPrinter(name)

    def close_printer(self, handle):
        import win32print
        win32print.ClosePrinter(handle)

    def document_properties(self, handle, printer, mode="get"):
        import win32print
        return win32print.DocumentProperties(0, handle, printer, None, None,
                                             _mode_flag(mode))

    def get_device_caps(self, hdc, field):
        import win32con
        import win32ui
        return win32ui.CreateDCFromHandle(int(hdc)).GetDeviceCaps(field)


def _mode_flag(mode):
    import win32print
    # "size" 仅询问总长（含驱动私有扩展区）；"get" 才取回填充好的结构
    return {"size": win32print.DM_INQUIRE, "get": win32print.DM_GETMODE}[mode]
```

`photoprint/win/probe.py`：

```python
"""驱动能力探测：不信任规格表，冲突时以驱动为准并出报告。

单位约定（易错）：
  DeviceCapabilities(DC_PAPERSIZE) → (w, h)，单位 0.1mm
  GetDeviceCaps(PHYSICAL*/PHYSICALOFFSET*/HORZRES/VERTRES) → 设备像素，
    换算 mm 需 / LOGPIXELSX(或 Y) * 25.4
"""
from __future__ import annotations

from dataclasses import dataclass, field

from photoprint.core import units

# DeviceCapabilities 字段（Windows 常量，此处自持以便脱机测试）
DC_PAPERS = 2
DC_PAPERNAMES = 16
DC_PAPERSIZE = 17

# GetDeviceCaps 字段
PHYSICALWIDTH = 110
PHYSICALHEIGHT = 111
PHYSICALOFFSETX = 112
PHYSICALOFFSETY = 113
HORZRES = 8
VERTRES = 10
LOGPIXELSX = 88
LOGPIXELSY = 90


@dataclass
class ProbeResult:
    printer: str
    paper_names: list = field(default_factory=list)
    paper_codes: list = field(default_factory=list)
    paper_sizes_mm: list = field(default_factory=list)
    physical_w_mm: float = 0.0
    physical_h_mm: float = 0.0
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0
    res_w_px: int = 0
    res_h_px: int = 0
    dpi_x: int = 0
    dpi_y: int = 0


def _px_to_mm(px, dpi):
    if not dpi:
        return 0.0
    return px / dpi * 25.4


def probe(api, printer, paper_code=None, dc=None):
    """探测一台打印机。dc 给定时用该设备上下文回读（直打时复用同一 hdc）。"""
    target = dc if dc is not None else api.open_printer(printer)
    own_handle = dc is None
    try:
        dpi_x = api.get_device_caps(target, LOGPIXELSX) if own_handle else 0
        dpi_y = api.get_device_caps(target, LOGPIXELSY) if own_handle else 0
        names = api.device_caps(printer, DC_PAPERNAMES) or []
        codes = api.device_caps(printer, DC_PAPERS) or []
        sizes = api.device_caps(printer, DC_PAPERSIZE) or []
        # 真机上 hdc 才是当前纸张的物理参数来源；脱机时用设备默认
        phys_w = api.get_device_caps(target, PHYSICALWIDTH) if own_handle else 0
        phys_h = api.get_device_caps(target, PHYSICALHEIGHT) if own_handle else 0
        off_x = api.get_device_caps(target, PHYSICALOFFSETX) if own_handle else 0
        off_y = api.get_device_caps(target, PHYSICALOFFSETY) if own_handle else 0
        hr = api.get_device_caps(target, HORZRES) if own_handle else 0
        vr = api.get_device_caps(target, VERTRES) if own_handle else 0
        if own_handle:
            dpi_x, dpi_y = dpi_x or 300, dpi_y or 300
    finally:
        if own_handle:
            api.close_printer(target)
    return ProbeResult(
        printer=printer,
        paper_names=list(names),
        paper_codes=list(codes),
        paper_sizes_mm=[(w / 10.0, h / 10.0) for w, h in sizes] if sizes else [],
        physical_w_mm=_px_to_mm(phys_w, dpi_x),
        physical_h_mm=_px_to_mm(phys_h, dpi_y),
        offset_x_mm=_px_to_mm(off_x, dpi_x),
        offset_y_mm=_px_to_mm(off_y, dpi_y),
        res_w_px=hr, res_h_px=vr, dpi_x=dpi_x, dpi_y=dpi_y,
    )


def _norm(name: str) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def match_driver_paper(names, want_name):
    """把 '4x6' 之类的期望名匹配到驱动实际叫法（'4 X 6'/'10x15'…）。"""
    want = _norm(want_name)
    codes = list(range(1, len(names) + 1))
    for code, name in zip(codes, names):
        if _norm(name) == want:
            return code, name
    for code, name in zip(codes, names):
        if want and want in _norm(name):
            return code, name
    return None, None


def borderless_active(result: ProbeResult) -> bool:
    """无边距是否生效：以驱动回报的物理偏移为零为唯一证据。

    绝不按"规格说支持无边距"就当成已生效——那是谎报的源头。
    """
    return abs(result.offset_x_mm) <= 0.05 and abs(result.offset_y_mm) <= 0.05


def diff_report(spec, result: ProbeResult) -> list:
    """规格值与驱动实测值的冲突清单，供 UI 同时显示两个数。"""
    out = []
    if result.physical_w_mm and abs(result.physical_w_mm - spec.w_mm) > 0.5:
        out.append(f"宽度：依规格 {spec.w_mm}mm，驱动实测 {result.physical_w_mm:.2f}mm")
    if result.physical_h_mm and abs(result.physical_h_mm - spec.h_mm) > 0.5:
        out.append(f"高度：依规格 {spec.h_mm}mm，驱动实测 {result.physical_h_mm:.2f}mm")
    if result.offset_x_mm and abs(result.offset_x_mm - spec.margins.left) > 0.2:
        out.append(f"左边距：依规格 {spec.margins.left}mm，驱动实测 "
                   f"{result.offset_x_mm:.2f}mm")
    if result.offset_y_mm and abs(result.offset_y_mm - spec.margins.top) > 0.2:
        out.append(f"上边距：依规格 {spec.margins.top}mm，驱动实测 "
                   f"{result.offset_y_mm:.2f}mm")
    return out
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_probe.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
git add photoprint/win/api.py photoprint/win/probe.py tests/test_probe.py
git commit -m "feat: 驱动能力探测与规格冲突报告"
```

---

### Task 11: DEVMODE 继承私有区只改纸张字段

**Files:**
- Create: `photoprint/win/devmode.py`
- Test: `tests/test_devmode.py`

**Interfaces:**
- Consumes: `units.win_mm`、`api.WinApi.document_properties`
- Produces:
  - `devmode.DMPAPER_USER = 259`
  - `devmode.DM_PAPERSIZE`、`devmode.DM_PAPERLENGTH`、`devmode.DM_PAPERWIDTH`、`devmode.DM_DEFAULTSOURCE`、`devmode.DM_SCALE`（Windows 常量自持）
  - `devmode.modify(dm, size, w_mm, h_mm, paper_code=None, default_source=True) -> int`（就地改，返回 size）
  - `devmode.build(api, printer, w_mm, h_mm, paper_code=None) -> tuple[object, int]`

- [ ] **Step 1: 写失败测试**

`tests/test_devmode.py`：

```python
"""DEVMODE 铁律：继承驱动私有扩展区，只改纸张相关字段。"""
import pytest

from photoprint.win import devmode


class FakeDM:
    def __init__(self):
        self.cbSize = 220
        self.dmFields = 0
        self.dmPaperSize = 9
        self.dmPaperLength = 2970
        self.dmPaperWidth = 2100
        self.dmDefaultSource = 1
        self.dmScale = 100
        self.duplex = 300  # 驱动私有区被建模为一个不得改动的字段
        self.mediaType = 700


class FakeApi:
    def __init__(self, size=520):
        self.size = size
        self.mode_log = []
        self.dm = FakeDM()

    def open_printer(self, name):
        return f"hnd:{name}"

    def close_printer(self, handle):
        pass

    def document_properties(self, handle, printer, mode):
        """mode="size" 只问结构大小；mode="get" 取回含私有区的已填结构。"""
        self.mode_log.append(mode)
        return self.size if mode == "size" else self.dm


def test_modify_sets_custom_size_in_tenth_mm():
    dm = FakeDM()
    devmode.modify(dm, 520, 89.0, 127.0)
    assert dm.dmPaperSize == devmode.DMPAPER_USER
    assert dm.dmPaperWidth == 890    # 0.1mm 单位：89mm × 10
    assert dm.dmPaperLength == 1270  # 127mm × 10


def test_modify_uses_preset_code_when_given():
    """preset 尺寸必须走驱动预设码，才可能继承无边距标志。"""
    dm = FakeDM()
    devmode.modify(dm, 520, 102.0, 152.0, paper_code=259 + 1)
    assert dm.dmPaperSize != devmode.DMPAPER_USER
    assert dm.dmPaperWidth == 1020  # 单位是 0.1mm：102mm → 1020


def test_preset_code_path_does_not_need_user_dims():
    dm = FakeDM()
    devmode.modify(dm, 520, 210.0, 297.0, paper_code=9)
    assert dm.dmPaperSize == 9


def test_dmfields_bits_are_set():
    dm = FakeDM()
    devmode.modify(dm, 520, 89.0, 127.0)
    for bit in (devmode.DM_PAPERSIZE, devmode.DM_PAPERLENGTH,
                devmode.DM_PAPERWIDTH, devmode.DM_DEFAULTSOURCE,
                devmode.DM_SCALE):
        assert dm.dmFields & bit, f"缺少位 {bit}"


def test_scale_is_forced_to_100():
    dm = FakeDM()
    dm.dmScale = 85  # 驱动被设成 85% 缩放，必须被纠回 1:1
    devmode.modify(dm, 520, 89.0, 127.0)
    assert dm.dmScale == 100


def test_cbsize_and_private_area_untouched():
    dm = FakeDM()
    before = (dm.cbSize, dm.duplex, dm.mediaType)
    devmode.modify(dm, 520, 89.0, 127.0)
    assert (dm.cbSize, dm.duplex, dm.mediaType) == before, "私有区被改动会丢失无边距设置"


def test_build_asks_size_then_gets_filled_struct():
    api = FakeApi(size=520)
    dm, size = devmode.build(api, "Canon G3800 series", 89.0, 127.0)
    assert size == 520
    assert api.mode_log == ["size", "get"], "必须先按驱动回报的 size 分配再取回，不得新建空结构"


def test_build_rejects_zero_size():
    api = FakeApi(size=0)
    with pytest.raises(RuntimeError, match="DocumentProperties"):
        devmode.build(api, "P", 89.0, 127.0)
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_devmode.py -v`
Expected: FAIL —`ModuleNotFoundError: No module named 'photoprint.win.devmode'`

- [ ] **Step 3: 实现 devmode**

`photoprint/win/devmode.py`：

```python
"""DEVMODE 的读取与最小化改写。

四条不可变语义：
  1. buffer 按驱动回报的 size 分配（含私有扩展区），不得按 sizeof(DEVMODE) 截断
  2. 必须先向驱动取回当前默认设置再改，以继承无边距/介质类型等私有开关
  3. 不得改 cbSize
  4. 只写纸张相关字段与 dmScale
常量在此自持，避免测试期强绑 win32；真机调用由 api.RealWinApi 提供。
"""
from __future__ import annotations

DMPAPER_USER = 259

DM_PAPERSIZE = 0x00000200
DM_PAPERLENGTH = 0x00000400
DM_PAPERWIDTH = 0x00000800
DM_DEFAULTSOURCE = 0x00001000
DM_SCALE = 0x00000001

DMBIN_USER = 4


def modify(dm, size, w_mm, h_mm, paper_code=None, default_source=True):
    """就地改 DEVMODE 的纸张字段，返回驱动给的 size（含私有区）。"""
    from photoprint.core import units

    dm.dmFields = getattr(dm, "dmFields", 0) | DM_PAPERSIZE | DM_PAPERLENGTH | DM_PAPERWIDTH | DM_SCALE
    if paper_code and paper_code != DMPAPER_USER:
        dm.dmPaperSize = int(paper_code)
    else:
        dm.dmPaperSize = DMPAPER_USER
    # 0.1mm 单位；preset 路径同样写入，避免驱动沿用旧的表单尺寸
    dm.dmPaperWidth = units.win_mm(w_mm)
    dm.dmPaperLength = units.win_mm(h_mm)
    if default_source:
        dm.dmFields |= DM_DEFAULTSOURCE
        dm.dmDefaultSource = DMBIN_USER
    dm.dmScale = 100
    return size


def build(api, printer, w_mm, h_mm, paper_code=None):
    """取驱动默认 devmode 后改纸张字段。返回 (dm, size)。

    两步调用不可合并：先以 mode="size" 问出含私有区的总长，
    再按该长度分配 buffer 并以 mode="get" 取回已填充的结构。
    RealWinApi 负责把 buffer 与 PyDEVMODE 的绑定包在内部。
    """
    handle = api.open_printer(printer)
    try:
        size = api.document_properties(handle, printer, "size")
        if not size:
            raise RuntimeError("DocumentProperties 返回 0，无法取得 DEVMODE")
        dm = api.document_properties(handle, printer, "get")
    finally:
        api.close_printer(handle)
    return modify(dm, size, w_mm, h_mm, paper_code), size
```

注：`mode="size"` 对应真机上的 `DocumentProperties(..., None, None, DM_INQUIRE)` 只拿长度；`mode="get"` 对应先 `create_string_buffer(size)` 再 `DocumentProperties(..., DM_GETMODE)` 拿回填充好的 `PyDEVMODE`。这两步的分配与绑定全部关在 `RealWinApi.document_properties` 内部，`tests/test_devmode.py` 用 `FakeApi` 只验证语义（先问长度再取回、只改纸张字段、保留私有区），真机行为在 M5 由用户回读校验把关。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_devmode.py -v`
Expected: PASS（8 passed）

- [ ] **Step 5: 提交**

```bash
git add photoprint/win/devmode.py tests/test_devmode.py
git commit -m "feat: DEVMODE 纸张字段改写与私有区继承"
```

---

### Task 12: GDI 送页与 0.5mm 回读校验

**Files:**
- Create: `photoprint/win/gdi_print.py`
- Test: `tests/test_gdi_verify.py`

**Interfaces:**
- Consumes: `devmode.build`、`probe.probe`、`units.mm_to_px`、`PIL.ImageWin.Dib`
- Produces:
  - `gdi_print.verify_physical_size(phys_w_mm, phys_h_mm, req_w_mm, req_h_mm, tol_mm=0.5) -> tuple[bool, str]`
  - `gdi_print.pick_dpi(driver_dpi, cap=600) -> int`
  - `gdi_print.print_job(api, printer, port, images, sheet, dpi, dm=None) -> dict`

- [ ] **Step 1: 写失败测试**

`tests/test_gdi_verify.py`：

```python
"""回读校验与 dpi 选取是纯函数：这两条决定直打会不会被驱动偷偷缩放。"""
import pytest

from photoprint.win import gdi_print


def test_accepts_within_half_mm():
    ok, msg = gdi_print.verify_physical_size(89.4, 127.3, 89.0, 127.0)
    assert ok is True
    assert msg == ""


def test_rejects_beyond_half_mm_and_explains():
    ok, msg = gdi_print.verify_physical_size(102.0, 152.0, 89.0, 127.0)
    assert ok is False
    assert "驱动忽略了自定义尺寸" in msg
    assert "102.00" in msg and "89.00" in msg


def test_tolerance_boundary_is_inclusive():
    assert gdi_print.verify_physical_size(89.5, 127.0, 89.0, 127.0)[0] is True
    assert gdi_print.verify_physical_size(89.51, 127.0, 89.0, 127.0)[0] is False


def test_pick_dpi_caps_4800_to_600():
    assert gdi_print.pick_dpi(4800) == 600
    assert gdi_print.pick_dpi(300) == 300
    assert gdi_print.pick_dpi(150) == 150
    assert gdi_print.pick_dpi(0) == 300  # 驱动没回报时的安全默认


def test_pick_dpi_respects_user_cap():
    assert gdi_print.pick_dpi(1200, cap=300) == 300
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_gdi_verify.py -v`
Expected: FAIL —`ModuleNotFoundError: No module named 'photoprint.win.gdi_print'`

- [ ] **Step 3: 实现 gdi_print**

`photoprint/win/gdi_print.py`：

```python
"""GDI 直打：CreateDC → BeginDoc → 逐页 StretchBlt → EndDoc。

内存纪律：G3800 标称 4800×1200 dpi，按驱动 dpi 直出 A4 会是约 40000×25000
像素，必然爆内存。因此渲染固定在 300/600 dpi，送图时用 StretchBlt 交给驱动放大。
"""
from __future__ import annotations

DEFAULT_DPI = 300
DPI_FLOOR = 150


def verify_physical_size(phys_w_mm, phys_h_mm, req_w_mm, req_h_mm, tol_mm=0.5):
    """回读驱动认定的物理纸张尺寸与请求值比对。

    超限说明驱动忽略了程序化设置的自定义尺寸（部分佳能驱动要求先在
    驱动内建立表单），此时必须中止直打并指向 PDF 兜底。
    """
    dw = abs(phys_w_mm - req_w_mm)
    dh = abs(phys_h_mm - req_h_mm)
    if dw <= tol_mm and dh <= tol_mm:
        return True, ""
    return False, (f"驱动忽略了自定义尺寸：请求 {req_w_mm:.2f}×{req_h_mm:.2f}mm，"
                   f"设备实际 {phys_w_mm:.2f}×{phys_h_mm:.2f}mm"
                   f"（偏差 宽{dw:.2f}/高{dh:.2f}mm，容差 {tol_mm}mm）。"
                   f"请在驱动首选项中建立同名自定义纸张表单，或改用 PDF 导出打印。")


def pick_dpi(driver_dpi, cap=600):
    """取驱动与用户上限中较小者，异常回报时回落 300。"""
    if not driver_dpi or driver_dpi <= 0:
        return DEFAULT_DPI
    return max(DPI_FLOOR, min(int(driver_dpi), int(cap)))


def print_job(api, printer, port, images, sheet, dpi, dm=None):
    """打印多页。返回 {'ok': bool, 'pages': int, 'message': str}。"""
    from PIL import ImageWin

    import win32con
    import win32print
    import win32ui

    from photoprint.core import units
    from photoprint.win import devmode as dm_mod
    from photoprint.win import probe

    if not images:
        return {"ok": False, "pages": 0, "message": "没有可打印的页面"}

    hprinter = api.open_printer(printer)
    try:
        size = api.document_properties(hprinter, printer, "get")
        dm_obj, size = _take_devmode(api, printer, size, sheet)
        hdc = win32ui.CreateDCFromHandle(_create_dc(api, printer, port, dm_obj))
        try:
            result = probe.probe(api, printer, dc=_as_dc_ref(hdc))
            ok, msg = verify_physical_size(result.physical_w_mm,
                                           result.physical_h_mm,
                                           sheet.w_mm, sheet.h_mm)
            if not ok:
                return {"ok": False, "pages": 0, "message": msg}
            hdc.StartDoc(f"PhotoPrint {sheet.label}")
            try:
                for img in images:
                    hdc.StartPage()
                    try:
                        dib = ImageWin.Dib(img)
                        w = units.mm_to_px(sheet.w_mm, dpi)
                        h = units.mm_to_px(sheet.h_mm, dpi)
                        hdc.SetStretchBltMode(win32con.HALFTONE)
                        dib.Draw(hdc.GetHandleOutput(), (0, 0, w, h))
                    finally:
                        hdc.EndPage()
            finally:
                hdc.EndDoc()
            return {"ok": True, "pages": len(images), "message": ""}
        finally:
            hdc.DeleteDC()
    except Exception as exc:  # 打印阶段不得崩溃：统一转成可读消息
        return {"ok": False, "pages": 0, "message": f"打印失败：{exc}"}
    finally:
        api.close_printer(hprinter)


def _take_devmode(api, printer, size, sheet):
    from photoprint.win import devmode as dm_mod

    return dm_mod.build(api, printer, sheet.w_mm, sheet.h_mm,
                        sheet.driver_paper_code)


def _create_dc(api, printer, port, dm_obj):
    import win32print

    return win32print.CreateDC("Win32", printer, port, dm_obj)


def _as_dc_ref(hdc):
    return hdc
```

注：`_as_dc_ref` 把 `PyCDC` 适配成 `probe.probe` 可回读的句柄对象；真机对接时若 `GetDeviceCaps` 走 `api.get_device_caps` 失败，改用 `hdc.GetDeviceCaps(field)`——两条路径都保留，验证以回读结果为准，任一失败即触发 PDF 兜底。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_gdi_verify.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add photoprint/win/gdi_print.py tests/test_gdi_verify.py
git commit -m "feat: GDI 送页流程与 0.5mm 回读校验"
```

---

### Task 13: 等尺寸 PDF 兜底导出

**Files:**
- Create: `photoprint/win/pdf_export.py`
- Test: `tests/test_pdf_export.py`

**Interfaces:**
- Consumes: `PIL.Image`、`img2pdf`
- Produces:
  - `pdf_export.mm_to_pt(mm: float) -> float`
  - `pdf_export.export_pdf(images: list[Image], sheet, out_path) -> Path`

- [ ] **Step 1: 写失败测试**

`tests/test_pdf_export.py`：

```python
"""兜底路径的价值在于页面尺寸就是纸张尺寸，可用点数反验。"""
import re
from pathlib import Path

import pytest

Image = pytest.importorskip("PIL.Image")
img2pdf = pytest.importorskip("img2pdf")
from PIL import Image as PILImage  # noqa: E402

from photoprint.core import specs  # noqa: E402
from photoprint.win import pdf_export  # noqa: E402


def test_mm_to_pt():
    assert pdf_export.mm_to_pt(25.4) == pytest.approx(72.0)
    assert pdf_export.mm_to_pt(89.0) == pytest.approx(252.283, abs=0.01)
    assert pdf_export.mm_to_pt(127.0) == pytest.approx(360.0, abs=0.01)


def _mediabox(data: bytes):
    m = re.search(rb"MediaBox\s*\[([\d.\s]+)\]", data)
    assert m, "PDF 里找不到 MediaBox"
    return [float(x) for x in m.group(1).split()]


def test_export_pdf_page_size_equals_3r(tmp_path):
    a4 = specs.find_spec("3R")
    img = PILImage.new("RGB", (89, 127), (255, 0, 0))
    out = pdf_export.export_pdf([img], a4, tmp_path / "p.pdf")
    box = _mediabox(Path(out).read_bytes())
    assert box[0] == 0 and box[1] == 0
    assert box[2] == pytest.approx(252.283, abs=1.0)
    assert box[3] == pytest.approx(360.0, abs=1.0)


def test_export_pdf_for_a4(tmp_path):
    img = PILImage.new("RGB", (210, 297), (0, 0, 255))
    out = pdf_export.export_pdf([img], specs.find_spec("A4"), tmp_path / "a.pdf")
    box = _mediabox(Path(out).read_bytes())
    assert box[2] == pytest.approx(595.276, abs=1.0)
    assert box[3] == pytest.approx(841.89, abs=1.0)


def test_export_multiple_pages(tmp_path):
    imgs = [PILImage.new("RGB", (210, 297), (0, 255, 0)) for _ in range(3)]
    out = pdf_export.export_pdf(imgs, specs.find_spec("A4"), tmp_path / "m.pdf")
    data = Path(out).read_bytes()
    assert data.count(b"MediaBox") >= 3


def test_empty_input_rejected(tmp_path):
    with pytest.raises(ValueError, match="没有"):
        pdf_export.export_pdf([], specs.find_spec("A4"), tmp_path / "e.pdf")
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_pdf_export.py -v`
Expected: FAIL —`ModuleNotFoundError: No module named 'photoprint.win.pdf_export'`（若 `img2pdf` 未装则先 `pip install img2pdf`，并确认已写进 `requirements.txt`）

- [ ] **Step 3: 实现 pdf_export**

`photoprint/win/pdf_export.py`：

```python
"""等尺寸 PDF 导出：直打被驱动拒绝时的兜底路径。

页面尺寸严格等于纸张物理尺寸，用户在 Acrobat/SumatraPDF 里选"实际大小/100%"
打印即可复现排版；不依赖程序化 DEVMODE。
"""
from __future__ import annotations

import io
from pathlib import Path

import img2pdf
from PIL import Image

MM_TO_PT = 72.0 / 25.4


def mm_to_pt(mm: float) -> float:
    return mm * MM_TO_PT


def export_pdf(images, sheet, out_path):
    """把已渲染的页面图导出为等尺寸 PDF。"""
    if not images:
        raise ValueError("没有可导出的页面")
    chunks = []
    for img in images:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        chunks.append(buf.getvalue())
    layout = img2pdf.get_layout_fun((mm_to_pt(sheet.w_mm), mm_to_pt(sheet.h_mm)))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(img2pdf.convert(*chunks, layout_fun=layout))
    return out_path
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_pdf_export.py -v`
Expected: PASS（5 passed）（若 `img2pdf` 未装则先 `pip install img2pdf`，并确认已写进 `requirements.txt`）

- [ ] **Step 5: 提交**

```bash
git add photoprint/win/pdf_export.py tests/test_pdf_export.py
git commit -m "feat: 等尺寸 PDF 兜底导出"
```

---

### Task 14: CLI 串联与 M1/M2 验收证据

**Files:**
- Create: `photoprint/cli.py`
- Create: `_lab/m1m2_check.py`
- Create: `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `store.Store`、`pack.pack`、`crop.cell_crop_box`、`modes.*`、`render.render_page`、`pdf_export.export_pdf`、`gdi_print.print_job`、`probe.probe`
- Produces:
  - `cli.build_plan_jobs(store, sheet_key, cell_key, gap_mm, bleed_mm, mode, borderless_active) -> tuple[LayoutPlan, str]`
  - `cli.main(argv=None) -> int`
  - 命令：`python -m photoprint.cli --photos ... --sheet A4 --cell 3R --out _lab/out/job.png`；`--print` 走 GDI，`--pdf` 走兜底

- [ ] **Step 1: 写失败测试**

`tests/test_cli.py`：

```python
"""CLI 只做编排：几何决策必须来自 core，不在 cli 里重算。"""
import pytest

pytest.importorskip("PIL", reason="需要 Pillow")

from photoprint import cli  # noqa: E402
from photoprint.core import modes, store  # noqa: E402


@pytest.fixture
def st(tmp_path):
    s = store.Store(tmp_path / "papers.json")
    s.load()
    return s


def test_default_mode_for_a4_3r_is_bleed_trim(st):
    plan, mode = cli.build_plan_jobs(st, "A4", "3R", 0.0, modes.DEFAULT_BLEED_MM,
                                     None, False)
    assert mode == modes.BLEED_TRIM
    assert plan.count == 4
    assert plan.cuts


def test_explicit_mode_is_respected(st):
    plan, mode = cli.build_plan_jobs(st, "A4", "3R", 0.0, 0.0,
                                     modes.FILL_PRINTABLE, False)
    assert mode == modes.FILL_PRINTABLE
    assert plan.count == 4


def test_illegal_bleed_on_3r_is_reported(st):
    with pytest.raises(ValueError, match="无边距"):
        cli.build_plan_jobs(st, "3R", "3R", 0.0, 3.0, modes.BLEED_TRIM, False)


def test_main_returns_2_when_no_photos(tmp_path, capsys):
    code = cli.main(["--sheet", "A4", "--cell", "3R",
                     "--out", str(tmp_path / "x.png")])
    assert code == 2
    assert "没有照片" in capsys.readouterr().err


def test_main_writes_png_with_exact_mm_size(tmp_path):
    from PIL import Image

    photos = []
    for i in range(4):
        p = tmp_path / f"{i}.jpg"
        Image.new("RGB", (400, 200), (i * 50, 30, 40)).save(p)
        photos.append(str(p))
    out = tmp_path / "page.png"
    code = cli.main(["--photos", *photos, "--sheet", "A4", "--cell", "3R",
                     "--dpi", "25.4", "--out", str(out)])
    assert code == 0
    img = Image.open(out)
    assert img.size == (210, 297)  # dpi 25.4 下 1px = 1mm，可直接核对物理尺寸


def test_main_writes_pdf_with_3r_box(tmp_path):
    import re
    from PIL import Image

    p = tmp_path / "0.jpg"
    Image.new("RGB", (400, 200), (10, 20, 30)).save(p)
    out = tmp_path / "page.pdf"
    code = cli.main(["--photos", str(p), "--sheet", "3R", "--cell", "3R",
                     "--dpi", "25.4", "--pdf", str(out)])
    assert code == 0
    m = re.search(rb"MediaBox\s*\[([\d.\s]+)\]", out.read_bytes())
    vals = [float(x) for x in m.group(1).split()]
    assert vals[2] == pytest.approx(252.283, abs=1.0)
    assert vals[3] == pytest.approx(360.0, abs=1.0)
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL —`ModuleNotFoundError: No module named 'photoprint.cli'`

- [ ] **Step 3: 实现 cli**

`photoprint/cli.py`：

```python
"""命令行编排：探测 → 装箱 → 裁切 → 渲染 → 直打/PDF。

本文件不得包含任何 mm/像素或裁切几何计算，一律调用 core/。
"""
from __future__ import annotations

import argparse
import sys

from PIL import Image

from photoprint.core import crop, modes, pack, render, specs, store, units


def load_photo(path):
    """读图并让 EXIF 方向生效，避免界面与打印各转一次。"""
    from PIL import ImageOps

    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


def build_plan_jobs(st, sheet_key, cell_key, gap_mm, bleed_mm, mode,
                    borderless_active):
    """返回 (排版方案, 生效模式)。mode 为 None 时按默认映射决定。"""
    sheet = st.resolve(sheet_key)
    cell = st.resolve(cell_key)
    printable = specs.printable_rect(sheet, borderless_active=borderless_active)
    probe_plan = pack.pack(sheet, cell, gap_mm=gap_mm, bleed_mm=0.0,
                           printable=printable)
    if mode is None:
        mode = modes.default_mode(sheet, cell, probe_plan.count, borderless_active)
    modes.assert_mode_legal(sheet, mode)
    bleed = bleed_mm if mode == modes.BLEED_TRIM else 0.0
    # 裁切模式在整张纸上装箱（无边距才容得下出血），其余在可打印区内装箱
    rect = specs.RectMM(0.0, 0.0, sheet.w_mm, sheet.h_mm) \
        if mode == modes.BLEED_TRIM else printable
    plan = pack.pack(sheet, cell, gap_mm=gap_mm, bleed_mm=bleed, printable=rect)
    if plan.count == 0 and mode != modes.BLEED_TRIM:
        # 退化情形：格子与纸张同尺寸（如 3R 纸打 3R 照片）。
        # 按可打印矩形装箱必然得 0 格，改为整纸装一格，
        # 画面收回可打印区由 render 层的交集负责。
        full = specs.RectMM(0.0, 0.0, sheet.w_mm, sheet.h_mm)
        plan = pack.pack(sheet, cell, gap_mm=gap_mm, bleed_mm=0.0, printable=full)
    if plan.count == 0:
        raise ValueError(f"{sheet.label} 放不下 {cell.label}，请换大纸或改小格子")
    return plan, mode


def _pages(plan, photos, sheet, dpi, mode, **kw):
    """按每页格子数切页。"""
    out = []
    for i in range(0, len(photos), plan.count):
        chunk = photos[i:i + plan.count]
        out.append(render.render_page(plan, chunk, sheet, dpi, mode, **kw))
    return out


def build_parser():
    ap = argparse.ArgumentParser(prog="photoprint", description="相片拼版打印")
    ap.add_argument("--photos", nargs="*", default=[])
    ap.add_argument("--printer", default=None)
    ap.add_argument("--sheet", default="A4")
    ap.add_argument("--cell", default="3R")
    ap.add_argument("--mode", default=None, choices=list(modes.MODES))
    ap.add_argument("--gap", type=float, default=0.0)
    ap.add_argument("--bleed", type=float, default=modes.DEFAULT_BLEED_MM)
    ap.add_argument("--dpi", type=float, default=300.0)
    ap.add_argument("--out", default=None, help="输出 PNG 路径（调试与验收用）")
    ap.add_argument("--pdf", default=None, help="兜底：输出等尺寸 PDF")
    ap.add_argument("--print", dest="do_print", action="store_true")
    ap.add_argument("--list-printers", action="store_true")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    st = store.Store()
    st.load()

    if args.list_printers:
        from photoprint.win import api as win_api

        for name in win_api.RealWinApi().enum_printers():
            print(name)
        return 0

    if not args.photos:
        print("没有照片：请用 --photos 指定至少一张", file=sys.stderr)
        return 2

    photos = [load_photo(p) for p in args.photos]
    sheet = st.resolve(args.sheet)
    plan, mode = build_plan_jobs(st, args.sheet, args.cell, args.gap,
                                args.bleed, args.mode, False)
    pages = _pages(plan, photos, sheet, args.dpi, mode)

    borderless = mode == modes.BLEED_TRIM
    note = ("需人工裁切：沿灰线切开后即为 "
            f"{plan.cells[0].inner_mm()[2]:.0f}×{plan.cells[0].inner_mm()[3]:.0f}mm 成品"
            if borderless else
            f"将保留白边：依规格约 上{sheet.margins.top}/下{sheet.margins.bottom}/"
            f"左{sheet.margins.left}/右{sheet.margins.right}mm（未经真机校准）")
    print(f"纸张 {sheet.label}，每页 {plan.count} 格，共 {len(pages)} 页。{note}")

    if args.out:
        pages[0].save(args.out)
        print(f"已输出 {args.out}")
    if args.pdf:
        from photoprint.win import pdf_export

        pdf_export.export_pdf(pages, sheet, args.pdf)
        print(f"已输出等尺寸 PDF {args.pdf}（打印时请选“实际大小/100%”）")
    if args.do_print:
        from photoprint.win import api as win_api
        from photoprint.win import gdi_print

        if not args.printer:
            print("--print 需要 --printer 指定打印机名", file=sys.stderr)
            return 2
        res = gdi_print.print_job(win_api.RealWinApi(), args.printer, None,
                                  pages, sheet, args.dpi)
        print(res["message"] or f"已发送 {res['pages']} 页")
        return 0 if res["ok"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: 全量回归 + 未使用导入清理**

Run: `python -m pytest -v`
Expected: 全绿（units/specs/store/pack×3/crop/modes/render/probe/devmode/gdi/pdf/cli）

`cli.py` 里 `crop`、`units` 若最终未直接调用，删除这两个 import，保持无死引用：

Run: `python -m pytest -q`
Expected: 全绿，无 warning 级别的导入错误

- [ ] **Step 6: 写 M1/M2 手工验收脚本**

`_lab/m1m2_check.py`：

```python
"""M1/M2 验收：不连打印机也能把几何做实。中文注释。

跑法：python _lab/m1m2_check.py
产出：_lab/out/ 下的 PNG 与 PDF，可用尺子和 Acrobat 逐项核对。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw  # noqa: E402

from photoprint.core import modes, pack, render, specs  # noqa: E402
from photoprint.win import pdf_export  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(parents=True, exist_ok=True)
DPI = 25.4  # 1px = 1mm，量得动


def synth(n, seed):
    """生成带网格的假照片，便于肉眼检查缩放与裁切是否变形。"""
    img = Image.new("RGB", (600, 300), (240, 240, 255))
    d = ImageDraw.Draw(img)
    for x in range(0, 600, 25):
        d.line([(x, 0), (x, 300)], fill=(200, 60, 60), width=2)
    for y in range(0, 300, 25):
        d.line([(0, y), (600, y)], fill=(60, 60, 200), width=2)
    d.rectangle([seed * 10, 10, seed * 10 + 120, 60], fill=(0, 0, 0))
    return img


def check(name, got, want, tol=1e-6):
    ok = abs(got - want) <= tol
    print(f"{'OK ' if ok else 'BAD'} {name}: {got} (期望 {want})")
    return ok


def main():
    allok = True
    a4, r3 = specs.find_spec("A4"), specs.find_spec("3R")

    # 1) A4 + 3R 出血 3mm：4 格，裁切后每格 89×127
    plan = pack.pack(a4, r3, bleed_mm=modes.DEFAULT_BLEED_MM,
                     printable=specs.RectMM(0, 0, a4.w_mm, a4.h_mm))
    allok &= check("A4+3R(bleed3) 格数", plan.count, 4)
    allok &= check("裁切线数", len(plan.cuts), 6)  # 居中 2×2：每轴 3 条（两侧边界 + 中间缝）
    page = render.render_page(plan, [synth(4, i) for i in range(4)], a4, DPI,
                              modes.BLEED_TRIM)
    allok &= check("页面宽 mm=px", page.width, 210)
    allok &= check("页面高 mm=px", page.height, 297)
    png = OUT / "a4_3r_bleed.png"
    page.save(png)
    print(f"→ 用尺子量 {png}：灰线间距应为 89.0 与 127.0 mm（屏幕 100% 显示）")

    # 2) A4 + 4R 混合带：3 格
    p2 = pack.pack(a4, specs.find_spec("4R"))
    allok &= check("A4+4R 格数", p2.count, 3)

    # 3) 3R 直打：可打印区 82.2×119.0
    p3 = pack.pack(r3, r3)
    allok &= check("3R 可打印宽", p3.printable.w_mm, 82.2, 1e-3)
    allok &= check("3R 可打印高", p3.printable.h_mm, 119.0, 1e-3)
    page3 = render.render_page(p3, [synth(1, 0)], r3, DPI, modes.FILL_PRINTABLE)
    allok &= check("3R 页面宽", page3.width, 89)

    # 4) 等尺寸 PDF：MediaBox 点数
    pdf = OUT / "single_3r.pdf"
    pdf_export.export_pdf([page3], r3, pdf)
    m = re.search(rb"MediaBox\s*\[([\d.\s]+)\]", pdf.read_bytes())
    vals = [float(x) for x in m.group(1).split()]
    allok &= check("3R PDF 宽(pt)", vals[2], 252.283, 1.0)
    allok &= check("3R PDF 高(pt)", vals[3], 360.0, 1.0)

    print("\n结论：", "全部通过" if allok else "存在失败项，见上面 BAD 行")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

Run: `python _lab/m1m2_check.py`
Expected: 全部 `OK`，末行输出"结论： 全部通过"，退出码 0

- [ ] **Step 7: 写 README**

`README.md` 必须包含以下五段，标题固定：

```markdown
# 相片打印助手（PhotoPrint）

## 它解决什么问题
佳能 Easy-PhotoPrint Editor 的相纸预设里没有 3R（5寸 89×127mm），但 G3800 驱动
支持自定义尺寸（宽 55–215.9mm、长 89–676mm），所以 5寸能打，只是官方软件没给入口。
本工具补齐 3R 及任意自建尺寸，并支持大纸拼版多张小图。

## 已知物理限制（勿绕过）
- 自定义尺寸不支持无边距 ⇒ 5寸直打必然留白边（依官方规格约 上3/下5/左右3.4mm）。
- 想要无边距 5寸：选 A4 + 3mm 出血拼版，打印后沿灰裁切线人工裁开。
- 12寸（254×305mm）超出 G3800 能力，已被阻断。

## 安装与运行
pip install -r requirements.txt
python -m photoprint.cli --photos 1.jpg 2.jpg 3.jpg 4.jpg --sheet A4 --cell 3R --out _lab/out/page.png
python -m photoprint.cli --photos *.jpg --sheet A4 --cell 3R --print --printer "Canon G3800 series"
python -m pytest -q            # 全部几何断言
python _lab/m1m2_check.py      # 本机可验证的端到端证据

## 驱动里建立 3R 表单（一次性，之后直打更稳）
1. 控制面板 → 设备和打印机 → Canon G3800 → 打印首选项 → 页设置
2. 纸张尺寸选"自定义"，宽 89mm、高 127mm，命名 "3R"，保存
3. 需无边距的 6寸：在同一面板把布局设为"无边距"，本工具会继承该私有设置
（若驱动保存后仍不出现该尺寸，改用 --pdf 路径：页面尺寸已是 89×127mm）
```

- [ ] **Step 8: 提交**

```bash
git add photoprint/cli.py _lab/m1m2_check.py README.md tests/test_cli.py
git commit -m "feat: CLI 编排与 M1/M2 验收证据脚本"
```

---

## 计划自审（写完后即时复核，结果记录在下方）

**1. 规格覆盖核对**

| 规格节 | 承接任务 |
|---|---|
| 2 事实基线（边距/范围/无边距列表） | T2 常量与断言 |
| 4 尺寸表、探测、自定义尺寸 | T2、T3、T10 |
| 5 pack 三级搜索与 5.3 基准 | T4、T5、T6 |
| 6 cell_crop_box 与同源禁则 | T7、T9 |
| 7 三档模式、默认映射、文案分档、7.4 归零 | T8、T2（归零断言） |
| 9 DEVMODE 继承、0.5mm 回读、dpi | T11、T12 |
| 10 PDF 兜底 | T13 |
| 12 持久化 | T3 |
| 13 错误处理矩阵 | T2（越界阻断）、T3（写盘失败）、T6（无格子）、T8（非法组合）、T12（回读拒绝）、T14（CLI 返回码） |
| 14 测试策略与变异测试 | T4 Step5、T5 Step5、T9 Step5 |
| 8 交互设计、11 校准页 | **不在本计划**，属第二份（M3+M4）——本计划是其依赖 |

**2. 占位符与自纠错误扫描**：无 TBD/TODO/“类似上一个任务”；每个代码步骤均给出可运行代码。各任务的 Expected 通过数已逐个重数并纠正（T1 6、T2 11、T3 7、T4 7、T5 10、T6 6、T7 10、T8 9、T9 12、T10 7、T11 8、T12 5、T13 5、T14 6）。

**2b. 自审发现并修掉的设计缺陷**（不是文字问题，会直接导致实现失败）：

1. **`win_mm` 量纲错**：DEVMODE 的 `dmPaperWidth/Length` 单位是 0.1mm（1mm = 10 单位），而初稿实现写成 `mm * 100`，与 T1 自身的断言 `win_mm(89.0) == 890` 相矛盾。已定为 `int(value_mm * 10)` 向下取整，并把 T11 的 8900/12700 改回 890/1270。这个错真到真机上会把纸张尺寸报大 10 倍。2. **“整张纸只放一格”退化情形**：原规则“装箱在可打印矩形内进行”使得 3R 纸打 3R 照片时算出 0 格（因为 89 > 82.2）。已改为：非 `BLEED_TRIM` 模式下照片落位目标 = 格子内框 ∩ 可打印矩形，并由 CLI 在算出 0 格时退回整纸装一格。该规则已同步补写回规格 5.1 与 6.2。

**3. 类型一致性**：`LayoutPlan(cells, cuts, count, waste_mm2, strategy, printable)` 在 T5 定义、T6/T8/T9/T14 消费一致；`Cell.inner_mm()` 在 T4 定义、T9 使用一致；`crop.Placement(crop_px, dest_mm)` 在 T7 定义、T9 使用一致；`specs.printable_rect` 在 T2 定义、T5/T8/T14 使用一致；`modes.BLEED_TRIM` 常量在 T8 定义、T9/T14 使用一致。`pack.pack(sheet, cell, gap_mm, bleed_mm, allow_rotate, printable)` 的 `printable` 参数在 T5 引入、T6/T14 传入 `RectMM`，类型一致。

**4. 歧义已消除项**：`fill_printable` 的目标矩形是可打印区而非整张纸（T7 模块注释 + T8 `target_rect` 测试）；无边距生效只由探测偏移为零判定（T10 `borderless_active`），不由规格表推定；裁切线在单格时不画（T6、T9 双处断言）。

**5. 已知未闭环风险（如实记录，不隐藏）**：`RealWinApi.document_properties` 与 `PyDEVMODE` 的真实绑定形态、`win32ui.CreateDCFromHandle` 与 `probe` 回读的句柄适配，必须在装有 G3800 驱动的机器上实测；本计划用 FakeApi 锁住语义，真机偏差由 M5 用户回读校验收敛。
