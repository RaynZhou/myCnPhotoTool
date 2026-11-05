# 逐张照片旋转 90° 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在界面上选中某张照片后点「旋转 90°」即可逐张顺时针旋转照片内容（格子与排版不变），预览与导出 PDF 走同一条渲染路径，角度随 last_job 持久化。

**Architecture:** 旋转作为照片属性进入核心渲染层（`render_page` 新增 `rotations` 参数，在取 `photo.width/height` 之前 transpose），`jobs.Job` 原样透传，界面层只维护 `photo_rotations` 列表与按钮。装箱层、CLI、偏移几何语义一行不改。

**Tech Stack:** Python 3 + Pillow（transpose）+ PySide6（offscreen 测试）+ pytest。

**规格文档:** `docs/superpowers/specs/2026-11-05-photoprint-per-photo-rotation-design.md`（决策已冻结，本计划只是落地拆解）

## Global Constraints

- 基线：`master` @ e3dc760，`python -m pytest tests/ -q` 现有 **232 项全绿**，每个任务收尾必须仍全绿。
- `photoprint/core/**` 与 `photoprint/jobs.py` 禁止 import `PySide6`/`win32print`/`win32ui`/`win32con`；`jobs.py` 禁止 `print(`（既有守门测试会扫源码，注释里也不得写出这些字样）。
- `app/` 层不得出现任何 mm↔像素换算与裁切几何；角度归一（`% 360`、非法→0）只在 core 层做。
- `cli.py` 行为与输出逐字冻结：不传 `rotations`，默认 `()` 必须与现行为逐像素等价。
- 顺时针 90° 一律用 `Image.ROTATE_270`（PIL 语义），与 `render.py` 现有旋转格同口径。
- 角度非法（归一后不在 {0,90,180,270}，或转不了 int）→ 按 0 处理，**不抛错**。
- 提交信息用中文，前缀沿用仓库惯例（`feat(gui):` / `test(gui):` / `docs:` 等）。
- 验证命令一律在仓库根 `c:\Users\allen\Documents\Qoder\2026-11-03\chat-2` 执行；PowerShell 用 `;` 分隔，不用 `&&`。

---

### Task 1: 渲染层 rotations（core/render.py）

**Files:**
- Modify: `photoprint/core/render.py`（模块常量区 + `render_page` 签名与照片循环）
- Create: `tests/test_render_rotations.py`

**Interfaces:**
- Consumes: 既有 `render_page(plan, photos, sheet, dpi, mode, show_mask=True, show_cut_lines=True, borderless_active=False, offset_pct=(0.0, 0.0))`、`pack.pack`、`specs.find_spec`。
- Produces: `render_page(..., rotations=())`（末位新参数）；模块级 `render._ANGLE_TRANSPOSE: dict[int, Image.Transpose]` 与 `render._apply_rotation(photo, angle) -> Image`（Task 2/3 不直接用，但测试对拍要引用同一映射）。

- [ ] **Step 1: 写失败测试 `tests/test_render_rotations.py`**

