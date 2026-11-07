# 文字叠加逐张调整（位置/旋转）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让日期标签与文字水印的**位置(四角)与旋转(八档)**可按每张照片单独调整，其余样式保持全局；选中照片即编辑该张，未选中编辑全局默认，提供"应用到所有照片"。

**Architecture:** `TextSpec` 加 `rotation`；`draw_overlay` 仅在 `rotation!=0` 走"文字→临时层→旋转→按旋转后包围盒锚点合成"新分支（0° 直绘路径不动）；`render_page` 加 `date_overrides`/`wm_overrides` 两个逐格 `(corner, rotation)` 平行参，用 `dataclasses.replace` 注入 base spec；`jobs` 透传；`app` 把 4 项逐张生效值存进 pool、选中即编辑、物化 overrides、持久化。

**Tech Stack:** PySide6（QComboBox/QPushButton）、PIL（`Image.rotate`/`alpha_composite`）、pytest-qt（offscreen）、monkeypatch。

## Global Constraints

- 分层红线：几何/旋转全在 `core`；`app` 只汇参数、物化逐张生效值、不做 mm/像素运算；`jobs` 纯透传。
- 向后兼容红线：`render_page`/`Job`/`build_job` 新参一律带默认（`()`＝无覆盖）；`TextSpec.rotation` 默认 0；`rotation==0` 走现有直绘路径 → 全默认时导出与升级前逐像素一致，既有全部测试零改动。
- 旋转方向口径：预设角度定义为**顺时针**；PIL `Image.rotate` 逆时针，故传 `-rotation`（与既有 `_ANGLE_TRANSPOSE` 顺时针同口径）。
- 八档预设：`(0, 45, 90, 135, 180, 225, 270, 315)`。
- 角下拉序：`CORNER_CHOICES = (左上 tl, 右上 tr, 左下 bl, 右下 br)` → 索引 0/1/2/3。
- 任何"旋转后像素变化"断言必须用**非对称/长文字**（避免纯色/对称无牙陷阱，见记忆 4d342c0f）。
- 变异验牙后必须 `residue=0`（无 `MUTATION-TEMP` 残留）。
- 新建/追加会构造 MainWindow 的测试须靠该文件既有 autouse `_no_leaked_threads` 收尾（见记忆 9899c86c）；本计划测试全部加在既有 `test_app_main_window.py`，夹具已在。
- PowerShell 用 `;` 分隔，不用 `&&`。提交消息用 UTF8 无 BOM 文件 + `git commit -F`。

---

### Task 1: core/text_overlay — rotation 字段 + 旋转绘制分支

**Files:**
- Modify: `photoprint/core/text_overlay.py`（`TextSpec` 加字段、加 `ROTATION_PRESETS`、`draw_overlay` 加分支）
- Test: `tests/test_text_overlay.py`

**Interfaces:**
- Consumes: 现有 `TextSpec`/`anchor_point`/`inset_px`/`size_px`/`FONT_TABLE`。
- Produces: `TextSpec.rotation: int`（默认 0）、`ROTATION_PRESETS`、`draw_overlay` 支持 `spec.rotation`。Task 2 依赖 `TextSpec.rotation` 与 `dataclasses.replace` 注入。

- [ ] **Step 1: 追加失败测试**（`tests/test_text_overlay.py` 末尾）

