# 照片列表缩略图 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在照片列表每个成功加载的条目左侧挂一张 ≤40px 的等比缩略图，让用户导入多张图后能一眼认出是哪张。

**Architecture:** 缩略图生成落在 `app/view.py`（PIL→Qt 唯一转换处），界面在 `app/main_window.py` 的 `append_photo` 成功分支给 `QListWidgetItem` 设 `QIcon`。纯显示层增量，不触碰 `jobs`/`core` 排版与渲染几何。

**Tech Stack:** PySide6（QListWidget / QIcon / QSize / QPixmap）、Pillow（`thumbnail` 等比缩放）、pytest（offscreen GUI 冒烟）。

## Global Constraints

- 分层：缩略图只做 PIL→QPixmap 与挂图标，**不得**进 `jobs`/`core`，不做 mm/像素换算与裁切几何（spec §2）。
- I-1 文案不变：`_photo_item_text` 输出逐字不变，既有断言列表文字 / `↻90°` 后缀的测试不得受扰动（spec §2）。
- I-2 不污染原图：`to_thumbnail` 只读 `img`，绝不原地改 `self.photos[i]`——必须先 `copy()`（spec §2、§3）。
- I-3 单一入口：只改 `append_photo`，"添加照片"与"启动恢复"两条路径共用，不分别处理（spec §2）。
- 缩略图不跟随旋转：`_on_rotate` 完全不改（spec §0 决策 1、§4）。
- 读取失败占位项（`img is None`）不挂图标，维持红字（spec §3、§6）。
- 窗口化 exe 无控制台：不新增会外抛的异常路径（spec §6，成功分支不包 try 但也不引新异常）。
- 尺寸常量 `THUMB_PX = 40`（spec §0 决策 2）。
- 测试全部脱机 `offscreen`（`tests/conftest.py` 已设 `QT_QPA_PLATFORM`）。

---

### Task 1: `view.to_thumbnail` 缩略图生成函数

**Files:**
- Modify: `photoprint/app/view.py`（新增函数）
- Test: `tests/test_app_view.py`（追加测试）

**Interfaces:**
- Consumes: 现有 `view.to_pixmap(img)`（要求 img 为 RGB）。
- Produces: `view.to_thumbnail(img, px) -> QPixmap`——把 PIL 图等比缩进 `px×px` 方框后转 QPixmap；不改动传入的 `img`。Task 2 依赖此签名。

- [ ] **Step 1: 写失败测试**

在 `tests/test_app_view.py` 末尾追加：

```python
def test_to_thumbnail_scales_into_box_keeping_aspect(qapp):
    """横图 200×100 缩进 40×40：长边 40、短边等比 20。用非正方图才有牙
    （正方/纯色图缩放比不显方向，宽高比断言会恒真）。"""
    pm = view.to_thumbnail(Image.new("RGB", (200, 100), (10, 20, 30)), 40)
    assert (pm.width(), pm.height()) == (40, 20)


def test_to_thumbnail_does_not_mutate_source(qapp):
    """I-2 的底层保证：缩略图绝不动传入原图——改了会污染 self.photos 进而污染导出。"""
    img = Image.new("RGB", (200, 100), (10, 20, 30))
    view.to_thumbnail(img, 40)
    assert img.size == (200, 100)


def test_to_thumbnail_is_rgb_safe(qapp):
    """非 RGB 源（调色板图）也要能出缩略图：convert("RGB") 兜住 raw RGB 前提。"""
    pal = Image.new("P", (60, 60))
    pm = view.to_thumbnail(pal, 40)
    assert not pm.isNull()
    assert max(pm.width(), pm.height()) <= 40
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_app_view.py -k to_thumbnail -q`
Expected: FAIL — `AttributeError: module 'photoprint.app.view' has no attribute 'to_thumbnail'`

- [ ] **Step 3: 写最小实现**

在 `photoprint/app/view.py` 末尾追加：

```python
def to_thumbnail(img, px):
    """PIL 图等比缩到 px×px 方框内转 QPixmap；不改动传入的 img。

    先 convert("RGB") 兜住 to_pixmap 的 raw RGB 前提（调色板/灰度源不炸），
    再 copy() 保证 thumbnail 的原地缩落在副本上——原图是渲染共享对象，
    改了就污染导出（spec I-2）。
    """
    small = img.convert("RGB").copy()
    small.thumbnail((px, px))
    return to_pixmap(small)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_app_view.py -k to_thumbnail -q`
Expected: PASS（3 个）

- [ ] **Step 5: 提交**

```bash
git add photoprint/app/view.py tests/test_app_view.py
git commit -m "feat(view): 新增 to_thumbnail 等比缩略图生成（不改动原图）"
```

---

### Task 2: 照片列表挂载缩略图图标

**Files:**
- Modify: `photoprint/app/main_window.py`（import 补 `QSize`/`QIcon`；常量 `THUMB_PX`；`_build_ui` 设 `setIconSize`；`append_photo` 成功分支设 icon）
- Test: `tests/test_app_main_window.py`（追加测试）

**Interfaces:**
- Consumes: `view.to_thumbnail(img, THUMB_PX)`（Task 1）。
- Produces: 无对外新符号；仅界面行为变化——成功加载的条目 `item.icon()` 非空。

- [ ] **Step 1: 写失败测试**

在 `tests/test_app_main_window.py` 顶部 import 段补一行（若尚未存在）：

```python
from PySide6.QtGui import QIcon  # noqa: E402
```

