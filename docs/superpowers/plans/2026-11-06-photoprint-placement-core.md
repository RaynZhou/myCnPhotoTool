# PhotoPrint 增量 2a（放置内核）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把"按列表下标顺序自动填充"换成"照片库 + 手动逐格放置"的内核：库/放置解耦、逐格旋转、命中几何、`last_job` 新 schema 与向后迁移，并为增量 2b 的拖放预留同一 `place()` 入口。

**Architecture:** 现有渲染本就是"下标≡格子、None≡空"，故放置模型只需物化成一条 `页数×每页格数` 的 PIL 列表交 `build_job`——`render_page`/`Job`/导出/打印零改动。命中几何与信箱缩放逆变换全落在 `core` 新增的三个纯函数里；GUI 层只上报点击点与控件尺寸。预览升级为可点击的 `PreviewView(QLabel)`。

**Tech Stack:** PySide6（QLabel/QListWidget/QPainter/QTest）、Pillow、pytest（offscreen）；分层 `photoprint/{core,app,jobs}`。

## Global Constraints

（每个任务的隐含前提，逐字取自 spec 与项目红线）

- 分层红线：`photoprint/app/` 禁一切 mm/像素/裁切几何运算，换算只在 `core`；`jobs.py` 禁几何、禁 Qt/win32、禁 stdout。
- 窗口化 exe 无控制台：任何异常一律收敛到状态栏，绝不让异常出界面（命中越界/空槽旋转/坏配置均 no-op 或降级，不裸抛）。
- `cli` 顺序填充逐字冻结、`_lab` parity 脚本不得转红：本增量只动 `app/` 与新增 `core` 纯函数，不改 `render_page`/`pack`/`cli` 既有行为。
- TDD：先写失败测试→跑红→最小实现→跑绿→变异验牙→全量回归→提交。变异用 SearchReplace 工具做（PowerShell 不支持 heredoc）。
- offscreen：新建 GUI 测试文件必须自带 session/autouse 收尾夹具 `_no_lealed_threads`（复刻 `tests/test_app_main_window.py`），否则进程退出 `0xC0000409` 硬崩。
- 无牙断言陷阱：验证 fit/旋转的测试图与格子必须**非正方**（如 400×200 图、宽≠高的视图），纯色/正方图旋转缩放不变会恒绿。
- 行为变更（本增量落地）：加入/导入库**不再自动进版面**；旋转从"逐图"改为"逐格"（作用于选中的格，`photo_rotations`/`_restore_rotations` 移除）。
- 提交说明：UTF-8 无 BOM；先 `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8`，用 python 写消息文件再 `git commit -F`。

---

## 文件结构（改动地图）

- 修改 `photoprint/core/render.py`：新增 `page_cells_px` / `_fit_rect` / `cell_index_at` / `cell_rects_view`（`_fit_rect` 私有）。
- 新建 `tests/test_render_hit_geometry.py`：三纯函数 headless 测试（`tests/test_render_geometry.py` 已被既有渲染输出测试占用，命中几何另起新文件不覆盖）。
- 新建 `photoprint/app/preview_view.py`：`PreviewView(QLabel)`——显示整页 pixmap + 描格框/高亮 + 点击发 `cellClicked(int 格内序)`。
- 新建 `tests/test_app_preview_view.py`：`PreviewView` offscreen 测试（含 `_no_leaked_threads`）。
- 修改 `photoprint/app/main_window.py`：数据模型 `pool`/`placements`/`cell_rot`/`_pages`/`_current_cell`/`_count_last`；`_rebuild_job` 物化 + 结构变更清空；`place`/`rotate_cell`/`clear_cell`/`_maybe_shrink_pages`；`_go_page` 增页/收缩 + 重置选中；`append_photo`/`_on_add_photos`/`import_folder` 不再自动排版；`_on_clear_photos` 清放置；`_on_rotate` 改逐格；`save_last_job`/`_restore_last_job` 新 schema + `_migrate_sequential`；预览切 `PreviewView`；`_on_cell_clicked` 接线；新增"清空格"按钮。
- 修改 `tests/test_app_main_window.py`：`_fill` 改为 append+顺序 place；`photo_paths`/`photos` 引用改 `pool`；逐图旋转测试与 `_restore_rotations` 系列改写为逐格/迁移语义；预览帧测试走 `PreviewView`。
- 修改 `tests/test_folder_import.py`：`w.photos` → `w.pool`（断言长度/None 占位）。
- 新建 `tests/test_placement.py`：放置内核 + 持久化 + 迁移的专项 GUI 测试（含 `_no_leaked_threads`）。

---

### Task 1: core 命中几何三函数

**Files:**
- Modify: `photoprint/core/render.py`（在 `_mask_bands` 之后追加）
- Test: `tests/test_render_hit_geometry.py`

**Interfaces:**
- Consumes: `units.mm_to_px`、`render_page` 已用的 `plan.cells`（每格 `.x_mm/.y_mm/.w_mm/.h_mm`）、`sheet.w_mm/.h_mm`；测试用 `jobs.build_job` 取真实 `plan`/`sheet`。
- Produces:
  - `page_cells_px(plan, sheet, dpi) -> (image_wh, rects)`，`image_wh=(int,int)`，`rects=[(x,y,w,h), …]` 图像像素坐标、与 `plan.cells` 等序。
  - `cell_index_at(cell_rects_px, image_wh, view_wh, pos) -> int | None`，`pos=(x,y)` 视图坐标，返回格内序（`[0,len(rects))`）或 `None`。
  - `cell_rects_view(cell_rects_px, image_wh, view_wh) -> [(x,y,w,h), …]` 视图像素坐标，与 `cell_index_at` 共用 `_fit_rect`。
  - `_fit_rect(image_wh, view_wh) -> (offset_x, offset_y, scale)`（模块私有）。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_render_hit_geometry.py`：

```python
"""core 命中几何：page_cells_px / cell_index_at / cell_rects_view。
全 headless；用非正方图像/视图，防无牙断言（fit 逆变换错也须转红）。"""
from PIL import Image  # noqa: F401  (确认可用即过；不直接绘图)

from photoprint import jobs
from photoprint.core import render


def _cell_rects():
    # 图像像素下 2×1 格：整页 400×200，两格各 200×200（非正方页 400×200）
    return [(0, 0, 200, 200), (200, 0, 200, 200)]