```python
def test_textspec_rotation_default_and_presets():
    assert TextSpec().rotation == 0
    assert to.ROTATION_PRESETS == (0, 45, 90, 135, 180, 225, 270, 315)


def test_draw_overlay_rotation_zero_equals_direct(monkeypatch):
    arial = _arial()
    if arial is None:
        pytest.skip("无 arial 字体")
    monkeypatch.setattr(to, "FONT_TABLE", {"t": (arial, None)})
    a = Image.new("RGB", (200, 120), (0, 0, 0))
    to.draw_overlay(a, (0, 0, 200, 120), _spec(rotation=0), "DATE", 25.4)
    b = Image.new("RGB", (200, 120), (0, 0, 0))
    to.draw_overlay(b, (0, 0, 200, 120), _spec(), "DATE", 25.4)
    assert a.tobytes() == b.tobytes()                    # 0° 逐像素等于直绘


def test_draw_overlay_rotation_90_changes_pixels(monkeypatch):
    arial = _arial()
    if arial is None:
        pytest.skip("无 arial 字体")
    monkeypatch.setattr(to, "FONT_TABLE", {"t": (arial, None)})
    base = Image.new("RGB", (200, 120), (0, 0, 0))
    to.draw_overlay(base, (0, 0, 200, 120), _spec(corner=Corner.TL), "WIDE", 25.4)
    rot = Image.new("RGB", (200, 120), (0, 0, 0))
    to.draw_overlay(rot, (0, 0, 200, 120),
                    _spec(corner=Corner.TL, rotation=90), "WIDE", 25.4)
    assert rot.tobytes() != base.tobytes()               # 非对称长文字：旋转有牙
    assert max(p[0] for p in rot.getdata()) == 255       # 仍实心红


def test_draw_overlay_rotation_clips_to_cell(monkeypatch):
    arial = _arial()
    if arial is None:
        pytest.skip("无 arial 字体")
    monkeypatch.setattr(to, "FONT_TABLE", {"t": (arial, None)})
    page = Image.new("RGB", (300, 300), (0, 0, 0))
    to.draw_overlay(page, (50, 50, 100, 100),
                    _spec(corner=Corner.BR, rotation=45), "MD", 25.4)
    assert page.crop((150, 150, 300, 300)).getbbox() is None
    assert page.crop((0, 0, 50, 300)).getbbox() is None


def test_draw_overlay_rotation_overflow_skips(monkeypatch):
    arial = _arial()
    if arial is None:
        pytest.skip("无 arial 字体")
    monkeypatch.setattr(to, "FONT_TABLE", {"t": (arial, None)})
    ok = Image.new("RGB", (200, 60), (0, 0, 0))
    to.draw_overlay(ok, (0, 0, 200, 60), _spec(rotation=0), "WATERMARK", 25.4)
    assert ok.getbbox() is not None                      # 不旋转塞得下（对照）
    page = Image.new("RGB", (200, 60), (0, 0, 0))
    to.draw_overlay(page, (0, 0, 200, 60), _spec(rotation=45), "WATERMARK", 25.4)
    assert page.getbbox() is None                        # 旋转后包围盒超格→不画不抛
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_text_overlay.py -q`
Expected: FAIL — `AttributeError: 'TextSpec' object has no attribute 'rotation'` / `module ... has no attribute 'ROTATION_PRESETS'`。

- [ ] **Step 3: 实现**（`text_overlay.py`）

`TextSpec` 在 `margin_pct` 之前加字段（保持其余字段不动）：

```python
    rotation: int = 0          # 文字顺时针角度，八档预设之一；0＝不旋转
```

`FONT_TABLE` 之后加常量：

```python
ROTATION_PRESETS = (0, 45, 90, 135, 180, 225, 270, 315)
```

`draw_overlay` 内，把现有 `ax, ay = anchor_point(...)` 到函数尾（原 121–128 行）替换为分支版：

```python
    fill = tuple(spec.rgb)[:3] + (int(spec.alpha),)
    if spec.rotation:
        text_img = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        ImageDraw.Draw(text_img).text((-l, -t), text, font=font, fill=fill,
                                      stroke_width=stroke, stroke_fill=fill)
        rot = text_img.rotate(-int(spec.rotation), expand=True,
                              resample=Image.BICUBIC)
        rw, rh = rot.size
        if rw > avail_w or rh > avail_h:                 # 旋转后放不下：降级不画
            return
        ax, ay = anchor_point(spec.corner, (cw, ch), (rw, rh), inset)
        layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        layer.alpha_composite(rot, (ax, ay))
    else:
        ax, ay = anchor_point(spec.corner, (cw, ch), (tw, th), inset)
        layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((ax - l, ay - t), text, font=font, fill=fill,
                                   stroke_width=stroke, stroke_fill=fill)
    region = page.crop((x, y, x + cw, y + ch)).convert("RGBA")
    region = Image.alpha_composite(region, layer)
    page.paste(region.convert("RGB"), (x, y))
```

> 注：原 `fill = ...` 行（现 123 行）上移到分支之前；`else` 分支即原直绘逻辑，逐像素不变。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_text_overlay.py -q`
Expected: PASS（新增 5 条 + 既有全绿）

- [ ] **Step 5: 变异验牙**

1. 删 `if spec.rotation:` 分支（永远走 else）→ `test_draw_overlay_rotation_90_changes_pixels` 红（旋转不生效）。
2. 删旋转分支里 `if rw > avail_w or rh > avail_h: return` → `test_draw_overlay_rotation_90_changes_pixels` 仍绿但 `test_draw_overlay_rotation_overflow_skips` 红（溢出被裁进格仍留痕）。
验后还原。Run：`python -m pytest tests/test_text_overlay.py -q`，Expected：坏时 FAIL、还原后 PASS。
（诚实记账：旋转**方向**（顺/逆时针，`-rotation` 取负）不被任何像素断言捕获——90° 用例只验"变了"不验"往哪变"；该方向由 exe 目测验收，本机无独立单测牙。）

- [ ] **Step 6: 提交**

```bash
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
python -c "open('.superpowers/sdd/_ovpr_t1_msg.txt','w',encoding='utf-8').write('core: TextSpec.rotation + draw_overlay 旋转分支（0° 直绘路径不动）\n')"; git add photoprint/core/text_overlay.py tests/test_text_overlay.py; git commit -F .superpowers/sdd/_ovpr_t1_msg.txt
```

---

### Task 2: core/render.py — 逐格 overrides 注入

**Files:**
- Modify: `photoprint/core/render.py`（`import dataclasses`、`_with_corner_rot`、`render_page` 新参与逐格 replace）
- Test: `tests/test_render_overlay.py`

**Interfaces:**
- Consumes: Task 1 `TextSpec.rotation`、`dataclasses.replace`。
- Produces: `render_page(..., date_overrides=(), wm_overrides=())`。Task 3 依赖这两个新参名。

- [ ] **Step 1: 追加失败测试**（`tests/test_render_overlay.py` 末尾）

```python
def test_date_overrides_apply_per_cell(real_font):
    a4, plan = _a4_id1()
    ph = _photo()
    base = _render(a4, plan, [ph] * plan.count)
    spec = TextSpec(enabled=True, font_key="t", size_mm=6.0, corner=Corner.TL,
                    rgb=(255, 255, 255), alpha=255)
    ov = [(Corner.BR, 0)] * plan.count                   # 逐格改右下 → 与 base(TL) 不同
    got = _render(a4, plan, [ph] * plan.count, date_overlay=spec,
                  date_texts=["2025-01-02"] * plan.count, date_overrides=ov)
    assert got.tobytes() != base.tobytes()


