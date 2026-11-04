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
| `photoprint/core/render.py` | Modify | 新增 `place_rotated_dest` 纯函数；`render_page` 透传 `dx_mm/dy_mm` |
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
  `render.render_page(..., dx_mm: float = 0.0, dy_mm: float = 0.0)`；
  `render.offset_mm_for_cell(offset_pct, w_mm, h_mm) -> tuple[float, float]`

偏移的纸面语义要在两种模式下都成立，而 `crop.cell_crop_box` 对 `dx_mm/dy_mm` 的用法
并不相同（实测：FILL 挪的是取景窗 `crop_px`，dest 不变；FIT 挪的是 `dest_mm`）。同一
个 `dx_mm=+1` 在 FILL 下画面会往**左**走。因此渲染层必须按生效的裁切模式补一次反号：
FILL（含 `bleed_trim`，它的 `crop_mode` 也是 fill）取负，fit 不取负。

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
                               dy_mm=1.0)
    probe = (int(ix + iw / 2), int(iy + 4.0))
    assert base.getpixel(probe) == (255, 0, 0)      # 原画面覆盖
    assert moved.getpixel(probe) == (255, 255, 255)  # 下移 1mm 后露白
    tail = (int(ix + iw / 2), int(iy + 29.0))
    assert base.getpixel(tail) == (255, 255, 255)
    assert moved.getpixel(tail) == (255, 0, 0)


def test_dx_offset_moves_rotated_cell_picture_right_on_paper():
    """旋转格的纸面水平偏移必须真往右：旧转置写法会整体反号（终审 C1）。

    A4+4R 两格都是旋转格，纸面格子 152×102，旋转前目标 102×152；
    正方形照片 FIT 后为 102×102，纸面起点 x = 29+25 = 54（占 54..155）。
    dx_mm=+3 → 旋转前 dy=-3 → 纸面起点 x=57（占 57..158）。
    """
    a4, r4 = specs.find_spec("A4"), specs.find_spec("4R")
    plan = pack.pack(a4, r4, gap_mm=0.0, allow_rotate=True,
                     printable=specs.printable_rect(a4))
    assert [c.rotated for c in plan.cells] == [True, True]
    photo = Image.new("RGB", (100, 100), (255, 0, 0))
    args = (plan, [photo] * plan.count, a4, DPI, modes.FIT_TO_PRINTABLE)
    base = render.render_page(*args, show_mask=False)
    moved = render.render_page(*args, show_mask=False, dx_mm=3.0)
    assert base.getpixel((55, 95)) == (255, 0, 0)       # 起点左侧 1mm 仍在画内
    assert moved.getpixel((55, 95)) == (255, 255, 255)  # 右移 3mm 后露白
    assert base.getpixel((157, 95)) == (255, 255, 255)  # 原本右侧留白 25mm
    assert moved.getpixel((157, 95)) == (255, 0, 0)     # 移进来才见红


def test_fill_mode_offset_moves_picture_toward_paper_direction():
    """FILL 的 dx/dy 在 crop 里挪的是取景窗，画面在纸面上反向；
    界面偏移是纸面语义，渲染层须按模式补一次反号。"""
    a4, plan = _a4_id1_plan()
    photo = Image.new("RGB", (200, 100), (255, 255, 255))
    photo.paste(Image.new("RGB", (40, 100), (255, 0, 0)), (80, 0))  # 中央红带
    ix, iy, iw, ih = plan.cells[0].inner_mm()
    y = int(iy + ih / 2)
    args = (plan, [photo] * plan.count, a4, DPI, modes.FILL_PRINTABLE)
    low = render.render_page(*args, show_mask=False, dx_mm=-3.0)
    high = render.render_page(*args, show_mask=False, dx_mm=3.0)

    def first_red(page):
        return min(x for x in range(int(ix), int(ix + iw))
                   if page.getpixel((x, y)) == (255, 0, 0))

    assert first_red(high) > first_red(low)  # dx 为正 → 画面往纸面右边走


def test_offset_mm_for_cell_half_page_is_50_pct():
    """±50% 就是半格：ID1 内框 25×32 → 12.5 / 16.0mm。"""
    assert render.offset_mm_for_cell((50.0, -50.0), 25.0, 32.0) == (12.5, -16.0)


def test_offset_mm_for_cell_zero_is_zero():
    assert render.offset_mm_for_cell((0.0, 0.0), 89.0, 127.0) == (0.0, 0.0)