```python
"""逐图旋转：渲染时转必须与读图时预转好逐像素等价（规格 I-1），坏角度降级为 0。"""
import pytest

pytest.importorskip("PIL", reason="需要 Pillow")

from PIL import Image  # noqa: E402

from photoprint.core import modes, pack, render, specs  # noqa: E402

DPI = 25.4  # 1 像素 = 1 毫米，便于直接按 mm 取点

# 与 render._ANGLE_TRANSPOSE 同表：测试自带一份，实现漂移时对拍当场变红
_ANGLE_OPS = {90: Image.ROTATE_270, 180: Image.ROTATE_180, 270: Image.ROTATE_90}


def pre_rotated(photo, angle):
    img = photo.copy()
    while angle % 360 in _ANGLE_OPS:
        img = img.transpose(_ANGLE_OPS[angle % 360])
        angle -= 90
    return img


def _landscape():
    """四象限异色的 200×100 横图：左上红、右上绿、左下蓝、右下白。"""
    img = Image.new("RGB", (200, 100), (255, 255, 255))
    img.paste(Image.new("RGB", (100, 50), (255, 0, 0)), (0, 0))
    img.paste(Image.new("RGB", (100, 50), (0, 255, 0)), (100, 0))
    img.paste(Image.new("RGB", (100, 50), (0, 0, 255)), (0, 50))
    return img


def _a4_id1():
    a4 = specs.find_spec("A4")
    plan = pack.pack(a4, specs.find_spec("ID1"), gap_mm=2.0, allow_rotate=False,
                     printable=specs.printable_rect(a4))
    return a4, plan


def _render(a4, plan, photos, **kw):
    return render.render_page(plan, photos, a4, DPI, modes.FIT_TO_PRINTABLE,
                              show_mask=False, show_cut_lines=False, **kw)


@pytest.mark.parametrize("angle", [90, 180, 270])
def test_rotation_equals_pre_rotated_pixelwise(angle):
    """I-1 主不变量：rotations=[angle] 与"先把图转好"逐像素相同。"""
    a4, plan = _a4_id1()
    photo = _landscape()
    got = _render(a4, plan, [photo] * plan.count, rotations=[angle] + [0] * (plan.count - 1))
    want = _render(a4, plan, [pre_rotated(photo, angle)] +
                   [photo] * (plan.count - 1))
    assert got.tobytes() == want.tobytes()


def test_empty_rotations_equals_explicit_zeros():
    a4, plan = _a4_id1()
    photo = _landscape()
    assert (_render(a4, plan, [photo] * plan.count).tobytes() ==
            _render(a4, plan, [photo] * plan.count,
                    rotations=[0] * plan.count).tobytes())


def test_rotated_landscape_fills_portrait_cell_taller():
    """用户场景：200×100 横图进 25×32mm 竖格，FIT 高 12.5mm；转 90° 后 25mm。

    探针取首格内框 x 中线、格底沿下 1mm：不转时该点在画面上方留白里（白），
    转后画面高恰好 25mm 居中、上下各留 3.5mm，该点落在红色半区（红）。
    断言用像素取点，不复刻 crop 几何公式。
    """
    a4, plan = _a4_id1()
    ix, iy, iw, ih = plan.cells[0].inner_mm()
    assert (iw, ih) == pytest.approx((25.0, 32.0))
    photo = _landscape()
    probe = (int(ix + iw / 2), int(iy + ih - 1.0))
    assert _render(a4, plan, [photo] * plan.count).getpixel(probe) == (255, 255, 255)
    turned = _render(a4, plan, [photo] * plan.count, rotations=[90])
    assert turned.getpixel(probe) == (255, 0, 0)


def test_cw90_quadrant_lands_top_right():
    """顺时针 90° 的方向锁：左上红块必须转到纸面右上（ROTATE_90 会到左上）。

    转后画面 25×25mm 水平居中（x0 = ix），右上 1mm 点在红色区（原左上块）；
    左上是绿色区（原左下）。方向反了这两点同时变红绿互换。
    """
    a4, plan = _a4_id1()
    ix, iy, iw, ih = plan.cells[0].inner_mm()
    photo = _landscape()
    turned = _render(a4, plan, [photo] * plan.count, rotations=[90])
    assert turned.getpixel((int(ix + iw - 1), int(iy + ih / 2))) == (255, 0, 0)
    assert turned.getpixel((int(ix + 1), int(iy + ih / 2))) == (0, 255, 0)


@pytest.mark.parametrize("bad", [45, 120, None, "90", 90.5])
def test_illegal_angles_degrade_to_zero_without_raising(bad):
    """归一后仍非法 / 转不了 int：按 0 渲染，不抛错，与不转逐像素相同。"""
    a4, plan = _a4_id1()
    photo = _landscape()
    got = _render(a4, plan, [photo] * plan.count, rotations=[bad])
    assert got.tobytes() == _render(a4, plan, [photo] * plan.count).tobytes()


def test_negative_90_normalizes_to_270():
    a4, plan = _a4_id1()
    photo = _landscape()
    got = _render(a4, plan, [photo] * plan.count, rotations=[-90])
    assert got.tobytes() == _render(a4, plan, [photo] * plan.count,
                                    rotations=[270]).tobytes()


def test_rotations_shorter_than_photos_pads_zero():
    a4, plan = _a4_id1()
    photo = _landscape()
    got = _render(a4, plan, [photo] * plan.count, rotations=[0])
    assert got.tobytes() == _render(a4, plan, [photo] * plan.count).tobytes()


def test_photo_rotation_on_rotated_cell_still_pixelwise_parity():
    """格子旋转（装箱朝向）与照片旋转可叠加：叠加时先转照片、后走格子旋转路径。

    A4+4R 两格都是旋转格；对拍等式在旋转格上同样必须成立。
    """
    a4 = specs.find_spec("A4")
    plan = pack.pack(a4, specs.find_spec("4R"), gap_mm=0.0, allow_rotate=True,
                     printable=specs.printable_rect(a4))
    assert all(c.rotated for c in plan.cells)
    photo = _landscape()
    args = (plan, [photo] * plan.count, a4, DPI, modes.FIT_TO_PRINTABLE)
    got = render.render_page(*args, show_mask=False, show_cut_lines=False,
                             rotations=[90, 270])
    pre = [pre_rotated(photo, 90), pre_rotated(photo, 270)]
    want = render.render_page(plan, pre + [photo] * (plan.count - 2), a4, DPI,
                              modes.FIT_TO_PRINTABLE, show_mask=False,
                              show_cut_lines=False)
    assert got.tobytes() == want.tobytes()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_render_rotations.py -q`
