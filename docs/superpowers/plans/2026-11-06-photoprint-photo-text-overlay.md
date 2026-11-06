# 照片叠加文字（日期标签 + 文字水印）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在逐张照片上叠加"日期标签"与"文字水印"两类文字（各配 颜色/字体/大小/粗细/位置，水印另有 自定义文字/不透明度），预览与导出共用同一渲染路径、所见即所得。

**Architecture:** 新增 `core/text_overlay.py`（纯数据 + PIL：字号 mm→px、四角锚点、逐格 clip 合成、加粗兜底、字体缺失降级）；`core/render.py` 在每张贴图后调用 `draw_overlay`；`jobs` 透传两个 `TextSpec` 与逐格 `date_texts`，并新增 `photo_date_text` 读 EXIF/文件时间；`app/main_window.py` 加可折叠"文字叠加"分组控件、`_params` 组装 `TextSpec`、`append_photo` 存日期、`_rebuild_job` 物化 `date_texts`、持久化回填。

**Tech Stack:** PySide6（QGroupBox/QCheckBox/QLineEdit/QSlider/QColorDialog/QComboBox）、Pillow（ImageFont/ImageDraw/Exif）、pytest（core 无 Qt；app 用 pytest-qt offscreen）。

## Global Constraints

- 几何/像素全部落 `core`；`app` 层禁做 mm/像素换算（既有红线）。
- `render_page` 是唯一渲染真相源，预览（96dpi）与导出（300/600dpi）共用；`size_mm` 恒定 → 跨 dpi 物理字号一致。
- **向后兼容红线**：`render_page`/`Job`/`build_job` 新参数一律带默认（`None`/`()`＝不叠加），既有全部测试与 CLI 逐像素不变、零改动。
- 异常一律收敛：字体缺失 / 日期解析失败 / 超长文字 → 该层不画 + 不抛（与 store"任何损坏降级成没有"同口径）。
- `jobs` 不 import Qt/win32、不写 stdout；`core` 不 import Qt。
- 逐格 clip：叠加文字绝不溢出到邻格。
- 测试：core 单元新增 `tests/test_text_overlay.py`（无 Qt）；渲染集成并入 `tests/test_render_rotations.py` 同风格新建 `tests/test_render_overlay.py`；EXIF 并入 `tests/test_jobs.py`；app 并入既有 `tests/test_app_main_window.py`（自带 `_no_leaked_threads`）。
- 提交消息：先 `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8`，python 写 UTF8 无 BOM 消息文件后 `git commit -F`。PowerShell 用 `;` 非 `&&`。
- 变异验牙后必须 `residue=0`（无 `MUTATION-TEMP` 残留）。

---

### Task 1: core/text_overlay 纯几何数据层

**Files:**
- Create: `photoprint/core/text_overlay.py`
- Test: `tests/test_text_overlay.py`

**Interfaces:**
- Consumes: `photoprint.core.units`（`mm_to_px`/`round_px`/`ppmm`）。
- Produces：`Corner`（`TL/TR/BL/BR` 字符串常量）、`TextSpec`（frozen dataclass，字段见 §2.1 spec）、`FONT_TABLE: dict[str, tuple[str, str|None]]`、`size_px(size_mm, dpi) -> int`、`inset_px(margin_pct, cell_wh) -> int`、`anchor_point(corner, cell_wh, text_wh, inset) -> (int, int)`。Task 2 依赖这些名。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_text_overlay.py`：

```python
"""叠加文字的纯几何：字号 dpi 无关、四角锚点、内缩边距。"""
import pytest

pytest.importorskip("PIL", reason="需要 Pillow")

from photoprint.core import units  # noqa: E402
from photoprint.core.text_overlay import (Corner, TextSpec, FONT_TABLE,  # noqa: E402
                                          size_px, inset_px, anchor_point)


def test_size_px_scales_with_dpi():
    # 同一 size_mm，dpi 越大像素越多（1px=1mm 时 size_mm 就是像素高）
    assert size_px(4.0, 25.4) == 4
    assert size_px(4.0, 25.4 * 3) == 12


def test_size_px_never_zero():
    assert size_px(0.0, 25.4) == 1


def test_inset_px_is_pct_of_short_edge():
    assert inset_px(10.0, (200, 100)) == 10          # 短边 100 的 10%
    assert inset_px(4.0, (200, 250)) == 8            # 短边 200 的 4%


def test_anchor_point_four_corners():
    cw, ch, tw, th, ins = 100, 80, 30, 20, 4
    assert anchor_point(Corner.TL, (cw, ch), (tw, th), ins) == (4, 4)
    assert anchor_point(Corner.TR, (cw, ch), (tw, th), ins) == (100 - 30 - 4, 4)
    assert anchor_point(Corner.BL, (cw, ch), (tw, th), ins) == (4, 80 - 20 - 4)
    assert anchor_point(Corner.BR, (cw, ch), (tw, th), ins) == (100 - 30 - 4, 80 - 20 - 4)


def test_textspec_defaults_and_font_table_shape():
    s = TextSpec()
    assert s.enabled is False and s.corner == Corner.BR and s.alpha == 255
    for key, (reg, bold) in FONT_TABLE.items():
        assert isinstance(reg, str) and (bold is None or isinstance(bold, str))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_text_overlay.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'photoprint.core.text_overlay'`。

- [ ] **Step 3: 实现纯几何层**

新建 `photoprint/core/text_overlay.py`：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_text_overlay.py -q`
Expected: PASS（6 条）