```

- [ ] **Step 2: 跑到失败**

Run: `python -m pytest tests/test_render_offset.py -v`
Expected: FAIL — 前两条 `AttributeError: ... has no attribute 'place_rotated_dest'`；
中间三条（透传偏移的像素测试）`TypeError: render_page() got an unexpected
keyword argument 'dy_mm' / 'dx_mm'`；后两条 `AttributeError: ... 'offset_mm_for_cell'`

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
    按格子内框而非纸张尺寸换算，否则同一页两种朝向的格子会偏移失真。
    """
    return (offset_pct[0] / 100.0 * w_mm, offset_pct[1] / 100.0 * h_mm)
```

把 `render_page` 的签名改为（只加两个参数，其余不动）：

```python
def render_page(plan, photos, sheet, dpi, mode, show_mask=True,
                show_cut_lines=True, borderless_active=False,
                dx_mm=0.0, dy_mm=0.0):
```

把循环里从 `target_w, target_h` 到转置那一段替换为：

```python
        target_w, target_h = (oh, ow) if cell.rotated else (ow, oh)
        # 界面偏移是纸面语义，旋转格须先换算到旋转前坐标再交给 crop
        in_dx, in_dy = crop.rotate_offset(dx_mm, dy_mm) if cell.rotated \
            else (dx_mm, dy_mm)
        if cm == crop.FILL:
            # FILL 的 dx/dy 挪的是取景窗，画面在纸面上会反向；fit 挪的是
            # 落位矩形，本身已是纸面语义，故只在 fill 档补一次反号
            in_dx, in_dy = -in_dx, -in_dy
        pl = crop.cell_crop_box(photo.width, photo.height, target_w, target_h,
                               cm, dx_mm=in_dx, dy_mm=in_dy,
                               ppmm=units.ppmm(dpi))
        piece = photo.crop(pl.crop_px)
        # dest_mm 是旋转前的目标矩形：转 90° 后宽高互换，落位也要换轴
        if cell.rotated:
            piece = piece.transpose(Image.ROTATE_270)
            dx, dy, dw, dh = place_rotated_dest(pl.dest_mm, target_h)
        else:
            dx, dy, dw, dh = pl.dest_mm
```

同时删掉原来那段"这是「转置」而非通用 90° 旋转映射"的行内注释（已被
`place_rotated_dest` 的文档取代）。

- [ ] **Step 4: 跑到通过**

Run: `python -m pytest tests/test_render_offset.py -v`
Expected: 7 passed

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
  - `jobs.Job`（dataclass：`plan / mode / sheet / photos / offset_pct / offset_mm / borderless_active`，
    属性 `count / page_count / note`，方法 `render(page_index, dpi, show_mask=False)`）
  - `jobs.build_job(st, photos, sheet_key, cell_key, *, gap_mm=0.0, bleed_mm=3.0, mode=None, offset_pct=(0.0, 0.0), borderless_active=False) -> Job`
  - `jobs.render_all(job, dpi, show_mask=False) -> list[Image]`
  - `jobs.load_photo(path) -> Image`（从 `cli.py` 搬来）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_jobs.py`：

```python
"""编排层必须与重构前的 cli 逐字段等价，且不含 print/GUI 依赖。"""
import inspect

import pytest

pytest.importorskip("PIL", reason="需要 Pillow")

from PIL import Image  # noqa: E402

from photoprint import cli, jobs  # noqa: E402
from photoprint.core import modes, store  # noqa: E402


@pytest.fixture
def st(tmp_path):
    s = store.Store(tmp_path / "papers.json")
    s.load()
    return s


def _photos(n, color=(200, 30, 30)):
    return [Image.new("RGB", (100, 100), color) for _ in range(n)]


@pytest.mark.parametrize("sheet,cell,gap,bleed,mode", [
    ("A4", "3R", 0.0, modes.DEFAULT_BLEED_MM, None),
    ("A4", "ID1", 2.0, modes.DEFAULT_BLEED_MM, None),
    ("A4", "4R", 0.0, modes.DEFAULT_BLEED_MM, None),
    ("3R", "3R", 0.0, 0.0, modes.FILL_PRINTABLE),
])
def test_build_layout_matches_legacy_cli(st, sheet, cell, gap, bleed, mode):
    plan_a, mode_a = cli.build_plan_jobs(st, sheet, cell, gap, bleed, mode, False)
    plan_b, mode_b = jobs.build_layout(st, sheet, cell, gap, bleed, mode,
                                       borderless_active=False)
    assert mode_a == mode_b
    assert plan_a == plan_b  # dataclass 逐字段相等