def test_overrides_default_empty_equals_base(real_font):
    a4, plan = _a4_id1()
    ph = _photo()
    spec = TextSpec(enabled=True, font_key="t", size_mm=6.0, corner=Corner.TL,
                    rgb=(255, 255, 255), alpha=255)
    none = _render(a4, plan, [ph] * plan.count, date_overlay=spec,
                   date_texts=["2025-01-02"] * plan.count)
    empty = _render(a4, plan, [ph] * plan.count, date_overlay=spec,
                    date_texts=["2025-01-02"] * plan.count, date_overrides=())
    assert none.tobytes() == empty.tobytes()             # 默认空＝向后兼容


def test_override_none_element_uses_base(real_font):
    a4, plan = _a4_id1()
    ph = _photo()
    spec = TextSpec(enabled=True, font_key="t", size_mm=6.0, corner=Corner.TL,
                    rgb=(255, 255, 255), alpha=255)
    ov = [None] * plan.count
    got = _render(a4, plan, [ph] * plan.count, date_overlay=spec,
                  date_texts=["2025-01-02"] * plan.count, date_overrides=ov)
    assert got.tobytes() == _render(a4, plan, [ph] * plan.count,
                                    date_overlay=spec,
                                    date_texts=["2025-01-02"] * plan.count).tobytes()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_render_overlay.py -q`
Expected: FAIL — `TypeError: render_page() got an unexpected keyword argument 'date_overrides'`。

- [ ] **Step 3: 实现**（`render.py`）

顶部 import 块补 `dataclasses`（在 `from PIL import ...` 之前）：

```python
import dataclasses
```

模块级（`render_page` 之前）加 helper：

```python
def _with_corner_rot(spec, ov):
    """ov=(corner, rotation) 或 None。None 原样返回；否则替换 corner/rotation。"""
    if ov is None:
        return spec
    corner, rotation = ov
    return dataclasses.replace(spec, corner=corner, rotation=rotation)
```

`render_page` 签名在 `date_texts=()` 之后加两参：

```python
                date_overlay=None, watermark_overlay=None, date_texts=(),
                date_overrides=(), wm_overrides=()):
```

循环内叠加段（现为 `rect_px = ...` 到 `draw_overlay(page, rect_px, date_overlay, dt, dpi)`）替换为：

```python
        rect_px = (paste_x, paste_y, piece.width, piece.height)
        if watermark_overlay is not None and watermark_overlay.enabled:
            wm_ov = wm_overrides[idx] if idx < len(wm_overrides) else None
            spec = _with_corner_rot(watermark_overlay, wm_ov)
            text_overlay.draw_overlay(page, rect_px, spec, spec.text, dpi)
        if date_overlay is not None and date_overlay.enabled:
            dt = date_texts[idx] if idx < len(date_texts) else None
            if dt:
                d_ov = date_overrides[idx] if idx < len(date_overrides) else None
                spec = _with_corner_rot(date_overlay, d_ov)
                text_overlay.draw_overlay(page, rect_px, spec, dt, dpi)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_render_overlay.py -q`
Expected: PASS（新增 3 条 + 既有 4 条全绿）

- [ ] **Step 5: 变异验牙**

1. `_with_corner_rot` 里 `return spec`（忽略 ov）→ `test_date_overrides_apply_per_cell` 红。
2. 删 `d_ov = ... if idx < len(...) else None` 改成恒 `None`（overrides 不生效）→ 同上红。
验后还原。Run：`python -m pytest tests/test_render_overlay.py -q`，Expected：坏时 FAIL、还原后 PASS。

- [ ] **Step 6: 提交**

```bash
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
python -c "open('.superpowers/sdd/_ovpr_t2_msg.txt','w',encoding='utf-8').write('core: render_page 逐格 date_overrides/wm_overrides 注入 corner/rotation（默认空＝向后兼容）\n')"; git add photoprint/core/render.py tests/test_render_overlay.py; git commit -F .superpowers/sdd/_ovpr_t2_msg.txt
```

---

### Task 3: jobs.py 透传 overrides

**Files:**
- Modify: `photoprint/jobs.py`（`Job` 字段 + `render` 切片透传 + `build_job` 参）
- Test: `tests/test_jobs_overlay.py`

**Interfaces:**
- Consumes: Task 2 `render_page` 新参。
- Produces: `Job.date_overrides/wm_overrides`、`build_job(..., date_overrides=(), wm_overrides=())`。Task 4 依赖 `build_job` 新参。

- [ ] **Step 1: 追加失败测试**（`tests/test_jobs_overlay.py` 末尾）

```python
def test_build_job_accepts_overrides(tmp_path):
    st = _store(tmp_path)
    job = jobs.build_job(st, [Image.new("RGB", (200, 100))], "A4", "ID1",
                         date_overrides=[("br", 45)], wm_overrides=[("tl", 90)])
    assert job.date_overrides == (("br", 45),)
    assert job.wm_overrides == (("tl", 90),)