- [ ] **Step 5: 变异验牙**

`anchor_point` 里把 `Corner.TR` 分支改成 `return (inset, inset)`（与 TL 同）→ `test_anchor_point_four_corners` 红。验后还原。
Run：`python -m pytest tests/test_text_overlay.py -q`
Expected：坏时 FAIL、还原后 PASS。

- [ ] **Step 6: 提交**

```bash
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
python -c "open('.superpowers/sdd/_overlay_t1_msg.txt','w',encoding='utf-8').write('core: text_overlay 纯几何——TextSpec/Corner/FONT_TABLE/size_px/inset_px/anchor_point\n')"; git add photoprint/core/text_overlay.py tests/test_text_overlay.py; git commit -F .superpowers/sdd/_overlay_t1_msg.txt
```

---

### Task 2: core/text_overlay.draw_overlay（PIL 绘制）

**Files:**
- Modify: `photoprint/core/text_overlay.py`（补 `Image`/`ImageDraw` 导入 + `draw_overlay`）
- Test: `tests/test_text_overlay.py`

**Interfaces:**
- Consumes: Task 1 的 `TextSpec/Corner/FONT_TABLE/size_px/inset_px/anchor_point`。
- Produces: `draw_overlay(page, cell_rect_px, spec, text, dpi) -> None`（原地改 `page`，逐格 clip 合成；前置不满足静默返回）。Task 3 依赖该名与签名。

- [ ] **Step 1: 写失败测试**

在 `tests/test_text_overlay.py` 末尾追加（顶部补 `from PIL import Image`）：

```python
import os
from PIL import Image

from photoprint.core import text_overlay as to


def _arial():
    p = os.path.join(r"C:\Windows\Fonts", "arial.ttf")
    return p if os.path.isfile(p) else None


def _spec(**kw):
    base = dict(enabled=True, font_key="t", size_mm=6.0, weight="normal",
                corner=Corner.TL, rgb=(255, 0, 0), alpha=255, margin_pct=4.0)
    base.update(kw)
    return TextSpec(**base)


def test_draw_overlay_solid_glyph_present(monkeypatch):
    arial = _arial()
    if arial is None:
        pytest.skip("无 arial 字体")
    monkeypatch.setattr(to, "FONT_TABLE", {"t": (arial, None)})
    page = Image.new("RGB", (200, 120), (0, 0, 0))
    to.draw_overlay(page, (0, 0, 200, 120), _spec(), "DATE", 25.4)
    assert max(p[0] for p in page.getdata()) == 255      # 实心红


def test_draw_overlay_alpha_is_semi(monkeypatch):
    arial = _arial()
    if arial is None:
        pytest.skip("无 arial 字体")
    monkeypatch.setattr(to, "FONT_TABLE", {"t": (arial, None)})
    page = Image.new("RGB", (200, 120), (0, 0, 0))
    to.draw_overlay(page, (0, 0, 200, 120), _spec(alpha=128), "DATE", 25.4)
    peak = max(p[0] for p in page.getdata())
    assert 0 < peak < 255                                 # 半透明压在黑底上


def test_draw_overlay_clips_to_cell(monkeypatch):
    arial = _arial()
    if arial is None:
        pytest.skip("无 arial 字体")
    monkeypatch.setattr(to, "FONT_TABLE", {"t": (arial, None)})
    page = Image.new("RGB", (200, 200), (0, 0, 0))
    to.draw_overlay(page, (0, 0, 100, 100), _spec(), "MMMMMMMM", 25.4)
    assert page.crop((100, 100, 200, 200)).getbbox() is None   # 邻区零污染


def test_draw_overlay_missing_font_skips(monkeypatch):
    monkeypatch.setattr(to, "FONT_TABLE", {"t": (r"C:\nope\no.ttf", None)})
    page = Image.new("RGB", (200, 120), (0, 0, 0))
    to.draw_overlay(page, (0, 0, 200, 120), _spec(), "DATE", 25.4)
    assert page.getbbox() is None                           # 未画、未抛


def test_draw_overlay_disabled_or_empty_noop(monkeypatch):
    arial = _arial()
    if arial is None:
        pytest.skip("无 arial 字体")
    monkeypatch.setattr(to, "FONT_TABLE", {"t": (arial, None)})
    page = Image.new("RGB", (200, 120), (0, 0, 0))
    to.draw_overlay(page, (0, 0, 200, 120), _spec(enabled=False), "DATE", 25.4)
    to.draw_overlay(page, (0, 0, 200, 120), _spec(), "", 25.4)
    assert page.getbbox() is None


def test_draw_overlay_bold_stroke_fallback_when_no_bold_file(monkeypatch):
    arial = _arial()
    if arial is None:
        pytest.skip("无 arial 字体")
    monkeypatch.setattr(to, "FONT_TABLE", {"t": (arial, None)})   # 无粗体文件
    page = Image.new("RGB", (200, 120), (0, 0, 0))
    to.draw_overlay(page, (0, 0, 200, 120), _spec(weight="bold"), "WWW", 25.4)
    assert max(p[0] for p in page.getdata()) == 255               # stroke 合成仍画出
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_text_overlay.py -k draw_overlay -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'draw_overlay'`。