def test_build_job_counts_pages(st):
    job = jobs.build_job(st, _photos(5), "A4", "3R", bleed_mm=3.0)
    assert job.count == 4
    assert job.page_count == 2


def test_build_job_page_count_is_one_when_empty(st):
    """界面允许零照片：预览要有一张空格可看，不得除零或返回 0 页。"""
    job = jobs.build_job(st, [], "A4", "3R", bleed_mm=3.0)
    assert job.page_count == 1


def test_note_uses_legacy_wording_bleed(st):
    job = jobs.build_job(st, _photos(4), "A4", "3R", bleed_mm=3.0)
    assert job.note.startswith("需人工裁切：沿灰线切开后即为 89×127mm 成品")


def test_note_uses_legacy_wording_margins(st):
    job = jobs.build_job(st, _photos(4), "A4", "ID1", gap_mm=2.0)
    assert "未经真机校准" in job.note


def test_render_out_of_range_raises(st):
    job = jobs.build_job(st, _photos(4), "A4", "3R", bleed_mm=3.0)
    with pytest.raises(IndexError, match="页码越界"):
        job.render(1, 25.4)


def test_offset_changes_rendered_pixels(st):
    a = jobs.build_job(st, _photos(4), "A4", "ID1", gap_mm=2.0)
    b = jobs.build_job(st, _photos(4), "A4", "ID1", gap_mm=2.0,
                       offset_pct=(0.0, 50.0))
    assert a.render(0, 25.4).tobytes() != b.render(0, 25.4).tobytes()


def test_offset_pct_is_converted_by_cell_inner_size(st):
    """百分比按格子内框换算：ID1 内框 25×32，±50% → (12.5, 16.0)mm。"""
    job = jobs.build_job(st, _photos(4), "A4", "ID1", gap_mm=2.0,
                         offset_pct=(50.0, -50.0))
    assert job.offset_mm == pytest.approx((12.5, -16.0))
    assert job.offset_pct == (50.0, -50.0)


def test_render_all_covers_every_page(st):
    job = jobs.build_job(st, _photos(5), "A4", "3R", bleed_mm=3.0)
    pages = jobs.render_all(job, 25.4)
    assert len(pages) == 2


def test_jobs_module_has_no_print_and_no_gui():
    """窗口化打包后 sys.stdout 是 None；jobs 一旦被输出污染就会崩。

    注：这是“源码不含某字样”的守门断言，所以 jobs 的注释也不得写出
    被禁模块的名字，否则测试自己打自己。
    """
    src = inspect.getsource(jobs)
    assert "print(" not in src
    for banned in ("PySide6", "win32print", "win32ui", "win32con"):
        assert banned not in src