def test_job_overrides_reach_render(tmp_path, monkeypatch):
    st = _store(tmp_path)
    seen = {}
    real = jobs.render.render_page

    def spy(*a, **k):
        seen["d"] = k.get("date_overrides")
        return real(*a, **k)
    monkeypatch.setattr(jobs.render, "render_page", spy)
    job = jobs.build_job(st, [Image.new("RGB", (200, 100))], "A4", "ID1",
                         date_texts=["2025-01-02"], date_overrides=[("br", 0)])
    job.render(0, 96.0)
    assert seen["d"] == (("br", 0),)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_jobs_overlay.py -q`
Expected: FAIL — `TypeError: build_job() got an unexpected keyword argument 'date_overrides'`。

- [ ] **Step 3: 实现**（`jobs.py`）

`Job` 在 `date_texts: tuple = ()` 之后加：

```python
    date_overrides: tuple = ()
    wm_overrides: tuple = ()
```

`Job.render` 内 `dt_chunk = ...` 之后加两切片，并把 `render_page` 调用补两参：

```python
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
                                  wm_overrides=wo_chunk)
```

`build_job` 签名在 `date_texts=()` 之后加 `date_overrides=(), wm_overrides=()`；`return Job(...)` 补：

```python
               date_texts=tuple(date_texts),
               date_overrides=tuple(date_overrides),
               wm_overrides=tuple(wm_overrides))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_jobs_overlay.py -q`
Expected: PASS（新增 2 条 + 既有全绿）

- [ ] **Step 5: 变异验牙**

`Job.render` 里把 `date_overrides=do_chunk` 改回 `date_overrides=()` → `test_job_overrides_reach_render` 红。验后还原。

- [ ] **Step 6: 提交**

```bash
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
python -c "open('.superpowers/sdd/_ovpr_t3_msg.txt','w',encoding='utf-8').write('jobs: Job/build_job 透传 date_overrides/wm_overrides\n')"; git add photoprint/jobs.py tests/test_jobs_overlay.py; git commit -F .superpowers/sdd/_ovpr_t3_msg.txt
```

---

### Task 4: app — 逐张生效值存 pool + 选中即编辑 + 物化

**Files:**
- Modify: `photoprint/app/main_window.py`（`__init__` 状态、`_build_ui` 加 date_rot/wm_rot + 应用按钮、防抖连接改向、`_on_photo_clicked`/`_on_clear_photos` 联动、`append_photo` 种子、`_params` 加 rotation、`_rebuild_job` 物化、新增编辑/物化 helper）
- Test: `tests/test_app_main_window.py`

**Interfaces:**
- Consumes: Task 1 `TextSpec.rotation`、Task 3 `build_job` 新参；既有 `_on_photo_clicked`/`_place_source`/`_select_by_data`/`_ov` 控件。
- Produces: `self._ov_base`/`self._ov_editing`/`self._ov_loading`；pool 条目 4 字段；`_params` base spec 带 rotation；`_rebuild_job` 传 overrides。

- [ ] **Step 1: 追加失败测试**（`tests/test_app_main_window.py` 末尾）

```python
def test_new_photo_seeds_overlay_from_base(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    w.date_corner.setCurrentIndex(3)                     # 无选中→写 base=右下
    w.date_rot.setCurrentIndex(1)                       # 45°
    w.append_photo(_make_photos(tmp_path, 1)[0])
    assert w.pool[0]["date_corner"] == "br"
    assert w.pool[0]["date_rot"] == 45


def test_select_photo_loads_its_overlay(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path, n=2)
    w.pool[1]["date_corner"] = "bl"
    w._on_photo_clicked(w.photo_list.item(1))
    assert w._ov_editing == 1
    assert w.date_corner.currentData() == "bl"


def test_editing_selected_photo_writes_only_that_photo(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path, n=2)
    w._on_photo_clicked(w.photo_list.item(0))
    base_before = dict(w._ov_base)
    w.date_corner.setCurrentIndex(3)                    # 右下
    assert w.pool[0]["date_corner"] == "br"
    assert w._ov_base == base_before                    # base 不动
    assert w.pool[1]["date_corner"] != "br"


def test_deselect_restores_base(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    w.date_corner.setCurrentIndex(3)                    # base=br（无选中）
    _fill(w, tmp_path, n=1)
    w.pool[0]["date_corner"] = "tl"                     # 令照片≠base
    item = w.photo_list.item(0)
    w._on_photo_clicked(item)                           # 选中→tl
    assert w.date_corner.currentData() == "tl"
    w._on_photo_clicked(item)                           # 再点取消→回 base
    assert w._ov_editing is None
    assert w.date_corner.currentData() == "br"


def test_apply_overlay_to_all(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path, n=2)
    w.date_corner.setCurrentIndex(3)                    # 右下（写 base）
    w._apply_overlay_to_all()
    assert w.pool[0]["date_corner"] == "br"
    assert w.pool[1]["date_corner"] == "br"


def test_rebuild_materializes_overrides(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    w.date_enabled.setChecked(True)
    _fill(w, tmp_path, n=2)
    w.pool[0]["date_corner"] = "br"
    w._rebuild_job()
    assert w.job.date_overrides[0] == ("br", w.pool[0]["date_rot"])
    assert w.job.date_overrides[1] is not None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_app_main_window.py -k "overlay or seed or select or edit or deselect or apply or materializ" -q`
Expected: FAIL — `AttributeError: 'MainWindow' object has no attribute '_ov_base'` / `date_rot`。

- [ ] **Step 3: `__init__` 加状态**（`self._place_source = None` 之后）

```python
        self._ov_base = None       # 全局默认（未选中时面板编辑它），_build_ui 后初始化
        self._ov_editing = None    # 当前编辑的 pool 下标（None＝编辑默认）
        self._ov_loading = False   # 载入照片值时阻断回写
```

`self._build_ui()` 调用之后（`_load_printers()` 之前）加：

```python
        self._ov_base = self._read_overlay_widgets()
```

- [ ] **Step 4: `_build_ui` 加 date_rot / wm_rot 与应用按钮**

在 `self.date_corner` 填充循环之后、`self.date_color_btn` 之前加：

```python
        self.date_rot = QComboBox()
        for label, deg in ROTATION_LABELS:
            self.date_rot.addItem(label, deg)
```

`drow` 的 widget 元组加入 `self.date_rot`（放在 `self.date_corner` 之后）：

```python
        for widget in (self.date_font, self.date_size, self.date_weight,
                       self.date_corner, self.date_rot, self.date_color_btn):
```

在 `self.wm_corner` 填充循环之后加：

```python
        self.wm_rot = QComboBox()
        for label, deg in ROTATION_LABELS:
            self.wm_rot.addItem(label, deg)
```

`wrow` 的 widget 元组加入 `self.wm_rot`（放在 `self.wm_corner` 之后）：

```python
        for widget in (self.wm_font, self.wm_size, self.wm_weight,
                       self.wm_corner, self.wm_rot, self.wm_color_btn, self.wm_alpha):
```

`panel.addRow(overlay)` 之后加应用按钮行：

```python
        self.apply_overlay_btn = QPushButton("应用到所有照片")
        self.apply_overlay_btn.clicked.connect(self._apply_overlay_to_all)
        panel.addRow("", self.apply_overlay_btn)
```

模块常量区（`CORNER_CHOICES` 之后）加：

```python
ROTATION_LABELS = (("0°", 0), ("45°", 45), ("90°", 90), ("135°", 135),
                   ("180°", 180), ("225°", 225), ("270°", 270), ("315°", 315))
```

- [ ] **Step 5: 防抖连接改向**

把 `__init__` 里现有连接循环中的 `self.date_corner`、`self.wm_corner` **移除**（它们改走专用 handler）：

```python
        for w in (self.date_font, self.date_size, self.date_weight,
                  self.wm_font, self.wm_size,
                  self.wm_weight, self.wm_alpha):
            _connect_param_changed(w, self._debounce.start)
```

紧随其后加 4 个逐张控件的专用连接：

```python
        for cb in (self.date_corner, self.date_rot, self.wm_corner, self.wm_rot):
            cb.currentIndexChanged.connect(self._on_overlay_widget_changed)
```

- [ ] **Step 6: `_on_photo_clicked` / `_on_clear_photos` 联动**

`_on_photo_clicked` 取消分支末尾（`self._set_status("已取消选中…")` 之后）加：

```python
            self._ov_editing = None
            self._load_overlay_widgets_from_base()
```

选中分支（`self.photo_list.setCurrentRow(row)` 之后）加：

```python
            self._ov_editing = row
            self._load_overlay_widgets_for(row)
```

`_on_clear_photos` 里 `self._place_source = None` 之后加：

```python
        self._ov_editing = None
        self._load_overlay_widgets_from_base()
```

- [ ] **Step 7: 新增编辑 helper**（`_refresh_overlay_btn_colors` 附近）

```python
    def _read_overlay_widgets(self):
        return {"date_corner": self.date_corner.currentData(),
                "date_rot": self.date_rot.currentData(),
                "wm_corner": self.wm_corner.currentData(),
                "wm_rot": self.wm_rot.currentData()}

    def _load_overlay_widgets_for(self, pi):
        e = self.pool[pi]
        self._ov_loading = True
        try:
            self._select_by_data(self.date_corner, e.get("date_corner", self._ov_base["date_corner"]))
            self._select_by_data(self.date_rot, e.get("date_rot", self._ov_base["date_rot"]))
            self._select_by_data(self.wm_corner, e.get("wm_corner", self._ov_base["wm_corner"]))
            self._select_by_data(self.wm_rot, e.get("wm_rot", self._ov_base["wm_rot"]))
        finally:
            self._ov_loading = False

    def _load_overlay_widgets_from_base(self):
        self._ov_loading = True
        try:
            for key, cb in (("date_corner", self.date_corner), ("date_rot", self.date_rot),
                            ("wm_corner", self.wm_corner), ("wm_rot", self.wm_rot)):
                self._select_by_data(cb, self._ov_base[key])
        finally:
            self._ov_loading = False

    def _on_overlay_widget_changed(self, *_):
        if self._ov_loading:
            return
        vals = self._read_overlay_widgets()
        pi = self._ov_editing
        if pi is not None and 0 <= pi < len(self.pool):
            self.pool[pi].update(vals)
        else:
            self._ov_base.update(vals)
        self._debounce.start()

    def _apply_overlay_to_all(self):
        vals = self._read_overlay_widgets()
        self._ov_base.update(vals)
        for e in self.pool:
            e.update(vals)
        self._rebuild_job()
```

- [ ] **Step 8: `append_photo` 种子 4 字段**

成功分支 `self.pool.append({...})` 改为：

```python
        self.pool.append({"path": str(path), "img": img,
                          "date": jobs.photo_date_text(path),
                          "date_corner": self._ov_base["date_corner"],
                          "date_rot": self._ov_base["date_rot"],
                          "wm_corner": self._ov_base["wm_corner"],
                          "wm_rot": self._ov_base["wm_rot"]})
```

失败分支改为：

```python
        self.pool.append({"path": str(path), "img": None, "date": None,
                          "date_corner": self._ov_base["date_corner"],
                          "date_rot": self._ov_base["date_rot"],
                          "wm_corner": self._ov_base["wm_corner"],
                          "wm_rot": self._ov_base["wm_rot"]})
```

> `append_photo` 在 `_ov_base` 尚未初始化时被调用（`__init__` 里 `_restore_last_job` 早于其设置？）——不会：`self._ov_base = self._read_overlay_widgets()` 在 `_build_ui()` 之后、`_restore_last_job()` 之前执行（Step 3）。确认顺序。

- [ ] **Step 9: `_params` base spec 加 rotation**

`date_overlay` 的 `TextSpec(...)` 加 `rotation=self.date_rot.currentData(),`（`corner=` 之后）；`watermark_overlay` 的 `TextSpec(...)` 加 `rotation=self.wm_rot.currentData(),`。

- [ ] **Step 10: `_rebuild_job` 物化 overrides**

`date_texts` 物化循环之后、`try:` 之前加：

```python
        date_over = [None] * n
        wm_over = [None] * n
        for slot, pi in self.placements.items():
            if 0 <= slot < n and 0 <= pi < len(self.pool):
                e = self.pool[pi]
                date_over[slot] = (e.get("date_corner", self._ov_base["date_corner"]),
                                   e.get("date_rot", self._ov_base["date_rot"]))
                wm_over[slot] = (e.get("wm_corner", self._ov_base["wm_corner"]),
                                 e.get("wm_rot", self._ov_base["wm_rot"]))
```

`build_job(...)` 调用补两参：

```python
                                      date_overlay=p["date_overlay"],
                                      watermark_overlay=p["watermark_overlay"],
                                      date_texts=date_texts,
                                      date_overrides=date_over,
                                      wm_overrides=wm_over)
```

- [ ] **Step 11: 跑测试确认通过**

Run: `python -m pytest tests/test_app_main_window.py -k "overlay or seed or select or edit or deselect or apply or materializ" -q`
Expected: PASS（新增 6 条）

- [ ] **Step 12: 变异验牙**

1. `append_photo` 种子漏用 `_ov_base`（写死 `"tl"`/`0`）→ `test_new_photo_seeds_overlay_from_base` 红。
2. `_on_overlay_widget_changed` 回写目标分流写反（选中却写 `_ov_base`）→ `test_editing_selected_photo_writes_only_that_photo` 红。
3. `_apply_overlay_to_all` 漏 `for e in self.pool` 循环 → `test_apply_overlay_to_all` 红。
4. `_rebuild_job` 物化把 `date_over[slot]` 恒留 None → `test_rebuild_materializes_overrides` 红。
验后还原。Run：`python -m pytest tests/test_app_main_window.py -k "overlay or seed or select or edit or deselect or apply or materializ" -q`，Expected：坏时 FAIL、还原后 PASS。

- [ ] **Step 13: 提交**

```bash
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
python -c "open('.superpowers/sdd/_ovpr_t4_msg.txt','w',encoding='utf-8').write('app: 逐张位置/旋转存 pool + 选中即编辑 + 应用到所有 + 物化 overrides\n')"; git add photoprint/app/main_window.py tests/test_app_main_window.py; git commit -F .superpowers/sdd/_ovpr_t4_msg.txt
```

---

### Task 5: app 持久化逐张覆盖 + 默认

**Files:**
- Modify: `photoprint/app/main_window.py`（`save_last_job` 加 `ov_base`/`pool_ov` 与 overlay dict 的 rotation；`_restore_last_job` 回填 `pool_ov`；`_restore_overlay` 回填 date_rot/wm_rot）
- Test: `tests/test_app_main_window.py`

**Interfaces:**
- Consumes: Task 4 的 `_ov_base`/pool 4 字段/`_load_overlay_widgets_from_base`。
- Produces: 重启后每张位置/旋转与全局默认回填一致。

- [ ] **Step 1: 追加失败测试**（`tests/test_app_main_window.py` 末尾）

```python
def test_overlay_per_photo_persist_roundtrip(qapp, tmp_path):
    st = _store(tmp_path)
    w = MainWindow(st=st)
    _fill(w, tmp_path, n=2)
    w._on_photo_clicked(w.photo_list.item(1))
    w.date_corner.setCurrentIndex(3)                    # photo1→右下
    w.date_rot.setCurrentIndex(2)                       # 90°
    w.save_last_job()
    w2 = MainWindow(st=_store(tmp_path))
    assert w2.pool[1]["date_corner"] == "br"
    assert w2.pool[1]["date_rot"] == 90
    assert w2.pool[0]["date_corner"] != "br"            # photo0 保自己的


def test_overlay_base_persist_roundtrip(qapp, tmp_path):
    st = _store(tmp_path)
    w = MainWindow(st=st)
    w.date_corner.setCurrentIndex(1)                    # 无选中→base=右上
    w.save_last_job()
    w2 = MainWindow(st=_store(tmp_path))
    assert w2._ov_base["date_corner"] == "tr"
    assert w2.date_corner.currentData() == "tr"         # 未选中态即编辑默认
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_app_main_window.py -k "persist_roundtrip" -q`
Expected: FAIL — `KeyError`/断言不等（未持久化逐张与 base）。

- [ ] **Step 3: `save_last_job` 增存**

在现有 `"date_overlay": {...}` dict 内加 `"rotation": self.date_rot.currentData(),`；`"watermark_overlay": {...}` 内加 `"rotation": self.wm_rot.currentData(),`。

在 `"pages": self._pages})` 之前加两键：

```python
            "ov_base": dict(self._ov_base),
            "pool_ov": [[e.get("date_corner"), e.get("date_rot"),
                         e.get("wm_corner"), e.get("wm_rot")] for e in self.pool],