- [ ] **Step 3: 实现 draw_overlay**

`text_overlay.py` 顶部把 `from PIL import ImageFont` 改为：

```python
from PIL import Image, ImageDraw, ImageFont
```

文件末尾追加：

```python
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
    ax, ay = anchor_point(spec.corner, (cw, ch), (tw, th), inset)
    layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    fill = tuple(spec.rgb)[:3] + (int(spec.alpha),)
    ImageDraw.Draw(layer).text((ax - l, ay - t), text, font=font, fill=fill,
                               stroke_width=stroke, stroke_fill=fill)
    region = page.crop((x, y, x + cw, y + ch)).convert("RGBA")
    region = Image.alpha_composite(region, layer)
    page.paste(region.convert("RGB"), (x, y))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_text_overlay.py -q`
Expected: PASS（全部）

- [ ] **Step 5: 变异验牙**

1. 把逐格 clip 的两行 `region = page.crop(...)`…`page.paste(...)` 换成 `page.alpha_composite(layer, (x, y))`（画到整页越界）→ `test_draw_overlay_clips_to_cell` 红。
2. 把 `fill = ... + (int(spec.alpha),)` 写死成 `+ (255,)` → `test_draw_overlay_alpha_is_semi` 红。
验后还原。
Run：`python -m pytest tests/test_text_overlay.py -q`
Expected：坏时 FAIL、还原后 PASS。

- [ ] **Step 6: 提交**

```bash
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
python -c "open('.superpowers/sdd/_overlay_t2_msg.txt','w',encoding='utf-8').write('core: text_overlay.draw_overlay 逐格 clip 合成 + 加粗兜底 + 超长/缺字体降级\n')"; git add photoprint/core/text_overlay.py tests/test_text_overlay.py; git commit -F .superpowers/sdd/_overlay_t2_msg.txt
```

---

### Task 3: core/render.py 集成叠加

**Files:**
- Modify: `photoprint/core/render.py`（`render_page` 签名 + 贴图后调用）
- Test: `tests/test_render_overlay.py`

**Interfaces:**
- Consumes: Task 2 的 `text_overlay.draw_overlay`、Task 1 的 `TextSpec/Corner`；既有 `plan.cells`/贴图落位量 `ox/dy/paste_x/paste_y/piece`。
- Produces: `render_page(..., date_overlay=None, watermark_overlay=None, date_texts=())`。Task 4 依赖这三个新参名。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_render_overlay.py`：

```python
"""渲染集成：叠加开启改变目标角、关闭逐像素等于基线、默认参零影响。"""
import os

import pytest

pytest.importorskip("PIL", reason="需要 Pillow")

from PIL import Image  # noqa: E402

from photoprint.core import modes, pack, render, specs, text_overlay as to  # noqa: E402
from photoprint.core.text_overlay import Corner, TextSpec  # noqa: E402

DPI = 25.4


def _a4_id1():
    a4 = specs.find_spec("A4")
    plan = pack.pack(a4, specs.find_spec("ID1"), gap_mm=2.0, allow_rotate=False,
                     printable=specs.printable_rect(a4))
    return a4, plan


def _photo():
    return Image.new("RGB", (200, 100), (10, 20, 30))


def _render(a4, plan, photos, **kw):
    return render.render_page(plan, photos, a4, DPI, modes.FIT_TO_PRINTABLE,
                              show_mask=False, show_cut_lines=False, **kw)


@pytest.fixture
def real_font(monkeypatch):
    arial = os.path.join(r"C:\Windows\Fonts", "arial.ttf")
    if not os.path.isfile(arial):
        pytest.skip("无 arial 字体")
    monkeypatch.setattr(to, "FONT_TABLE", {"t": (arial, None)})


def test_no_overlay_params_equals_baseline(real_font):
    a4, plan = _a4_id1()
    ph = _photo()
    base = _render(a4, plan, [ph] * plan.count)
    got = _render(a4, plan, [ph] * plan.count, date_overlay=None,
                  watermark_overlay=None, date_texts=())
    assert got.tobytes() == base.tobytes()


def test_date_overlay_enabled_changes_pixels(real_font):
    a4, plan = _a4_id1()
    ph = _photo()
    base = _render(a4, plan, [ph] * plan.count)
    spec = TextSpec(enabled=True, font_key="t", size_mm=6.0, corner=Corner.TL,
                    rgb=(255, 255, 255), alpha=255)
    got = _render(a4, plan, [ph] * plan.count, date_overlay=spec,
                  date_texts=["2025-01-02"] * plan.count)
    assert got.tobytes() != base.tobytes()


def test_date_overlay_disabled_equals_baseline(real_font):
    a4, plan = _a4_id1()
    ph = _photo()
    base = _render(a4, plan, [ph] * plan.count)
    spec = TextSpec(enabled=False, font_key="t")
    got = _render(a4, plan, [ph] * plan.count, date_overlay=spec,
                  date_texts=["2025-01-02"] * plan.count)
    assert got.tobytes() == base.tobytes()