在文件末尾追加：

```python
def test_photo_list_has_thumbnail_icon(qapp, tmp_path):
    """加载成功的条目须带非空缩略图图标，且长边 ≤ 40（删 setIcon 则转红）。"""
    w = MainWindow(st=_store(tmp_path))
    paths = _make_photos(tmp_path, n=1)          # 400×200 横图
    w.append_photo(paths[0])
    item = w.photo_list.item(0)
    icon = item.icon()
    assert not icon.isNull()
    sizes = icon.availableSizes()
    assert sizes and max(max(s.width(), s.height()) for s in sizes) <= 40


def test_failed_photo_has_no_icon(qapp, tmp_path):
    """读取失败占位项不挂图标，仍红字（钉住失败分支不回归）。"""
    bad = tmp_path / "missing.jpg"
    bad.write_bytes(b"not an image")
    w = MainWindow(st=_store(tmp_path))
    w.append_photo(str(bad))
    item = w.photo_list.item(0)
    assert item.icon().isNull()
    assert "（读取失败）" in item.text()


def test_thumbnail_does_not_mutate_shared_photo(qapp, tmp_path):
    """I-2 界面侧：挂完缩略图 self.photos[-1] 仍是原图尺寸，未被 thumbnail 改小。"""
    w = MainWindow(st=_store(tmp_path))
    paths = _make_photos(tmp_path, n=1)          # 400×200
    w.append_photo(paths[0])
    assert w.photos[-1].size == (400, 200)


def test_rotate_keeps_thumbnail_unchanged(qapp, tmp_path):
    """spec §0 决策 1：旋转只改文字 ↻ 后缀，不重生成/改动图标。"""
    w = MainWindow(st=_store(tmp_path))
    paths = _make_photos(tmp_path, n=1)
    w.append_photo(paths[0])
    w.photo_list.setCurrentRow(0)
    before = w.photo_list.item(0).icon().pixmap(64, 64).toImage()
    w._on_rotate()
    assert "↻90°" in w.photo_list.item(0).text()
    after = w.photo_list.item(0).icon().pixmap(64, 64).toImage()
    assert before == after
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_app_main_window.py -k "thumbnail_icon or failed_photo_has_no_icon or mutate_shared_photo or rotate_keeps_thumbnail" -q`
Expected: FAIL — `test_photo_list_has_thumbnail_icon` 断言 `not icon.isNull()` 失败（当前无图标）。

- [ ] **Step 3a: 补 import 与常量**

`photoprint/app/main_window.py` 现有：

```python
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
```

改为：

```python
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QColor, QIcon
```

在常量区 `OFFSET_MAX_PCT = 50` 下方新增一行：

```python
THUMB_PX = 40
```

- [ ] **Step 3b: 设图标占位尺寸**

`_build_ui` 中现有：

```python
        self.photo_list = QListWidget()
        self.photo_list.setFixedWidth(260)   # 只钉宽；高度不封顶，随窗口纵向伸展
        panel.addRow("照片", self.photo_list)
```

在 `setFixedWidth` 与 `panel.addRow` 之间插入一行：

```python
        self.photo_list.setIconSize(QSize(THUMB_PX, THUMB_PX))
```

- [ ] **Step 3c: 成功分支挂图标**

`append_photo` 末尾现有：

```python
        self.photos.append(img)
        self.photo_paths.append(str(path))
        self.photo_rotations.append(0)
        self.photo_list.addItem(
            QListWidgetItem(self._photo_item_text(name, img, 0)))
```

改为（建 item 变量、挂缩略图、再 addItem；失败分支上方代码不动）：

```python
        self.photos.append(img)
        self.photo_paths.append(str(path))
        self.photo_rotations.append(0)
        item = QListWidgetItem(self._photo_item_text(name, img, 0))
        item.setIcon(QIcon(view.to_thumbnail(img, THUMB_PX)))
        self.photo_list.addItem(item)
```

- [ ] **Step 4: 跑新增测试确认通过**

Run: `python -m pytest tests/test_app_main_window.py -k "thumbnail_icon or failed_photo_has_no_icon or mutate_shared_photo or rotate_keeps_thumbnail" -q`
Expected: PASS（4 个）

- [ ] **Step 5: 变异验牙**

临时把 `item.setIcon(...)` 那行注释掉，跑 `test_photo_list_has_thumbnail_icon` 应转红，还原：

Run: `python -m pytest tests/test_app_main_window.py::test_photo_list_has_thumbnail_icon -q`
Expected（注释后）: FAIL；（还原后）: PASS。
再全仓 grep 确认无残留：`Grep regex=MUTATION-TEMP` 命中 0。

- [ ] **Step 6: 全量回归确认既有测试不红（I-1/I-3）**

Run: `python -m pytest tests/ -q`
Expected: 全绿（含既有列表文字、`↻90°`、旋转、导出、持久化测试不受扰动）。

- [ ] **Step 7: 提交**

```bash
git add photoprint/app/main_window.py tests/test_app_main_window.py
git commit -m "feat(ui): 照片列表挂载 40px 缩略图图标（不随旋转、不污染原图）"
```

---

## 手工验收（spec §8）

重新打包 exe（`build_exe.ps1`）后：导入多张不同照片 → 列表每项左侧出现可辨认小缩略图；选中一张点「旋转 90°」→ 文字 `↻90°` 变、缩略图方向不变；导出 PDF 与加缩略图前逐像素一致。