Expected: FAIL/ERROR，报错含 `render_page() got an unexpected keyword argument 'rotations'`（前置用例还可能报 `_ANGLE_TRANSPOSE` 缺失——都算红到位）。

- [ ] **Step 3: 实现 `photoprint/core/render.py`**

在 `MASK_RGB`/`_MASK_ALPHA` 常量之后加：

```python
# 逐图旋转（M3-GUI 增量）：顺时针角度 → PIL transpose 操作。
# PIL 的 ROTATE_270 是顺时针 90°，与旋转格既有用法同口径。
_ANGLE_TRANSPOSE = {90: Image.ROTATE_270, 180: Image.ROTATE_180,
                    270: Image.ROTATE_90}


def _apply_rotation(photo, angle):
    """按顺时针 angle° 转照片。非法角度一律按 0（不转）降级：旋转是增强项，
    一次坏数据不得把整页渲染打死（与 store 的"任何损坏降级成没有"同口径）。
    归一必须是 90 的整数倍，45° 一类残余不得借 `% 360` 混进映射表。"""
    try:
        op = _ANGLE_TRANSPOSE.get(int(angle) % 360)
    except (TypeError, ValueError):
        return photo
    return photo if op is None else photo.transpose(op)
```

`render_page` 签名末位加 `rotations=()`：

```python
def render_page(plan, photos, sheet, dpi, mode, show_mask=True,
                show_cut_lines=True, borderless_active=False,
                offset_pct=(0.0, 0.0), rotations=()):
```

循环内 `photo = photos[idx] if idx < len(photos) else None` 与 `if photo is None: continue` 之后、`if mode == modes.BLEED_TRIM:` 之前插入一行（必须早于任何 `photo.width/height` 取值）：

```python
        photo = _apply_rotation(photo, rotations[idx] if idx < len(rotations) else 0)
```

- [ ] **Step 4: 跑新测试确认全绿**

Run: `python -m pytest tests/test_render_rotations.py -q`
Expected: 全部 PASS（13 条）。

- [ ] **Step 5: 全量回归（CLI 与既有渲染必须无感）**

Run: `python -m pytest tests/ -q`
Expected: 245 passed（232 + 13），0 failed。

- [ ] **Step 6: Commit**

```powershell
git add photoprint/core/render.py tests/test_render_rotations.py
git commit -m "feat(core): render_page 支持逐图顺时针旋转，非法角度降级为 0"
```