def test_date_text_none_skips_that_photo(real_font):
    a4, plan = _a4_id1()
    ph = _photo()
    base = _render(a4, plan, [ph] * plan.count)
    spec = TextSpec(enabled=True, font_key="t", size_mm=6.0, corner=Corner.TL,
                    rgb=(255, 255, 255), alpha=255)
    got = _render(a4, plan, [ph] * plan.count, date_overlay=spec,
                  date_texts=[None] * plan.count)
    assert got.tobytes() == base.tobytes()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_render_overlay.py -q`
Expected: FAIL — `TypeError: render_page() got an unexpected keyword argument 'date_overlay'`。

- [ ] **Step 3: 扩展 render_page**

`render.py` 顶部 import 块加 `text_overlay`：

```python
from photoprint.core import crop, modes, specs, text_overlay, units
```

`render_page` 签名（`rotations=()` 之后）加三参：

```python
def render_page(plan, photos, sheet, dpi, mode, show_mask=True,
                show_cut_lines=True, borderless_active=False,
                offset_pct=(0.0, 0.0), rotations=(),
                date_overlay=None, watermark_overlay=None, date_texts=()):
```

循环内 `page.paste(piece, (paste_x, paste_y))` 之后加：

```python
        rect_px = (paste_x, paste_y, piece.width, piece.height)
        if watermark_overlay is not None and watermark_overlay.enabled:
            text_overlay.draw_overlay(page, rect_px, watermark_overlay,
                                      watermark_overlay.text, dpi)
        if date_overlay is not None and date_overlay.enabled:
            dt = date_texts[idx] if idx < len(date_texts) else None
            if dt:
                text_overlay.draw_overlay(page, rect_px, date_overlay, dt, dpi)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_render_overlay.py -q`
Expected: PASS（4 条）

- [ ] **Step 5: 变异验牙**

把 `if dt:` 的守卫删掉（`dt` 为 `None` 也照调）→ `test_date_text_none_skips_that_photo` 红（`draw_overlay` 收 `None` text 会 `not text` 返回——故须把 `date_texts[idx]` 直接传且 `draw_overlay` 空串守卫仍在；改为传 `dt or ""` 仍不红，故此变异改测：把整段 `if date_overlay...` 无条件执行、`dt` 缺失时传 `"X"`）→ 红。验后还原为守卫版。
Run：`python -m pytest tests/test_render_overlay.py -q`
Expected：坏时 FAIL、还原后 PASS。

- [ ] **Step 6: 提交**

```bash
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
python -c "open('.superpowers/sdd/_overlay_t3_msg.txt','w',encoding='utf-8').write('core: render_page 逐张贴图后叠加日期/水印（新参默认 None，向后兼容）\n')"; git add photoprint/core/render.py tests/test_render_overlay.py; git commit -F .superpowers/sdd/_overlay_t3_msg.txt
```

---

### Task 4: jobs 透传 + EXIF 日期

**Files:**
- Modify: `photoprint/jobs.py`（`Job` 字段 + `render` 透传 + `build_job` 参 + 新增 `photo_date_text`）
- Test: `tests/test_jobs_overlay.py`

**Interfaces:**
- Consumes: Task 1 `TextSpec`、Task 3 `render_page` 新参。
- Produces: `Job.date_overlay/date_texts/watermark_overlay` 字段、`build_job(..., date_overlay=None, watermark_overlay=None, date_texts=())`、`photo_date_text(path) -> str|None`。Task 5 依赖 `photo_date_text` 与 `build_job` 新参。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_jobs_overlay.py`：

```python
"""jobs：photo_date_text 取 EXIF→回退 mtime→坏值 None；Job 透传叠加参不改变无叠加渲染。"""
import os

import pytest

pytest.importorskip("PIL", reason="需要 Pillow")

from PIL import Image  # noqa: E402

from photoprint import jobs  # noqa: E402
from photoprint.core import store, text_overlay  # noqa: E402
from photoprint.core.text_overlay import TextSpec  # noqa: E402


def _store(tmp_path):
    s = store.Store(tmp_path / "papers.json")
    s.load()
    return s


def test_photo_date_text_falls_back_to_mtime(tmp_path):
    p = tmp_path / "n.jpg"
    Image.new("RGB", (40, 40), (0, 0, 0)).save(p)      # 无 EXIF
    got = jobs.photo_date_text(str(p))
    import time
    want = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(str(p))))
    assert got == want


def test_photo_date_text_missing_file_returns_none(tmp_path):
    assert jobs.photo_date_text(str(tmp_path / "nope.jpg")) is None


def test_job_without_overlay_equals_legacy_render(tmp_path):
    st = _store(tmp_path)
    ph = Image.new("RGB", (200, 100), (10, 20, 30))
    photos = [ph]
    legacy = jobs.build_job(st, photos, "A4", "ID1")
    withfield = jobs.build_job(st, photos, "A4", "ID1", date_texts=["2025-01-02"])
    assert legacy.render(0, 96.0).tobytes() == withfield.render(0, 96.0).tobytes()


def test_build_job_accepts_specs(tmp_path):
    st = _store(tmp_path)
    spec = TextSpec(enabled=True, font_key="arial", corner="tl")
    job = jobs.build_job(st, [Image.new("RGB", (200, 100))], "A4", "ID1",
                         date_overlay=spec,
                         date_texts=["2025-01-02"])
    assert job.date_overlay is spec and job.date_texts == ("2025-01-02",)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_jobs_overlay.py -q`