def test_page_cells_px_counts_and_within_image():
    job = jobs.build_job(_store_a4(), [], "A4", "5R")
    image_wh, rects = render.page_cells_px(job.plan, job.sheet, 300)
    assert len(rects) == job.count
    iw, ih = image_wh
    for (x, y, w, h) in rects:
        assert x >= 0 and y >= 0
        assert x + w <= iw + 1 and y + h <= ih + 1


def _store_a4():
    from photoprint.core import store
    import tempfile, pathlib
    d = pathlib.Path(tempfile.mkdtemp()) / "papers.json"
    st = store.Store(path=d)
    st.load()
    return st


def test_hit_center_of_each_cell():
    rects = _cell_rects()
    # 视图与图像同尺寸：scale=1、零偏移
    assert render.cell_index_at(rects, (400, 200), (400, 200), (100, 100)) == 0
    assert render.cell_index_at(rects, (400, 200), (400, 200), (300, 100)) == 1


def test_hit_respects_letterbox_offset():
    # 图像 400×200 放进 400×400 视图 → scale=1、上下各留白 100（非正方才有位移）
    rects = _cell_rects()
    assert render.cell_index_at(rects, (400, 200), (400, 400), (100, 150)) == 0
    assert render.cell_index_at(rects, (400, 200), (400, 400), (100, 50)) is None


def test_hit_gap_between_cells_is_none():
    rects = [(0, 0, 100, 100), (200, 0, 100, 100)]
    assert render.cell_index_at(rects, (300, 100), (300, 100), (150, 50)) is None


def test_scaled_view_hit_matches_unscaled():
    # 图像放大一倍显示：图像点 (100,100)→视图 (200,200) 仍命中第 0 格
    rects = _cell_rects()
    assert render.cell_index_at(rects, (400, 200), (800, 400), (200, 200)) == 0


def test_rects_view_covers_hit_point():
    rects = _cell_rects()
    view = render.cell_rects_view(rects, (400, 200), (400, 400))
    vx, vy, vw, vh = view[0]
    assert vx <= 100 < vx + vw and vy <= 150 < vy + vh   # 与命中同一 fit
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_render_hit_geometry.py -v`
Expected: FAIL — `AttributeError: module 'photoprint.core.render' has no attribute 'page_cells_px'`

- [ ] **Step 3: 最小实现**

在 `photoprint/core/render.py` 末尾（`_mask_bands` 定义之后、`render_page` 之外）追加：

```python
def page_cells_px(plan, sheet, dpi):
    """整页图像像素尺寸 + 各格在图像像素坐标的矩形 (x,y,w,h)。

    与 render_page 的 mm→px 装箱同源，供预览命中/描框复用——杜绝第二套几何
    真相源；只算格框，不含遮罩/切缝。
    """
    image_wh = (units.mm_to_px(sheet.w_mm, dpi), units.mm_to_px(sheet.h_mm, dpi))
    rects = [(units.mm_to_px(c.x_mm, dpi), units.mm_to_px(c.y_mm, dpi),
              units.mm_to_px(c.w_mm, dpi), units.mm_to_px(c.h_mm, dpi))
             for c in plan.cells]
    return image_wh, rects


def _fit_rect(image_wh, view_wh):
    """KeepAspectRatio 信箱：图像等比缩放进视图时的 (offset_x, offset_y, scale)。

    与 QLabel.setPixmap(scaled(..., KeepAspectRatio)) 的居中放置逐条对齐；
    退化尺寸（≤0）按不缩放处理，避免除零。
    """
    iw, ih = image_wh
    vw, vh = view_wh
    if iw <= 0 or ih <= 0 or vw <= 0 or vh <= 0:
        return (0.0, 0.0, 1.0)
    scale = min(vw / iw, vh / ih)
    ow, oh = iw * scale, ih * scale
    return ((vw - ow) / 2.0, (vh - oh) / 2.0, scale)


def cell_index_at(cell_rects_px, image_wh, view_wh, pos):
    """视图坐标点 pos=(x,y) 命中的格内序；信箱留白区/格间空隙 → None。

    先经 _fit_rect 逆变换回图像坐标，再逐格判定（左闭右开，边界不串邻格）。
    """
    ox, oy, s = _fit_rect(image_wh, view_wh)
    px, py = pos
    ix, iy = (px - ox) / s, (py - oy) / s
    for idx, (rx, ry, rw, rh) in enumerate(cell_rects_px):
        if rx <= ix < rx + rw and ry <= iy < ry + rh:
            return idx
    return None


def cell_rects_view(cell_rects_px, image_wh, view_wh):
    """格矩形映到视图像素坐标，供 paintEvent 描格框；与 cell_index_at 共用 _fit_rect。"""
    ox, oy, s = _fit_rect(image_wh, view_wh)
    return [(rx * s + ox, ry * s + oy, rw * s, rh * s)
            for (rx, ry, rw, rh) in cell_rects_px]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_render_hit_geometry.py -v`
Expected: PASS（7 条全绿）

- [ ] **Step 5: 变异验牙**

用 SearchReplace 把 `cell_index_at` 的 `ix, iy = (px - ox) / s, (py - oy) / s` 改成 `ix, iy = (px - ox) / s, (px - oy) / s`（复制粘贴笔误：y 误用 px），跑 `pytest tests/test_render_hit_geometry.py::test_hit_respects_letterbox_offset -v` 必须转红；还原。再删 `_fit_rect` 里的居中偏移（`return (0.0, 0.0, scale)`）→ `test_scaled_view_hit_matches_unscaled` 或 letterbox 用例须转红；还原。

- [ ] **Step 6: 提交**

```bash
git add photoprint/core/render.py tests/test_render_hit_geometry.py
```
用无 BOM 消息文件：`core: 新增命中几何三函数（page_cells_px/cell_index_at/cell_rects_view）`

---

### Task 2: PreviewView 交互预览控件

**Files:**
- Create: `photoprint/app/preview_view.py`
- Test: `tests/test_app_preview_view.py`

**Interfaces:**
- Consumes: `view.to_pixmap`（Task：既有）、`render.cell_index_at` / `render.cell_rects_view`（Task 1）。
- Produces（`main_window` 依赖）：
  - `PreviewView(parent=None)`，信号 `cellClicked = Signal(int)`（格内序）。
  - `set_geometry(cell_rects_px, image_wh)`、`set_current_cell(position_or_None)`、
    `show_image(pil)`、`clear_image()`、`hit_position(x, y) -> int | None`。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_app_preview_view.py`：