---

### Task 2: 编排层透传（jobs.py）

**Files:**
- Modify: `photoprint/jobs.py`（`Job` dataclass + `build_job`）
- Create: `tests/test_jobs_rotations.py`

**Interfaces:**
- Consumes: Task 1 的 `render_page(..., rotations=())`。
- Produces: `Job.rotations: tuple`（dataclass 字段，默认 `()`，位置在 `offset_pct` 之后）；`build_job(st, photos, sheet_key, cell_key, *, gap_mm=0.0, bleed_mm=modes.DEFAULT_BLEED_MM, mode=None, offset_pct=(0.0, 0.0), borderless_active=False, rotations=()) -> Job`。Task 3/4 的界面与持久化经 `build_job(rotations=...)` 进核心。

- [ ] **Step 1: 写失败测试 `tests/test_jobs_rotations.py`**

```python
"""rotations 必须原样透传到渲染层：编排层不得自己换算或归一角度（几何禁则）。"""
import pytest

pytest.importorskip("PIL", reason="需要 Pillow")

from PIL import Image  # noqa: E402

from photoprint import jobs  # noqa: E402
from photoprint.core import render, store  # noqa: E402


@pytest.fixture
def st(tmp_path):
    s = store.Store(tmp_path / "papers.json")
    s.load()
    return s


def _photo():
    return Image.new("RGB", (100, 100), (200, 30, 30))


def test_job_rotations_defaults_to_empty_tuple(st):
    job = jobs.build_job(st, [_photo()] * 4, "A4", "ID1", gap_mm=2.0)
    assert job.rotations == ()
    # 默认路径与旧行为逐像素等价（CLI 不传本参数，靠这条守住冻结）
    assert job.render(0, 25.4).tobytes()


def test_build_job_keeps_rotations_verbatim(st):
    job = jobs.build_job(st, [_photo()] * 4, "A4", "ID1", gap_mm=2.0,
                         rotations=(90, -90, 45, "x"))
    assert job.rotations == (90, -90, 45, "x")


def test_job_render_forwards_rotations_without_touching(st, monkeypatch):
    """与 test_build_job_passes_percentage_through 同款 spy：只拦一层看真参数。"""
    seen = {}
    real = render.render_page

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(render, "render_page", spy)
    job = jobs.build_job(st, [_photo()] * 4, "A4", "ID1", gap_mm=2.0,
                         rotations=(90, 0, 0, 0))
    job.render(0, 25.4)
    assert seen["rotations"] == (90, 0, 0, 0)


def test_rotation_changes_rendered_pixels(st):
    a = jobs.build_job(st, [_photo()] * 4, "A4", "ID1", gap_mm=2.0)
    b = jobs.build_job(st, [_photo()] * 4, "A4", "ID1", gap_mm=2.0,
                       rotations=(90,) + (0,) * 3)
    assert a.render(0, 25.4).tobytes() != b.render(0, 25.4).tobytes()
```

（注意：`test_jobs.py` 有扫源码的守门断言，新代码与注释里不得出现 `print(`、`PySide6`、`win32print` 字样。）

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_jobs_rotations.py -q`
Expected: FAIL，`build_job() got an unexpected keyword argument 'rotations'`。

- [ ] **Step 3: 实现 `photoprint/jobs.py`**

`Job` 字段表在 `offset_pct` 之后加：

```python
    rotations: tuple = ()   # 逐图顺时针角度，原样交 core 归一；短于 photos 缺位按 0
```

`build_job` 签名末位加 `rotations=()`，构造 `Job` 时带上：

```python
def build_job(st, photos, sheet_key, cell_key, *, gap_mm=0.0,
              bleed_mm=modes.DEFAULT_BLEED_MM, mode=None,
              offset_pct=(0.0, 0.0), borderless_active=False,
              rotations=()) -> Job:
    plan, mode_eff = build_layout(st, sheet_key, cell_key, gap_mm, bleed_mm,
                                  mode, borderless_active=borderless_active)
    # 百分比原样交给 core：同一页可能两种朝向混排，"按哪个尺寸换算"是逐格
    # 决策（T3 评审 I-1），本层若先按首格换算成 mm，其余格的 ±50% 就失真
    return Job(plan=plan, mode=mode_eff, sheet=st.resolve(sheet_key),
               photos=list(photos),
               offset_pct=tuple(float(v) for v in offset_pct),
               borderless_active=borderless_active,
               rotations=tuple(rotations))
