# PhotoPrint 图形界面与单文件 exe 实现计划（M3-GUI）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给已完成的打印内核加一层 PySide6 单窗口表单界面，让用户选图、选纸张/格子/模式、看整页预览、一键导出等尺寸 PDF，并把它打包成单文件 `PhotoPrint.exe`。

**Architecture:** 三层单向依赖不变（`core/` 纯函数 ← `win/` Windows 打印 ← 新增 `jobs.py` 编排 ← 新增 `app/` 界面）。`jobs.py` 是从 `cli.py` 抽出的共用编排，CLI 与 GUI 共用同一真相源，因此两边输出必然一致。本次唯一的几何改动是裁切偏移的透传与旋转格落位映射由转置改为真旋转。

**Tech Stack:** Python 3.13、PySide6 6.10（界面）、Pillow（渲染）、img2pdf（PDF）、pytest（测试）、PyInstaller（打包，仅构建期）。

**Spec:** `docs/superpowers/specs/2026-11-04-photoprint-gui-exe-design.md`

## Global Constraints

每个任务的隐含前提，逐条来自 spec，数值一律照抄不得改：

- `photoprint/core/**` 禁止 import `PySide6`、`win32print`、`win32ui`、`win32con`。
- `photoprint/jobs.py` 除上述禁则外，**禁止 `print`**：`--windowed` 打包后 `sys.stdout is None`。
- `photoprint/app/**` 不得出现 mm↔像素换算与裁切几何；数值一律经 `core/units`、`core/crop`。
- mm↔px 的唯一换算是 `ppmm = dpi / 25.4`（`core/units.py`），取整一律走 `units.round_px`。
- `cli.py` 重构后**输出文案与 return code 逐字不变**，现有 145 项测试必须保持全绿。
- 导出路径（GUI 的 PDF、CLI 的 `--out`/`--pdf`）`show_mask=False`；`render_page` 的 `show_mask` 默认值仍为 `True` 不改。
- 预览 `dpi=96` 且 `show_mask=True`；输出 dpi 默认 `300`；裁切微调端点 `±50%`；参数防抖 `250ms`；exe 名 `PhotoPrint`。
- 界面文案：`bleed_trim` 必须显示"需人工裁切"，不得写"无边距打印"；`fill_printable` 不得写"铺满整张纸"；`margin_source == "spec"` 时必须显示"依规格推定，未经真机校准"。
- 测试不引入 `pytest-qt`，Qt 相关测试用 `QT_QPA_PLATFORM=offscreen` 手工驱动。
- 代码注释一律中文。需要真机或手工比对的脚本进 `_lab/`，其输出进 `_lab/out/`。
- 直接 import 的运行时包必须在 `requirements.txt` 显式声明；PyInstaller 不被 import，写进新建的 `requirements-build.txt`。

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `photoprint/core/crop.py` | Modify | 新增 `rotate_offset`：纸面偏移 → 旋转前偏移 |
| `photoprint/core/render.py` | Modify | 新增 `place_rotated_dest` 纯函数；`render_page` 透传 `offset_pct`（逐格换算） |
| `photoprint/jobs.py` | Create | 共用编排：`build_layout` / `Job` / `build_job` / `render_all` / `load_photo` |
| `photoprint/cli.py` | Modify | 变薄为调用 `jobs`；新增 `--mask`；导出默认关遮罩 |
| `photoprint/core/store.py` | Modify | 新增 `get_last_job` / `set_last_job` |
| `photoprint/app/__init__.py` | Create | 包声明 |
| `photoprint/app/worker.py` | Create | 子线程执行渲染任务，异常转信号 |
| `photoprint/app/view.py` | Create | PIL Image → QPixmap 的唯一转换 |
| `photoprint/app/main_window.py` | Create | 控件、防抖、预览、状态栏、导出 |
| `photoprint/app/crashlog.py` | Create | 崩溃日志路径与双异常钩子 |
| `photoprint/app/__main__.py` | Create | exe/`python -m` 入口 |
| `tests/conftest.py` | Create | offscreen 平台变量 |
| `tests/test_crop_offset.py` | Create | T1 测试 |
| `tests/test_render_offset.py` | Create | T2 测试 |
| `tests/test_jobs.py` | Create | T3 测试 |
| `tests/test_cli.py` | Modify | T4 追加遮罩断言 |
| `tests/test_store.py` | Modify | T5 追加 last_job 断言 |
| `tests/test_app_worker.py` / `test_app_view.py` / `test_app_main_window.py` / `test_app_crashlog.py` | Create | T6–T8 测试 |
| `requirements-build.txt` / `build_exe.ps1` / `_lab/check_exe.ps1` | Create | T9 打包与验收 |
| `README.md` / `.gitignore` | Modify | T9 文档与产物忽略 |

---

### Task 1: 纸面偏移 → 旋转前偏移的换算函数

**Files:**
- Modify: `photoprint/core/crop.py`（在 `cell_crop_box` 之后追加）
- Test: `tests/test_crop_offset.py`（Create）

**Interfaces:**
- Consumes: 无
- Produces: `crop.rotate_offset(ox_mm: float, oy_mm: float) -> tuple[float, float]`

旋转格按 `Image.ROTATE_270`（顺时针 90°）落位，纸面坐标与旋转前满足 `x' = H-(y+h)`、`y' = x`。
因此纸面"向右"对应旋转前的 `y` 轴**负**方向。界面偏移是纸面语义，必须在进 `cell_crop_box` 之前换算。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_crop_offset.py`：

```python
"""裁切偏移的轴向语义：界面偏移是纸面方向，crop 吃的是旋转前方向。"""
from photoprint.core import crop


def test_rotate_offset_maps_paper_axes_to_pre_rotation_axes():
    """纸面右 2mm / 下 5mm → 旋转前 (上 -2mm, 右 5mm) 的等价写法。"""
    assert crop.rotate_offset(2.0, 5.0) == (5.0, -2.0)


def test_rotate_offset_is_identity_at_zero():
    assert crop.rotate_offset(0.0, 0.0) == (0.0, 0.0)


def test_rotate_offset_accepts_ints_and_returns_floats():
    got = crop.rotate_offset(1, 2)
    assert got == (2.0, -1.0)
    assert all(isinstance(v, float) for v in got)
```

- [ ] **Step 2: 跑到失败**

Run: `python -m pytest tests/test_crop_offset.py -v`
Expected: FAIL — `AttributeError: module 'photoprint.core.crop' has no attribute 'rotate_offset'`

- [ ] **Step 3: 最小实现**

在 `photoprint/core/crop.py` 末尾追加：

```python
def rotate_offset(ox_mm, oy_mm):
    """纸面方向偏移 → 旋转前坐标系偏移，返回 (dx_pre, dy_pre)。

    旋转格按顺时针 90°（Image.ROTATE_270）落位，纸面与旋转前满足
    x' = H-(y+h)、y' = x：纸面向右对应旋转前 y 轴负方向，纸面向下对应
    旋转前 x 轴正方向。界面上的偏移是纸面语义，必须在进 cell_crop_box
    之前换算，否则旋转格的水平微调会整体反号。
    """
    return float(oy_mm), -float(ox_mm)
```

- [ ] **Step 4: 跑到通过**

Run: `python -m pytest tests/test_crop_offset.py -v`
Expected: 3 passed

- [ ] **Step 5: 全量回归 + 提交**

```bash
python -m pytest tests/ -q
git add tests/test_crop_offset.py photoprint/core/crop.py
git commit -m "feat(core): 纸面裁切偏移换算 rotate_offset"
```

---

### Task 2: 渲染层透传偏移，旋转落位改真旋转映射

**Files:**
- Modify: `photoprint/core/render.py`（`render_page` 签名与旋转段落）
- Test: `tests/test_render_offset.py`（Create）

**Interfaces:**
- Consumes: `crop.rotate_offset`（T1）、`crop.cell_crop_box` 的既有 `dx_mm/dy_mm` 形参
- Produces: `render.place_rotated_dest(dest_mm, target_h_mm) -> tuple[float, float, float, float]`；
  `render.render_page(..., offset_pct: tuple[float, float] = (0.0, 0.0))`；
  `render.offset_mm_for_cell(offset_pct, w_mm, h_mm) -> tuple[float, float]`

偏移的纸面语义要在两种模式下都成立，而 `crop.cell_crop_box` 对 `dx_mm/dy_mm` 的用法
并不相同（实测：FILL 挪的是取景窗 `crop_px`，dest 不变；FIT 挪的是 `dest_mm`）。同一
个纸面 +1mm 在 FILL 下画面会往**左**走。因此渲染层必须按生效的裁切模式补一次反号：
FILL（含 `bleed_trim`，它的 `crop_mode` 也是 fill）取负，fit 不取负。

`render_page` 交的是百分比而不是页级 mm 偏移（T3 评审 I-1，用户裁决）：同一页可能
两种朝向混排（bands 装箱），“按哪个尺寸换算”是逐格决策，只有渲染层手里有每格的内框。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_render_offset.py`：

```python
"""偏移透传与旋转落位映射。旋转映射必须与旧转置在居中时逐像素等价。"""
import pytest

pytest.importorskip("PIL", reason="需要 Pillow")

from PIL import Image  # noqa: E402

from photoprint.core import modes, pack, render, specs  # noqa: E402

DPI = 25.4  # 1 像素 = 1 毫米，便于直接按 mm 取点


def _a4_id1_plan():
    a4, id1 = specs.find_spec("A4"), specs.find_spec("ID1")
    return a4, pack.pack(a4, id1, gap_mm=2.0, allow_rotate=False,
                         printable=specs.printable_rect(a4))


def test_place_rotated_dest_equals_transpose_when_centered():
    """居中回归锁：旋转前目标高 100、画面高 40 居中 → dy=30，
    真旋转映射给 x'=30，与旧转置 (dy,dx,dh,dw) 完全相同。"""
    got = render.place_rotated_dest((10.0, 30.0, 60.0, 40.0), 100.0)
    assert got == pytest.approx((30.0, 10.0, 40.0, 60.0))


def test_place_rotated_dest_flips_horizontal_when_off_center():
    """偏上落位（dy=10 < 居中值 30）在纸面上必须靠右，
    旧转置会给出 x'=10（靠左），方向整体反。"""
    got = render.place_rotated_dest((10.0, 10.0, 60.0, 40.0), 100.0)
    assert got[0] == pytest.approx(50.0)


def test_dy_offset_moves_picture_down_on_paper():
    a4, plan = _a4_id1_plan()
    photo = Image.new("RGB", (100, 100), (255, 0, 0))
    cell = plan.cells[0]
    ix, iy, iw, ih = cell.inner_mm()
    # 正方形照片进 25×32 的格：宽填满、上下各留白 (32-25)/2 = 3.5mm
    base = render.render_page(plan, [photo] * plan.count, a4, DPI,
                              modes.FIT_TO_PRINTABLE, show_mask=False)
    moved = render.render_page(plan, [photo] * plan.count, a4, DPI,
                               modes.FIT_TO_PRINTABLE, show_mask=False,
                               offset_pct=(0.0, 100.0 * 1.0 / ih))  # 纸面下移 1mm
    probe = (int(ix + iw / 2), int(iy + 4.0))
    assert base.getpixel(probe) == (255, 0, 0)      # 原画面覆盖
    assert moved.getpixel(probe) == (255, 255, 255)  # 下移 1mm 后露白
    tail = (int(ix + iw / 2), int(iy + 29.0))
    assert base.getpixel(tail) == (255, 255, 255)
    assert moved.getpixel(tail) == (255, 0, 0)


def test_dx_offset_moves_rotated_cell_picture_right_on_paper():
    """旋转格的纸面水平偏移必须真往右：旧转置写法会整体反号（终审 C1）。

    A4+4R 两格都是旋转格；正方形照片 FIT 进旋转前目标后是 102×102，
    在纸面格内左右各留白，起点 x = 格左沿 + (格宽 - 格高)/2。
    探针取起点内 1mm 与右沿外 1mm，偏移 3mm 后两者必须恰好互换。
    """
    a4, r4 = specs.find_spec("A4"), specs.find_spec("4R")
    plan = pack.pack(a4, r4, gap_mm=0.0, allow_rotate=True,
                     printable=specs.printable_rect(a4))
    assert [c.rotated for c in plan.cells] == [True, True]
    cx, cy, cw, ch = plan.cells[0].inner_mm()
    start = int(round(cx + (cw - ch) / 2.0))
    y_mid = int(round(cy + ch / 2.0))
    inside = (start + 1, y_mid)          # 原画面内、右移 3mm 后露白
    outside = (start + ch + 1, y_mid)    # 原留白、右移 3mm 后被覆盖
    photo = Image.new("RGB", (100, 100), (255, 0, 0))
    args = (plan, [photo] * plan.count, a4, DPI, modes.FIT_TO_PRINTABLE)
    pct = (100.0 * 3.0 / cw, 0.0)        # 纸面向右 3mm
    base = render.render_page(*args, show_mask=False)
    moved = render.render_page(*args, show_mask=False, offset_pct=pct)
    assert base.getpixel(inside) == (255, 0, 0), f"起点前提已破：{inside} 应为红"
    assert moved.getpixel(inside) == (255, 255, 255), (
        f"纸面向右 3mm 后 {inside} 应露白（仍为红 = 没动或反向）")
    assert base.getpixel(outside) == (255, 255, 255), f"起点前提已破：{outside} 应为白"
    assert moved.getpixel(outside) == (255, 0, 0), (
        f"纸面向右 3mm 后 {outside} 应转红（仍为白 = 方向反了）")


def test_fill_mode_offset_moves_picture_toward_paper_direction():
    """FILL 的 dx/dy 在 crop 里挪的是取景窗，画面在纸面上反向；
    界面偏移是纸面语义，渲染层须按模式补一次反号。"""
    a4, plan = _a4_id1_plan()
    photo = Image.new("RGB", (200, 100), (255, 255, 255))
    photo.paste(Image.new("RGB", (40, 100), (255, 0, 0)), (80, 0))  # 中央红带
    ix, iy, iw, ih = plan.cells[0].inner_mm()
    y = int(iy + ih / 2)
    args = (plan, [photo] * plan.count, a4, DPI, modes.FILL_PRINTABLE)
    low = render.render_page(*args, show_mask=False,
                             offset_pct=(-100.0 * 3.0 / iw, 0.0))
    high = render.render_page(*args, show_mask=False,
                              offset_pct=(100.0 * 3.0 / iw, 0.0))

    def first_red(page):
        cols = [x for x in range(int(ix), int(ix + iw))
                if page.getpixel((x, y)) == (255, 0, 0)]
        assert cols, "红带不在首格内，测试前提已破"
        return min(cols)

    moved_by = first_red(high) - first_red(low)
    assert moved_by >= 1, f"dx 为正应使画面往纸面右边走，实际差 {moved_by}px"


def test_offset_pct_is_applied_per_cell_on_mixed_orientation_page():
    """混合朝向页（7R+3R 的 bands 装箱）：偏移必须逐格按本格尺寸换算。

    首格是转置格（纸面 127×89），第二格是竖格（89×127），整纸高 254。
    offset_pct=(0, 8) 下三种假设会算出不同的顶沿（实测留白夹持上限 19mm）：

    - 按本格高 127 算：10.16mm → 顶沿 136（正确答案）
    - 按首格高 89 算：7.12mm → 顶沿 133
    - 按整纸高 254 算：20.32mm → 夹到 19 → 顶沿 145

    两个探针各挡一支：y=135 区分“本格 vs 首格”，y=140 区分“本格 vs 整纸”——
    只用一个点的话，拿纸张尺寸当格子尺寸的写法会和逐格换算长得一模一样。
    """
    sheet, cell = specs.find_spec("7R"), specs.find_spec("3R")
    plan = pack.pack(sheet, cell, gap_mm=0.0, allow_rotate=True,
                     printable=specs.printable_rect(sheet))
    assert [c.rotated for c in plan.cells] == [True, False, False]
    bx, by, bw, bh = plan.cells[1].inner_mm()
    photo = Image.new("RGB", (100, 100), (255, 0, 0))
    args = (plan, [photo] * plan.count, sheet, DPI, modes.FIT_TO_PRINTABLE)
    base = render.render_page(*args, show_mask=False)
    moved = render.render_page(*args, show_mask=False, offset_pct=(0.0, 8.0))
    col = int(bx + bw / 2)
    above = (col, int(by + 28.0))     # y=135：本格算已露白，首格算仍红
    below = (col, int(by + 33.0))     # y=140：本格算仍红，整纸算露白
    assert base.getpixel(above) == (255, 0, 0), f"零偏移前提已破：{above} 应为红"
    assert base.getpixel(below) == (255, 0, 0), f"零偏移前提已破：{below} 应为红"
    assert moved.getpixel(above) == (255, 255, 255), (
        f"偏移按首格高 89mm 算了（只挠到顶沿 133，{above} 仍为红），"
        f"应按本格高 {bh:.0f}mm 算到 136")
    assert moved.getpixel(below) == (255, 0, 0), (
        f"偏移按整纸高 {sheet.h_mm:.0f}mm 算了（夹到 19mm→顶沿 145，"
        f"{below} 成白），应按本格高 {bh:.0f}mm 算到 136")


def test_offset_mm_for_cell_half_page_is_50_pct():
    """±50% 就是半格：ID1 内框 25×32 → 12.5 / 16.0mm。"""
    assert render.offset_mm_for_cell((50.0, -50.0), 25.0, 32.0) == (12.5, -16.0)


def test_offset_mm_for_cell_zero_is_zero():
    assert render.offset_mm_for_cell((0.0, 0.0), 89.0, 127.0) == (0.0, 0.0)
```