```python
"""PreviewView：显示 pixmap + 命中发 cellClicked + 描框高亮。offscreen。"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
pytest.importorskip("PySide6")
from PIL import Image  # noqa
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from photoprint.app.preview_view import PreviewView

pytest.importorskip("PySide6", reason="需要 Qt")
App = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _no_leaked_threads(qapp):
    yield
    # 本模块不起后台线程；保留夹具骨架以对齐项目约定（收尾无需 wait）


def _two_cell_rects():
    return [(0, 0, 200, 200), (200, 0, 200, 200)]


def test_show_image_sets_non_null_pixmap():
    w = PreviewView()
    w.resize(400, 200)
    w.show_image(Image.new("RGB", (400, 200), (10, 20, 30)))
    assert not w.pixmap().isNull()


def test_clear_image_empties():
    w = PreviewView()
    w.show_image(Image.new("RGB", (40, 30), (0, 0, 0)))
    w.clear_image()
    assert w.pixmap() is None or w.pixmap().isNull()


def test_hit_position_uses_geometry(qapp):
    w = PreviewView()
    w.resize(400, 400)                      # 视图 400×400，图像 400×200 → 上下留白
    w.set_geometry(_two_cell_rects(), (400, 200))
    assert w.hit_position(100, 150) == 0
    assert w.hit_position(300, 150) == 1
    assert w.hit_position(100, 20) is None   # 信箱留白带


def test_no_geometry_no_hit(qapp):
    w = PreviewView()
    w.resize(300, 300)
    assert w.hit_position(10, 10) is None    # 未 set_geometry：不命中、不抛


def test_click_emits_cell_clicked(qapp):
    w = PreviewView()
    w.resize(400, 200)
    w.set_geometry(_two_cell_rects(), (400, 200))
    got = []
    w.cellClicked.connect(lambda i: got.append(i))
    w.show()
    QTest.mouseClick(w, Qt.LeftButton, Qt.NoModifier, QPoint(300, 100))
    assert got == [1]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_app_preview_view.py -v`
Expected: FAIL — `ModuleNotFoundError: photoprint.app.preview_view`

- [ ] **Step 3: 最小实现**

新建 `photoprint/app/preview_view.py`：

```python
"""交互式预览：整页 pixmap 之上描格框、高亮当前格，点击→格内序信号。

几何全部问 core（render.cell_index_at / cell_rects_view），本模块不写任何
mm/像素/裁切运算——守住 app 层红线。
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel

from photoprint.app import view
from photoprint.core import render

_CELL_PEN = QColor(120, 120, 120)
_CURRENT_PEN = QColor(0, 120, 215)
_EMPTY_TEXT = "（无预览）"


class PreviewView(QLabel):
    cellClicked = Signal(int)          # 格内序 [0, count)

    def __init__(self, parent=None):
        super().__init__(_EMPTY_TEXT, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(360, 240)
        self._full_pm = None
        self._cell_rects_px = []
        self._image_wh = (1, 1)
        self._current_cell = None

    # ---------- 几何注入（main_window 每次 _rebuild_job 调） ----------

    def set_geometry(self, cell_rects_px, image_wh):
        self._cell_rects_px = [tuple(r) for r in cell_rects_px]
        self._image_wh = tuple(image_wh)
        self.update()

    def set_current_cell(self, position):
        self._current_cell = position
        self.update()

    # ---------- 图像 ----------

    def show_image(self, image):
        self._full_pm = view.to_pixmap(image)
        self._rescale()

    def clear_image(self):
        self._full_pm = None
        self.clear()

    def _rescale(self):
        if self._full_pm is None or self._full_pm.isNull():
            return
        self.setPixmap(self._full_pm.scaled(self.size(), Qt.KeepAspectRatio,
                                            Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()

    # ---------- 命中 / 点击 ----------

    def hit_position(self, x, y):
        if not self._cell_rects_px:
            return None
        return render.cell_index_at(self._cell_rects_px, self._image_wh,
                                    (self.width(), self.height()), (x, y))

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        idx = self.hit_position(event.position().x(), event.position().y())
        if idx is not None:
            self.cellClicked.emit(idx)

    # ---------- 绘制格框 ----------

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._cell_rects_px or self._full_pm is None:
            return
        painter = QPainter(self)
        rects = render.cell_rects_view(self._cell_rects_px, self._image_wh,
                                       (self.width(), self.height()))
        pen = QPen(_CELL_PEN)
        pen.setWidth(1)
        painter.setPen(pen)
        for (x, y, w, h) in rects:
            painter.drawRect(QRectF(x, y, w, h))
        if self._current_cell is not None and 0 <= self._current_cell < len(rects):
            cpen = QPen(_CURRENT_PEN)
            cpen.setWidth(3)
            painter.setPen(cpen)
            cx, cy, cw, ch = rects[self._current_cell]
            painter.drawRect(QRectF(cx, cy, cw, ch))
        painter.end()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_app_preview_view.py -v`
Expected: PASS（5 条全绿）

- [ ] **Step 5: 变异验牙**

把 `hit_position` 的 `if not self._cell_rects_px: return None` 删掉（未注入几何时会拿空 rects 调 core）→ `test_no_geometry_no_hit` 仍应绿（core 空列表返回 None），故改验另一处：把 `mousePressEvent` 里 `if idx is not None` 去掉（无条件 emit）→ `test_click_emits_cell_clicked` 对 `QPoint(300,100)` 命中 1 不变、但补一条点留白区不 emit 的用例（Step 1 里 `test_no_geometry_no_hit` 只测 hit_position，未测点击留白）。为留白点击加牙：给测试补
```python
def test_click_in_letterbox_emits_nothing(qapp):
    w = PreviewView(); w.resize(400, 400)
    w.set_geometry(_two_cell_rects(), (400, 200))
    got = []; w.cellClicked.connect(got.append); w.show()
    QTest.mouseClick(w, Qt.LeftButton, Qt.NoModifier, QPoint(100, 20))
    assert got == []
```
先补此测试跑绿，再用 SearchReplace 去掉 `mousePressEvent` 的 `if idx is not None` 守卫 → 该测试转红；还原。