```

`Job.render` 的 `render.render_page(...)` 调用末位加：

```python
                                  rotations=self.rotations)
```

- [ ] **Step 4: 跑测试确认全绿**

Run: `python -m pytest tests/test_jobs_rotations.py tests/test_jobs.py -q`
Expected: 全 PASS。

- [ ] **Step 5: 全量回归**

Run: `python -m pytest tests/ -q`
Expected: 249 passed（245 + 4），0 failed。

- [ ] **Step 6: Commit**

```powershell
git add photoprint/jobs.py tests/test_jobs_rotations.py
git commit -m "feat(jobs): Job 增加 rotations 字段并原样透传至渲染层"
```

---

### Task 3: 界面「旋转 90°」按钮与列表角度后缀

**Files:**
- Modify: `photoprint/app/main_window.py`（`__init__`、`_build_ui`、`append_photo`、`_on_clear_photos`、`_rebuild_job`、新增 `_photo_item_text`/`_on_rotate`）
- Modify: `tests/test_app_main_window.py`（文件末尾追加用例）

**Interfaces:**
- Consumes: Task 2 的 `jobs.build_job(..., rotations=...)`；既有 `self.photo_list.currentRow()`、`self._debounce`。
- Produces: `MainWindow.photo_rotations: list[int]`（与 `photos` 严格等长同序）；`MainWindow._photo_item_text(name, img, angle) -> str`（0° 时逐字等于现文案）；`MainWindow.rotate_btn`（objectName `"rotate_btn"`，Task 4 测试经它触发）；`MainWindow._on_rotate()`。

- [ ] **Step 1: 追加失败测试到 `tests/test_app_main_window.py`**

```python
def _rotate_btn(w):
    return w.findChild(type(w.export_btn), "rotate_btn")