```

- [ ] **Step 4: `_restore_overlay` 回填 date_rot/wm_rot**

在 `_restore_overlay` 的 `for key, cb in (...)` 元组里加入旋转下拉：

```python
        for key, cb in (("font_key", self.date_font if is_date else self.wm_font),
                        ("weight", self.date_weight if is_date else self.wm_weight),
                        ("corner", self.date_corner if is_date else self.wm_corner),
                        ("rotation", self.date_rot if is_date else self.wm_rot)):
```

- [ ] **Step 5: `_restore_last_job` 回填 pool_ov 与 base**

在 `append_photo` 逐张入站的 for 循环之后、`self._ensure_count()` 之前加：

```python
        pool_ov = job.get("pool_ov")
        if isinstance(pool_ov, (list, tuple)):
            for i, ov in enumerate(pool_ov):
                if i < len(self.pool) and isinstance(ov, (list, tuple)) and len(ov) == 4:
                    self._safe(lambda e=self.pool[i], v=ov: e.update({
                        "date_corner": v[0], "date_rot": v[1],
                        "wm_corner": v[2], "wm_rot": v[3]}))
```

在 `_restore_last_job` 末尾（`_restore_overlay` 两行调用之后）加：

```python
        self._ov_editing = None
        self._ov_base = self._read_overlay_widgets()