Expected: FAIL — `AttributeError: module 'photoprint.jobs' has no attribute 'photo_date_text'` / `build_job() got an unexpected keyword argument 'date_overlay'`。

- [ ] **Step 3: 实现 jobs 改动**

`jobs.py` 顶部 import 补 `os`、`time`（标准库）：

```python
import os
import time
```

`Job` dataclass 在 `rotations: tuple = ()` 之后加字段：

```python
    date_overlay: object = None
    watermark_overlay: object = None
    date_texts: tuple = ()
```

`Job.render` 内 `rot_chunk = ...` 之后加切片，并把 `render_page` 调用补三参：

```python
        dt_chunk = self.date_texts[i:i + self.count]
        return render.render_page(self.plan, chunk, self.sheet, dpi, self.mode,
                                  show_mask=show_mask,
                                  borderless_active=self.borderless_active,
                                  offset_pct=self.offset_pct,
                                  rotations=rot_chunk,
                                  date_overlay=self.date_overlay,
                                  watermark_overlay=self.watermark_overlay,
                                  date_texts=dt_chunk)
```

`build_job` 签名加参并透传（`rotations=()` 之后）：

```python
def build_job(st, photos, sheet_key, cell_key, *, gap_mm=0.0,
              bleed_mm=modes.DEFAULT_BLEED_MM, mode=None,
              offset_pct=(0.0, 0.0), borderless_active=False,
              rotations=(), date_overlay=None, watermark_overlay=None,
              date_texts=()) -> Job:
```

`return Job(...)` 补：

```python
               rotations=tuple(rotations),
               date_overlay=date_overlay, watermark_overlay=watermark_overlay,
               date_texts=tuple(date_texts))
```

文件末尾新增：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_jobs_overlay.py -q`
Expected: PASS（4 条）

- [ ] **Step 5: 变异验牙**

把 `photo_date_text` 里 mtime 回退分支删掉（`except OSError: return None` 之上直接 `return None`）→ `test_photo_date_text_falls_back_to_mtime` 红（无 EXIF 时返回 None 而非 mtime）。验后还原。
Run：`python -m pytest tests/test_jobs_overlay.py -q`
Expected：坏时 FAIL、还原后 PASS。

- [ ] **Step 6: 提交**

```bash
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
python -c "open('.superpowers/sdd/_overlay_t4_msg.txt','w',encoding='utf-8').write('jobs: Job/build_job 透传叠加配置 + photo_date_text 读 EXIF/文件时间\n')"; git add photoprint/jobs.py tests/test_jobs_overlay.py; git commit -F .superpowers/sdd/_overlay_t4_msg.txt
```

---

### Task 5: app 界面控件 + 参数 + 日期物化 + 持久化

**Files:**
- Modify: `photoprint/app/main_window.py`（import、常量、`_build_ui` 分组、`_params`、`append_photo`、`_rebuild_job`、`save_last_job`、`_restore_last_job`）
- Test: `tests/test_app_main_window.py`

**Interfaces:**
- Consumes: Task 1 `TextSpec/Corner`、Task 4 `jobs.photo_date_text`/`build_job` 新参；既有 `_params`/`_rebuild_job`/`append_photo`/`save_last_job`/`_restore_last_job`/`_connect_param_changed`/`_debounce`。
- Produces: 控件属性 `date_*`/`wm_*`、`self._date_rgb`/`self._wm_rgb`；`_params()` 返回含 `date_overlay`/`watermark_overlay`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_app_main_window.py` 末尾追加：

```python
def test_params_builds_two_text_specs(qapp, tmp_path):
    from photoprint.core.text_overlay import TextSpec
    w = MainWindow(st=_store(tmp_path))
    p = w._params()
    assert isinstance(p["date_overlay"], TextSpec)
    assert isinstance(p["watermark_overlay"], TextSpec)
    assert p["date_overlay"].enabled is False          # 默认关


def test_enabling_watermark_reaches_job(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    w.wm_enabled.setChecked(True)
    w.wm_text.setText("样片")
    w._rebuild_job()
    assert w.job.watermark_overlay.enabled is True
    assert w.job.watermark_overlay.text == "样片"


def test_append_photo_stores_date_text(qapp, tmp_path):
    import time
    w = MainWindow(st=_store(tmp_path))
    p = _make_photos(tmp_path, 1)[0]
    w.append_photo(p)
    got = w.pool[0]["date"]
    want = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(p)))
    assert got == want                                   # 无 EXIF→mtime 日期


def test_rebuild_materializes_date_texts(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    w.date_enabled.setChecked(True)
    _fill(w, tmp_path, n=2)
    assert w.job.date_texts[0] is not None
    assert w.job.date_overlay.enabled is True


def test_overlay_persist_roundtrip(qapp, tmp_path):
    st = _store(tmp_path)
    w = MainWindow(st=st)
    w.date_enabled.setChecked(True)
    w.date_size.setValue(9.0)
    w.date_corner.setCurrentIndex(1)                     # 右上
    w.save_last_job()
    w2 = MainWindow(st=_store(tmp_path))                 # 同 store 路径
    assert w2.date_enabled.isChecked() is True
    assert abs(w2.date_size.value() - 9.0) < 1e-6
    assert w2.date_corner.currentIndex() == 1
```