- [ ] **Step 6: 提交**

```bash
git add photoprint/app/preview_view.py tests/test_app_preview_view.py
```
消息：`app: 新增 PreviewView 交互预览（描格框/高亮/点击发 cellClicked）`

---

### Task 3: main_window 放置数据模型 + 逐格旋转/清空 + 持久化迁移

> 本任务把渲染依赖的三平行列表换成库/放置解耦模型，落地行为变更（加入不再自动排版、逐图旋转→逐格），并同步迁移受波及的既有测试。预览控件仍是 `QLabel`（点击接线在 Task 4）。

**Files:**
- Modify: `photoprint/app/main_window.py`（`__init__` 属性、`_rebuild_job`、`append_photo`、`_photo_item_text`、`_on_rotate`、`_go_page`、`_on_clear_photos`、`export_to`、`save_last_job`、`_restore_last_job`；新增 `place`/`rotate_cell`/`clear_cell`/`_maybe_shrink_pages`/`_ensure_count`/`_has_any_photo`/`_reset_placements`/`_restore_placements`/`_migrate_sequential`）
- Create: `tests/test_placement.py`
- Modify: `tests/test_app_main_window.py`（`_fill` 重定义、`photo_paths`/`photos` 改名、逐图旋转与落盘旋转系列改写为逐格/迁移）
- Modify: `tests/test_folder_import.py`（`w.photos` → `w.pool`）

**Interfaces:**
- Consumes: `jobs.build_job`/`build_layout`/`load_photo`/`PREVIEW_DPI`、`view.to_thumbnail`、`THUMB_PX`、`store`。
- Produces（Task 4 依赖）：属性 `pool`/`placements`/`cell_rot`/`_pages`/`_current_cell`/`_count_last`；方法 `place(slot,pool_idx)->bool`、`rotate_cell(slot)`、`clear_cell(slot)`、`_ensure_count()->int`、`_has_any_photo()->bool`。`Job.photos` 即物化后的 `页数*count` 长 PIL 列表（`job.photos[slot]` 可断言）。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_placement.py`（`_no_lealed_threads`/`_settle`/`_store`/`_fill` 逐字复刻自 `test_app_main_window.py`，`_fill` 改为 append + 顺序 place）：

```python
"""放置内核：库/放置解耦、逐格旋转、页数派生、持久化与迁移。offscreen。"""
import pytest

pytest.importorskip("PIL", reason="需要 Pillow")
pytest.importorskip("PySide6", reason="需要 Qt 绑定")

from PySide6.QtCore import QElapsedTimer, QEventLoop  # noqa: E402
from PIL import Image  # noqa: E402

from photoprint.app.main_window import MainWindow  # noqa: E402
from photoprint.core import store  # noqa: E402


def _store(tmp_path):
    s = store.Store(tmp_path / "papers.json")
    s.load()
    return s


@pytest.fixture(autouse=True)
def _no_lealed_threads(qapp):
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


def _settle(window, qapp, timeout_ms=5000):
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


def _make_photos(tmp_path, n=4):
    paths = []
    for i in range(n):
        p = tmp_path / f"{i}.jpg"
        Image.new("RGB", (400, 200), (200 - 30 * i, 30, 40)).save(p)
        paths.append(str(p))
    return paths


def _fill(window, tmp_path, n=4):
    """append 进库后顺序 place 到槽 0..n-1——复现旧“自动填充”对既有测试的意义。"""
    for p in _make_photos(tmp_path, n):
        window.append_photo(p)
    for i in range(n):
        window.place(i, i)
    window._refresh()