def test_rotate_without_selection_prompts_and_keeps_state(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    w.photo_list.clearSelection()
    before = list(w.photo_rotations)
    _rotate_btn(w).click()
    assert w.photo_rotations == before == [0, 0, 0, 0]
    assert "请先选中照片" in w.statusBar().currentMessage()


def test_rotate_cycles_90_degrees_and_marks_list(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    w.photo_list.setCurrentRow(1)
    _rotate_btn(w).click()
    assert w.photo_rotations == [0, 90, 0, 0]
    assert "↻90°" in w.photo_list.item(1).text()
    assert "↻" not in w.photo_list.item(0).text()   # 0° 行逐字保持原文案
    w._refresh()
    assert w.job.rotations == (0, 90, 0, 0)         # 角度进了编排层（Task 2 接口）
    for _ in range(3):                              # 4 次一循环回 0
        _rotate_btn(w).click()
    assert w.photo_rotations == [0, 0, 0, 0]
    assert "↻" not in w.photo_list.item(1).text()


def test_rotate_then_refresh_changes_preview_pixels(qapp, tmp_path):
    """所见即所得的构造保证：按钮 → photo_rotations → build_job → 渲染层，
    全链路走通后当前页像素必须真的变了（断言像素，不断言中间变量）。"""
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    w._refresh()
    before = w.job.render(0, 25.4).tobytes()
    w.photo_list.setCurrentRow(0)
    _rotate_btn(w).click()
    w._refresh()
    assert w.job.render(0, 25.4).tobytes() != before


def test_clear_resets_rotations(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    w.photo_list.setCurrentRow(0)
    _rotate_btn(w).click()
    w._on_clear_photos()
    assert w.photo_rotations == []


def test_failed_photo_still_tracks_rotation(qapp, tmp_path):
    """读取失败占位项也允许记角度（渲染时被跳过，数据不坏）：不做特殊分支。"""
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    w = MainWindow(st=_store(tmp_path))
    w.append_photo(str(bad))
    w.photo_list.setCurrentRow(0)
    _rotate_btn(w).click()
    assert w.photo_rotations == [90]
    assert "↻90°" in w.photo_list.item(0).text()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_app_main_window.py -q -k rotate`
Expected: FAIL/ERROR，`_rotate_btn` 返回 None 后 `.click()` 抛 AttributeError（按钮还不存在）。

- [ ] **Step 3: 实现 `photoprint/app/main_window.py`**

`__init__` 中 `self.photo_paths = []` 之后加：

```python
        self.photo_rotations = []  # 逐图顺时针角度，与 photos 严格等长同序
```

`_build_ui` 按钮行改为（在 `clear_btn` 之后加一个）：

```python
        rotate_btn = QPushButton("旋转 90°")
        rotate_btn.setObjectName("rotate_btn")
        rotate_btn.clicked.connect(self._on_rotate)
        btns = QHBoxLayout()
        btns.addWidget(add_btn)
        btns.addWidget(clear_btn)
        btns.addWidget(rotate_btn)
```

（原 `btns` 两行 addWidget 保持不变，只追加第三行；`clear_btn.clicked.connect(self._on_clear_photos)` 等既有连接不动。）

新增两个方法（放在 `_on_clear_photos` 之前）：

```python
    @staticmethod
    def _photo_item_text(name, img, angle):
        """列表项文字单一真相源：0° 时逐字等于旧文案，既有断言不受扰动。"""
        if img is None:
            base = f"{name}（读取失败）"
        else:
            base = f"{name}  {img.width}×{img.height}px"
        return base if angle == 0 else f"{base}  ↻{angle}°"

    def _on_rotate(self):
        row = self.photo_list.currentRow()
        if not 0 <= row < len(self.photo_rotations):
            self._set_status("请先选中照片")     # 正常色：这是引导，不是错误
            return
        self.photo_rotations[row] = (self.photo_rotations[row] + 90) % 360
        item = self.photo_list.item(row)
        img = self.photos[row] if row < len(self.photos) else None
        item.setText(self._photo_item_text(
            Path(self.photo_paths[row]).name, img, self.photo_rotations[row]))
        self._debounce.start()
```

`append_photo` 三处改：成功分支 `self.photo_paths.append(str(path))` 之后加 `self.photo_rotations.append(0)`；失败分支同样在 `self.photo_paths.append(str(path))` 之后加 `self.photo_rotations.append(0)`，并把 `QListWidgetItem(f"{name}（读取失败）")` 改为 `QListWidgetItem(self._photo_item_text(name, None, 0))`；成功分支把 `QListWidgetItem(f"{name}  {img.width}×{img.height}px")` 改为 `QListWidgetItem(self._photo_item_text(name, img, 0))`（两处都写成 `self._photo_item_text(name, img_or_None, 0)` 的定式，防"非 0 入口"漏网）。

`_on_clear_photos` 首行改为：

```python
        self.photos, self.photo_paths, self.photo_rotations = [], [], []
```

`_rebuild_job` 里 `jobs.build_job(...)` 调用参数 `offset_pct=p["offset_pct"])` 改为 `offset_pct=p["offset_pct"], rotations=tuple(self.photo_rotations))`。

- [ ] **Step 4: 跑本文件全部测试确认全绿**

Run: `python -m pytest tests/test_app_main_window.py -q`
Expected: 全 PASS（既有 + 新增 5 条）。

- [ ] **Step 5: 全量回归**

Run: `python -m pytest tests/ -q`
Expected: 254 passed（249 + 5），0 failed。

- [ ] **Step 6: Commit**

```powershell
git add photoprint/app/main_window.py tests/test_app_main_window.py
git commit -m "feat(gui): 照片列表增加「旋转 90°」按钮与角度后缀显示"
```

---

### Task 4: last_job 持久化 rotations

**Files:**
- Modify: `photoprint/app/main_window.py`（`save_last_job`、`_restore_last_job`）
- Modify: `tests/test_app_main_window.py`（追加用例）

**Interfaces:**
- Consumes: Task 3 的 `photo_rotations`/`rotate_btn`；既有 `st.set_last_job`/`get_last_job`（dict 直存，store 层无需改动）。
- Produces: `last_job["rotations"]`（`list[int]`，与 `photo_paths` 下标一一对应）；`MainWindow._restore_rotations(job)`。

- [ ] **Step 1: 追加失败测试到 `tests/test_app_main_window.py`**

```python
def test_rotations_roundtrip_through_two_windows(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    w.photo_list.setCurrentRow(1)
    _rotate_btn(w).click()
    w.save_last_job(out_dir=str(tmp_path))
    again = MainWindow(st=_store(tmp_path))
    assert again.photo_rotations == [0, 90, 0, 0]        # 角度与照片下标对齐
    assert "↻90°" in again.photo_list.item(1).text()


@pytest.mark.parametrize("bad", ["[90]", [90, "x"], [90, None]])
def test_bad_rotations_config_degrades_to_all_zero(qapp, tmp_path, bad):
    """形状坏 / 含不可转 int 的条目：整体不恢复（全 0），其余字段照常——
    逐项降级会让角度错位到别的照片上，比全不恢复更糟（规格第 5 节）。"""
    s = _store(tmp_path)
    s.set_last_job({"sheet_key": "A4", "cell_key": "ID1",
                    "photo_paths": _make_photos(tmp_path, 2),
                    "rotations": bad})
    s.save()
    w = MainWindow(st=_store(tmp_path))                   # 不应抛
    assert w.photo_rotations == [0, 0]


def test_rotations_length_mismatch_truncates_or_pads(qapp, tmp_path):
    s = _store(tmp_path)
    s.set_last_job({"sheet_key": "A4", "cell_key": "ID1",
                    "photo_paths": _make_photos(tmp_path, 2),
                    "rotations": [90, 180, 270, 45]})     # 超长：截到 2
    s.save()
    w = MainWindow(st=_store(tmp_path))
    assert w.photo_rotations == [90, 180]
    # 45 不在 {0,90,180,270}，core 归一按 0 渲染；界面原样保留，不在此层换算


def test_rotations_out_of_range_still_renderable(qapp, tmp_path):
    """-90 存得下、渲染等价于 270：归一只在 core 做，界面不换算。"""
    s = _store(tmp_path)
    s.set_last_job({"sheet_key": "A4", "cell_key": "ID1",
                    "photo_paths": _make_photos(tmp_path, 1),
                    "rotations": [-90]})
    s.save()
    w = MainWindow(st=_store(tmp_path))
    assert w.photo_rotations == [-90]
    w._refresh()
    assert w.job is not None                              # 渲染路径不被坏角度打死
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_app_main_window.py -q -k rotation`
Expected: FAIL，`photo_rotations` 恢复后为 `[0, 0]` 而断言 `[0, 90, 0, 0]` 不成立（roundtrip 第一条红）。

- [ ] **Step 3: 实现 `photoprint/app/main_window.py`**

`save_last_job` 的 dict 里 `"photo_paths": list(self.photo_paths)` 之后加一行：

```python
            "rotations": list(self.photo_rotations)})