- [ ] **Step 2: 跑到失败**

Run: `python -m pytest tests/test_render_offset.py -v`
Expected: FAIL — 前两条 `AttributeError: ... has no attribute 'place_rotated_dest'`；
中间四条（透传偏移的像素测试）`TypeError: render_page() got an unexpected
keyword argument 'offset_pct'`；后两条 `AttributeError: ... 'offset_mm_for_cell'`

- [ ] **Step 3: 加纯函数并改签名**

在 `photoprint/core/render.py` 的 `intersect_mm` 之后插入：

```python
def place_rotated_dest(dest_mm, target_h_mm):
    """旋转前落位 → 纸面落位：顺时针 90° 时 x' = H-(y+h)，y' = x。

    旧写法 `dx, dy, dw, dh = dy, dx, dh, dw` 是转置，只在落位居中时与真旋转
    等价；一旦有裁切偏移，水平方向会整体反号（终审对旋转落位的补充说明）。
    """
    dx, dy, dw, dh = dest_mm
    return ((target_h_mm - dh) - dy, dx, dh, dw)
```

紧接其后再加一个换算入口（界面只能交百分比，不得自己算 mm）：

```python
def offset_mm_for_cell(offset_pct, w_mm, h_mm):
    """百分比偏移 → 该格的 mm 偏移：±50% 即最多挪半格。

    换算本体留在 core：界面层禁做几何，而“按哪个尺寸换算”本身就是几何决策。
    必须逐格调用（拿本格尺寸），同一页两种朝向的格子若不逐格算，±50% 就只对
    算出的那一格成立（T3 评审 I-1）。
    """
    return (offset_pct[0] / 100.0 * w_mm, offset_pct[1] / 100.0 * h_mm)
```

把 `render_page` 的签名改为（只加一个参数，其余不动）：

```python
def render_page(plan, photos, sheet, dpi, mode, show_mask=True,
                show_cut_lines=True, borderless_active=False,
                offset_pct=(0.0, 0.0)):
```

把循环里从 `target_w, target_h` 到转置那一段替换为：

```python
        target_w, target_h = (oh, ow) if cell.rotated else (ow, oh)
        # 偏移是纸面语义且按本格尺寸逐格换算；旋转格还要再换算到旋转前坐标
        cell_dx, cell_dy = offset_mm_for_cell(offset_pct, ow, oh)
        in_dx, in_dy = crop.rotate_offset(cell_dx, cell_dy) if cell.rotated \
            else (cell_dx, cell_dy)
        if cm == crop.FILL:
            # FILL 的 dx/dy 挪的是取景窗，画面在纸面上会反向；fit 挪的是
            # 落位矩形，本身已是纸面语义，故只在 fill 档补一次反号
            in_dx, in_dy = -in_dx, -in_dy
        pl = crop.cell_crop_box(photo.width, photo.height, target_w, target_h,
                               cm, dx_mm=in_dx, dy_mm=in_dy,
                               ppmm=units.ppmm(dpi))
        piece = photo.crop(pl.crop_px)
        # 旋转格还要把落位换轴：照片转 90° 后宽高互换，若沿用旋转前的
        # (dx, dy)，尺寸检查会拿错轴、缩放补偿到错误的 (w, h)，画面会撑出
        # 格子并压到邻格（终审 C1 实测），映射见 place_rotated_dest
        if cell.rotated:
            piece = piece.transpose(Image.ROTATE_270)
            dx, dy, dw, dh = place_rotated_dest(pl.dest_mm, target_h)
        else:
            dx, dy, dw, dh = pl.dest_mm
```

同时删掉原来那段"这是「转置」而非通用 90° 旋转映射"的行内注释，并把旧写法
留下的 `dx, dy, dw, dh = ...` 重复赋值改成上面的 if/else 形态（T2 评审 Minor1）。

- [ ] **Step 4: 跑到通过**

Run: `python -m pytest tests/test_render_offset.py -v`
Expected: 8 passed

- [ ] **Step 5: 全量回归 + 本机证据**

```bash
python -m pytest tests/ -q
python _lab/m1m2_check.py
```
Expected: 测试全绿；`m1m2_check` 仍 12 条全 OK、exit 0（它直接调 `render_page`，偏移默认 0 不改变既有像素结果）。

- [ ] **Step 6: 提交**

```bash
git add tests/test_render_offset.py photoprint/core/render.py
git commit -m "feat(core): 渲染层透传裁切偏移，旋转落位改真旋转映射"
```

---

### Task 3: 共用编排层 `jobs.py`

**Files:**
- Create: `photoprint/jobs.py`
- Test: `tests/test_jobs.py`（Create）

**Interfaces:**
- Consumes: `core/{specs,pack,modes,render}`、`store.Store.resolve`
- Produces:
  - `jobs.build_layout(st, sheet_key, cell_key, gap_mm, bleed_mm, mode, borderless_active=False) -> tuple[LayoutPlan, str]`
  - `jobs.Job`（dataclass：`plan / mode / sheet / photos / offset_pct / borderless_active`，
    属性 `count / page_count / note`，方法 `render(page_index, dpi, show_mask=False)`）
    —— 偏移只存 `offset_pct`，不存页级 mm（逐格换算在 core，T3 评审 I-1）
  - `jobs.build_job(st, photos, sheet_key, cell_key, *, gap_mm=0.0, bleed_mm=3.0, mode=None, offset_pct=(0.0, 0.0), borderless_active=False) -> Job`
  - `jobs.render_all(job, dpi, show_mask=False) -> list[Image]`
  - `jobs.load_photo(path) -> Image`（从 `cli.py` 搬来）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_jobs.py`：

```python
"""编排层必须与重构前的 cli 逐字段等价，且不含 print/GUI 依赖。"""
import inspect
import sys

import pytest

pytest.importorskip("PIL", reason="需要 Pillow")

from PIL import Image  # noqa: E402

from photoprint import cli, jobs  # noqa: E402
from photoprint.core import modes, render, specs, store  # noqa: E402


@pytest.fixture
def st(tmp_path):
    s = store.Store(tmp_path / "papers.json")
    s.load()
    return s


def _photos(n, color=(200, 30, 30)):
    return [Image.new("RGB", (100, 100), color) for _ in range(n)]


@pytest.mark.parametrize("sheet,cell,gap,bleed,mode,borderless", [
    ("A4", "3R", 0.0, modes.DEFAULT_BLEED_MM, None, False),
    ("A4", "ID1", 2.0, modes.DEFAULT_BLEED_MM, None, False),
    ("A4", "4R", 0.0, modes.DEFAULT_BLEED_MM, None, False),
    ("3R", "3R", 0.0, 0.0, modes.FILL_PRINTABLE, False),
    # 无边距实测生效是另一条排版分支（可打印区换成整张纸），也得对拍
    ("A4", "4R", 0.0, modes.DEFAULT_BLEED_MM, None, True),
])
def test_build_layout_matches_legacy_cli(st, sheet, cell, gap, bleed, mode,
                                         borderless):
    """与重构前的 cli 逐字段对拍：这一层是搬过来的，必须证明没搬坏。

    Task 4 把 cli 改成薄转发之后，这里会退化成自己比自己，届时换成绝对格数
    断言（见计划 Task 4 Step 4）；本 commit 里两边仍是两份实现，对拍是真对拍。
    """
    plan_a, mode_a = cli.build_plan_jobs(st, sheet, cell, gap, bleed, mode,
                                         borderless)
    plan_b, mode_b = jobs.build_layout(st, sheet, cell, gap, bleed, mode,
                                       borderless_active=borderless)
    assert mode_a == mode_b
    assert plan_a == plan_b  # dataclass 逐字段相等


def test_build_layout_rejects_cell_larger_than_sheet_with_same_message(st):
    """报错分支也要对拍：文案是用户唯一能看见的出口，漂了就没人知道为何失败。

    卡片纸（91×55）在出血档装不下带 3mm 出血的美国签证（57×57 > 55），
    且出血档不走“整纸一格”退化分支，是预设组合里真能走到的报错。

    与 `test_build_layout_matches_legacy_cli` 同一命运：Task 4 后换成整句断言。
    """
    with pytest.raises(ValueError) as ea:
        cli.build_plan_jobs(st, "CARD", "USVISA", 0.0,
                            modes.DEFAULT_BLEED_MM, modes.BLEED_TRIM, False)
    with pytest.raises(ValueError) as eb:
        jobs.build_layout(st, "CARD", "USVISA", 0.0, modes.DEFAULT_BLEED_MM,
                          modes.BLEED_TRIM, borderless_active=False)
    assert str(ea.value) == str(eb.value)
    assert "放不下" in str(eb.value)


def test_build_job_counts_pages(st):
    job = jobs.build_job(st, _photos(5), "A4", "3R", bleed_mm=3.0)
    assert job.count == 4
    assert job.page_count == 2


def test_build_job_page_count_is_one_when_empty(st):
    """界面允许零照片：预览要有一张空格可看，不得除零或返回 0 页。"""
    job = jobs.build_job(st, [], "A4", "3R", bleed_mm=3.0)
    assert job.page_count == 1


def test_note_bleed_states_cut_action_and_provenance(st):
    """出血档也得说清边距从哪来：全局约束对 margin_source 的点名是无条件的，
    而出血档的预览仍在按规格边距画不可印遮罩——界面正在用一组没证据的数字。"""
    job = jobs.build_job(st, _photos(4), "A4", "3R", bleed_mm=3.0)
    assert job.mode == modes.BLEED_TRIM  # 前提：默认映射确实落到裁切档
    assert job.note.startswith("需人工裁切：沿灰线切开后即为 89×127mm 成品")
    assert job.note.endswith("（边距依规格推定，未经真机校准）")


def test_note_bleed_provenance_follows_margin_source(st):
    """来源换了出血档文案也得跟着换，否则分档表成了只对白边档生效的摆设。"""
    st.override_margins("A4", specs.Margins(3.0, 5.0, 3.4, 3.4), "calibrated")
    job = jobs.build_job(st, _photos(4), "A4", "3R", bleed_mm=3.0)
    # 钉整括号而不是“真机校准”四个字：spec 档那句也含这四个字
    assert job.note.endswith("（边距已经真机校准）")
    assert "依规格推定" not in job.note


def test_note_spec_source_says_unproven(st):
    """全局约束点名的一句：margin_source=spec 时必须逐字出现该文案。"""
    job = jobs.build_job(st, _photos(4), "A4", "ID1", gap_mm=2.0)
    assert job.sheet.margin_source == "spec"  # 前提：开发期常态
    assert "（边距依规格推定，未经真机校准）" in job.note
    assert "上3.0/下5.0/左3.4/右3.4mm" in job.note  # 数字不得丢


def test_note_probed_source_says_driver_measured(st):
    st.override_margins("A4", specs.Margins(3.0, 5.0, 3.4, 3.4), "probed")
    job = jobs.build_job(st, _photos(4), "A4", "ID1", gap_mm=2.0)
    assert "边距已由驱动实测" in job.note
    assert "未经真机校准" not in job.note  # 已实测就不许再说不确定


def test_note_calibrated_source_says_machine_calibrated(st):
    st.override_margins("A4", specs.Margins(3.0, 5.0, 3.4, 3.4), "calibrated")
    job = jobs.build_job(st, _photos(4), "A4", "ID1", gap_mm=2.0)
    # 钉整括号而不是"真机校准"四个字：光说“未经真机校准”也含这四个字
    assert "（边距已经真机校准）" in job.note
    assert "未经" not in job.note and "依规格推定" not in job.note


def test_note_unknown_margin_source_falls_back_to_most_conservative(st):
    """手改的 papers.json 可能交来历不明的来源；凭空说"实测"就是谎报。"""
    st.raw["overrides"]["A4"] = {
        "margins_mm": {"top": 3.0, "bottom": 5.0, "left": 3.4, "right": 3.4},
        "margin_source": "guessed",
    }
    job = jobs.build_job(st, _photos(4), "A4", "ID1", gap_mm=2.0)
    assert "依规格推定，未经真机校准" in job.note


def test_render_out_of_range_raises(st):
    job = jobs.build_job(st, _photos(4), "A4", "3R", bleed_mm=3.0)
    with pytest.raises(IndexError, match="页码越界"):
        job.render(1, 25.4)


def test_offset_changes_rendered_pixels(st):
    a = jobs.build_job(st, _photos(4), "A4", "ID1", gap_mm=2.0)
    b = jobs.build_job(st, _photos(4), "A4", "ID1", gap_mm=2.0,
                       offset_pct=(0.0, 50.0))
    assert a.render(0, 25.4).tobytes() != b.render(0, 25.4).tobytes()


def test_build_job_passes_percentage_through_without_converting(st, monkeypatch):
    """编排层不得自己换算成 mm：±50% 必须原样送到 core，逐格按本格尺寸换算。

    本层只按首格换算的话，混合朝向页上其余格的偏移会失真（T3 评审 I-1），
    而界面交来的百分比本身是与格子无关的量。 spy 只拦一层，真渲染照跑。
    """
    seen = {}
    real = render.render_page

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(render, "render_page", spy)
    job = jobs.build_job(st, _photos(4), "A4", "ID1", gap_mm=2.0,
                         offset_pct=(50.0, -50.0))
    job.render(0, 25.4)
    assert job.offset_pct == (50.0, -50.0)
    assert seen["offset_pct"] == (50.0, -50.0)


def test_render_all_covers_every_page(st):
    job = jobs.build_job(st, _photos(5), "A4", "3R", bleed_mm=3.0)
    pages = jobs.render_all(job, 25.4)
    assert len(pages) == 2


def test_jobs_module_has_no_print_and_no_gui():
    """窗口化打包后 sys.stdout 是 None；jobs 一旦被输出污染就会崩。

    注：这是“源码不含某字样”的守门断言，所以 jobs 的注释也不得写出
    被禁模块的名字，否则测试自己打自己。字样拦不住别名与 logging，
    真正兜住它的是下面那条把 sys.stdout 设为 None 的行为断言。
    """
    src = inspect.getsource(jobs)
    assert "print(" not in src
    for banned in ("PySide6", "win32print", "win32ui", "win32con"):
        assert banned not in src


def test_jobs_stay_silent_when_stdout_is_unavailable(st, monkeypatch):
    """--windowed 下 sys.stdout 真的是 None：编排层写一句就 AttributeError。

    行为断言而不是文本扫描：logging/traceback.print_exc/别名转发都绕得过扫描。
    """
    monkeypatch.setattr(sys, "stdout", None)
    job = jobs.build_job(st, _photos(5), "A4", "3R", bleed_mm=3.0)
    assert job.note
    assert len(jobs.render_all(job, 25.4)) == 2