`test_app_main_window.py` 顶部若未 `import os` 则补：`import os`（在 `import re` 附近）。

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_app_main_window.py -k "overlay or text_spec or watermark or date" -q`
Expected: FAIL — `KeyError: 'date_overlay'` / `AttributeError: 'MainWindow' object has no attribute 'wm_enabled'`。

- [ ] **Step 3: 补 import 与常量**

`main_window.py` QtWidgets import 块加 `QCheckBox, QColorDialog, QGroupBox, QLineEdit, QSlider`（QSlider 已在，去重）；QtCore 已有 `Qt`。加：

```python
from PySide6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListView,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QSlider, QVBoxLayout, QWidget)
from photoprint.core.text_overlay import Corner, TextSpec
```

常量区（`IMAGE_EXTS` 之后）加：

```python
FONT_CHOICES = (("微软雅黑", "yahei"), ("黑体", "heiti"), ("宋体", "songti"),
                ("Arial", "arial"))
WEIGHT_CHOICES = (("常规", "normal"), ("加粗", "bold"))
CORNER_CHOICES = (("左上", Corner.TL), ("右上", Corner.TR),
                  ("左下", Corner.BL), ("右下", Corner.BR))
OVERLAY_DEFAULT_RGB = (255, 255, 255)
```

- [ ] **Step 4: `_build_ui` 加"文字叠加"分组**

在 `panel.addRow("垂直微调", ...)` 之后、`self.preview = PreviewView()` 之前插入：

```python
        overlay = QGroupBox("文字叠加")
        ovl = QVBoxLayout(overlay)
        self._date_rgb = OVERLAY_DEFAULT_RGB
        self._wm_rgb = OVERLAY_DEFAULT_RGB

        self.date_enabled = QCheckBox("日期标签")
        self.date_font = QComboBox()
        for label, key in FONT_CHOICES:
            self.date_font.addItem(label, key)
        self.date_size = _spin(1.0, 30.0, 4.0)
        self.date_weight = QComboBox()
        for label, key in WEIGHT_CHOICES:
            self.date_weight.addItem(label, key)
        self.date_corner = QComboBox()
        for label, key in CORNER_CHOICES:
            self.date_corner.addItem(label, key)
        self.date_color_btn = QPushButton()
        self.date_color_btn.clicked.connect(self._pick_date_color)
        drow = QHBoxLayout()
        for widget in (self.date_font, self.date_size, self.date_weight,
                       self.date_corner, self.date_color_btn):
            drow.addWidget(widget)
        ovl.addWidget(self.date_enabled)
        ovl.addLayout(drow)

        self.wm_enabled = QCheckBox("文字水印")
        self.wm_text = QLineEdit()
        self.wm_font = QComboBox()
        for label, key in FONT_CHOICES:
            self.wm_font.addItem(label, key)
        self.wm_size = _spin(1.0, 30.0, 6.0)
        self.wm_weight = QComboBox()
        for label, key in WEIGHT_CHOICES:
            self.wm_weight.addItem(label, key)
        self.wm_corner = QComboBox()
        for label, key in CORNER_CHOICES:
            self.wm_corner.addItem(label, key)
        self.wm_color_btn = QPushButton()
        self.wm_color_btn.clicked.connect(self._pick_wm_color)
        self.wm_alpha = QSlider(Qt.Horizontal)
        self.wm_alpha.setRange(0, 100)
        self.wm_alpha.setValue(50)
        wrow = QHBoxLayout()
        for widget in (self.wm_font, self.wm_size, self.wm_weight,
                       self.wm_corner, self.wm_color_btn, self.wm_alpha):
            wrow.addWidget(widget)
        ovl.addWidget(self.wm_enabled)
        ovl.addWidget(self.wm_text)
        ovl.addLayout(wrow)
        panel.addRow(overlay)

        self._refresh_overlay_btn_colors()
```

- [ ] **Step 5: 颜色选择与色块刷新**

类内新增方法（`_set_status` 附近）：

```python
    def _pick_date_color(self):
        c = QColorDialog.getColor(QColor(*self._date_rgb), self, "日期颜色")
        if c.isValid():
            self._date_rgb = (c.red(), c.green(), c.blue())
            self._refresh_overlay_btn_colors()
            self._debounce.start()

    def _pick_wm_color(self):
        c = QColorDialog.getColor(QColor(*self._wm_rgb), self, "水印颜色")
        if c.isValid():
            self._wm_rgb = (c.red(), c.green(), c.blue())
            self._refresh_overlay_btn_colors()
            self._debounce.start()

    def _refresh_overlay_btn_colors(self):
        for btn, rgb in ((self.date_color_btn, self._date_rgb),
                         (self.wm_color_btn, self._wm_rgb)):
            btn.setStyleSheet(
                "background:rgb(%d,%d,%d);border:1px solid #888;" % rgb)