```

> 说明：`_restore_overlay` 已把 base 的 corner/rotation 灌进 4 控件（未选中态），`_read_overlay_widgets()` 据此刷新 `_ov_base`；`pool_ov` 逐张覆盖优先于 append 时的种子。

- [ ] **Step 6: 跑测试确认通过**

Run: `python -m pytest tests/test_app_main_window.py -k "persist_roundtrip" -q`
Expected: PASS（新增 2 条）

- [ ] **Step 7: 变异验牙**

1. 删 `pool_ov` 回填循环 → `test_overlay_per_photo_persist_roundtrip` 红（photo1 回落到种子值）。
2. 删 `save_last_job` 的 `"ov_base"` 键 → `test_overlay_base_persist_roundtrip` 红。
验后还原。Run：`python -m pytest tests/test_app_main_window.py -k "persist_roundtrip" -q`，Expected：坏时 FAIL、还原后 PASS。

- [ ] **Step 8: 提交**

```bash
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
python -c "open('.superpowers/sdd/_ovpr_t5_msg.txt','w',encoding='utf-8').write('app: 持久化逐张位置/旋转(pool_ov) + 全局默认(ov_base) + overlay rotation 回填\n')"; git add photoprint/app/main_window.py tests/test_app_main_window.py; git commit -F .superpowers/sdd/_ovpr_t5_msg.txt
```

---

### Task 6: 全量回归 + 重打包收尾

**Files:**
- 无新增改动；验证 Task 1–5 未破坏既有渲染/放置/导出/叠加。

- [ ] **Step 1: 全量回归**

Run: `python -m pytest tests/ -q`
Expected: 全部 PASS，`EXIT=0`。重点确认既有 `test_render_*`、`test_cli`、`test_jobs`、`test_text_overlay`、`test_render_overlay` 逐像素不变（默认参向后兼容）。

- [ ] **Step 2: 无 MUTATION-TEMP 残留自查**

Run: `$r = Select-String -Path photoprint/core/*.py,photoprint/jobs.py,photoprint/app/main_window.py,tests/*.py -Pattern 'MUTATION-TEMP'; echo "residue=$($r.Count)"`
Expected: `residue=0`

- [ ] **Step 3: 结束残留进程后重打包**

Run：
```powershell
Get-Process PhotoPrint -ErrorAction SilentlyContinue | Stop-Process -Force; Start-Sleep -Seconds 2
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 2>&1 | Select-Object -Last 3
```
Expected: 末行 `OK 产物：…\dist\PhotoPrint.exe（…MB）`（先清残留进程防 `PermissionError`，见记忆 8c2e894b）。

- [ ] **Step 4: smoke 启动**

Run：
```powershell
$exe = Get-Item dist\PhotoPrint.exe; echo "age_min=$([math]::Round(((Get-Date)-$exe.LastWriteTime).TotalMinutes,2))"
$p = Start-Process -FilePath "dist\PhotoPrint.exe" -PassThru; Start-Sleep -Seconds 6
if (Get-Process -Id $p.Id -ErrorAction SilentlyContinue) { echo "SMOKE OK"; Stop-Process -Id $p.Id -Force } else { echo "SMOKE FAIL" }
```
Expected: `age_min` 接近 0 且 `SMOKE OK`。收尾再 `Stop-Process -Name PhotoPrint -Force` 防遗留下次打包。

- [ ] **Step 5: 交用户 exe 手测清单**

告知走查：① 点一张竖图→改其日期位置/旋转、水印位置/旋转，只有它变；② 点另一张横图→各调各的；③ 不点任何照片改位置/旋转＝设默认，新加图继承；④ "应用到所有照片"一键统一；⑤ 斜向水印（45°/135°）方向正确（顺时针）、不溢出邻格；⑥ 重启后每张位置/旋转回填正确；⑦ 全默认（无单独改、旋转都 0）导出与升级前逐像素一致。

---

## Self-Review

**1. Spec coverage：**
- spec §2.1 rotation/ROTATION_PRESETS、§3.2 旋转分支 → Task 1。
- spec §3.1 `_with_corner_rot` + render_page 新参 → Task 2。
- spec §4 jobs 透传 → Task 3。
- spec §2.2/2.3 pool 生效值/`_ov_base`、§5.1–5.4 控件/选中即编辑/应用/物化 → Task 4。
- spec §5.5 持久化 → Task 5。
- spec §6 边界（旋转溢出/缺字段兜底）→ Task 1 溢出测试 + Task 4 `.get` 兜底。
- spec §7 测试与变异、§8 验收 → 各 Step + Task 6。

**2. Placeholder scan：** 无 TBD/TODO；每步含完整代码与命令。通过。

**3. Type consistency：** `TextSpec.rotation`（Task 1 定义）在 render `_with_corner_rot`（Task 2）、app `_params`/控件 data（Task 4）一致；`date_overrides`/`wm_overrides` 参名 Task 2 定义、Task 3 透传、Task 4 物化一致；pool 4 字段名 `date_corner/date_rot/wm_corner/wm_rot` 在 Task 4 种子/编辑/物化、Task 5 持久化一致；`ROTATION_LABELS` 与 `ROTATION_PRESETS` 值集一致（0..315 八档）。通过。