```

（并把原 `"photo_paths": list(self.photo_paths)})` 行尾改为 `,`。）

`_restore_last_job` 末尾（照片 append 循环之后）加调用，并新增方法：

```python
        self._restore_rotations(job)

    def _restore_rotations(self, job):
        """rotations 与 photo_paths 按下标对齐：任一元素不可转 int 就整体不
        恢复（全 0）——逐项降级会把"第 3 张转了"错位成"第 4 张转了"，比全丢
        更糟。长度不符按第 5 节截断/补 0。角度原样存，归一只在 core 做。"""
        rots = job.get("rotations")
        n = len(self.photo_rotations)
        if rots is None or not isinstance(rots, (list, tuple)):
            return
        try:
            vals = [int(v) for v in rots]
        except (TypeError, ValueError, OverflowError):
            return
        vals = vals[:n]
        self.photo_rotations = vals + [0] * (n - len(vals))
        for row in range(n):
            img = self.photos[row] if row < len(self.photos) else None
            name = Path(self.photo_paths[row]).name
            self.photo_list.item(row).setText(
                self._photo_item_text(name, img, self.photo_rotations[row]))
```

- [ ] **Step 4: 跑本文件全部测试确认全绿**

Run: `python -m pytest tests/test_app_main_window.py -q`
Expected: 全 PASS。

- [ ] **Step 5: 全量回归**

Run: `python -m pytest tests/ -q`
Expected: 261 passed（254 + 7，parametrize 计 3），0 failed。

- [ ] **Step 6: Commit**

```powershell
git add photoprint/app/main_window.py tests/test_app_main_window.py
git commit -m "feat(gui): 逐图旋转角度随 last_job 持久化并在启动时恢复"
```

---

### Task 5: 全量验收（测试 + _lab 比对 + 手工核对）

**Files:**
- 无代码改动；如任何一步变红，回到对应 Task 修复后重跑。

**Interfaces:**
- Consumes: Task 1–4 全部产出。
- Produces: 验收结论（写进本计划执行记录）。

- [ ] **Step 1: 全量测试**

Run: `python -m pytest tests/ -q`
Expected: 261 passed，0 failed。

- [ ] **Step 2: 内核比对脚本（不改动、必须仍绿）**

Run: `python _lab/m1m2_check.py`
Expected: 全 OK、exit 0（`$LASTEXITCODE` 为 0）。

- [ ] **Step 3: GUI/CLI parity 脚本（不改动、必须仍 OK）**

Run: `python _lab/check_gui_cli_parity.py`
Expected: OK（CLI 不传 rotations，默认 `()` 与历史逐像素等价由 Task 1 的 `test_empty_rotations_equals_explicit_zeros` 与 parity 脚本共同守住）。

- [ ] **Step 4: exe 重建与手工核对（需交互桌面，可与用户一起做）**

Run: `powershell -File build_exe.ps1`，然后启动 `dist\PhotoPrint.exe`：
1. 添加截图中的横图（1870×1071），A4 + 3R + 完整放入；
2. 选中该照片点「旋转 90°」→ 预览画面占格高度明显增大，列表出现 `↻90°`；
3. 导出 PDF，与预览一致（无灰遮罩、画面方向正确）；
4. 关窗重开 → 照片与角度都自动恢复。

- [ ] **Step 5: 收尾提交（若验收中有文档/账本更新）**

```powershell
git status --short
```
Expected: 干净（Task 1–4 已各自提交）；如有遗留改动按内容补提交，信息前缀 `docs:` 或 `fix(gui):`。

---

## Self-Review 记录

- **规格覆盖**：spec §1 范围 → Task 1–4 逐项对应；§2 语义（I-1、偏移不改、归一、短表补 0）→ Task 1 测试；§3 接口 → Task 1/2；§4 界面 → Task 3；§5 持久化 → Task 4；§6 错误处理 → Task 1（非法角度）/3（未选中）/4（坏配置）；§7 测试方案全覆盖（`test_render_rotations.py`、`test_jobs_rotations.py`、`test_app_main_window.py` 增补，既有 CLI 冻结由 parity + 全量回归守住）；§8 验收 → Task 5。
- **占位符扫描**：无 TBD/TODO；所有代码步骤给出完整代码。
- **类型一致性**：`rotations` 在 render（默认 `()`、按下标取值、短表补 0）、jobs（`tuple` 字段 + `tuple(rotations)` 落库）、GUI（`list[int]` 活状态 + `tuple(...)` 交 build_job）三层命名一致；`_photo_item_text(name, img, angle)` 签名在 Task 3 定义、Task 4 复用；`rotate_btn` objectName 在 Task 3 定义、Task 4 测试引用。