```

- [ ] **Step 2: 跑到失败**

Run: `python -m pytest tests/test_jobs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'photoprint.jobs'`

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


def load_photo(path):
    """读图并让 EXIF 方向生效，避免界面与打印各转一次。

    自 cli.py 搬来：界面也要读图，两处各写一遍会漂移。
    """
    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


def build_layout(st, sheet_key, cell_key, gap_mm, bleed_mm, mode,
                 borderless_active=False):
    """返回 (排版方案, 生效模式)。mode 为 None 时按默认映射决定。

    逻辑逐字来自 cli.build_plan_jobs，那条函数已改为本函数的薄转发。
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
    offset_mm: tuple[float, float] = (0.0, 0.0)
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
        """状态栏文案，口径与 cli 逐字一致。"""
        if self.mode == modes.BLEED_TRIM:
            inner = self.plan.cells[0].inner_mm()
            return (f"需人工裁切：沿灰线切开后即为 {inner[2]:.0f}×{inner[3]:.0f}mm 成品")
        m = self.sheet.margins
        return (f"将保留白边：依规格约 上{m.top}/下{m.bottom}/"
                f"左{m.left}/右{m.right}mm（未经真机校准）")

    def render(self, page_index: int, dpi: float, show_mask: bool = False) -> Image.Image:
        """渲染单页。show_mask 只在预览开，导出必须关（否则灰边进相纸）。"""
        if not 0 <= page_index < self.page_count:
            raise IndexError(f"页码越界：{page_index}（共 {self.page_count} 页）")
        i = page_index * self.count
        chunk = self.photos[i:i + self.count]
        return render.render_page(self.plan, chunk, self.sheet, dpi, self.mode,
                                  show_mask=show_mask,
                                  borderless_active=self.borderless_active,
                                  dx_mm=self.offset_mm[0], dy_mm=self.offset_mm[1])


def build_job(st, photos, sheet_key, cell_key, *, gap_mm=0.0,
              bleed_mm=modes.DEFAULT_BLEED_MM, mode=None,
              offset_pct=(0.0, 0.0), borderless_active=False) -> Job:
    plan, mode_eff = build_layout(st, sheet_key, cell_key, gap_mm, bleed_mm,
                                  mode, borderless_active=borderless_active)
    # 界面交来的是百分比（±50% = 最多挪半格）；换算本体在 core，本层只调用
    inner = plan.cells[0].inner_mm()
    offset_mm = render.offset_mm_for_cell(offset_pct, inner[2], inner[3])
    return Job(plan=plan, mode=mode_eff, sheet=st.resolve(sheet_key),
               photos=list(photos), offset_mm=offset_mm,
               offset_pct=tuple(float(v) for v in offset_pct),
               borderless_active=borderless_active)


def render_all(job: Job, dpi: float, show_mask: bool = False) -> list[Image.Image]:
    """CLI 用：等价于逐页调用 job.render，避免两边各写一套切页。"""
    return [job.render(i, dpi, show_mask) for i in range(job.page_count)]
```

- [ ] **Step 4: 跑到通过**

Run: `python -m pytest tests/test_jobs.py -v`
Expected: 13 passed（parametrize 4 条 + 其余 9 条）

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
- Test: `tests/test_cli.py`（追加 3 条）

**Interfaces:**
- Consumes: `jobs.build_layout` / `jobs.build_job` / `jobs.render_all` / `jobs.load_photo`
- Produces: `cli.build_plan_jobs(...)` 与 `cli.load_photo(path)` 保持历史签名不变（薄转发）

- [ ] **Step 1: 写失败测试**