```

- [ ] **Step 6: `_params` 组装 TextSpec**

`_params()` 返回 dict 增两键（`"offset_pct": (...)` 之后）：

```python
            "date_overlay": TextSpec(
                enabled=self.date_enabled.isChecked(),
                font_key=self.date_font.currentData(),
                size_mm=float(self.date_size.value()),
                weight=self.date_weight.currentData(),
                corner=self.date_corner.currentData(),
                rgb=self._date_rgb, alpha=255),
            "watermark_overlay": TextSpec(
                enabled=self.wm_enabled.isChecked(),
                text=self.wm_text.text(),
                font_key=self.wm_font.currentData(),
                size_mm=float(self.wm_size.value()),
                weight=self.wm_weight.currentData(),
                corner=self.wm_corner.currentData(),
                rgb=self._wm_rgb,
                alpha=int(round(self.wm_alpha.value() / 100.0 * 255))),
```

- [ ] **Step 7: 控件变更接防抖**

`__init__` 里 `for w in (self.sheet_box, ...): _connect_param_changed(...)` 之后加：

```python
        for w in (self.date_font, self.date_size, self.date_weight,
                  self.date_corner, self.wm_font, self.wm_size,
                  self.wm_weight, self.wm_corner, self.wm_alpha):
            _connect_param_changed(w, self._debounce.start)
        for cb in (self.date_enabled, self.wm_enabled):
            cb.toggled.connect(lambda _: self._debounce.start())
        self.wm_text.textChanged.connect(lambda _: self._debounce.start())
```

- [ ] **Step 8: `append_photo` 存日期 + `_rebuild_job` 物化**

`append_photo` 成功分支 `self.pool.append({"path": str(path), "img": img})` 改为：

```python
        self.pool.append({"path": str(path), "img": img,
                          "date": jobs.photo_date_text(path)})
```

失败分支 `self.pool.append({"path": str(path), "img": None})` 改为：

```python
        self.pool.append({"path": str(path), "img": None, "date": None})
```

`_rebuild_job` 里 `rotations = [...]` 之后加 `date_texts` 物化，并把 `build_job(...)` 调用补三参：

```python
        date_texts = [None] * n
        for slot, pi in self.placements.items():
            if 0 <= slot < n and 0 <= pi < len(self.pool):
                date_texts[slot] = self.pool[pi].get("date")
```

```python
            self.job = jobs.build_job(self.st, photos, p["sheet_key"], p["cell_key"],
                                      gap_mm=p["gap_mm"], bleed_mm=p["bleed_mm"],
                                      mode=p["mode"], offset_pct=p["offset_pct"],
                                      rotations=rotations,
                                      date_overlay=p["date_overlay"],
                                      watermark_overlay=p["watermark_overlay"],
                                      date_texts=date_texts)
```

- [ ] **Step 9: 持久化 save/restore**

`save_last_job` 的 dict 增（`"pages": self._pages` 之前）：

```python
            "date_overlay": {"enabled": self.date_enabled.isChecked(),
                             "font_key": self.date_font.currentData(),
                             "size_mm": float(self.date_size.value()),
                             "weight": self.date_weight.currentData(),
                             "corner": self.date_corner.currentData(),
                             "rgb": list(self._date_rgb)},
            "watermark_overlay": {"enabled": self.wm_enabled.isChecked(),
                                  "text": self.wm_text.text(),
                                  "font_key": self.wm_font.currentData(),
                                  "size_mm": float(self.wm_size.value()),
                                  "weight": self.wm_weight.currentData(),
                                  "corner": self.wm_corner.currentData(),
                                  "rgb": list(self._wm_rgb),
                                  "alpha_pct": self.wm_alpha.value()},
```

`_restore_last_job` 末尾加回填（用既有 `_safe`/`_select_by_data`，坏形状降级默认）：

```python
        self._restore_overlay(job.get("date_overlay"), is_date=True)
        self._restore_overlay(job.get("watermark_overlay"), is_date=False)

    def _restore_overlay(self, d, is_date):
        if not isinstance(d, dict):
            return
        box = self.date_enabled if is_date else self.wm_enabled
        self._safe(lambda: box.setChecked(bool(d.get("enabled", False))))
        for key, cb in (("font_key", self.date_font if is_date else self.wm_font),
                        ("weight", self.date_weight if is_date else self.wm_weight),
                        ("corner", self.date_corner if is_date else self.wm_corner)):
            v = d.get(key)
            if v is not None:
                self._safe(lambda c=cb, val=v: self._select_by_data(c, val))
        size = self.date_size if is_date else self.wm_size
        if isinstance(d.get("size_mm"), (int, float)):
            self._safe(lambda b=size, v=float(d["size_mm"]): b.setValue(v))
        rgb = d.get("rgb")
        if isinstance(rgb, (list, tuple)) and len(rgb) == 3:
            if is_date:
                self._date_rgb = tuple(int(x) for x in rgb)
            else:
                self._wm_rgb = tuple(int(x) for x in rgb)
        if not is_date:
            if isinstance(d.get("text"), str):
                self._safe(lambda: self.wm_text.setText(d["text"]))
            if isinstance(d.get("alpha_pct"), (int, float)):
                self._safe(lambda: self.wm_alpha.setValue(int(d["alpha_pct"])))
        self._safe(self._refresh_overlay_btn_colors)