def test_append_does_not_auto_place(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    for p in _make_photos(tmp_path, 3):
        w.append_photo(p)
    w._refresh()
    assert len(w.pool) == 3 and w.placements == {}
    assert all(ph is None for ph in w.job.photos)        # 入列不进版面


def test_place_materializes_into_job(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    w.append_photo(_make_photos(tmp_path, 1)[0])
    assert w.place(0, 0) is True
    w._refresh()
    assert w.job.photos[0] is w.pool[0]["img"]
    assert sum(1 for ph in w.job.photos if ph is not None) == 1


def test_same_photo_repeatable_multiple_slots(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    w.append_photo(_make_photos(tmp_path, 1)[0])
    w.place(0, 0)
    w.place(2, 0)
    w._refresh()
    assert w.job.photos[0] is w.pool[0]["img"]
    assert w.job.photos[2] is w.pool[0]["img"]           # 引用不消耗
    assert w.placements[0] == w.placements[2] == 0


def test_place_out_of_range_fails(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    w.append_photo(_make_photos(tmp_path, 1)[0])
    assert w.place(0, 5) is False                        # 库下标越界
    assert w.placements == {}


def test_rotate_is_per_cell_only(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)                                   # 4 张顺序入槽
    w._current_cell = 1
    w.rotate_cell(1)
    assert w.cell_rot == {1: 90}                          # 只这格
    w._refresh()
    assert w.job.rotations[1] == 90 and w.job.rotations[0] == 0


def test_rotate_without_current_cell_prompts(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    w._current_cell = None
    before = dict(w.cell_rot)
    w._on_rotate()
    assert w.cell_rot == before
    assert "请先点选版面中已放图的格" in w.statusBar().currentMessage()


def test_clear_cell_empties_slot(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    w.clear_cell(0)
    w._refresh()
    assert 0 not in w.placements
    assert w.job.photos[0] is None


def test_layout_count_change_clears_placements(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    assert w.placements
    w._select_by_data(w.cell_box, "ID1")                # 换大格 → 每页格数变
    w._refresh()
    assert w.placements == {} and w._pages == 1
    assert "布局已变" in w.statusBar().currentMessage()


def test_next_page_extends_and_prev_shrinks(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path, n=1)
    pages0 = w._pages
    w._go_page(1)                                        # 末页之后 → 追加空页
    assert w._pages == pages0 + 1
    w._go_page(-1)                                       # 离开空末页 → 收缩
    assert w._pages == pages0


def test_clear_button_wipes_pool_and_placements(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    w._on_clear_photos()
    assert w.pool == [] and w.placements == {} and w.cell_rot == {}
    assert w._pages == 1 and w.photo_list.count() == 0


def test_persist_roundtrip_new_schema(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path, n=2)
    w._current_cell = 1
    w.rotate_cell(1)
    s2 = _store(tmp_path)
    w.st = s2                                            # 换新存储再落盘
    w.save_last_job()
    w2 = MainWindow(st=s2)
    assert len(w2.pool) == 2
    assert w2.placements == {0: 0, 1: 1}
    assert w2.cell_rot.get(1) == 90


def test_migration_sequential_from_legacy_rotations(qapp, tmp_path):
    """旧 last_job（photo_paths+rotations、无 placements）→ 顺序重放、逐格旋转。"""
    s = _store(tmp_path)
    s.set_last_job({"sheet_key": "A4", "cell_key": "3R",
                    "photo_paths": _make_photos(tmp_path, 2),
                    "rotations": [90, 180]})
    s.save()
    w = MainWindow(st=_store(tmp_path))
    assert len(w.pool) == 2
    assert w.placements == {0: 0, 1: 1}
    assert w.cell_rot == {0: 90, 1: 180}
    w._refresh()
    assert w.job.rotations[0] == 90 and w.job.rotations[1] == 180


def test_migration_bad_rotations_all_zero(qapp, tmp_path):
    s = _store(tmp_path)
    s.set_last_job({"sheet_key": "A4", "cell_key": "3R",
                    "photo_paths": _make_photos(tmp_path, 2),
                    "rotations": [90, "x"]})             # 含坏项 → 整体不恢复
    s.save()
    w = MainWindow(st=_store(tmp_path))
    assert w.cell_rot == {}                              # 全 0
    assert w.placements == {0: 0, 1: 1}                  # 顺序放置仍成立


def test_migration_overlong_rotations_truncated(qapp, tmp_path):
    s = _store(tmp_path)
    s.set_last_job({"sheet_key": "A4", "cell_key": "3R",
                    "photo_paths": _make_photos(tmp_path, 2),
                    "rotations": [90, 180, 270, 45]})     # 超长 → 截到库长 2
    s.save()
    w = MainWindow(st=_store(tmp_path))
    assert w.cell_rot == {0: 90, 1: 180}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_placement.py -v`
Expected: FAIL — `AttributeError: 'MainWindow' object has no attribute 'pool'`（或 `place` 不存在）

- [ ] **Step 3: 实现——数据模型与操作**

`__init__`（替换 91-96 三列表段，保留其后 `_thread/_task/_gen/_stale` 等）：

```python
        self.st.load()
        self.pool = []             # 库：[{"path": str, "img": PIL|None}]
        self.placements = {}       # 槽位下标 → 库下标；缺省即空格
        self.cell_rot = {}         # 槽位下标 → 0/90/180/270（缺省 0）
        self._pages = 1            # 当前总页数（派生 + 翻页增页）
        self.page_index = 0
        self._current_cell = None  # 预览选中的全局槽位
        self._count_last = None    # 上次每页格数（检测结构性布局变更）
        self.job = None
        self._full_pm = None
```

新增辅助与操作（放 `_params` 之后）：

```python
    def _ensure_count(self):
        """不依赖 job 拿当前每页格数：恢复/迁移在首刷前也要用它算页数。"""
        p = self._params()
        try:
            plan, _ = jobs.build_layout(self.st, p["sheet_key"], p["cell_key"],
                                        p["gap_mm"], p["bleed_mm"], p["mode"],
                                        borderless_active=False)
        except ValueError:
            return self._count_last or 0
        self._count_last = plan.count
        return plan.count

    def _has_any_photo(self):
        return any(self.pool[pi]["img"] is not None
                   for pi in self.placements.values() if 0 <= pi < len(self.pool))

    def _reset_placements(self, msg):
        self.placements = {}
        self.cell_rot = {}
        self._pages = 1
        self.page_index = 0
        self._current_cell = None
        self._set_status(msg)                    # 正常色：引导重摆，非错误

    def place(self, slot, pool_idx):
        """唯一写放置入口（2b 的 dropEvent、迁移重放都走它）。"""
        if not 0 <= pool_idx < len(self.pool):
            return False
        count = self._count_last or 0
        if count and slot >= 0:
            self._pages = max(self._pages, slot // count + 1)
        self.placements[slot] = pool_idx
        self._current_cell = slot
        self._debounce.start()
        return True

    def rotate_cell(self, slot):
        if slot is None or slot not in self.placements:
            self._set_status("请先点选版面中已放图的格")
            return
        self.cell_rot[slot] = (self.cell_rot.get(slot, 0) + 90) % 360
        self._debounce.start()

    def clear_cell(self, slot):
        if slot is None:
            self._set_status("请先点选版面中的格")
            return
        self.placements.pop(slot, None)
        self.cell_rot.pop(slot, None)
        self._maybe_shrink_pages()
        self._debounce.start()

    def _maybe_shrink_pages(self):
        count = self._count_last or 0
        if not count:
            return
        while self._pages > 1:
            last_start = (self._pages - 1) * count
            last_filled = any(last_start <= s < self._pages * count
                              for s in self.placements)
            if last_filled or self.page_index == self._pages - 1:
                break
            self._pages -= 1
```

- [ ] **Step 4: 实现——`_rebuild_job` 物化 + 结构变更清空**

整体替换 `_rebuild_job`：

```python
    def _rebuild_job(self):
        """算 count→派生 photos/rotations→build_job。结构变（count 变）清空放置。"""
        p = self._params()
        try:
            plan, _ = jobs.build_layout(self.st, p["sheet_key"], p["cell_key"],
                                        p["gap_mm"], p["bleed_mm"], p["mode"],
                                        borderless_active=False)
        except ValueError as exc:
            self.job = None
            self._set_status(str(exc), error=True)
            self.export_btn.setEnabled(False)
            return
        count = plan.count
        if count != self._count_last:
            if self._count_last is not None and self.placements:
                self._reset_placements("布局已变，请重新摆放")
            self._count_last = count
        n = self._pages * count
        photos = [None] * n
        for slot, pi in self.placements.items():
            if 0 <= slot < n and 0 <= pi < len(self.pool):
                photos[slot] = self.pool[pi]["img"]
        rotations = [self.cell_rot.get(i, 0) for i in range(n)]
        try:
            # 复用 build_job 作唯一权威构造（含模式校验、rotations 归一交 core）；
            # 前面 build_layout 只为先拿 count 给物化定长——两次纯函数同输入同输出。
            self.job = jobs.build_job(self.st, photos, p["sheet_key"], p["cell_key"],
                                      gap_mm=p["gap_mm"], bleed_mm=p["bleed_mm"],
                                      mode=p["mode"], offset_pct=p["offset_pct"],
                                      rotations=rotations)
        except ValueError as exc:
            self.job = None
            self._set_status(str(exc), error=True)
            self.export_btn.setEnabled(False)
            return
        self.page_index = min(self.page_index, self.job.page_count - 1)
        self.export_btn.setEnabled(self._has_any_photo())
        self._set_status(f"每页 {self.job.count} 格 · 共 {self.job.page_count} 页 · "
                         f"{self.job.note}")
```

- [ ] **Step 5: 实现——照片入列/列表文字/旋转/翻页/清空/导出**

`append_photo`（替换，改存 `pool`、文字去角度）：

```python
    def append_photo(self, path):
        """读图失败不阻塞其余：img=None 进库，被放置时物化成空格；列表标红。"""
        name = Path(path).name
        try:
            img = jobs.load_photo(path)
        except Exception as exc:
            self.pool.append({"path": str(path), "img": None})
            item = QListWidgetItem(self._photo_item_text(name, None))
            item.setForeground(QColor(ERROR_COLOR))
            self.photo_list.addItem(item)
            self._set_status(f"无法读取 {name}：{exc}", error=True)
            return
        self.pool.append({"path": str(path), "img": img})
        item = QListWidgetItem(self._photo_item_text(name, img))
        item.setIcon(QIcon(view.to_thumbnail(img, THUMB_PX)))
        self.photo_list.addItem(item)

    @staticmethod
    def _photo_item_text(name, img):
        """列表项文字：旋转已移到格上，不再有角度段。"""
        if img is None:
            return f"{name}（读取失败）"
        return f"{name}  {img.width}×{img.height}px"
```

`_on_rotate` 改为逐格：

```python
    def _on_rotate(self):
        self.rotate_cell(self._current_cell)
```

`_go_page`（替换，加增页/收缩/重置选中）：

```python
    def _go_page(self, delta):
        if delta > 0 and self.page_index >= self._pages - 1:
            self._pages += 1                        # 末页之后追加空页
        nxt = self.page_index + delta
        if 0 <= nxt < self._pages:
            self.page_index = nxt
            self._current_cell = None               # 翻页即弃旧选中
            self._maybe_shrink_pages()              # 离开空末页时收缩
            self._refresh()
```

`_on_clear_photos`（替换）：

```python
    def _on_clear_photos(self):
        self.pool = []
        self.placements = {}
        self.cell_rot = {}
        self._pages = 1
        self.page_index = 0
        self._current_cell = None
        self.photo_list.clear()
        self._refresh()
```

`export_to` 中的空判定（417 行附近）：

```python
        if self.job is None or not self._has_any_photo():
            raise ValueError("没有可导出的照片")
```

- [ ] **Step 6: 实现——持久化新 schema + 迁移**

`save_last_job`、`_restore_last_job` 整体替换，并新增 `_restore_placements`/`_migrate_sequential`（代码见本任务末「持久化参考」，逐字采用）。删除 `_restore_rotations`。

- [ ] **Step 7: 迁移既有测试**

`tests/test_app_main_window.py`：
- 重定义 `_fill`（与 test_placement 同）：append 后 `for i in range(n): window.place(i, i)` 再 `_refresh()`。
- 删 `test_rotate_without_selection_prompts_and_keeps_state` 与 `test_rotate_cycles_90_degrees_and_marks_list`（已由 test_placement 逐格版覆盖）。
- `187` 行 `assert w.photos[-1] is None` → `assert w.pool[-1]["img"] is None`。
- `253` 行 `assert w.photos == []` → `assert w.pool == []`。
- 落盘旋转系列 `test_bad_rotations_config_degrades_to_all_zero` / `test_rotations_length_mismatch_truncates_or_pads` / `test_rotations_short_list_pads_to_equal_length` / `test_rotations_out_of_range_still_renderable`：断言从 `w.photo_rotations == [...]` 改为读迁移结果——前三者 `assert w.cell_rot == {}` / `== {0:90,1:180}` / `== {0:90}`；`_out_of_range` 用 `assert w.cell_rot[0] == -90`（原样存、core 归一）且 `w._refresh(); assert w.job is not None`。这些参数里 `cell_key` 为 `"ID1"` 保留（count 变小不影响迁移按库长截断的断言）。

`tests/test_folder_import.py`：
- `98` 行 `assert len(w.photos) == 3` → `assert len(w.pool) == 3`。
- `112` 行 `assert w.photos.count(None) == 1` → `assert sum(1 for e in w.pool if e["img"] is None) == 1`。

- [ ] **Step 8: 跑测试确认通过**

Run: `pytest tests/test_placement.py tests/test_app_main_window.py tests/test_folder_import.py -v`
Expected: PASS（新 + 迁移后全绿）

- [ ] **Step 9: 变异验牙**

用 SearchReplace 逐一制造破坏并确认对应测试转红、随后还原：
1. `place` 去掉 `if not 0 <= pool_idx < len(self.pool): return False` → `test_place_out_of_range_fails` 红。
2. `_rebuild_job` 去掉 `if count != self._count_last` 清空段 → `test_layout_count_change_clears_placements` 红。
3. `_go_page` 去掉 `self._maybe_shrink_pages()` → `test_next_page_extends_and_prev_shrinks` 红。
4. `_migrate_sequential` 去掉 `parsed = parsed[:n]` 截断 → `test_migration_overlong_rotations_truncated` 红。
5. `append_photo` 若误加回“自动 place” → `test_append_does_not_auto_place` 红（本步仅作语义确认，不实际加）。

- [ ] **Step 10: 全量回归 + 提交**

Run: `pytest tests/`
Expected: EXIT=0 全绿、无 `MUTATION-TEMP` 残留。
```bash
git add photoprint/app/main_window.py tests/test_placement.py tests/test_app_main_window.py tests/test_folder_import.py
```
消息：`app: 放置内核——库/放置解耦 + 逐格旋转 + 页数派生 + last_job 迁移（移除自动填充）`

**持久化参考（Step 6 逐字采用）:**

```python
    def save_last_job(self, out_dir=None):
        p = self._params()
        self.st.set_last_job({
            "sheet_key": p["sheet_key"], "cell_key": p["cell_key"],
            "mode_index": self.mode_box.currentIndex(),
            "gap_mm": p["gap_mm"], "bleed_mm": p["bleed_mm"], "dpi": p["dpi"],
            "offset_pct": [self.h_slider.value(), self.v_slider.value()],
            "out_dir": out_dir or self._last_out_dir(),
            "pool_paths": [e["path"] for e in self.pool],
            "placements": {str(s): pi for s, pi in self.placements.items()},
            "cell_rot": {str(s): a for s, a in self.cell_rot.items() if a},
            "pages": self._pages,
        })
        if not self.st.save():
            self._set_status("本次设置未持久化（写入失败）", error=True)

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
        new_shape = ("placements" in job) or ("pool_paths" in job)
        paths = job.get("pool_paths") if new_shape else job.get("photo_paths")
        for pth in (paths if isinstance(paths, (list, tuple)) else []):
            self.append_photo(str(pth))
        self._ensure_count()
        if new_shape:
            self._safe(lambda: self._restore_placements(job))
        else:
            self._safe(lambda: self._migrate_sequential(job))

    def _restore_placements(self, job):
        pl = job.get("placements")
        if not isinstance(pl, dict):
            return                                    # 放置段整体降级：保库、重摆
        for k, v in pl.items():
            try:
                slot, pi = int(k), int(v)
            except (TypeError, ValueError, OverflowError):
                continue
            if slot >= 0 and 0 <= pi < len(self.pool):
                self.placements[slot] = pi
        rot = job.get("cell_rot")
        if isinstance(rot, dict):
            for k, v in rot.items():
                try:
                    slot, a = int(k), int(v)
                except (TypeError, ValueError, OverflowError):
                    continue
                if slot in self.placements:
                    self.cell_rot[slot] = a
        count = self._count_last or 1
        try:
            self._pages = max(1, int(job.get("pages")))
        except (TypeError, ValueError, OverflowError):
            self._pages = 1
        if self.placements:
            self._pages = max(self._pages, max(self.placements) // count + 1)

    def _migrate_sequential(self, job):
        """旧 last_job（photo_paths+rotations、无 placements）→ 顺序重放：
        槽 i 放库 i，rotations 位置对齐逐格；任一坏角度整体不恢复（全 0），
        超长截到库长、不足补 0——与旧 _restore_rotations 同容错口径。"""
        count = self._count_last or 0
        n = len(self.pool)
        if not count or not n:
            return
        rots = job.get("rotations")
        vals = [0] * n
        if isinstance(rots, (list, tuple)):
            try:
                parsed = [int(v) for v in rots]
            except (TypeError, ValueError, OverflowError):
                parsed = None
            if parsed is not None:
                parsed = parsed[:n]
                vals = parsed + [0] * (n - len(parsed))
        for i in range(n):
            self.placements[i] = i
            if vals[i] % 360:
                self.cell_rot[i] = vals[i]
        self._pages = max(1, -(-n // count))
```

---

### Task 4: 接线——预览切 PreviewView + 点击指派/选中 + 逐格旋转/清空格 UI

> 把只读 `QLabel` 预览换成 `PreviewView`，接上“选库图 + 点格→放入 / 无选中→纯选中”、逐格旋转与新增“清空格”按钮，并在每次 `_rebuild_job` 向预览注入命中几何。这些 affordance 与 2b 拖放共用同一 `place()`。

**Files:**
- Modify: `photoprint/app/main_window.py`（`__init__` 去 `_full_pm`、`_build_ui` 预览+按钮、`_on_preview`/`_on_cell_clicked`/`_highlight_current_cell`/`_on_clear_cell`、`_rebuild_job` 注几何；删 `_rescale_preview`/`resizeEvent`；新增 `render`/`PreviewView` import）
- Modify: `tests/test_placement.py`（新增点击/按钮/几何注入用例）

**Interfaces:**
- Consumes: `PreviewView`（Task 2）、`render.page_cells_px`（Task 1）、Task 3 的 `place`/`clear_cell`/`_current_cell`/`_count_last`。
- Produces: 方法 `_on_cell_clicked(position)`、`_highlight_current_cell()`、`_on_clear_cell()`；控件 `clear_cell_btn`（objectName）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_placement.py` 末尾追加：

```python
def test_rebuild_injects_geometry(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    _settle(w, qapp)
    assert len(w.preview._cell_rects_px) == w.job.count   # 预览拿到当页格框


def test_click_places_selected_pool_photo(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    w.append_photo(_make_photos(tmp_path, 1)[0])          # 库只 1 张，未放置
    w._refresh()
    w.photo_list.setCurrentRow(0)                          # 选中库图
    w.page_index = 0
    w._on_cell_clicked(2)                                  # 点第 3 格
    assert w.placements == {2: 0}                          # 槽位 = 0*count+2
    assert w._current_cell == 2


def test_click_without_selection_only_selects(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    w.photo_list.clearSelection()
    assert w.photo_list.currentRow() == -1
    before = dict(w.placements)
    w._on_cell_clicked(1)
    assert w.placements == before                          # 无库选中→不改放置
    assert w._current_cell == 1


def test_clear_cell_button_exists_and_clears(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    w._current_cell = 1
    btn = w.findChild(type(w.export_btn), "clear_cell_btn")
    assert btn is not None
    btn.click()
    assert 1 not in w.placements and 1 not in w.cell_rot
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_placement.py -k "injects or click or clear_cell_button" -v`
Expected: FAIL — `AttributeError: ... has no attribute '_on_cell_clicked'`（或 `preview._cell_rects_px` 不存在：仍是 QLabel）

- [ ] **Step 3: 实现——预览与按钮**

`main_window` 顶部 import 补：

```python
from photoprint.app.preview_view import PreviewView
from photoprint.core import modes, render, specs, store
```

`__init__` 删往 `self._full_pm = None` 一行（已迁进 `PreviewView`）。

`_build_ui` 预览行（191-194）整段替换：

```python
        self.preview = PreviewView()
        self.preview.cellClicked.connect(self._on_cell_clicked)
        body.addWidget(self.preview, 1)
```

按钮行（139-147）在 `rotate_btn` 后新增“清空格”：

```python
        rotate_btn = QPushButton("旋转 90°")
        rotate_btn.setObjectName("rotate_btn")
        rotate_btn.clicked.connect(self._on_rotate)
        self.rotate_btn = rotate_btn
        clear_cell_btn = QPushButton("清空格")
        clear_cell_btn.setObjectName("clear_cell_btn")
        clear_cell_btn.clicked.connect(self._on_clear_cell)
        self.clear_cell_btn = clear_cell_btn
        btns = QHBoxLayout()
        btns.addWidget(add_btn)
        btns.addWidget(import_btn)
        btns.addWidget(clear_btn)
        btns.addWidget(rotate_btn)
        btns.addWidget(clear_cell_btn)
        panel.addRow("", btns)
```

- [ ] **Step 4: 实现——点击/高亮/清除接线 + 几何注入**

`_on_preview` 整段替换，并删 `_rescale_preview` 与 `resizeEvent` 两个方法（几何缩放已由 `PreviewView` 接管）：

```python
    def _on_preview(self, image, gen):
        if gen != self._gen:
            return                          # 过期帧不上屏
        self.preview.show_image(image)

    def _on_cell_clicked(self, position):
        count = self._count_last or (self.job.count if self.job else 0)
        slot = self.page_index * count + position
        row = self.photo_list.currentRow()
        if 0 <= row < len(self.pool):
            self.place(slot, row)           # 选库图 + 点格 → 放入（与 2b 同入口）
        else:
            self._current_cell = slot       # 无选中 → 纯选中，供旋转/清空格
        self._highlight_current_cell()

    def _highlight_current_cell(self):
        count = self._count_last or 0
        pos = None
        if self._current_cell is not None and count \
                and self._current_cell // count == self.page_index:
            pos = self._current_cell % count
        self.preview.set_current_cell(pos)

    def _on_clear_cell(self):
        self.clear_cell(self._current_cell)
        self._highlight_current_cell()
```

`_rebuild_job` 在 `self.export_btn.setEnabled(...)` 之后、状态栏文案之前插入几何注入：

```python
        self.export_btn.setEnabled(self._has_any_photo())
        img_wh, rects = render.page_cells_px(self.job.plan, self.job.sheet,
                                              jobs.PREVIEW_DPI)
        self.preview.set_geometry(rects, img_wh)
        self._highlight_current_cell()
        self._set_status(f"每页 {self.job.count} 格 · 共 {self.job.page_count} 页 · "
                         f"{self.job.note}")
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/test_placement.py tests/test_app_preview_view.py tests/test_app_main_window.py -v`
Expected: PASS（含预览帧旧用例 301-306 仍绿：`PreviewView` 继承 `setPixmap/pixmap`，`_on_preview` 仍按 gen 丢弃过期帧）

- [ ] **Step 6: 变异验牙**

1. `_on_cell_clicked` 去掉 `if 0 <= row < len(self.pool)` 分支（总走 place）→ `test_click_without_selection_only_selects` 红。
2. `slot` 计算去掉 `page_index * count`（只用 position）→ `test_click_places_selected_pool_photo` 在 `page_index>0` 时红（可先翻到第 2 页再断言）。还原。
3. `_rebuild_job` 去掉 `set_geometry` → `test_rebuild_injects_geometry` 红。
4. `_highlight_current_cell` 去掉 `// count == page_index` 限定 → 翻页后陈旧选中会误高亮（补一条“翻页后 preview._current_cell is None”断言再验）。还原。

- [ ] **Step 7: 全量回归 + 提交**

Run: `pytest tests/`
Expected: EXIT=0 全绿。`_lab` parity 脚本与 `cli` 顺序填充逐字不变（本增量未碰 render_page/pack/cli）。
```bash
git add photoprint/app/main_window.py tests/test_placement.py
```
消息：`app: 预览接线——PreviewView + 点格指派/选中 + 逐格旋转/清空格 UI + 几何注入`

---

## 收尾：重新打包

- [ ] **Step 8: 重打包验证**

改完需 `build_exe.ps1` 重新打包后实测：导入/添加→库有图但不自动上版→选库图点格放入→同图可多格→点格选中后旋转/清空格→换纸张弹“布局已变”→重启保留放置（含旧配置迁移）。

---

## 自查（写完计划后对 spec）

**1. Spec 覆盖：** §2 数据模型→Task3；§3 页数→Task3（`_go_page`/`_maybe_shrink_pages`）；§4 布局变更→Task3（`_rebuild_job`）；§5 命中几何三函数→Task1；§6 预览控件→Task2（+Task4 接线）；§7 指派/旋转/擦除→Task3（方法）+Task4（UI）；§8 库/清空→Task3；§9 持久化+迁移→Task3；§10 错误处理→各任务（状态栏引导、`_safe` 包裹、逐条/整体降级）；§11 测试→各任务 Step1+变异；§12 2b 衔接→`place()`/`hit_position` 已就位（无代码）。无缺口。

**2. 占位符扫描：** 已消——持久化参考给了完整体代码；Task4 `_rebuild_job` 插入块以 `export_btn.setEnabled` 行为锚与 Step4 一致。

**3. 类型一致：** 全程用 `pool/placements/cell_rot/_pages/_current_cell/_count_last`；方法名 `place/rotate_cell/clear_cell` 在 Task3 定义、Task4 引用一致；`PreviewView.set_geometry/set_current_cell/show_image/clear_image/hit_position/cellClicked` 与 Task4 调用一致；core 三函数签名与 Task1 定义一致。

**修正：** Task3 `_rebuild_job` 不注几何（预览尚未换）；Task4 才插 `set_geometry`——两任务对 `_rebuild_job` 的修改不冲突（Task4 在 Task3 成果上追加行）。

---

## 执行交接

计划已存 `docs/superpowers/plans/2026-11-06-photoprint-placement-core.md`。两种执行方式：

1. **子代理驱动（推荐）**——每任务派新子代理、任务间两阶段评审，本环境适配方式见记忆“Qoder 环境跑 subagent-driven-development”。
2. **内联执行**——本会话内逐任务执行，带检查点。

选哪种？