```

- [ ] **Step 2: 跑到失败**

Run: `python -m pytest tests/test_jobs.py -v`
Expected: FAIL — 收集阶段就错。测试写的是 `from photoprint import cli, jobs`，
子模块缺失时 Python 抛的是 `ImportError: cannot import name 'jobs' from 'photoprint'`
（不是 `ModuleNotFoundError`，同一回事：模块还不存在）

- [ ] **Step 3: 写 `photoprint/jobs.py`**

```python
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
        m = self.sheet.margins
        return (f"将保留白边：上{m.top}/下{m.bottom}/左{m.left}/右{m.right}mm"
                f"（边距{provenance}）")

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
```

- [ ] **Step 4: 跑到通过**

Run: `python -m pytest tests/test_jobs.py -v`
Expected: 20 passed（parametrize 5 条 + 其余 15 条）

- [ ] **Step 5: 全量回归 + 提交**

```bash
python -m pytest tests/ -q
git add photoprint/jobs.py tests/test_jobs.py
git commit -m "feat: 抽出 jobs 共用编排层（build_layout/Job/build_job/render_all）"
```

---

### Task 4: CLI 变薄、导出关遮罩、新增 `--mask`

**Files:**
- Modify: `photoprint/cli.py`
- Modify: `tests/test_jobs.py`（退役与 cli 的对拍测试，见 Step 4）
- Test: `tests/test_cli.py`（追加 4 条）

**Interfaces:**
- Consumes: `jobs.build_layout` / `jobs.build_job` / `jobs.render_all` / `jobs.load_photo`
- Produces: `cli.build_plan_jobs(...)` 与 `cli.load_photo(path)` 保持历史签名不变（薄转发）

- [ ] **Step 1: 写失败测试**

先把一个隔离 fixture 插到 `tests/test_cli.py` 的 `st` fixture 之后（autouse）：
`cli.main` 自己 `store.Store()`，吃的是 `%APPDATA%\PhotoPrint\papers.json`，
不隔离的话测试钉的边距数字就取决于开发机上那份配置——界面一旦跑过驱动实测
并 `override_margins + save()`（写的就是同一个文件），pytest 会因为与本改动
无关的原因变红：

```python
@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """cli.main 自己 new `store.Store()`，吃的是默认配置路径（%APPDATA%）。

    不隔离的话测试钉的边距数字与遮罩带宽度就取决于开发机上那份 papers.json：
    界面一旦跑过驱动实测并 override_margins + save()（写的就是同一个文件），
    pytest 会因与本改动无关的原因变红。`Store.__init__` 在调用时才读模块全局，
    所以 patch 该变量就能顶住。
    """
    monkeypatch.setattr(store, "DEFAULT_PATH", tmp_path / "papers.json")
```

再在文件末尾追加：

```python
def _four_red_photos(tmp_path):
    from PIL import Image

    photos = []
    for i in range(4):
        p = tmp_path / f"{i}.jpg"
        Image.new("RGB", (400, 200), (255, 0, 0)).save(p)
        photos.append(str(p))
    return photos