```

- [ ] **Step 10: 跑测试确认通过**

Run: `python -m pytest tests/test_app_main_window.py -k "overlay or text_spec or watermark or date" -q`
Expected: PASS（5 条）

- [ ] **Step 11: 变异验牙**

1. `_params` 里把 `watermark_overlay` 的 `alpha=int(...)` 写死 `alpha=255` → 无独立断言（本轮 app 不测 alpha 数值），改测：把 `date_overlay` 的 `enabled=` 写死 `False` → `test_rebuild_materializes_date_texts` 红。
2. `append_photo` 去掉 `"date": jobs.photo_date_text(path)`（改回无 date）→ `test_append_photo_stores_date_text` 红。
3. `_rebuild_job` 里 `date_texts` 全传 `None` → `test_rebuild_materializes_date_texts` 的 `date_texts[0] is not None` 红。
验后还原。
Run：`python -m pytest tests/test_app_main_window.py -k "overlay or text_spec or watermark or date" -q`
Expected：坏时 FAIL、还原后 PASS。

- [ ] **Step 12: 提交**

```bash
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
python -c "open('.superpowers/sdd/_overlay_t5_msg.txt','w',encoding='utf-8').write('app: 文字叠加控件（日期/水印）+ _params 组装 TextSpec + 日期物化 + 持久化回填\n')"; git add photoprint/app/main_window.py tests/test_app_main_window.py; git commit -F .superpowers/sdd/_overlay_t5_msg.txt
```

---

### Task 6: 全量回归 + 重打包收尾

**Files:**
- 无新增改动；验证 Task 1–5 未破坏既有渲染/放置/导出。

**Interfaces:**
- Consumes: Task 1–5 成品。
- Produces: 通过验证的 exe（`dist/PhotoPrint.exe`）。

- [ ] **Step 1: 全量回归**

Run: `python -m pytest tests/ -q`
Expected: 全部 PASS，`EXIT=0`。重点确认既有 `test_render_*`、`test_cli`、`test_jobs` 逐像素不变（默认参向后兼容）。

- [ ] **Step 2: 无 MUTATION-TEMP 残留自查**

Run: `$r = Select-String -Path photoprint/core/*.py,photoprint/jobs.py,photoprint/app/main_window.py,tests/*.py -Pattern 'MUTATION-TEMP'; echo "residue=$($r.Count)"`
Expected: `residue=0`

- [ ] **Step 3: 重打包**

Run: `powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 2>&1 | Select-Object -Last 3`
Expected: 末行 `OK 产物：…\dist\PhotoPrint.exe（…MB）`（管道 ExitCode 1 是 stderr 假象）。

- [ ] **Step 4: smoke 启动**

Run：
```powershell
$exe = Get-Item dist\PhotoPrint.exe; echo "age_min=$([math]::Round(((Get-Date)-$exe.LastWriteTime).TotalMinutes,2))"
$p = Start-Process -FilePath "dist\PhotoPrint.exe" -PassThru; Start-Sleep -Seconds 6
if (Get-Process -Id $p.Id -ErrorAction SilentlyContinue) { echo "SMOKE OK"; Stop-Process -Id $p.Id -Force } else { echo "SMOKE FAIL" }
```
Expected: `age_min` 接近 0 且 `SMOKE OK`。

- [ ] **Step 5: 交用户 exe 手测清单**

告知用户走查：① 勾日期标签→逐张在其所选角显示各自日期；② 勾水印→输入文字、半透明可调、位置可选；③ 改字号/颜色/字体/粗细即时更新预览；④ 日期与水印同开、各占一角互不干扰；⑤ 导出 PDF 与预览一致；⑥ 无 EXIF 图用文件日期、缺字体不崩。

---

## Self-Review

**1. Spec coverage：**
- spec §2 TextSpec/Corner/FONT_TABLE → Task 1；§2.3 draw_overlay（clip/加粗/透明度/超长/缺字体）→ Task 2。
- spec §3 render_page 新参 + 绘制时机 + 四角锚点 → Task 3（锚点公式在 Task 1 anchor_point）。
- spec §4 Job 字段/render 透传/build_job/photo_date_text → Task 4。
- spec §5 UI 控件/_params/append_photo 日期/_rebuild_job 物化/持久化/导出复用 → Task 5。
- spec §6 边界（缺字体/超长/无日期/空水印）→ Task 2/3/4 降级测试覆盖。
- spec §7 测试策略与变异 → 各任务 Step1/Step5 覆盖。
- spec §8 验收 → Task 6。

**2. Placeholder scan：** 无 TBD/TODO；每步含完整代码与命令。通过。

**3. Type consistency：** `TextSpec` 字段名（enabled/text/font_key/size_mm/weight/corner/rgb/alpha/margin_pct）在 Task 1 定义、Task 3/5 使用一致；`draw_overlay(page, cell_rect_px, spec, text, dpi)` 签名 Task 2 定义、Task 3 调用一致；`render_page` 新参名 `date_overlay/watermark_overlay/date_texts` Task 3 定义、Task 4 `Job.render` 传参一致；`build_job` 新参 Task 4 定义、Task 5 调用一致；`photo_date_text` Task 4 定义、Task 5 `append_photo` 调用一致；控件属性名 `date_*/wm_*` 与 `_date_rgb/_wm_rgb` Task 5 内部一致。通过。