在 `tests/test_cli.py` 末尾追加：

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
    """遮罩是界面诚实性用的，导出进相纸就是缺陷：四边不得是 210 灰。"""
    from PIL import Image

    out = tmp_path / "page.png"
    code = cli.main(["--photos", *_four_red_photos(tmp_path), "--sheet", "A4",
                     "--cell", "3R", "--dpi", "25.4", "--out", str(out)])
    assert code == 0
    img = Image.open(out)
    w, h = img.size
    assert img.getpixel((3, h // 2)) != (210, 210, 210)
    assert img.getpixel((w // 2, 3)) != (210, 210, 210)


def test_main_mask_flag_keeps_mask(tmp_path):
    from PIL import Image

    out = tmp_path / "page.png"
    code = cli.main(["--photos", *_four_red_photos(tmp_path), "--sheet", "A4",
                     "--cell", "3R", "--dpi", "25.4", "--mask",
                     "--out", str(out)])
    assert code == 0
    img = Image.open(out)
    w, h = img.size
    assert img.getpixel((3, h // 2)) == (210, 210, 210)


def test_build_plan_jobs_is_still_positional(st):
    """历史调用形状不得变：test_cli 与既有脚本都按 7 个位置参数调它。"""
    plan, mode = cli.build_plan_jobs(st, "A4", "3R", 0.0,
                                     modes.DEFAULT_BLEED_MM, None, False)
    assert plan.count == 4
    assert mode == modes.BLEED_TRIM
```

- [ ] **Step 2: 跑到失败**

Run: `python -m pytest tests/test_cli.py -v -k "mask or positional"`
Expected: 前两条 FAIL — `unrecognized arguments: --mask` 或四边仍为 `(210,210,210)`

- [ ] **Step 3: 改 `cli.py`**

把顶部 import 段与 `load_photo` / `build_plan_jobs` 替换为：

```python
from photoprint import jobs
from photoprint.core import modes, specs, store  # pack/render 不再由此层直接调用


def load_photo(path):
    """薄转发：读图实现已搬到 jobs，历史调用点不变。"""
    return jobs.load_photo(path)


def build_plan_jobs(st, sheet_key, cell_key, gap_mm, bleed_mm, mode,
                    borderless_active):
    """薄转发：保持 7 个位置参数与 (plan, mode) 返回的历史形状。"""
    return jobs.build_layout(st, sheet_key, cell_key, gap_mm, bleed_mm, mode,
                             borderless_active=borderless_active)
```

删除原 `build_plan_jobs` 函数体与 `_pages`，`build_parser` 里在 `--list-printers` 之前加一行：

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
    print(f"纸张 {sheet.label}，每页 {job.count} 格，共 {len(pages)} 页。{job.note}")
```

其余段落（`--out` 建父目录与"仅第一页"提示、`--pdf`、`--print`）保持原样不动。

- [ ] **Step 4: 跑到通过**

Run: `python -m pytest tests/test_cli.py -v`
Expected: 全部通过（含原 11 条 + 新 3 条）

- [ ] **Step 5: 全量回归 + 手工证据**

```bash
python -m pytest tests/ -q
python -m photoprint.cli --photos _lab/out/p.jpg --sheet A4 --cell 3R --dpi 25.4 --out _lab/out/t4.png
python -c "from PIL import Image; im=Image.open('_lab/out/t4.png'); print(im.getpixel((3, im.size[1]//2)))"
```
Expected: 最后一行不是 `(210, 210, 210)`。

- [ ] **Step 6: 提交**

```bash
git add photoprint/cli.py tests/test_cli.py
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

在 `tests/test_store.py` 末尾追加（文件已有 `json`、`pytest`、`store` 导入与 `tmp_store` fixture）：

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
```

- [ ] **Step 2: 跑到失败**

Run: `python -m pytest tests/test_store.py -v -k last_job`
Expected: FAIL — `AttributeError: 'Store' object has no attribute 'set_last_job'`

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
Expected: 全部通过（原有条目 + 新 5 条）

- [ ] **Step 5: 全量回归 + 提交**

```bash
python -m pytest tests/ -q
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


def _settle(window, qapp, rounds=60):
    """offscreen 下没有自转的事件循环，手动泵到渲染线程停下、信号投递完。"""
    for _ in range(rounds):
        qapp.processEvents()
        if window._thread is None:
            return
        if not window._thread.isRunning():
            qapp.processEvents()
            return
    pytest.fail("预览线程未在预期时间内停下")


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
    _fill(w, tmp_path, n=5)          # 5 张亍 A4+3R 是 2 页
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
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(1000)
        job, index = self.job, self.page_index
        self._thread, self._task = worker.start(
            lambda: job.render(index, jobs.PREVIEW_DPI, show_mask=True))
        self._task.succeeded.connect(self._on_preview)
        self._task.failed.connect(lambda msg: self._set_status(msg, error=True))
        self._thread.start()

    def _on_preview(self, image):
        pm = view.to_pixmap(image)
        self.preview.setPixmap(pm.scaled(self.preview.size(), Qt.KeepAspectRatio,
                                        Qt.SmoothTransformation))

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

    def _restore_last_job(self):
        job = self.st.get_last_job()
        if not job:
            return
        for key, box in (("sheet_key", self.sheet_box), ("cell_key", self.cell_box)):
            idx = box.findData(job.get(key))
            if idx >= 0:
                box.setCurrentIndex(idx)
        mode_index = job.get("mode_index")
        if isinstance(mode_index, int) and 0 <= mode_index < self.mode_box.count():
            self.mode_box.setCurrentIndex(mode_index)
        for key, box in (("gap_mm", self.gap_box), ("bleed_mm", self.bleed_box)):
            if isinstance(job.get(key), (int, float)):
                box.setValue(float(job[key]))
        if isinstance(job.get("dpi"), (int, float)):
            idx = self.dpi_box.findData(float(job["dpi"]))
            if idx >= 0:
                self.dpi_box.setCurrentIndex(idx)
        pct = job.get("offset_pct")
        if isinstance(pct, (list, tuple)) and len(pct) == 2:
            self.h_slider.setValue(int(pct[0]))
            self.v_slider.setValue(int(pct[1]))
        for p in job.get("photo_paths") or []:
            self.append_photo(str(p))      # 文件已删则走标红分支，不阻塞

    def _last_out_dir(self):
        d = self.st.get_last_job().get("out_dir")
        return d if d and Path(d).is_dir() else ""

    def _start_dir(self):
        return self._last_out_dir() or str(Path.home())

    def closeEvent(self, event):
        self.save_last_job()
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)
        super().closeEvent(event)
```

- [ ] **Step 4: 跑到通过**

Run: `python -m pytest tests/test_app_main_window.py -v`
Expected: 8 passed

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


def test_write_appends_instead_of_overwriting(tmp_path):
    p = tmp_path / "error.log"
    for _ in range(2):
        try:
            raise KeyError("sheet_key")
        except KeyError:
            crashlog.write(sys.exc_info(), p)
    assert p.read_text(encoding="utf-8").count("KeyError") == 2


def test_write_failure_returns_none(tmp_path):
    """日志路径是个目录时不得抛：日志不能反过来拖垮进程。"""
    assert crashlog.write((ValueError, ValueError("x"), None), tmp_path) is None


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
    """把 traceback 追加写入日志，返回日志路径；写失败返回 None。"""
    target = Path(path) if path else log_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write("".join(traceback.format_exception(*exc_info)) + "\n")
    except OSError:
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
- Create: `requirements-build.txt`、`build_exe.ps1`、`_lab/check_exe.ps1`
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

if (-not (Test-Path $venv)) {
    python -m venv $venv
}
$py = Join-Path $venv "Scripts\python.exe"
& $py -m pip install --upgrade pip
& $py -m pip install -r (Join-Path $root "requirements.txt")
& $py -m pip install -r (Join-Path $root "requirements-build.txt")

if ($Clean) {
    foreach ($d in "build", "dist") {
        $p = Join-Path $root $d
        if (Test-Path $p) { Remove-Item -Recurse -Force $p }
    }
}

# 入口是真实 .py 文件；--windowed 等于 --noconsole
& $py -m PyInstaller --noconfirm --clean --onefile --windowed --name PhotoPrint `
    --paths $root (Join-Path $root "photoprint\app\__main__.py")

if (-not (Test-Path (Join-Path $root "dist\PhotoPrint.exe"))) {
    throw "构建结束但未产出 dist\PhotoPrint.exe"
}
$mb = [math]::Round((Get-Item (Join-Path $root "dist\PhotoPrint.exe")).Length / 1MB, 1)
Write-Host "OK 产物：$root\dist\PhotoPrint.exe（$mb MB）"
```

- [ ] **Step 4: 跑构建**

Run: `powershell -ExecutionPolicy Bypass -File .\build_exe.ps1`
Expected: 末尾输出 `OK 产物：…\dist\PhotoPrint.exe（… MB）`，体积落在 100–180MB。
若体积低于 60MB，说明 PySide6 插件没收全，先查 `build\PhotoPrint\Analysis-00.toc` 里有无 `qwindows.dll`。

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
$p = Start-Process -FilePath $exe -PassThru

$found = $null
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    $candidate = Get-Process -Id $p.Id -ErrorAction SilentlyContinue
    if ($null -eq $candidate) { break }
    if ($candidate.MainWindowTitle -like "*相片打印助手*") { $found = $candidate; break }
}
$elapsed = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)

if ($null -eq $found) {
    Write-Host "FAIL 窗口未出现（体积 $sizeMb MB，等待 $elapsed s）"
    if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force }
    exit 1
}
Write-Host "OK 窗口标题：$($found.MainWindowTitle)（体积 $sizeMb MB，启动 $elapsed s）"
Stop-Process -Id $p.Id -Force
exit 0
```

- [ ] **Step 6: 跑验收脚本**

Run: `powershell -ExecutionPolicy Bypass -File .\_lab\check_exe.ps1`
Expected: `OK 窗口标题：相片打印助手（… MB，启动 … s）`，exit 0。

- [ ] **Step 7: 提交**

```bash
git add requirements-build.txt build_exe.ps1 _lab/check_exe.ps1 .gitignore
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

from PIL import Image

from photoprint import jobs
from photoprint.core import store

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
- **与 spec 的两处有意偏差**（均已写进代码注释）：① `Job` 吃 `offset_pct` 而非 `offset_mm`，
  因为百分比→mm 的换算是几何决策，必须留在 `core`；② `last_job` 存 `mode_index` 而非
  `mode`，避开“自动”档是 `None` 的反序列化歧义。
- **占位符扫描**：无 TBD/TODO；每个代码步都给了完整可粘正文。
- **类型一致性**：`worker.start` 在 T6 定死“只组装不启动”，T7 `_render_async` 显式
  `self._thread.start()`；`build_job` 的关键字参数名 `offset_pct` 在 T3/T7/T10 一致。