def test_main_out_png_has_no_unprintable_mask(tmp_path):
    """遮罩是界面诚实性用的，导出进相纸就是缺陷。

    探针取 (1, ·) / (·, 1)：A4 的左/上边距是 3.4/3.0mm，dpi 25.4 下遮罩带
    只覆盖 0..2 像素（矩形右下角减 1），取 x=3 会探到带外——带外本来就是白的，
    这条测试就会无论如何都绿，遮罩没关也报不了。顶缘探针取 w//4 而不是 w//2：
    A4+3R 的列缝正好在 105mm（= w//2），虽当前从格上沿起画填不到 y=1，但也不必
    把像素断言寄在切缝长度规则上。
    """
    from PIL import Image

    out = tmp_path / "page.png"
    code = cli.main(["--photos", *_four_red_photos(tmp_path), "--sheet", "A4",
                     "--cell", "3R", "--dpi", "25.4", "--out", str(out)])
    assert code == 0
    img = Image.open(out)
    w, h = img.size
    assert img.getpixel((1, h // 4)) == (255, 255, 255), "左缘不得有灰遮罩带"
    assert img.getpixel((w // 4, 1)) == (255, 255, 255), "上缘不得有灰遮罩带"


def test_main_mask_flag_keeps_mask(tmp_path):
    """默认关不等于删功：调试时 `--mask` 必须还能把遮罩拿回来。"""
    from PIL import Image

    out = tmp_path / "page.png"
    code = cli.main(["--photos", *_four_red_photos(tmp_path), "--sheet", "A4",
                     "--cell", "3R", "--dpi", "25.4", "--mask",
                     "--out", str(out)])
    assert code == 0
    img = Image.open(out)
    w, h = img.size
    # (210, 210, 210) = MASK_RGB(150) 以 alpha 110 压在白纸上的合成值
    assert img.getpixel((1, h // 4)) == (210, 210, 210)
    assert img.getpixel((w // 4, 1)) == (210, 210, 210)


def test_build_plan_jobs_is_still_positional(st):
    """历史调用形状不得变：本文件 6 处调用全按 7 个位置参数（无关键字）调它。

    还得钉格子几何：gap 与 bleed 是相邻同类型的 float 位置参数，转发时写错
    顺序不会炸签名，只会静默换掉出血与间距。Task 4 退役对拍测试后，这条是
    唯一守这层转发映射的测试——只钉 (count, mode) 的话 4 格照样是 4 格，
    参数换了位也绿。（实测：正确 (95.0, 105.0)，互换 gap/bleed → (89.0, 106.5)）
    """
    plan, mode = cli.build_plan_jobs(st, "A4", "3R", 0.0,
                                     modes.DEFAULT_BLEED_MM, None, False)
    assert plan.count == 4
    assert mode == modes.BLEED_TRIM
    assert (plan.cells[0].w_mm, plan.cells[1].x_mm) == (95.0, 105.0)


def test_cli_stdout_note_wording_is_frozen(tmp_path, capsys):
    """全局约束：“cli 输出文案逐字不变”。重构前就应该通过——
    它是逐字冻结的回归锁，不是 RED 步骤：界面用的 `Job.note` 按 margin_source
    分档，措辞与本句不同，cli 这一侧必须自己钉住。

    钉整行而不只钉 note 子句：“每页 N 格 / 共 M 页”本轮从 `plan.count` /
    `len(_pages(...))` 换成了 `job.count` / `len(render_all(...))`，只钉后半句
    的话这两处漂了测试也不红。两档分支（白边 / 出血）都得钉。
    """
    photos = _four_red_photos(tmp_path)
    # 不传 --gap：格数跟的是 cli 自己的默认值 0.0（72），不是对拍用的 2.0（56）
    assert cli.main(["--photos", *photos, "--sheet", "A4", "--cell", "ID1",
                     "--dpi", "25.4"]) == 0
    assert capsys.readouterr().out == (
        "纸张 A4，每页 72 格，共 1 页。将保留白边：依规格约 "
        "上3.0/下5.0/左3.4/右3.4mm（未经真机校准）\n")

    assert cli.main(["--photos", *photos, "--sheet", "A4", "--cell", "3R",
                     "--dpi", "25.4"]) == 0
    assert capsys.readouterr().out == (
        "纸张 A4，每页 4 格，共 1 页。"
        "需人工裁切：沿灰线切开后即为 89×127mm 成品\n")
```

- [ ] **Step 2: 跑到失败**

Run: `python -m pytest tests/test_cli.py -v -k "mask or positional"`
Expected: 两条遮罩测试 FAIL —— `unrecognized arguments: --mask`，以及左/上缘
仍探到 `(210,210,210)`；`test_build_plan_jobs_is_still_positional` 是调用形状
回归锁，本步即绿。（`test_cli_stdout_note_wording_is_frozen` 也是回归锁，
本步同样即绿：它钉的是重构前后逐字相同的那一行）

- [ ] **Step 3: 改 `cli.py`**

把顶部 import 段与 `load_photo` / `build_plan_jobs` 替换为：

```python
from photoprint import jobs
from photoprint.core import modes, store  # pack/render/specs 不再由此层直接调用


def load_photo(path):
    """薄转发：读图实现已搬到 jobs，历史调用点不变。"""
    return jobs.load_photo(path)


def build_plan_jobs(st, sheet_key, cell_key, gap_mm, bleed_mm, mode,
                    borderless_active):
    """薄转发：保持 7 个位置参数与 (plan, mode) 返回的历史形状。"""
    return jobs.build_layout(st, sheet_key, cell_key, gap_mm, bleed_mm, mode,
                             borderless_active=borderless_active)
```

删除原 `build_plan_jobs` 函数体与 `_pages`（连同顶部 `from PIL import Image`：
它的唯一使用点就是被搬走的 `load_photo`），`build_parser` 里在 `--list-printers`
之前加一行：

```python
    ap.add_argument("--mask", action="store_true",
                    help="导出时保留不可印区灰遮罩（调试用，默认不导出）")
```

`main` 中从 `photos = [load_photo(p) ...]` 到打印那一段替换为：

```python
    photos = [load_photo(p) for p in args.photos]
    sheet = st.resolve(args.sheet)
    job = jobs.build_job(st, photos, args.sheet, args.cell, gap_mm=args.gap,
                         bleed_mm=args.bleed, mode=args.mode)
    pages = jobs.render_all(job, args.dpi, show_mask=args.mask)
    # 文案逐字冻结（全局约束）：cli 沿用本层原有的两分支 note 表达式，
    # 不取 job.note——那条属性按 margin_source 分档，spec 档写的是
    # “依规格推定，未经真机校准”，与历史输出不同一句
    borderless = job.mode == modes.BLEED_TRIM
    note = ("需人工裁切：沿灰线切开后即为 "
            f"{job.plan.cells[0].inner_mm()[2]:.0f}×"
            f"{job.plan.cells[0].inner_mm()[3]:.0f}mm 成品"
            if borderless else
            f"将保留白边：依规格约 上{sheet.margins.top}/下{sheet.margins.bottom}/"
            f"左{sheet.margins.left}/右{sheet.margins.right}mm（未经真机校准）")
    print(f"纸张 {sheet.label}，每页 {job.count} 格，共 {len(pages)} 页。{note}")
```

其余段落（`--out` 建父目录与"仅第一页"提示、`--pdf`、`--print`）保持原样不动。

薄转发落地后 `jobs.build_layout` 的 docstring 就成了假话（它写着“本 commit
里两边仍是两份实现，等价测试是真对拍”，而 Task 3 代码块里那段注释到此为止
就是历史现场），一并改掉：

```python
    """返回 (排版方案, 生效模式)。mode 为 None 时按默认映射决定。

    本函数是唯一真相源，cli.build_plan_jobs 只是它的薄转发（Task 4）。
    与旧 cli 实现的等价性已在历史提交上逐字段对拍过一次，此后不再靠
    两份实现互比——那只会退化成自己比自己，改由绝对格数与报错整句钉住。
    """
```

- [ ] **Step 4: 退役 `test_jobs.py` 里的两条对拍测试**

cli 变成 `jobs.build_layout` 的薄转发后，`test_build_layout_matches_legacy_cli` 与
`test_build_layout_rejects_cell_larger_than_sheet_with_same_message` 就是拿
`jobs.build_layout` 和它自己比——永远绿，却不声明任何事。它们证明的等价性已经
在 Task 3 的历史提交上完成过一次，不留下；换成重构前 cli 实测出的绝对值：

把 `tests/test_jobs.py` 里那两条测试整体删掉，在原位（`_photos` 之后）插入：

```python
# (纸张, 格子, gap, 出血, 指定模式, 无边距生效, 每页格数, 生效模式)
_CELL_COUNTS = [
    ("A4", "3R", 0.0, modes.DEFAULT_BLEED_MM, None, False, 4, modes.BLEED_TRIM),
    ("A4", "ID1", 2.0, modes.DEFAULT_BLEED_MM, None, False, 56,
     modes.FIT_TO_PRINTABLE),
    ("A4", "4R", 0.0, modes.DEFAULT_BLEED_MM, None, False, 2, modes.BLEED_TRIM),
    # 格与纸同尺寸：走“整纸一格”退化分支
    ("3R", "3R", 0.0, 0.0, modes.FILL_PRINTABLE, False, 1, modes.FILL_PRINTABLE),
    # 无边距生效时换的是可打印区，同一组合 2 格→ 3 格；不单独钉的话
    # 这一分支只能靠 Task 3 历史提交的对拍证明它当时确实与 cli 一致
    ("A4", "4R", 0.0, 0.0, modes.FIT_TO_PRINTABLE, True, 3, modes.FIT_TO_PRINTABLE),
]


@pytest.mark.parametrize("sheet,cell,gap,bleed,mode,borderless,want_count,"
                         "want_mode", _CELL_COUNTS)
def test_build_layout_cell_counts_are_frozen(st, sheet, cell, gap, bleed, mode,
                                             borderless, want_count, want_mode):
    """格数与生效模式全部钉死：数字漂了照样红，不需要另一个实现来参照。

    原方案是与重构前的 cli.build_plan_jobs 逐字段对拍；Task 4 把 cli 改成
    `jobs.build_layout` 的薄转发后，那两条就退化成自己比自己——永远绿，
    却不声明任何事。这里的绝对值是重构前实测抄下的。
    """
    plan, mode_eff = jobs.build_layout(st, sheet, cell, gap, bleed, mode,
                                       borderless_active=borderless)
    assert (plan.count, mode_eff) == (want_count, want_mode)


def test_cell_larger_than_sheet_raises_actionable_message(st):
    """报错文案是用户唯一能看见的出口，改成整句断言而不是与 cli 对拍。

    卡片纸（91×55）在出血档装不下带 3mm 出血的美国签证（57×57 > 55），
    且出血档不走“整纸一格”退化分支，是预设组合里真能走到的报错。
    """
    with pytest.raises(ValueError) as exc:
        jobs.build_layout(st, "CARD", "USVISA", 0.0, modes.DEFAULT_BLEED_MM,
                          modes.BLEED_TRIM, borderless_active=False)
    assert str(exc.value) == "卡片 放不下 美国签证，请换大纸或改小格子"
```

格数（4/56/2/1/3）是本步开工前用重构前的 `cli.build_plan_jobs` 实测得到的，
逐字照抄不得重算。两条对拍测试是 `test_jobs.py` 里唯一用到 `cli` 的地方，
删完后顶部 import 得改成 `from photoprint import jobs`，否则留下一个没人用的
`cli`；`render` / `specs` 仍被其余测试用着，不要跟着删。模块 docstring 也得从
「必须与重构前的 cli 逐字段等价」改成钉死绝对值的那句话——对拍退役后旧标题
声明的事已不存在。

- [ ] **Step 5: 跑到通过**

Run: `python -m pytest tests/test_cli.py tests/test_jobs.py -v`
Expected: `test_cli.py` 全部通过（含原 10 条 + 新 4 条）；`test_jobs.py` 20 passed
（parametrize 仍是 5 条，只是从“对拍”换成“绝对值”）

- [ ] **Step 6: 全量回归 + 手工证据**

```bash
python -m pytest tests/ -q
python -m photoprint.cli --photos _lab/out/p.jpg --sheet A4 --cell 3R --dpi 25.4 --out _lab/out/t4.png
python -c "from PIL import Image; im=Image.open('_lab/out/t4.png'); print(im.getpixel((1, im.size[1]//2)))"
```
Expected: 最后一行是 `(255, 255, 255)`，不是 `(210, 210, 210)`。探针取 x=1 而不是
x=3：dpi 25.4 下 A4 的遮罩带只覆盖 0..2 像素，取 3 探的是带外，本来就很白。

逐字冻结不能只靠新测试自己钉自己（那只能证明“现在是这样”，证不了“和历史
一样”），所以本步还跑两个专用脚本：

```bash
python .superpowers/sdd/verify_t4_cli_parity.py      # 从 0370989 取旧 cli，五组参数逐字节对拍
python .superpowers/sdd/verify_t4_store_isolation.py  # 把 %APPDATA% 指到已校准过的配置再跑测试
```
Expected: 前者“五组输出完全相同”，后者先在毒配置下把裸 cli 输出刷成
`上0.5/下0.5/左0.5/右0.5mm`（证明风险真存在），再给出 `pytest rc = 0`——
测试已经被 fixture 隔开。

- [ ] **Step 7: 提交**

```bash
git add photoprint/cli.py tests/test_cli.py tests/test_jobs.py
git commit -m "feat(cli): 改用 jobs 编排，导出默认关不可印区遮罩并加 --mask"
```

---

### Task 5: `store` 的 last_job 读写

**Files:**
- Modify: `photoprint/core/store.py`（`Store` 类内，`save` 之前）
- Test: `tests/test_store.py`（末尾追加）

**Interfaces:**
- Consumes: 已有的 `Store.raw["last_job"]` 槽位与 `load()` 的形状校验
- Produces: `Store.get_last_job() -> dict`、`Store.set_last_job(job: dict) -> None`

- [ ] **Step 1: 写失败测试**

在 `tests/test_store.py` 末尾追加 9 条（简报原给 5 条，开工后补 4 条，理由
见表后说明；文件已有 `json`、`pytest`、`specs`、`store` 导入、`Path` 与
`tmp_store` fixture）：

```python
def test_last_job_roundtrip(tmp_store):
    tmp_store.load()
    tmp_store.set_last_job({"sheet_key": "A4", "cell_key": "3R", "dpi": 300.0})
    assert tmp_store.save() is True
    again = store.Store(tmp_store.path)
    again.load()
    assert again.get_last_job()["cell_key"] == "3R"


def test_last_job_bad_shape_degrades_to_empty(tmp_path):
    """手改坏的配置不得卡住启动：与 load() 既有口径一致。"""
    p = tmp_path / "papers.json"
    p.write_text(json.dumps({"last_job": [1, 2]}), encoding="utf-8")
    s = store.Store(p)
    s.load()
    assert s.get_last_job() == {}


def test_get_last_job_returns_copy_not_live_dict(tmp_store):
    tmp_store.load()
    tmp_store.set_last_job({"gap_mm": 2.0})
    got = tmp_store.get_last_job()
    got["gap_mm"] = 99.0
    assert tmp_store.get_last_job()["gap_mm"] == 2.0


def test_set_last_job_rejects_non_dict(tmp_store):
    tmp_store.load()
    with pytest.raises(ValueError, match="必须是 dict"):
        tmp_store.set_last_job(["A4"])


def test_save_failure_propagates_but_memory_still_effective(tmp_path):
    """路径指向一个目录时写盘必失败：save 回 False，内存改动仍生效。"""
    s = store.Store(tmp_path)          # 目录当文件用
    s.load()
    s.set_last_job({"dpi": 150.0})
    assert s.save() is False
    assert s.get_last_job()["dpi"] == 150.0


def test_set_last_job_does_not_alias_caller_dict(tmp_store):
    """存的是副本：调用方手里的字典之后怎么改，都不能隔空改已存的任务。

    get 侧不返回活字典已由上一条钉住，写入侧不接活引用是同一枚币的另一面。
    """
    tmp_store.load()
    live = {"dpi": 300.0}
    tmp_store.set_last_job(live)
    live["dpi"] = 96.0
    assert tmp_store.get_last_job()["dpi"] == 300.0


def test_load_degrades_non_dict_last_job(tmp_store):
    """降级发生在读盘时，不只是读的时候好看。

    不围住的话坏形状会原样留在 raw 里，下次 save() 又把它写回去，“任何损坏
    都降级成没有”那句就不成立了。
    """
    Path(tmp_store.path).write_text(json.dumps({"last_job": [1, 2]}),
                                    encoding="utf-8")
    tmp_store.load()  # 不得抛
    assert tmp_store.raw["last_job"] == {}
    assert tmp_store.save() is True
    disk = json.loads(Path(tmp_store.path).read_text(encoding="utf-8"))
    assert disk["last_job"] == {}


def test_get_last_job_guard_survives_dirty_raw(tmp_store):
    """get 的形状守卫得自己顶得住：raw 可以被不经 load() 的路径弄脏。

    本层以外直接改 raw（后续任务的导入配置、测试里的搭伏）都可能把
    last_job 撑成 list；只靠 load() 一道闸的话，“读一下上次任务”就能 TypeError。
    """
    tmp_store.load()
    tmp_store.raw["last_job"] = [1, 2]
    assert tmp_store.get_last_job() == {}


def test_set_last_job_only_touches_its_own_slot(tmp_store):
    """docstring 的承诺：写 last_job 不得捎动 overrides 与 user_sizes。

    三个真相源共住一个 raw，串了位就是拿任务参数去盖掉用户标定。只比旁
    不变就行，不靠“读回来对”——那读的是同一个字典，盖错了也看不出来。
    """
    tmp_store.load()
    tmp_store.override_margins("3R", specs.Margins(2.0, 4.0, 3.0, 3.0),
                               "calibrated")
    # user_sizes 必须先非空：否则 before/after 都是 []，"顺手清空 user_sizes"
    # 这种串位变异照样过——快照比对只有旁槽真装了值才承重。
    tmp_store.add_user_size(specs.SizeSpec("user-4d", "4D 自建", 100.0, 148.0,
                                            "paper", "user", False,
                                            specs.Margins(), "spec"))
    before = json.dumps({k: v for k, v in tmp_store.raw.items()
                         if k != "last_job"}, sort_keys=True)
    tmp_store.set_last_job({"dpi": 300.0})
    after = json.dumps({k: v for k, v in tmp_store.raw.items()
                        if k != "last_job"}, sort_keys=True)
    assert after == before
    assert set(tmp_store.raw) == {"overrides", "user_sizes", "last_job"}
```

上块末尾四条（alias / 读盘降级 / 脏 raw / 串位）是开工后补的，不是简报原有内容：
变异检查第一轮探到两条存活——`get_last_job` 的形状守卫删了照样全绿（load()
已先把磁盘坏值降级成 `{}`，灌磁盘那条根本走不到 get 的闸上），而
`set_last_job` 里的 `dict(job)` 副本与“只写自己槽位”的 docstring 承诺无任何测试
依赖。四条各杀一个变异，记在自审记录 ⑭。


- [ ] **Step 2: 跑到失败**

Run: `python -m pytest tests/test_store.py -v -k last_job`
Expected: FAIL — 五条 `AttributeError: 'Store' object has no attribute 'set_last_job'`
（灌脏 raw 与写盘失败那两条也一样先死在 setter 上），`get_last_job` 那几条报
`no attribute 'get_last_job'`

- [ ] **Step 3: 实现**

在 `photoprint/core/store.py` 的 `_sync_user_sizes` 之后、`save` 之前插入：

```python
    def get_last_job(self) -> dict:
        """上次任务参数。形状不对就回空表：坏配置不得卡住启动。"""
        job = self.raw.get("last_job")
        return dict(job) if isinstance(job, dict) else {}

    def set_last_job(self, job: dict) -> None:
        """只写 raw["last_job"]，不碰 overrides 与 user_sizes：真相源各归各位。"""
        if not isinstance(job, dict):
            raise ValueError(f"last_job 必须是 dict，收到 {type(job).__name__}")
        self.raw["last_job"] = dict(job)
```

- [ ] **Step 4: 跑到通过**

Run: `python -m pytest tests/test_store.py -v`
Expected: 全部通过（原有 16 项 + 新 9 项 = 25 passed；其中简报给 5 条、
开工后补 4 条）

- [ ] **Step 5: 变异检查 + 全量回归 + 提交**

```bash
python .superpowers/sdd/mutate_gui_t5.py
python .superpowers/sdd/check_t5_plan_verbatim.py
python -m pytest tests/ -q
python _lab/m1m2_check.py
```

Expected: 变异脚本 7 个变异全部有效、还原后 25 条仍绿、退出码 0（它逐条改写
`store.py` 再跑 `tests/test_store.py`，结束时在 `finally` 里按字节还原）；
逐行校对“代码块 2 个，缺失行 0 条”；全量 189 点退出码 0。

```bash
git add photoprint/core/store.py tests/test_store.py
git commit -m "feat(store): last_job 读写与形状降级"
```

---

### Task 6: 子线程渲染与位图转换

**Files:**
- Create: `photoprint/app/__init__.py`、`photoprint/app/worker.py`、`photoprint/app/view.py`
- Create: `tests/conftest.py`、`tests/test_app_worker.py`、`tests/test_app_view.py`

**Interfaces:**
- Consumes: 任意无参可调用（后续任务传 `job.render`）
- Produces: `worker.RenderTask`（信号 `succeeded(object)` / `failed(str)`）、
  `worker.start(fn) -> tuple[QThread, RenderTask]`（**只组装不启动**，
    调用方连完信号后自己 `thread.start()`）、
  `view.to_pixmap(img: Image.Image) -> QPixmap`

- [ ] **Step 1: 建包与 offscreen 配置**

`photoprint/app/__init__.py`：

```python
"""界面层：唯一有窗口的层，不得包含 mm/像素与裁切几何。"""
```

`tests/conftest.py`（必须在任何 PySide6 导入之前生效；`qapp` 放这里而不是某个测试文件里，
因为 `tests` 不是包，`from tests.test_app_worker import qapp` 会 ImportError）：

```python
"""Qt 测试统一走 offscreen：CI 与本机都不该弹真窗口。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    """全测试会话共用一个 QApplication：多实例会撞 Qt 的单例约束。"""
    pytest.importorskip("PySide6", reason="需要 Qt 绑定")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
```

- [ ] **Step 2: 写失败测试**

`tests/test_app_worker.py`：

```python
"""线程边界：结果与异常都必须能回到主线程，不得静默死掉。"""
import pytest

pytest.importorskip("PySide6", reason="需要 Qt 绑定")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402

from photoprint.app import worker  # noqa: E402


def _run_and_drain(fn, timeout_ms=3000):
    """组装→连信号→启动→等停下来；返回 (结果列表, 错误列表)。"""
    thread, task = worker.start(fn)
    results, errors = [], []
    task.succeeded.connect(results.append)
    task.failed.connect(errors.append)
    thread.start()
    loop = QEventLoop()
    thread.finished.connect(loop.quit)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    thread.deleteLater()
    return results, errors


def test_start_returns_unstarted_thread_and_task(qapp):
    """start() 不得自己 start：否则调用方还来不及连信号，结果就丢了。"""
    thread, task = worker.start(lambda: 1)
    assert isinstance(task, worker.RenderTask)
    assert not thread.isRunning()


def test_task_emits_result_object(qapp):
    assert _run_and_drain(lambda: {"dpi": 300})[0] == [{"dpi": 300}]


def test_task_turns_exception_into_readable_text(qapp):
    def boom():
        raise ValueError("A4 放不下 5R，请换大纸或改小格子")

    errors = _run_and_drain(boom)[1]
    assert errors and "ValueError" in errors[0] and "换大纸" in errors[0]
```

`tests/test_app_view.py`：

```python
"""PIL → QPixmap 的唯一转换处。"""
import pytest

pytest.importorskip("PIL", reason="需要 Pillow")
pytest.importorskip("PySide6", reason="需要 Qt 绑定")

from PIL import Image  # noqa: E402

from photoprint.app import view  # noqa: E402


def test_to_pixmap_keeps_size_and_pixels(qapp):
    pm = view.to_pixmap(Image.new("RGB", (3, 2), (10, 20, 30)))
    assert (pm.width(), pm.height()) == (3, 2)
    got = pm.toImage().pixelColor(0, 0)
    assert (got.red(), got.green(), got.blue()) == (10, 20, 30)


def test_to_pixmap_survives_source_garbage_collection(qapp):
    """copy() 是必需的：原 buffer 被回收后 QPixmap 会变野指针。"""
    imgs = [view.to_pixmap(Image.new("RGB", (64, 64), (i, 0, 0))) for i in range(8)]
    assert all(not p.isNull() for p in imgs)
    assert imgs[-1].toImage().pixelColor(0, 0).red() == 7
```

- [ ] **Step 3: 跑到失败**

Run: `python -m pytest tests/test_app_worker.py tests/test_app_view.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'photoprint.app.worker'`

- [ ] **Step 4: 实现 `worker.py`**

```python
"""把渲染搬出主线程：主线程只做显示与输入。

异常必须转成信号，绝不让线程静默死掉——窗口化 exe 没有控制台，
静默失败等于用户完全无从得知。start() 只组装不启动：调用方先连信号
再 thread.start()，否则任务可能在连上之前就跑完了（信号丢失）。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal


class RenderTask(QObject):
    """在子线程里跑一个无参可调用，结果与异常都走信号。"""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            self.succeeded.emit(self._fn())
        except Exception as exc:  # 线程边界：任何异常都要变成可读消息
            self.failed.emit(f"{type(exc).__name__}: {exc}")


def start(fn):
    """组装 (thread, task)；调用方连信号后自己 thread.start()。"""
    thread = QThread()
    task = RenderTask(fn)
    task.moveToThread(thread)
    thread.started.connect(task.run)
    task.succeeded.connect(thread.quit)
    task.failed.connect(thread.quit)
    thread.finished.connect(task.deleteLater)
    return thread, task
```

- [ ] **Step 5: 实现 `view.py`**

```python
"""PIL → QPixmap 的唯一转换处；本层不得做尺寸换算（全局约束）。"""
from __future__ import annotations

from PySide6.QtGui import QImage, QPixmap


def to_pixmap(img):
    """RGB 位图转 QPixmap。

    `copy()` 不可省：QImage 只引用传入的 bytes，buf 一被回收就是野指针。
    """
    buf = img.tobytes("raw", "RGB")
    qimg = QImage(buf, img.width, img.height, img.width * 3,
                  QImage.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())
```

- [ ] **Step 6: 跑到通过**

Run: `python -m pytest tests/test_app_worker.py tests/test_app_view.py -v`
Expected: 5 passed

- [ ] **Step 7: 全量回归 + 提交**

```bash
python -m pytest tests/ -q
git add photoprint/app tests/conftest.py tests/test_app_worker.py tests/test_app_view.py
git commit -m "feat(app): 子线程渲染任务与 PIL→QPixmap 转换"
```

---

### Task 7: 主窗口

**Files:**
- Create: `photoprint/app/main_window.py`
- Test: `tests/test_app_main_window.py`

**Interfaces:**
- Consumes: `jobs.build_job/render_all/load_photo/PREVIEW_DPI`、`worker.start`、
  `view.to_pixmap`、`store.Store.get_last_job/set_last_job/save`、
  `specs.PAPER_PRESETS/CELL_PRESETS`、`modes.DEFAULT_BLEED_MM`、`win.pdf_export.export_pdf`
- Produces: `main_window.MainWindow(st=None)`，对测试暴露
  `append_photo(path)`、`export_to(path)`、`save_last_job(out_dir=None)`、`_refresh()`、
  属性 `job / photos / photo_paths / page_index`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_app_main_window.py`：

```python
"""界面冒烟：offscreen 下构造窗口、驱动一次排版与导出，不碰文件对话框。"""
import re

import pytest

pytest.importorskip("PIL", reason="需要 Pillow")
pytest.importorskip("PySide6", reason="需要 Qt 绑定")

from PySide6.QtCore import QElapsedTimer, QEventLoop  # noqa: E402

from PIL import Image  # noqa: E402

from photoprint import jobs  # noqa: E402
from photoprint.app.main_window import MainWindow  # noqa: E402
from photoprint.core import store  # noqa: E402


def _store(tmp_path):
    s = store.Store(tmp_path / "papers.json")
    s.load()
    return s


def _make_photos(tmp_path, n=4):
    paths = []
    for i in range(n):
        p = tmp_path / f"{i}.jpg"
        Image.new("RGB", (400, 200), (200 - 30 * i, 30, 40)).save(p)
        paths.append(str(p))
    return paths


def _fill(window, tmp_path, n=4):
    for p in _make_photos(tmp_path, n):
        window.append_photo(p)
    window._refresh()


def _settle(window, qapp, timeout_ms=5000):
    """offscreen 下没有自转的事件循环，手动泵到渲染线程停下、信号投递完。

    必须给 processEvents 传 maxTime：无参忙轮询不会等跨线程事件送达，
    慢机上几百次空转都可能还没轮到子线程 quit 的回投（计划原 rounds=60
    正是栽在这）。带超时就变成「事件一到立刻返回」，用墙钟兜底判定真挂了。
    """
    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < timeout_ms:
        qapp.processEvents(QEventLoop.AllEvents, 50)
        if window._thread is None:
            return
        if not window._thread.isRunning():
            qapp.processEvents(QEventLoop.AllEvents, 50)
            return
    pytest.fail("预览线程未在预期时间内停下")


@pytest.fixture(autouse=True)
def _no_leaked_threads(qapp):
    """每个用例收尾时停掉 debounce、泵停渲染线程、再关窗口。

    多数用例只 _refresh（经 _render_async 起了渲染线程）却不关窗口；
    线程跑到完成只会把 quit 排队到主线程，没人泵就永远不停；窗口随进程
    退出被析构时线程还在跑→解释器硬崩（0xC0000409），即使 pytest 已打印
    “N passed”，退出码仍非零、CI 会判失败。收尾三步：先停 debounce（否则
    下面泵送会触发新的 250ms 延迟渲染又起一条线程），再泵到现有线程全停，
    最后 close 触发 closeEvent 里的 quit+wait 兜底。
    """
    yield
    wins = [w for w in qapp.topLevelWidgets() if isinstance(w, MainWindow)]
    for w in wins:
        w._debounce.stop()
    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < 3000:
        qapp.processEvents(QEventLoop.AllEvents, 50)
        if not any(w._thread is not None and w._thread.isRunning() for w in wins):
            break
    for w in wins:
        w.close()
    qapp.processEvents(QEventLoop.AllEvents, 100)


def test_window_starts_with_preview_and_status(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    _settle(w, qapp)
    assert not w.preview.pixmap().isNull()
    assert "每页 4 格" in w.statusBar().currentMessage()
    assert w.export_btn.isEnabled()


def test_export_writes_equal_size_pdf(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    out = w.export_to(str(tmp_path / "page.pdf"))
    m = re.search(rb"MediaBox\s*\[([\d.\s]+)\]", out.read_bytes())
    vals = [float(x) for x in m.group(1).split()]
    assert vals[2] == pytest.approx(595.276, abs=1.0)   # A4 宽 210mm
    assert vals[3] == pytest.approx(841.89, abs=1.0)    # A4 高 297mm


def test_exported_page_has_no_unprintable_mask(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    page = jobs.render_all(w.job, 25.4, show_mask=False)[0]
    assert page.getpixel((3, page.height // 2)) != (210, 210, 210)


def test_too_big_cell_reports_instead_of_crashing(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    w.sheet_box.setCurrentIndex(w.sheet_box.findData("3R"))
    w.cell_box.setCurrentIndex(w.cell_box.findData("A4"))
    w._refresh()
    assert "放不下" in w.statusBar().currentMessage()
    assert not w.export_btn.isEnabled()


def test_unreadable_photo_is_marked_and_does_not_block(qapp, tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    w = MainWindow(st=_store(tmp_path))
    w.append_photo(str(bad))
    assert w.photos[-1] is None
    assert "无法读取" in w.statusBar().currentMessage()
    assert "读取失败" in w.photo_list.item(0).text()


def test_last_job_roundtrip_through_two_windows(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    w.gap_box.setValue(2.5)
    w.cell_box.setCurrentIndex(w.cell_box.findData("ID1"))
    w.save_last_job(out_dir=str(tmp_path))

    again = MainWindow(st=_store(tmp_path))
    assert again.gap_box.value() == 2.5
    assert again.cell_box.currentData() == "ID1"


def test_offset_sliders_reach_jobs(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    w.h_slider.setValue(50)
    w._refresh()
    assert w.job.offset_pct == (50.0, 0.0)


def test_page_navigation_clamps_at_edges(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path, n=5)          # 5 张于 A4+3R 是 2 页
    assert w.job.page_count == 2
    w._go_page(1)
    assert w.page_index == 1
    w._go_page(1)
    assert w.page_index == 1         # 越界不得变页码
    w._go_page(-1)
    assert w.page_index == 0
```

- [ ] **Step 2: 跑到失败**

Run: `python -m pytest tests/test_app_main_window.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'photoprint.app.main_window'`

- [ ] **Step 3: 实现 `photoprint/app/main_window.py`**

```python
"""单窗口表单界面：选图 → 选纸/格/模式 → 预览 → 导出等尺寸 PDF。

本层不含 mm/像素换算与裁切几何（全局约束）：百分比偏移、页码切分、
格子尺寸一律交 jobs/core。异常一律收敛成状态栏文字，不得外抛——
窗口化 exe 没有控制台，抛出去就是静默闪退。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QPushButton, QSlider,
                               QVBoxLayout, QWidget)

from photoprint import jobs
from photoprint.app import view, worker
from photoprint.core import modes, specs, store

MODE_LABELS = (
    ("自动", None),
    ("完整放入（留白）", modes.FIT_TO_PRINTABLE),
    ("铺满可打印区（留白边）", modes.FILL_PRINTABLE),
    ("出血拼版（需人工裁切）", modes.BLEED_TRIM),
)
DPI_CHOICES = ((150.0, "150"), (300.0, "300"), (600.0, "600"))
DEBOUNCE_MS = 250
OFFSET_MAX_PCT = 50
IMAGE_FILTER = "图片 (*.jpg *.jpeg *.png *.tif *.tiff *.bmp)"
ERROR_COLOR = "#b00000"


def _spin(lo, hi, value=0.0):
    box = QDoubleSpinBox()
    box.setRange(lo, hi)
    box.setDecimals(1)
    box.setSingleStep(0.5)
    box.setValue(value)
    return box


def _slider_row(slider, label):
    row = QHBoxLayout()
    row.addWidget(slider, 1)
    row.addWidget(label)
    return row


def _connect_param_changed(widget, handler):
    """各控件的“值变了”信号名不同，这里统一接到 handler。

    带 `*_` 是因为 valueChanged 会传值、currentIndexChanged 也传值，
    而 handler（QTimer.start）不接受参数。
    """
    for name in ("valueChanged", "currentIndexChanged"):
        sig = getattr(widget, name, None)
        if sig is not None:
            sig.connect(lambda *_: handler())
            return
    raise TypeError(f"控件没有可用的值变更信号：{type(widget).__name__}")


class MainWindow(QMainWindow):
    def __init__(self, st=None):
        super().__init__()
        self.st = st if st is not None else store.Store()
        self.st.load()
        self.photos = []        # PIL 图；读取失败的占位 None 会被渲染当空格
        self.photo_paths = []
        self.page_index = 0
        self.job = None
        self._thread = None
        self._task = None
        self._gen = 0
        self._stale = []        # wait 超时没停干净的旧线程，留住引用防其在跑时被回收
        self.setWindowTitle("相片打印助手")
        self._build_ui()
        # debounce 必须先于恢复设置建好： setCurrentIndex 一类调用会打到信号
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._refresh)
        for w in (self.sheet_box, self.cell_box, self.mode_box, self.gap_box,
                  self.bleed_box, self.dpi_box, self.h_slider, self.v_slider):
            _connect_param_changed(w, self._debounce.start)
        self._restore_last_job()
        self._refresh()

    # ---------- 布局 ----------

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        body = QHBoxLayout()
        outer.addLayout(body, 1)

        panel = QFormLayout()
        body.addLayout(panel)

        self.photo_list = QListWidget()
        self.photo_list.setFixedWidth(260)
        self.photo_list.setMaximumHeight(150)
        panel.addRow("照片", self.photo_list)

        add_btn = QPushButton("添加照片…")
        add_btn.clicked.connect(self._on_add_photos)
        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self._on_clear_photos)
        btns = QHBoxLayout()
        btns.addWidget(add_btn)
        btns.addWidget(clear_btn)
        panel.addRow("", btns)

        # 纸张只列 role=paper；格子列 role=cell 加全部 role=paper（人设计 4.3）
        self.sheet_box = QComboBox()
        for s in specs.PAPER_PRESETS:
            self.sheet_box.addItem(s.label, s.key)
        panel.addRow("纸张", self.sheet_box)

        self.cell_box = QComboBox()
        for s in list(specs.CELL_PRESETS) + list(specs.PAPER_PRESETS):
            self.cell_box.addItem(s.label, s.key)
        # 默认选 3R 而非下拉首项 ID1：spec/Step 5 手工核对都写“默认 A4/3R”，
        # 3R 在 PAPER_PRESETS 里、findData 必命中；max(0, …) 只是防 findData 返回 -1。
        self.cell_box.setCurrentIndex(max(0, self.cell_box.findData("3R")))
        panel.addRow("格子", self.cell_box)

        self.mode_box = QComboBox()
        for label, _value in MODE_LABELS:
            self.mode_box.addItem(label)
        panel.addRow("模式", self.mode_box)

        self.gap_box = _spin(0.0, 50.0)
        panel.addRow("格间距 mm", self.gap_box)
        self.bleed_box = _spin(0.0, 20.0, modes.DEFAULT_BLEED_MM)
        panel.addRow("出血 mm", self.bleed_box)

        self.dpi_box = QComboBox()
        for value, label in DPI_CHOICES:
            self.dpi_box.addItem(label, value)
        self.dpi_box.setCurrentIndex(1)      # 默认 300
        panel.addRow("输出 dpi", self.dpi_box)

        self.h_slider = QSlider(Qt.Horizontal)
        self.h_slider.setRange(-OFFSET_MAX_PCT, OFFSET_MAX_PCT)
        self.v_slider = QSlider(Qt.Horizontal)
        self.v_slider.setRange(-OFFSET_MAX_PCT, OFFSET_MAX_PCT)
        self.h_label = QLabel("0%")
        self.v_label = QLabel("0%")
        self.h_slider.valueChanged.connect(lambda v: self.h_label.setText(f"{v}%"))
        self.v_slider.valueChanged.connect(lambda v: self.v_label.setText(f"{v}%"))
        panel.addRow("水平微调", _slider_row(self.h_slider, self.h_label))
        panel.addRow("垂直微调", _slider_row(self.v_slider, self.v_label))

        self.preview = QLabel("（无预览）")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(360, 480)
        body.addWidget(self.preview, 1)

        nav = QHBoxLayout()
        self.prev_btn = QPushButton("上一页")
        self.next_btn = QPushButton("下一页")
        self.prev_btn.clicked.connect(lambda: self._go_page(-1))
        self.next_btn.clicked.connect(lambda: self._go_page(1))
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.next_btn)
        nav.addStretch(1)
        self.export_btn = QPushButton("导出 PDF…")
        self.export_btn.clicked.connect(self._on_export)
        nav.addWidget(self.export_btn)
        outer.addLayout(nav)

        self.statusBar().showMessage("就绪")

    # ---------- 参数与刷新 ----------

    def _params(self):
        return {
            "sheet_key": self.sheet_box.currentData(),
            "cell_key": self.cell_box.currentData(),
            "gap_mm": self.gap_box.value(),
            "bleed_mm": self.bleed_box.value(),
            "mode": MODE_LABELS[self.mode_box.currentIndex()][1],
            "dpi": float(self.dpi_box.currentData()),
            "offset_pct": (float(self.h_slider.value()),
                           float(self.v_slider.value())),
        }

    def _refresh(self):
        """算排版 → 起线程渲当前页。排版失败只报状态栏，不弹不崩。"""
        p = self._params()
        try:
            self.job = jobs.build_job(self.st, self.photos, p["sheet_key"],
                                      p["cell_key"], gap_mm=p["gap_mm"],
                                      bleed_mm=p["bleed_mm"], mode=p["mode"],
                                      offset_pct=p["offset_pct"])
        except ValueError as exc:      # 放不下 / 非法模式组合 / 未知尺寸
            self.job = None
            self._set_status(str(exc), error=True)
            self.export_btn.setEnabled(False)
            return
        self.page_index = min(self.page_index, self.job.page_count - 1)
        self.export_btn.setEnabled(any(ph is not None for ph in self.photos))
        self._set_status(f"每页 {self.job.count} 格 · 共 {self.job.page_count} 页 · "
                         f"{self.job.note}")
        self._render_async()

    def _render_async(self):
        self._gen += 1
        gen = self._gen
        self._retire_threads()
        job, index = self.job, self.page_index
        self._thread, self._task = worker.start(
            lambda: job.render(index, jobs.PREVIEW_DPI, show_mask=True))
        self._task.succeeded.connect(lambda image, g=gen: self._on_preview(image, g))
        self._task.failed.connect(
            lambda msg, g=gen: self._on_render_failed(msg, g))
        self._thread.start()

    def _retire_threads(self, timeout=2000):
        """quit 打不断正在 run 的渲染，wait 超时就不能丢引用——丢了引用，在跑的
        QThread 被回收就是 0xC0000409；被丢弃线程迟到的回投靠 gen 当过期帧丢弃。
        timeout=None 是无上限等到底（关窗收尾用：渲染有限，值得等，且不留
        _stale——它是实例属性，随窗口析构即释放，那时再丢引用同样会崩）。"""
        threads = self._stale + ([self._thread] if self._thread is not None else [])
        keep = []
        for th in threads:
            if th.isRunning():
                th.quit()
                if timeout is None:
                    th.wait()
                elif not th.wait(timeout):
                    keep.append(th)
        self._stale = keep

    def _on_preview(self, image, gen):
        if gen != self._gen:
            return                       # 被丢弃的慢线程迟到的旧帧，不覆盖当前页
        pm = view.to_pixmap(image)
        self.preview.setPixmap(pm.scaled(self.preview.size(), Qt.KeepAspectRatio,
                                        Qt.SmoothTransformation))

    def _on_render_failed(self, msg, gen):
        if gen == self._gen:
            self._set_status(msg, error=True)

    def _go_page(self, delta):
        if self.job is None:
            return
        nxt = self.page_index + delta
        if 0 <= nxt < self.job.page_count:
            self.page_index = nxt
            self._render_async()

    def _set_status(self, text, error=False):
        self.statusBar().setStyleSheet(f"color:{ERROR_COLOR}" if error else "")
        self.statusBar().showMessage(text)

    # ---------- 照片 ----------

    def _on_add_photos(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择照片",
                                                self._start_dir(), IMAGE_FILTER)
        for p in paths:
            self.append_photo(p)
        self._debounce.start()

    def append_photo(self, path):
        """读图失败不阻塞其余：占位 None 进渲染当空格，列表标红。"""
        name = Path(path).name
        try:
            img = jobs.load_photo(path)
        except Exception as exc:      # IO 边界什么都可能抛，全部收敛
            self.photos.append(None)
            self.photo_paths.append(str(path))
            item = QListWidgetItem(f"{name}（读取失败）")
            item.setForeground(QColor(ERROR_COLOR))
            self.photo_list.addItem(item)
            self._set_status(f"无法读取 {name}：{exc}", error=True)
            return
        self.photos.append(img)
        self.photo_paths.append(str(path))
        self.photo_list.addItem(
            QListWidgetItem(f"{name}  {img.width}×{img.height}px"))

    def _on_clear_photos(self):
        self.photos, self.photo_paths = [], []
        self.photo_list.clear()
        self.page_index = 0
        self._refresh()

    # ---------- 导出 ----------

    def export_to(self, out_path):
        """导出等尺寸 PDF。测试直接调它，不经文件对话框。"""
        from photoprint.win import pdf_export

        if self.job is None or not any(ph is not None for ph in self.photos):
            raise ValueError("没有可导出的照片")
        pages = jobs.render_all(self.job, self._params()["dpi"], show_mask=False)
        pdf_export.export_pdf(pages, self.job.sheet, out_path)
        self.save_last_job(out_dir=str(Path(out_path).parent))
        return Path(out_path)

    def _on_export(self):
        suggested = str(Path(self._start_dir()) / "photoprint.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "导出 PDF", suggested,
                                             "PDF (*.pdf)")
        if not path:
            return
        try:
            got = self.export_to(path)
        except Exception as exc:      # 无权限/磁盘满/img2pdf 异常
            self._set_status(f"导出失败：{exc}", error=True)
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        self._set_status(f"已导出 {got.name}（打印时请选“实际大小/100%”）")

    # ---------- 上次设置 ----------

    def save_last_job(self, out_dir=None):
        p = self._params()
        self.st.set_last_job({
            "sheet_key": p["sheet_key"], "cell_key": p["cell_key"],
            # 存下拉索引而不是 mode 内部值：“自动”是 None，反序列化时要判空，
            # 索引没有这个歧义
            "mode_index": self.mode_box.currentIndex(),
            "gap_mm": p["gap_mm"], "bleed_mm": p["bleed_mm"], "dpi": p["dpi"],
            "offset_pct": [self.h_slider.value(), self.v_slider.value()],
            "out_dir": out_dir or self._last_out_dir(),
            "photo_paths": list(self.photo_paths)})
        if not self.st.save():
            self._set_status("本次设置未持久化（写入失败）", error=True)

    def _safe(self, fn):
        """坏配置只降级成“这一项不恢复”，绝不让异常出 __init__（全局约束：窗口化 exe
        无控制台，外抛即静默闪退）。与 store 的“单条坏记录不牵连其余”同口径。
        覆盖 TypeError/ValueError/OverflowError——含 int()/float() 转换、以及 setValue
        把超大值喂给 shiboken C int（4 字节）的溢出（±50% 之外的手改配置、超大数、Infinity）。"""
        try:
            fn()
        except (TypeError, ValueError, OverflowError):
            pass

    def _restore_last_job(self):
        job = self.st.get_last_job()
        if not job:
            return
        for key, box in (("sheet_key", self.sheet_box), ("cell_key", self.cell_box)):
            self._safe(lambda b=box, v=job.get(key): self._select_by_data(b, v))
        mode_index = job.get("mode_index")
        if isinstance(mode_index, int) and 0 <= mode_index < self.mode_box.count():
            self._safe(lambda: self.mode_box.setCurrentIndex(mode_index))
        for key, box in (("gap_mm", self.gap_box), ("bleed_mm", self.bleed_box)):
            if isinstance(job.get(key), (int, float)):
                self._safe(lambda b=box, v=job[key]: b.setValue(float(v)))
        if isinstance(job.get("dpi"), (int, float)):
            self._safe(lambda: self._select_by_data(self.dpi_box, float(job["dpi"])))
        pct = job.get("offset_pct")
        if isinstance(pct, (list, tuple)) and len(pct) == 2:
            self._safe(lambda: self._apply_offset(pct))
        paths = job.get("photo_paths")
        for p in (paths if isinstance(paths, (list, tuple)) else []):
            self.append_photo(str(p))      # 文件已删则走标红分支，不阻塞（append_photo 内部已收敛）

    def _select_by_data(self, box, value):
        idx = box.findData(value)
        if idx >= 0:
            box.setCurrentIndex(idx)

    def _apply_offset(self, pct):
        self.h_slider.setValue(int(pct[0]))
        self.v_slider.setValue(int(pct[1]))

    def _last_out_dir(self):
        d = self.st.get_last_job().get("out_dir")
        if not isinstance(d, str):       # 坏配置（非字符串）不报错：与其余字段同口径降级
            return ""
        try:
            return d if d and Path(d).is_dir() else ""
        except (OSError, ValueError):    # 含空字节等非法路径，Path 会抛，一律当“无”处理
            return ""

    def _start_dir(self):
        return self._last_out_dir() or str(Path.home())

    def closeEvent(self, event):
        self._debounce.stop()      # 关窗后 debounce 若还 fire 会另起线程，绕过收尾
        self.save_last_job()
        self._gen += 1             # 之后任何回投都算过期帧
        self._retire_threads(timeout=None)   # 收尾无上限等到底，不留随窗口析构即失效的 _stale
        super().closeEvent(event)
```

- [ ] **Step 4: 跑到通过**

Run: `python -m pytest tests/test_app_main_window.py -v`
Expected: 21 passed（round-1 新增 3 条 + round-2 新增 5 条 + round-3 新增 5 条：数值超大配置降级参数化 4 条、render_failed 过期帧 1 条）

- [ ] **Step 5: 全量回归 + 手工看一扇窗口**

```bash
python -m pytest tests/ -q
```
手工启动（本任务还没有 `__main__.py`，T8 之后改用 `python -m photoprint.app`）：

```powershell
python -c "from PySide6.QtWidgets import QApplication; from photoprint.app.main_window import MainWindow; app = QApplication([]); w = MainWindow(); w.show(); app.exec()"
```
手工核对：下拉默认 A4/3R、预览有图与灰裁切线、状态栏含“需人工裁切”、
拖动微调滑块时画面跟着动。关掉窗口会自动写 last_job。

- [ ] **Step 6: 提交**

```bash
git add photoprint/app/main_window.py tests/test_app_main_window.py
git commit -m "feat(app): 表单主窗口（预览、微调滑块、状态栏、PDF 导出、设置恢复）"
```

---

### Task 8: 入口与崩溃日志

**Files:**
- Create: `photoprint/app/crashlog.py`、`photoprint/app/__main__.py`
- Test: `tests/test_app_crashlog.py`

**Interfaces:**
- Consumes: `store.default_path()`（日志与配置同目录，不另起一套路径规则）
- Produces: `crashlog.log_path() -> Path`、`crashlog.write(exc_info, path=None) -> Path | None`、
  `crashlog.install(path=None) -> Path`、`__main__.run(argv=None) -> int`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_app_crashlog.py`：

```python
"""窗口化 exe 没有控制台，异常只能落盘才看得见。"""
import sys
import threading
import types

import pytest

from photoprint.app import crashlog


def test_log_path_sits_next_to_config(tmp_path, monkeypatch):
    monkeypatch.setattr(crashlog.store, "default_path",
                        lambda: tmp_path / "PhotoPrint" / "papers.json")
    assert crashlog.log_path() == tmp_path / "PhotoPrint" / "error.log"


def test_write_appends_traceback(tmp_path):
    p = tmp_path / "error.log"
    try:
        raise ValueError("A4 放不下 5R")
    except ValueError:
        got = crashlog.write(sys.exc_info(), p)
    assert got == p
    text = p.read_text(encoding="utf-8")
    assert "ValueError" in text and "A4 放不下 5R" in text


def test_write_creates_missing_parent_dir(tmp_path):
    """日志目录还没建时 write 要用 mkdir(parents=True) 补上（真实首次运行
    即此情形）：不建则 open 抛 FileNotFoundError 被吞掉、返回 None，首启崩溃反而
    留不下任何日志。tmp_path 下两级子目录都预先不存在。"""
    p = tmp_path / "PhotoPrint" / "nested" / "error.log"
    try:
        raise ValueError("首启")
    except ValueError:
        got = crashlog.write(sys.exc_info(), p)
    assert got == p and p.exists()


def test_write_appends_instead_of_overwriting(tmp_path):
    p = tmp_path / "error.log"
    for _ in range(2):
        try:
            raise KeyError("sheet_key")
        except KeyError:
            crashlog.write(sys.exc_info(), p)
    # 钉的是“追加两条、没互相覆盖”，而非某易变字符串出现几次：一次 traceback 里
    # KeyError 会出现两遍（源码行 raise KeyError(...) + 末尾 KeyError: 'sheet_key'），
    # 按计划原写法 count("KeyError")==2 恒不成立。改数“Traceback 抬头”条数，直读意图且
    # 不受 traceback 具体排版影响。
    text = p.read_text(encoding="utf-8")
    assert text.count("Traceback (most recent call last)") == 2
    assert text.count("KeyError: 'sheet_key'") == 2


def test_write_failure_returns_none(tmp_path):
    """日志路径是个目录时不得抛：日志不能反过来拖垮进程。"""
    assert crashlog.write((ValueError, ValueError("x"), None), tmp_path) is None


@pytest.mark.parametrize("bad_exc_info,bad_path", [
    ("oops", None),                        # 解包不成三元组 → TypeError
    ((ValueError,), None),                 # value 缺 → TypeError
    ((ValueError, "x"), None),             # tb 缺 → ValueError
    ((str, "not-exc", None), None),        # 非异常类 → AttributeError
    ((ValueError, ValueError("x"), None), 5),   # path=5 → Path(5) TypeError（原在 try 外）
])
def test_write_never_raises_on_malformed_input(bad_exc_info, bad_path, tmp_path,
                                                monkeypatch):
    """“异常一律收敛”契约：任何畸形入参都只能返 None，不得穿出（窗口化 exe
    无控制台，外抛即静默闪退）。只捕 OSError 的写法会让前四条仍外抛。前四条走
    path=None→log_path()：畸形 exc_info 要到 format_exception 才报错，晚于 mkdir+
    open(append) 建盘，不隔离就会在真 %APPDATA%\\PhotoPrint 落一个空 error.log（实测
    复现）。故把 store.default_path 打到 tmp_path，既覆盖 path=None 分支又不污染真目录。"""
    monkeypatch.setattr(crashlog.store, "default_path",
                        lambda: tmp_path / "PhotoPrint" / "papers.json")
    assert crashlog.write(bad_exc_info, bad_path) is None
    if bad_path is None:   # 钉住隔离本身：删掉上面 monkeypatch 就会回退成污染真目录
        assert (tmp_path / "PhotoPrint" / "error.log").exists()


def test_write_survives_lone_surrogate(tmp_path):
    """errors="replace" 保日志落地：孤立代理项在 strict 编码下会触发
    UnicodeEncodeError，若被收敛成 None 就等于崩溃日志静默丢失（窗口化 exe 无从
    得知）。断言 write 仍返回路径、traceback 行真的落下来——删掉 errors="replace"
    本用例会因 write 返 None 而红（畸形字符被替成 '?'、不追求逐字保真）。"""
    p = tmp_path / "error.log"
    got = crashlog.write((ValueError, ValueError("\ud800"), None), p)
    assert got == p and p.exists()
    assert "ValueError" in p.read_text(encoding="utf-8")   # 日志没丢，只是畸形字符被替掉


def test_install_replaces_both_hooks(tmp_path):
    old, old_thread = sys.excepthook, threading.excepthook
    target = tmp_path / "error.log"
    try:
        crashlog.install(target)
        try:
            raise RuntimeError("预览炸了")
        except RuntimeError:
            sys.excepthook(*sys.exc_info())
        assert "RuntimeError" in target.read_text(encoding="utf-8")
        # 名字叫 both_hooks 就得两条钩子都真承重：threading.excepthook 收的是
        # 一个带 exc_type/exc_value/exc_traceback 的 args。不驱动它，删产品
        # 代码里 `threading.excepthook = thread_hook` 那一行本用例仍会绿（真缺口）。
        try:
            raise ValueError("子线程炸了")
        except ValueError as exc:
            args = types.SimpleNamespace(exc_type=type(exc), exc_value=exc,
                                        exc_traceback=exc.__traceback__)
            threading.excepthook(args)
        text = target.read_text(encoding="utf-8")
        assert "ValueError" in text and "子线程炸了" in text
    finally:
        sys.excepthook, threading.excepthook = old, old_thread
```

- [ ] **Step 2: 跑到失败**

Run: `python -m pytest tests/test_app_crashlog.py -v`
Expected: FAIL — `ImportError: cannot import name 'crashlog'`

- [ ] **Step 3: 实现 `crashlog.py`**

```python
"""崩溃日志：窗口化 exe 没有控制台，异常只能落盘才看得见。

日志写失败绝不反过来抛：诊断手段不得拖垮主流程。
"""
from __future__ import annotations

import sys
import threading
import traceback
from pathlib import Path

from photoprint.core import store

LOG_NAME = "error.log"


def log_path() -> Path:
    """与配置同目录（%APPDATA%\\PhotoPrint\\error.log）。"""
    return store.default_path().parent / LOG_NAME


def write(exc_info, path=None):
    """把 traceback 追加写入日志，返回日志路径；写失败返回 None。

    异常一律收敛、无逃逸路径：路径构造、建目录、格式化、编码全部纳入 try。
    兜底 except Exception 而非只 OSError——本模块的契约是“诊断不得拖垮主流程”，
    畸形 exc_info（TypeError/ValueError）与孤立代理项编码错（UnicodeEncodeError）
    都得收敛成 None。不捕 BaseException：放行 KeyboardInterrupt/SystemExit。
    """
    try:
        target = Path(path) if path else log_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8", errors="replace") as fh:
            fh.write("".join(traceback.format_exception(*exc_info)) + "\n")
    except Exception:
        return None
    return target


def install(path=None) -> Path:
    """装主线程与子线程两个钩子。Qt 槽内的异常走 sys.excepthook。"""
    target = Path(path) if path else None

    def hook(etype, value, tb):
        write((etype, value, tb), target)

    def thread_hook(args):
        write((args.exc_type, args.exc_value, args.exc_traceback), target)

    sys.excepthook = hook
    threading.excepthook = thread_hook
    return target or log_path()
```

- [ ] **Step 4: 实现 `__main__.py`**

```python
"""exe 与 `python -m photoprint.app` 的入口。

入口必须是真实 .py 文件：PyInstaller 不认 `python -m` 形式。
本文件不得 print：--windowed 下 sys.stdout 是 None。
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from photoprint.app import crashlog, main_window


def run(argv=None):
    crashlog.install()
    app = QApplication(argv if argv is not None else sys.argv[:1])
    win = main_window.MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
```

- [ ] **Step 5: 跑到通过**

Run: `python -m pytest tests/test_app_crashlog.py -v`
Expected: 5 passed

- [ ] **Step 6: 入口手工验证**

```powershell
python -m pytest tests/ -q
python -m photoprint.app
```
Expected: 窗口弹出；关掉后 `%APPDATA%\PhotoPrint\papers.json` 里出现 `last_job`。

- [ ] **Step 7: 提交**

```bash
git add photoprint/app/crashlog.py photoprint/app/__main__.py tests/test_app_crashlog.py
git commit -m "feat(app): 入口与双异常钩子崩溃日志"
```

---

### Task 9: 单文件 exe 打包

**Files:**
- Create: `requirements-build.txt`、`build_exe.ps1`、`_lab/check_exe.ps1`、`tests/test_build_scripts_encoding.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `photoprint/app/__main__.py`（入口）
- Produces: `dist/PhotoPrint.exe`

- [ ] **Step 1: 写 `requirements-build.txt`**

```
# 构建期依赖：不被任何运行时代码 import，故与 requirements.txt 分开
pyinstaller>=6.0
```

- [ ] **Step 2: 写 `.gitignore` 追加段**

在 `.gitignore` 末尾追加：

```
# PyInstaller 产物与构建用虚环境
build/
dist/
*.spec
.venv-build/
```

- [ ] **Step 3: 写 `build_exe.ps1`**

```powershell
# 构建单文件 exe：独立 venv → 装依赖 → PyInstaller onefile/windowed
# 用法：.\build_exe.ps1        正常构建
#      .\build_exe.ps1 -Clean  先删 build/ 与 dist/
param(
    [switch]$Clean
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$venv = Join-Path $root ".venv-build"

if ($Clean) {
    foreach ($d in "build", "dist") {
        $p = Join-Path $root $d
        if (Test-Path $p) { Remove-Item -Recurse -Force $p }
    }
}

$py = Join-Path $venv "Scripts\python.exe"
# 判解释器真存在（只看目录会放过半残 venv，炸在后面 & $py 找不到命令）
if (-not (Test-Path $py)) {
    python -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "python -m venv 失败 rc=$LASTEXITCODE" }
}
& $py --version
& $py -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip 升级失败 rc=$LASTEXITCODE" }
& $py -m pip install -r (Join-Path $root "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "装运行时依赖失败 rc=$LASTEXITCODE" }
& $py -m pip install -r (Join-Path $root "requirements-build.txt")
if ($LASTEXITCODE -ne 0) { throw "装构建期依赖失败 rc=$LASTEXITCODE" }

# 入口是真实 .py 文件；--windowed 等于 --noconsole
# 原生命令非零退出不会被 ErrorActionPreference=Stop 拦下（那是 7.3+ 才有的），必须手查 $LASTEXITCODE
# 显式钉死输出路径到 $root（不依赖 CWD），否则从别处按绝对路径调用时 PyInstaller 会往 CWD 写 dist、
# 而下面的产物检查与 -Clean 都锚在 $root，会错报“未产出”或删错位置。
$buildStart = Get-Date
& $py -m PyInstaller --noconfirm --clean --onefile --windowed --name PhotoPrint `
    --distpath (Join-Path $root "dist") --workpath (Join-Path $root "build") --specpath $root `
    --paths $root (Join-Path $root "photoprint\app\__main__.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败 rc=$LASTEXITCODE" }

$exePath = Join-Path $root "dist\PhotoPrint.exe"
if (-not (Test-Path $exePath)) {
    throw "构建结束但未产出 dist\PhotoPrint.exe"
}
# 新鲜度：本次没真产出、但上一次残留 exe 还在原位时，不能对着旧 exe 报 OK
if ((Get-Item $exePath).LastWriteTime -lt $buildStart) {
    throw "dist\PhotoPrint.exe 时间戳早于本次构建，疑似上次残留"
}
$mb = [math]::Round((Get-Item $exePath).Length / 1MB, 1)
Write-Host "OK 产物：$exePath（$mb MB）"
```

- [ ] **Step 4: 跑构建**

Run: `powershell -ExecutionPolicy Bypass -File .\build_exe.ps1`
Expected: 末尾输出 `OK 产物：…\dist\PhotoPrint.exe（… MB）`。
体积估算：本应用只 import QtWidgets/QtGui/QtCore/QtNetwork、不带 WebEngine，实测约 60–70MB（低于早期 100–180MB 预估属正常）。
若体积显著低于 60MB，才怀疑 PySide6 插件没收全，先查 `build\PhotoPrint\Analysis-00.toc` 里有无 `qwindows.dll`。

- [ ] **Step 5: 写 `_lab/check_exe.ps1`**

```powershell
# 手工验收：启动 exe → 断言进程存活且窗口标题正确 → 打印体积与启动耗时
# 先跑 build_exe.ps1；本脚本不构建
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $root "dist\PhotoPrint.exe"
if (-not (Test-Path $exe)) { throw "未找到 $exe，先跑 build_exe.ps1" }

$sizeMb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
$started = Get-Date
# onefile 下真实窗口属子进程（引导父进程无窗口）→ 必须按映像名而非父 PID 取标题。
# 但 PhotoPrint 就是产品 exe 名，绝不能按名全机强杀（会打掉用户自己开着的实例、丢 last_job）。
# 归属边界用"排除法"：只排除快照时已存在的 PhotoPrint；从快照起到清理二次枚举为止
# （≈轮询 30s + 关窗 2s）新起的外部实例仍会被当成本轮 own，匹配与清理都可能误伤——
# dev-only 手工脚本可接受的窄 TOCTOU。
$before = @(Get-Process -Name "PhotoPrint" -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
if ($before.Count -gt 0) {
    Write-Host "注：检测到 $($before.Count) 个既存 PhotoPrint 实例，本轮不碰也不回收（历史孤儿需手工清）"
}
Start-Process -FilePath $exe | Out-Null

function Get-OwnPhotoPrint {
    Get-Process -Name "PhotoPrint" -ErrorAction SilentlyContinue |
        Where-Object { $before -notcontains $_.Id }
}

# 先礼貌关窗（走 closeEvent 落 last_job），仍没退的再强杀——把"误伤外部实例"的后果从
# 强杀丢数据降为正常关窗。只对"本轮 own"（含 TOCTOU 窗口内误纳者）生效。
# 注意：CloseMainWindow() 是 .NET 方法，对"枚举后已自行退出"的对象会抛 MethodInvocationException，
# 且该异常不受 -EA SilentlyContinue 管辖（必须 try/catch）；一旦在清理里抛出会中断脚本、
# 让本轮 own 残留并落进下次的 $before 被永久豁免。故先判 HasExited、再包 try/catch 兜底。
function Stop-OwnPhotoPrint {
    foreach ($proc in @(Get-OwnPhotoPrint)) {
        if (-not $proc.HasExited) { try { [void]$proc.CloseMainWindow() } catch { } }
    }
    Start-Sleep -Seconds 2
    @(Get-OwnPhotoPrint) | Where-Object { -not $_.HasExited } |
        Stop-Process -Force -ErrorAction SilentlyContinue
}

$found = $null
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    $own = @(Get-OwnPhotoPrint)
    $found = $own | Where-Object { $_.MainWindowTitle -like "*相片打印助手*" } | Select-Object -First 1
    if ($found) { break }
    if ($own.Count -eq 0) { break }   # 本轮进程全没了（崩/退），别再空等 30s
}
$elapsed = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
$alive = @(Get-OwnPhotoPrint)

if ($null -eq $found) {
    # 区分"本轮进程已崩/退"与"进程活着但本会话无可枚举窗口"（无交互桌面）
    $state = if ($alive.Count -gt 0) { "本轮进程存活 $($alive.Count) 个但无窗口（本会话无交互桌面？）" }
             else { "本轮进程已退出（崩溃或未能启动）" }
    Write-Host "FAIL 窗口未出现（体积 $sizeMb MB，等待 $elapsed s）：$state"
    Stop-OwnPhotoPrint
    exit 1
}
Write-Host "OK 窗口标题：$($found.MainWindowTitle)（体积 $sizeMb MB，启动 $elapsed s，PID $($found.Id)）"
Stop-OwnPhotoPrint
exit 0
```

- [ ] **Step 6: 跑验收脚本**

Run: `powershell -ExecutionPolicy Bypass -File .\_lab\check_exe.ps1`
Expected: `OK 窗口标题：相片打印助手（… MB，启动 … s，PID …）`，exit 0。
需带交互桌面的机器；headless 会话下 `MainWindowTitle` 枚举间歇（有时命中、有时恒空而 FAIL），属环境非脚本（见 ㉕）。

- [ ] **Step 7: 提交**

```bash
git add requirements-build.txt build_exe.ps1 _lab/check_exe.ps1 tests/test_build_scripts_encoding.py .gitignore
git commit -m "build: PyInstaller 单文件 exe 构建与启动验收脚本"
```

---

### Task 10: 最终验收与文档

**Files:**
- Modify: `README.md`
- Modify: `.superpowers/sdd/progress.md`（台账，不入库）

**Interfaces:**
- Consumes: T1–T9 的全部产出
- Produces: 无代码接口；一份可复跑的验收记录

- [ ] **Step 1: 三条基础验收全跑**

```bash
python -m pytest tests/ -q
python _lab/m1m2_check.py
```

Run: `powershell -ExecutionPolicy Bypass -File .\_lab\check_exe.ps1`
Expected：
1. 测试全绿（145 原有 + 新增约 40 条）
2. `m1m2_check` 12 条全 OK、exit 0
3. exe 输出 `OK 窗口标题：相片打印助手`、exit 0

- [ ] **Step 2: GUI 与 CLI 像素一致性（机器化）**

创建 `_lab/check_gui_cli_parity.py`：

```python
"""GUI 与 CLI 必须出同一张图：共用 jobs 编排的机器化验证。

同时钉住导出遮罩口径：两边产物的四边都不得是 (210, 210, 210)。
测试图本脚本自造，不依赖任何已存在的目录。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

# 本目录脚本以 `python _lab/xxx.py` 直跑时 sys.path[0] 是 _lab/、非仓库根，
# 需显式把根加进来（与 m1m2_check.py 同法），否则 `import photoprint` 当场失败。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

from photoprint import jobs  # noqa: E402
from photoprint.core import store  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "_lab" / "out"
DPI = 300.0


def make_photos(tmp: Path):
    paths = []
    for i in range(2):
        p = tmp / f"p{i}.jpg"
        Image.new("RGB", (1200, 800), (200 - 60 * i, 90, 40 + 50 * i)).save(p)
        paths.append(str(p))
    return paths


def gui_page(paths):
    """界面走的那条路：build_job + 单页 render。"""
    st = store.Store()
    st.load()
    photos = [jobs.load_photo(p) for p in paths]
    job = jobs.build_job(st, photos, "A4", "3R", bleed_mm=3.0)
    return job.render(0, DPI, show_mask=False)


def cli_page(paths, tmp: Path):
    """CLI 走的那条路：子进程跑真实命令行，不碰内部函数。"""
    out = tmp / "cli.png"
    subprocess.run([sys.executable, "-m", "photoprint.cli", "--photos", *paths,
                    "--sheet", "A4", "--cell", "3R", "--dpi", str(int(DPI)),
                    "--out", str(out)], check=True, cwd=str(ROOT))
    return Image.open(out)


def edge_is_clean(img) -> bool:
    w, h = img.size
    return (img.getpixel((3, h // 2)) != (210, 210, 210)
            and img.getpixel((w // 2, 3)) != (210, 210, 210))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        paths = make_photos(tmp)
        a, b = gui_page(paths), cli_page(paths, tmp)
        same_size = a.size == b.size
        same_pixels = same_size and list(a.getdata()) == list(b.getdata())
        clean = edge_is_clean(a) and edge_is_clean(b)
        a.save(OUT / "parity_gui.png")
        b.save(OUT / "parity_cli.png")
    print(f"同尺寸 {same_size} · 同像素 {same_pixels} · 四边无遮罩 {clean}")
    return 0 if (same_size and same_pixels and clean) else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

Run: `python _lab/check_gui_cli_parity.py`
Expected: `同尺寸 True · 同像素 True · 四边无遮罩 True`，exit 0。
不一致就是两个出口漂移，先查 T3 的 `build_layout` 与 T4 的转发是否改了参数顺序。

- [ ] **Step 3: 更新 README**

把 README 的“安装与运行”小节换成下面内容（保留原有内核命令，新增界面与 exe）：

```markdown
## 安装与运行
依赖：Pillow（读图/渲染）、pywin32（GDI 直打）、img2pdf（等尺寸 PDF）、pytest（测试）、PySide6（界面）
pip install -r requirements.txt

### 图形界面
python -m photoprint.app          # 选照片 → 选纸张/格子 → 预览 → 导出 PDF
### 单文件 exe
.\build_exe.ps1                   # 产出 dist\PhotoPrint.exe（需联网装 pyinstaller）
.\_lab\check_exe.ps1              # 启动验收

### 命令行
python -m photoprint.cli --photos 1.jpg 2.jpg 3.jpg 4.jpg --sheet A4 --cell 3R --out _lab/out/page.png
python -m photoprint.cli --print 需要 --printer；PowerShell 下 `--photos *.jpg` 不会展开，
请逐个列出或用 `(Get-ChildItem *.jpg).FullName`
python -m pytest -q            # 全部几何断言
python _lab/m1m2_check.py      # 本机可验证的端到端证据
```

同时在“已知物理限制”后补一行：

```markdown
- 导出产物（PNG/PDF）不含不可印区灰遮罩；预览里看到灰边是提醒，不是成品的一部分（调试用 `--mask`）。
```

- [ ] **Step 4: 台账记录**

在 `.superpowers/sdd/progress.md` 追加 M3-GUI 的任务链路、提交区间与验收输出（台账不入库）。

- [ ] **Step 5: 提交**

```bash
git add README.md _lab/check_gui_cli_parity.py
git commit -m "docs: 界面与 exe 用法、导出遮罩口径；补 GUI/CLI 一致性脚本"
```

---

## 计划自审记录

- **Spec 覆盖**：第 1–12 节逐节对应到任务——范围§1→T3/T7、架构§2→T3/T6/T7、界面§3→T7、
  接口§4→T3、偏移几何§5→T1/T2、遮罩§6→T2/T4/T7、错误处理§7→T6/T7、持久化§8→T5/T7、
  打包§9→T8/T9、测试§10→各任务 Step 1、验收§11→T10、遗留§12→无任务（有意不做）。
- **与 spec 的三处有意偏差**（均已写进代码注释）：① `Job` 吃 `offset_pct` 而非
  `offset_mm`，因为百分比→mm 的换算是逐格几何决策，必须留在 `core`（T3 评审 I-1）；
  ② `Job.note` 两档（白边与出血）都按 `margin_source` 带上边距来源，与 cli 的逐字
  冻结文案不同一句（T3 评审 I-2 + round-2 I-1，用户裁决：界面要说清证据从哪来，
  cli 历史输出不得变）；③ `last_job` 存 `mode_index`
  而非 `mode`，避开“自动”档是 `None` 的反序列化歧义。
- **T3 round-2 评审后的两处计划内修正**：④ 混合朝向页的逐格测试加第二个探针，
  同时挡住“按首格换算”与“按整纸换算”两支（单探针时两种错写法长得一样）；
  ⑤ T4 新增 Step 4 退役与 cli 的两条对拍测试——cli 变薄转发后对拍就是自己比自己。
- **T4 开工时的两处计划内修正**：⑥ 两条遮罩测试的像素探针从 `(3, ·)`/`(·, 3)`
  改成 `(1, ·)`/`(·, 1)`，断言同时从 `!= (210,210,210)` 换成 `== (255,255,255)`：
  dpi 25.4 下 A4 的遮罩带只覆盖 0..2 像素（矩形右下角减 1），原坐标探的是带外，
  于是一条恒真一条恒假——导出没关遮罩也报不了；⑦ Step 3 的 import 行去掉 `specs`
  （使用点全在被删的函数体内，照抄会留一个未用 import），`Image` 随 `load_photo`
  搬走一起删。两处均经 `.superpowers/sdd/check_t4_plan_verbatim.py` 逐行校对。
- **T4 各轮评审后的六处计划内修正**（⑧⑨⑩⑪ 出自 round-1，⑫ 出自 round-2，
  ⑬ 出自 round-3）：⑧ `tests/test_cli.py` 加 autouse 的
  `_isolated_store`——`cli.main` 自己 `store.Store()` 读 `%APPDATA%`，不隔离则
  测试钉的边距数字取决于开发机配置（T6/T7 的 `MainWindow` 同样用默认路径，
  界面校准后会连带把 pytest 跑红）；⑨ 逐字冻结锁改钉整行（含“每页 N 格 /
  共 M 页”，本轮这两个量换了来源）并用 `verify_t4_cli_parity.py` 与重构前的
  cli 逐字节对拍，不再只靠新测试自证；⑩ 薄转发落地后 `jobs.build_layout` 里
  “两边仍是两份实现”的注释成了假话，随 T4 改写；⑪ 顶缘遮罩探针避开 105mm
  列缝（`w//2` 正好是格缝）；⑫ 对拍退役后 `gap_mm`/`bleed_mm` 这两个相邻同
  类型位置参数的转发映射没了守卫（实测互换后 34 条仍全绿），
  `test_build_plan_jobs_is_still_positional` 补钉格子几何
  `(cells[0].w_mm, cells[1].x_mm) == (95.0, 105.0)`，互换时实测变
  `(89.0, 106.5)` 当场红（round-2 发现；`w_mm` 只随 bleed 变、`x_mm` 只随 gap 变，
  两条合起来在该邻域内对 (gap, bleed) 是一一映射）；⑬ 同测试首句里的“既有脚本”
  已无存在（`_lab/` 无调用点，对拍调用随 Step 4 退役），改为本文件 6 处调用。
  ⑫⑬ 已经 round-3 复审 Approved（M-R2-1 已修，变异注入实测仅该一条变红）。
- **T5 开工时的变异检查补的四条测试（⑭）**：`get_last_job`
  的形状守卫在简报给的 5 条下是**删了也不红**的死代码——`load()` 已先把磁盘
  上的坏值降级成 `{}`，灌磁盘的测试根本走不到 get 的闸上（第一轮实测存活）。
  另有三处无断言的口头承诺：`set_last_job` 的 `dict(job)` 副本、docstring 里
  “不碰 overrides 与 user_sizes”、以及“降级发生在读盘时”本身。
  补 `test_get_last_job_guard_survives_dirty_raw`（直接把 raw 弄脏）、
  `test_set_last_job_does_not_alias_caller_dict`、
  `test_set_last_job_only_touches_its_own_slot`、
  `test_load_degrades_non_dict_last_job` 四条，各杀一个变异；本任务净新增
  9 条测试（test_store.py 16→25，全量 180→189），
  `mutate_gui_t5.py` 7 个变异全有效，`check_t5_plan_verbatim.py` 缺失 0 行。
- **T5 round-1 评审的 I-1 修正（⑮）**：`test_set_last_job_only_touches_its_own_slot`
  只调 `override_margins`，`raw["user_sizes"]` 在 before/after 都是 `[]`（恒等
  快照），“`set_last_job` 顺手清空 user_sizes”这类串位变异当场存活。修法：
  在 `override_margins(...)` 之后、`before = json.dumps(...)` 之前补一条
  `add_user_size(...)` 把 user_sizes 弄非空，使快照比对真承重（V8 实测变红、
  还原后 25 条仍绿）；生产代码不动。顺带把成品里误置末尾的
  `test_save_failure_propagates_but_memory_still_effective` 上移到第 5 位，
  使文件顺序与计划逐字块一致，“上块末尾四条是补的”重新成立。
- **T7 开工时的两处计划内部矛盾修正（⑯）**：
  （a）`_build_ui` 原逐字块把 `cell_box` 默认落在下拉首项，而
  `CELL_PRESETS[0]=ID1`，与 spec/Step 5 手工核对“默认 A4/3R”矛盾，
  `test_page_navigation`（5 张 A4+3R=2 页）直接变红。修法：填充
  循环后补 `setCurrentIndex(max(0, findData("3R")))`，意图明确为默认 3R。
  （b）`_settle` 原逐字块用 `rounds=60` 的无参 `processEvents()` 忙轮询，
  offscreen 下跨线程 `quit` 回投送达慢（隔离探测实测需 ~134 轮），
  `test_window_starts_with_preview_and_status` 确定性失败 5/5。根因在测试
  泵送方式（产品代码正确：真实应用有自转事件循环），修法：改为带
  `maxTime` 的 `processEvents(QEventLoop.AllEvents, 50)` + 墙钟 `QElapsedTimer`
  时间预算，事件一到立刻返回、超时才判挂；断言不放宽。
  （c）计列原逐字测试都不关窗口：除 `test_window_starts`（经 `_settle`
  泵停线程）外，其余 6 条只 `_refresh` 起了渲染线程却不收尾，线程完成
  后只把 quit 排队到主线程、无人泵则不停；窗口随进程退出被析构时
  线程还在跑 → 解释器硬崩（0xC0000409），退出码非零（实测原测试即使打印
  8 passed 仍 RC=0xC0000409）。新增 autouse `_no_leaked_threads` fixture：
  收尾先 stop debounce（否则泵送会触发新的 250ms 延迟渲染又起线程），再
  泵到现有线程全停，最后 close 触发 closeEvent 里的 quit+wait 兜底（连跑
  15 次 RC=0）。均回写进计划块。
- **T7 round-1 评审的修复波（⑰）**：CodeReview round-1 独立核实后确认 4 项，
  逐条已修并回写 Step 3 块、补 3 条承重测试、变异表扩到 10 点全杀：
  （C1）`closeEvent` 未 `stop` debounce——改滑块后 250ms 内关窗，debounce 仍会
  fire 起新线程绕过收尾，触发 "QThread: Destroyed while running" 硬崩（实测复现）；
  修法：closeEvent 先 `self._debounce.stop()`。
  （I2）过期帧竞态：慢线程迟到的 `succeeded` 回投会覆盖新页。修法：`_gen`
  代际号，`_on_preview`/`_on_render_failed` 丢弃 `gen != self._gen` 的回投；
  `_retire_threads` 对 `wait` 超时的线程留引用进 `_stale`，防在跑线程被回收崩溃。
  （I3）`export_to` 的 `show_mask`/`dpi` 无测试承重——临时把它改成 `show_mask=True`
  且用 `PREVIEW_DPI`，原 8 条全过（真缺口）。修法：补 `test_export_passes_selected_dpi_and_no_mask`
  用 spy 断言 `show_mask is False and dpi == 300.0`（X1/X2 各杀一发）。
  （I4）`_restore_last_job` 对 `offset_pct` 裸 `int()`——坏配置（如 `["a", None]`）
  在 `__init__` 抛 ValueError 阻塞启动（实测复现）。修法：try/except 后保持滑块默认 0，
  与其余字段降级同口径。全局约束“异常一律收敛不外抛”正是被 I4 破坏、本轮修复。
  说明：I2 的代际/留引用是竞态防御，预览实测 ~11ms、测试造不出确定性的慢线程
  迟到时序，故不入变异表（同 T6 M4 已知冗余处理）。
- **T7 round-2 复审的修复波（⑱）**：CodeReview round-2 实测复核后确认，逐条已修并
  回写 Step 3 块、补 5 条测试、变异表扩到 16 点全杀：
  （I5）round-1 的 I4 只堵了 offset_pct，同函数/同全局约束还有三条外抛路（均实测复现）：
  坏 `photo_paths`（不可选代）抛在 `__init__`；`offset_pct=[Infinity,0]` 的 `int(inf)`
  抛 `OverflowError`（except 只接 TypeError/ValueError）；坏 `out_dir`（非字符串）的 `Path` 抛
  在 `save_last_job`/`_start_dir`。修法：photo_paths 加 isinstance 防御、except 补 OverflowError、
  `_last_out_dir` 加 isinstance + try/except。
  （I8）closeEvent 退休用默认 2000ms 超时会把未停线程留进 `_stale`，而 `_stale` 是实例
  属性、随窗口析构即释放→那时丢引用同样会崩。修法：`_retire_threads(timeout)` 参数化，
  关窗收尾传 `None` 无上限等到底（渲染有限、值得等）。
  （I6）代际守卫与 keep.append 此前零承重：报告以“造不出竞态”为由未入变异表，但混淆了
  “复现竞态”与“测守卫”——守卫是纯函数式调用，直接 `_on_preview(img, gen=self._gen-1)` 与
  注 FakeThread 进 `_stale` 就能确定性钉住（不碰真线程、不孤儿它）。`gen` 改为必填位置参数
  （M1，去掉 `gen=None` 可静默绕过的口子）。修后 T7 16 passed、全量 210 passed RC=0。
  （M2）`_build_ui` 注释“3R 已不在预设里”与事实相反（3R 在 PAPER_PRESETS）→改为 findData 必命中。
  变异表新增 I5a/I5b/I5c/I6a/I6b/I8 六点全杀（共 16）；_on_render_failed 的 gen 判断无测试能造
  慢线程失败迟到时序，仍不入表（同 T6 M4）。
- **T7 round-3 复审的修复波（⑲）**：CodeReview round-3 判 I5/I6/I7/I8/M1/M2/M4 全关、
  Spec ✅，但揪出 W1——同一函数、同一“异常一律收敛不外抛”约束被第四次破坏：round-2 的
  I5 只把 `int()`/`float()` 转换纳进 try/except，而 `setValue(huge)`（喂给 shiboken C int
  溢出）与 `float(huge_int)` 都在护栏之外（四条路径均实测复现 OverflowError 出 __init__）。
  不再打地鼠，改结构性收敛：新增 `_safe(fn)` 护栏，`_restore_last_job` 里每一处控件写入
  （_select_by_data/mode_box/gap·bleed 的 setValue/dpi/offset）一律过 `_safe`，捕获
  TypeError+ValueError+OverflowError，使这一整类“坏数值配置卡启动”彻底终结而非第五次补丁。
  offset 的 try/except 裸转改写为 `_apply_offset` 经 `_safe` 调用。补测：`test_bad_numeric_configs_do_not_block_startup`
  参数化 gap/bleed/dpi/offset 四类超大值不卡启动（W1a 杀）、`test_stale_generation_render_failed_is_dropped`
  钉住 _on_render_failed 的代际守卫（S2，此前因“造不出竞态”未测，实则纯函数式调用可确定钉）；
  FakeThread 加 quit_calls 计数（S1，证 _retire_threads 先 quit 再 wait）。变异表重写并扩到 18 点
  全杀（I4 锚点改指 _safe 包裹、I5c 缩进改到 _safe 的 except、新增 W1a/S1）。修后 T7 21 passed、
  全量 215 passed RC=0、逐字校对 0 缺失。_retire_threads 的超时留引用（I6b）仍靠 keep.append。
- **T8 实现期与 round-1 复审的修正（⑳）**：
  （实现期两处）① 计划自带 `test_write_appends_instead_of_overwriting` 的
  `count("KeyError")==2` 恒不成立——`format_exception` 每条把 KeyError 输出两遍（源码行 +
  异常头），两次追加实得 4；改数 `"Traceback (most recent call last)"` 与 `"KeyError: 'sheet_key'"`
  各 == 2（直读“追加两条”意图、不受排版影响）。② 计划两个真缺口：`install` 用例名叫
  both_hooks 却只驱动 sys.excepthook（删 threading 钩子行仍绿）、`write` 的 `mkdir(parents=True)`
  无测试触达（去 mkdir 仍绿）；各补承重分支（`types.SimpleNamespace` 驱 threading.excepthook、
  `test_write_creates_missing_parent_dir`）。
  （round-1 I-1）CodeReview 实测确认全局约束“异常一律收敛不外抛”在 `write` 上未穷尽：
  `target = Path(path) if path else log_path()` 在 try 外（`write(exc_info, 5)` → Path(5) TypeError 外抛）、
  `except OSError` 偏窄（畸形 exc_info 如 `"oops"`/`(ValueError,)`/`(ValueError,"x")` 的
  TypeError/ValueError 穿透）。修法与 T7 W1 同构：路径构造/建目录/格式化/编码全纳入 try，
  兜底 `except Exception`（不捕 BaseException 以放行 KeyboardInterrupt/SystemExit）+ `errors="replace"`
  挡 UnicodeEncodeError。补 `test_write_never_raises_on_malformed_input` 参数化 5 类畸形入参只返 None。
  变异表扩到 10 点（C6 改测 except 缩回 OSError、新增 C9 测 Path 移出 try）。修后 T8 11 passed、
  全量 226 passed RC=0、逐字校对 0。round-1 Minor（`run` 的 `sys.argv[:1]` 丢 Qt 参数、install 返回值与
  每异常重评 log_path 的对偶、write 无 `-> Path | None` 注解）：前者 plan-mandated（GUI exe 故意不透传
  CLI 参数）、后两项计划 Interfaces 与参考代码自身不一，非实现偏差，登台账交终审。
- **T8 round-2 复审的修正（㉑）**：round-2 确认 I-1 已穷尽闭合（write 无逃逸路径，逐条
  枚举 Path/mkdir/format/编码/close 及 RecursionError 均收敛；`return target` 无未绑定风险；
  不捕 BaseException 与文档串一致），但发现 round-1 我新加的 `test_write_never_raises_on_malformed_input`
  自身污染真目录（I-A，实测复现）：前四条传 `bad_path=None` 走 `log_path()` → 真
  `store.default_path()`，`mkdir`+`open(append)` 在 `format_exception` 报错前已建出真
  `%APPDATA%\PhotoPrint\error.log`（与用例文档串“不污染”声明相反）。修法：`monkeypatch`
  把 `store.default_path` 打到 `tmp_path`，既保留 path=None 分支收敛覆盖又不落真目录。顺手
  补 round-2 Minor M-1 的空档：`errors="replace"` 无测试守（删该行仍全绿），新增
  `test_write_survives_lone_surrogate` 喂孤立代理项、断言 write 返路径且 traceback 行落地（替成
  `?`、非 `�`——UTF-8 replace 的真实行为）。变异表加 C10（去 errors=replace）共 11 点全杀。
  round-2 判定 install line42 `Path(path)` 为 plan-mandated、不在“日志写失败不反抛”射程（主语是
  write、且唯一调用点 `install()` 不传 path），维持 Minor 不阻塞。修后 T8 12 passed、全量回归 RC=0。
- **T8 round-3 复审（Approved）与 M-2 加固（㉒）**：round-3 实测确认 I-1/I-A/M-1 均闭合、
  无新 Critical/Important，Spec与质量皆 Approved。唯 M-2（评审标 CONSIDER 不阻塞）：
  I-A 的两行 monkeypatch 本身不承重——删掉它们测试仍全绿、却默默把污染改回来（变异表
  盖不到，属测试侧属性）。采纳一行断言守卫：`if bad_path is None: assert (tmp_path/…/error.log).exists()`，
  既钉住隔离不被动回退、又坐实 path=None 分支真走到了 tmp_path。实测删 patch 后该用例转 RC=1。
  产品代码 crashlog.py 本轮未改。
- **T9 打包实现期的环境适配（㉓）**：两个 `.ps1` 脚本含中文注释与全角标点（：（）），
  实跑发现 Windows PowerShell 5.1 读**无 BOM 的 UTF-8** 会按系统 GBK 码页解码、全角字符
  打断字符串字面量解析（首跑 `build_exe.ps1` 在 line34 `Write-Host "OK 产物：…"` 直接报
  `字符串缺少终止符` ParserError，根本没进到 venv）。修法：两个 `.ps1` 存为 **UTF-8 with BOM**
  （内容逐字不变、只换编码），5.1 才正确按 UTF-8 读。重建后实跑 `build_exe.ps1 -Clean` 成功产出
  `dist\PhotoPrint.exe`（63.3 MB，Analysis-00.toc 已收 `qwindows.dll` 平台插件与 Qt6Core/Gui/Widgets）。
  体积低于 Step 4 预估的 100–180MB 但高于“<60MB 插件未收全”地板线：因应用只 import
  QtWidgets/QtGui/QtCore/QtNetwork，PyInstaller 按 import 收集、不带 WebEngine（Step 4 预估已据此订正）。
  另：外层 `2>&1 | Tee-Object` 管道偶发 ExitCode=1 是 pip/PyInstaller 把 INFO 写 stderr 触发本环境
  `$ErrorActionPreference=Stop` 的假报错，脚本本体跑到末行 Write-Host 未抛。
- **T9 round-1 修复波（㉔）**：评审推翻了我初版 ㉓“check_exe FAIL 属无交互 window station 环境限制”的结论——
  实测不成立。真相是 `check_exe.ps1` 有真实缺陷：PyInstaller onefile 是“父引导进程 + 子功能进程”，
  窗口属子进程，而脚本按 `Start-Process -PassThru` 返回的**父 PID** 取 `MainWindowTitle`（引导进程恒无窗口，
  任何机器上都恒空）→ 轮询 30 次必 FAIL。我独立复核：同会话按**映像名**轮询 `Get-Process -Name PhotoPrint`，
  子进程 PID 的 `MainWindowTitle` 确为“相片打印助手”，连跑 3 次均 5–7s 命中、收尾残留 0。修法：check_exe 改按名
  轮询、起跑前先杀残留 PhotoPrint（防上轮孤儿被本轮秒匹配假阳性，评审 I-B2）、两条退出路径都按名清进程、FAIL
  消息带存活/退出态以区分“崩/退”与“无窗口”（M-B3）。同时 `build_exe.ps1` 补 `$LASTEXITCODE` 检查与产物新鲜度
  判定（原生命令非零退出不被 Stop 拦下、且默认不删 dist 会对着旧 exe 假报 OK，评审 I-B3）——重建实测产 63.3MB、
  验收真 OK。Step 3/4/5 计划正文与脚本已同步回写，逐字校对仍 0 缺失。
- **T9 round-2 修复波（㉕）**：round-1 的“验收真 OK”后经反复实测发现本会话窗口枚举**间歇可用**（同一 headless 会话
  曾连跑 3 次 5–7s 真 OK，稍后又 5 次全 FAIL、直接采样活子进程 20s `MainWindowTitle` 恒为 `''`/`Handle=0`）——
  说明按名修脚本是真修复（否则永不可 OK），但本环境无稳定交互桌面，Step 6 **不能在本会话稳定复现**，
  带桌面的真机 OK 仍归 Task 10/终审验证项。本轮采纳 round-2 评审两条新 Important：
  ① **I-2（round-1 把窄杀改成了宽杀）**：`check_exe.ps1` 改为“先快照已有 PhotoPrint PID、匹配与清理只认本轮新增”，
  不再按名全机 `Stop-Process`（`PhotoPrint` 即产品 exe 名，宽杀会掉用户自己实例、丢 `last_job` 落盘）——实测
  预开一个“外部”实例后跑 check_exe，外部实例全部存活、仅 check_exe 自己那批被清（但该探针只覆盖了
  “既存于快照”这一支，快照后新起者见 ㉖ TOCTOU）。补回
  “本轮进程全没即早退”（Minor-4，真崩不再白等 30s）。② **I-1（`$PSScriptRoot`↔CWD 两基准）**：`build_exe.ps1`
  给 PyInstaller 显式传 `--distpath/--workpath/--specpath` 锈定到 $root，免得从别处按绝对路径调用时产物落到 CWD
  dist 、而产物检查与 `-Clean` 锚 $root 导致错报。另采 M-B2 新加了 `tests/test_build_scripts_encoding.py`
  （.ps1 BOM 字节守卫，剥 BOM→RC=1）；已把它补进 Task 9 Files/Step 7 git add。回写 Step 3/5 块与 Step 6 预期（含 PID）。
  回归 228 passed（系统解释器 RC=0）；注：**勿用 `.venv-build` 解释器跑回归**（Qt 退出 fastfail 会 RC≠0 但用例全过）。
- **T9 round-3 修复波（㉖）**：round-3 复审确认 round-2 两条 Important 已闭、(A) Spec Approved，但新提 I-3：
  归属快照用“排除法”，只排除快照时已存在的实例；快照后至清理前（命中约 5–6s、走 FAIL 则满 30s）新起的
  外部 PhotoPrint 仍会被当成本轮 own → 匹配（假阳性 OK）与清理（误伤）两向都可能。评审给的定级意见是“收紧
  措词+登台账即可降为 Minor”（不改归属算法）。已执行：① L12 注释写实 TOCTOU 窄窗；② 清理改“先
  `CloseMainWindow()` 礼貌关窗（走 closeEvent 落 last_job）、2s 后仍未退才强杀”→ 最坏情况从“强杀丢数据”降为
  “被礼貌关窗”；③ 开头打印既存实例数并明写“历史孤儿不自动回收、需手工清”（M-B2 孤儿累积）。回写 Step 5 逐字
  块。登台账遗留交 Task 10/终审：A-1——spec §9 要求“实测确认 img2pdf/Pillow 无遗漏 + exe 真能出 PDF”尚未坐实
  （现仅 qwindows/Qt6* 有收集凭证），且 63.3MB 低于 spec §9 原 100–180MB、Step 4 就地订正未回同步 spec；
  这两条（加 exe 导出 PDF 实测 + spec §9 区间/证据二选一同步）归 Task 10。M-B1（`.gitignore` `*.spec` 全域偏宽）：
  保留计划逐字选择，若后续需入库手写 spec 再收窄为 `/PhotoPrint.spec`。
- **T9 round-4 确认性复审（㉗）**：round-4 给 (A) Spec Approved、(B) Approved（I-3 正式降为已声明 Minor 残余），
  但附本轮唯一新真实缺陷 W-1（SHOULD FIX、不阻塞）：`Stop-OwnPhotoPrint` 第一阶段 `foreach { [void]$proc.CloseMainWindow() }`
  对“枚举后已自行退出”的对象抛 `MethodInvocationException`（本会话实测：活而无窗口对象返回 False 不抛、
  已退对象抛“进程已退出…”），且 **.NET 方法异常不受 `-EA SilentlyContinue` 管辖（实测连 `Continue` 也照样终止），必须 try/catch**。
  若不修：清理中途抛→本轮 own 残留→落进下次 `$before` 被永久豁免、并被“历史孤儿”提示掩盖。修法（一行守卫，
  第二阶段已用 HasExited 保护、无需改）：`if (-not $proc.HasExited) { try { [void]$proc.CloseMainWindow() } catch { } }`。另 S-1：
  TOCTOU 措辞从“含整个轮询窗口”改为“从快照起到清理二次枚举为止（≈轮询 30s + 关窗 2s）”——二次枚举把暴露面延到
  关窗之后。回写 Step 5 逐字块（verbatim 仍 0）、两 .ps1 重编码保 BOM、`check_exe.ps1` 连跑两次走 FAIL 路径均干净退出 1、
  无异常、残留 0（本会话窗口枚举此刻不可用，带桌面 OK 归 Task 10）。round-4 既双 Approved，此波只清 SHOULD/CONSIDER，
  不再派 round-5。A-1 遗留交 Task 10（img2pdf/Pillow 收集 grep 凭证 + exe 导出 PDF 实测 + spec §9 区间与实测同步）。
- **占位符扫描**：无 TBD/TODO；每个代码步都给了完整可粘正文。
- **类型一致性**：`worker.start` 在 T6 定死“只组装不启动”，T7 `_render_async` 显式
  `self._thread.start()`；`build_job` 的关键字参数名 `offset_pct` 在 T3/T7/T10 一致。
