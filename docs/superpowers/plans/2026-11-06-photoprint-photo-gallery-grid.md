# 照片库网格画廊 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把左侧照片库从窄竖排列表改成 IconMode 缩略图网格（120px 图 + 图下两行"文件名/尺寸"），零回归保留点选放置与取消选中交互。

**Architecture:** 纯 `app` 显示层改动，落在 `main_window.py` 四处：新增 `GALLERY_THUMB_PX` 常量、`_build_ui` 给 `photo_list` 设 IconMode 配置并去掉固定宽、`append_photo` 图标尺寸改大、`_photo_item_text` 改两行。`QListWidget` 即 `QListView` 子类，IconMode 不改 `row()`/`currentRow()`/`itemClicked`，故放置/取消选中逻辑与 `core`/`jobs`/`render`/`preview_view` 一律不动。

**Tech Stack:** PySide6（QListWidget/QListView/QSize/QIcon）、Pillow（`view.to_thumbnail`）、pytest-qt（offscreen 冒烟）。

## Global Constraints

- 缩略图方框尺寸：`GALLERY_THUMB_PX = 120`（逐字取自 spec 第 3/4 节）。
- 只允许改动 `photoprint/app/main_window.py` 与 `tests/test_app_main_window.py`；不得触碰 `core`/`jobs`/`render`/`preview_view`/`_place_source`/`_on_photo_clicked`/`_on_cell_clicked`。
- 回归红线：`photo_list.row(item)` 仍返回池下标；`itemClicked`→`_on_photo_clicked` 的"点选=设放置源 / 再点同张=取消"仍生效；`_place_source` 仍是放置源唯一真相；读取失败项仍 `setForeground(ERROR_COLOR)` 标红。
- 窗口化 exe 无控制台：不新增异常面，沿用 `append_photo` 既有 try/except 收敛。
- 测试一律加在既有 `tests/test_app_main_window.py`（该文件自带 autouse `_no_leaked_threads` 收尾夹具），不新建 GUI 测试文件。
- 提交消息：先 `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8`，用 python 写 UTF8 无 BOM 消息文件后 `git commit -F`。
- PowerShell 不支持 `&&`，用 `;`。

---

### Task 1: IconMode 网格配置

**Files:**
- Modify: `photoprint/app/main_window.py`（import 行 13-16；常量区 ~32；`_build_ui` photo_list 段 131-135）
- Test: `tests/test_app_main_window.py`

**Interfaces:**
- Consumes: 无（首个任务）
- Produces: 模块常量 `GALLERY_THUMB_PX: int`（=120）；`photo_list` 处于 IconMode 网格配置。Task 2 依赖 `GALLERY_THUMB_PX` 命名。

- [ ] **Step 1: 写失败测试**

在 `tests/test_app_main_window.py` 末尾追加：

```python
def test_photo_list_is_wrapping_grid(qapp, tmp_path):
    """照片库须是随栏宽换行的 IconMode 网格（图标在上、文字在下）。"""
    from PySide6.QtWidgets import QListView
    from photoprint.app.main_window import GALLERY_THUMB_PX
    w = MainWindow(st=_store(tmp_path))
    pl = w.photo_list
    assert pl.viewMode() == QListView.IconMode
    assert pl.isWrapping() is True
    assert pl.movement() == QListView.Static
    assert pl.wordWrap() is True
    assert pl.iconSize().width() == GALLERY_THUMB_PX
    assert pl.iconSize().height() == GALLERY_THUMB_PX
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_app_main_window.py::test_photo_list_is_wrapping_grid -q`
Expected: FAIL —`ImportError: cannot import name 'GALLERY_THUMB_PX'`（或 viewMode 断言失败）。

- [ ] **Step 3: 加 `GALLERY_THUMB_PX` 常量并补 `QListView` 导入**

`main_window.py` import 块（13-16 行）加入 `QListView`（保持字母序，插在 `QListWidgetItem` 前）：

```python
from PySide6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QListWidget,
                               QListView, QListWidgetItem, QMainWindow, QMessageBox,
                               QPushButton, QSlider, QVBoxLayout, QWidget)
```

常量区（32 行 `THUMB_PX = 40` 处）替换为：

```python
GALLERY_THUMB_PX = 120
```

（`THUMB_PX` 仅 `_build_ui` 与 `append_photo` 两处引用，Task 1/2 分别改掉，故删除旧名。）

- [ ] **Step 4: 给 `photo_list` 设 IconMode 网格配置**

`_build_ui` 里把原 photo_list 段（131-135）：

```python
        self.photo_list = QListWidget()
        self.photo_list.setFixedWidth(260)   # 只钉宽；高度不封顶，随窗口纵向伸展
        self.photo_list.setIconSize(QSize(THUMB_PX, THUMB_PX))
        self.photo_list.itemClicked.connect(self._on_photo_clicked)
        panel.addRow("照片", self.photo_list)
```

改为：

```python
        self.photo_list = QListWidget()
        self.photo_list.setViewMode(QListView.IconMode)   # 图标在上、文字在下、自动换行
        self.photo_list.setMovement(QListView.Static)     # 格子固定不可拖拽重排
        self.photo_list.setWrapping(True)                 # 随栏宽换行成多列
        self.photo_list.setResizeMode(QListView.Adjust)   # 宽度变化时重排列数
        self.photo_list.setWordWrap(True)                 # 长文件名换行
        self.photo_list.setUniformItemSizes(True)         # 网格整齐 + 大数据性能
        self.photo_list.setIconSize(QSize(GALLERY_THUMB_PX, GALLERY_THUMB_PX))
        self.photo_list.itemClicked.connect(self._on_photo_clicked)
        panel.addRow("照片", self.photo_list)
```

（去掉了 `setFixedWidth(260)`，让网格填满表单字段列、与下方设置项对齐。）

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest tests/test_app_main_window.py::test_photo_list_is_wrapping_grid -q`
Expected: PASS

- [ ] **Step 6: 变异验牙**

对 `main_window.py` 逐项临时改坏、各跑 Step 1 测试确认转红，验后还原：

1. 删 `setViewMode(QListView.IconMode)` 整行 → `viewMode()` 断言红。
2. 删 `setWrapping(True)` 整行 → `isWrapping()` 断言红。
3. `setIconSize(QSize(GALLERY_THUMB_PX, GALLERY_THUMB_PX))` 改成 `QSize(40, 40)` → `iconSize().width()` 断言红。
4. 删 `setWordWrap(True)` 整行 → `wordWrap()` 断言红。

Run（每次还原后）：`python -m pytest tests/test_app_main_window.py::test_photo_list_is_wrapping_grid -q`
Expected：坏时 FAIL、还原后 PASS。

- [ ] **Step 7: 提交**

```bash
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
python -c "open('.superpowers/sdd/_gallery_t1_msg.txt','w',encoding='utf-8').write('app: 照片库切 IconMode 网格（120px 缩略图 + 随栏宽换行，去固定宽对齐设置项）\n')"
git add photoprint/app/main_window.py tests/test_app_main_window.py
git commit -F .superpowers/sdd/_gallery_t1_msg.txt
```

---

### Task 2: 图下两行文字（文件名 + 尺寸）

**Files:**
- Modify: `photoprint/app/main_window.py`（`append_photo` ~498；`_photo_item_text` ~501-506）
- Test: `tests/test_app_main_window.py`

**Interfaces:**
- Consumes: Task 1 的 `GALLERY_THUMB_PX`（图标尺寸参数）。
- Produces: `_photo_item_text` 返回两行文本（含 `\n`）；网格项显示"文件名 / 宽×高px"。

- [ ] **Step 1: 写失败测试**

在 `tests/test_app_main_window.py` 末尾追加：

```python
def test_gallery_item_text_is_two_lines_with_size(qapp, tmp_path):
    """网格项文字两行：第一行文件名，第二行像素尺寸。"""
    w = MainWindow(st=_store(tmp_path))
    w.append_photo(_make_photos(tmp_path, 1)[0])   # 400×200 横图
    text = w.photo_list.item(0).text()
    lines = text.split("\n")
    assert len(lines) == 2
    assert lines[0].endswith(".jpg")
    assert "400" in lines[1] and "200" in lines[1] and "px" in lines[1]


def test_gallery_failed_item_text_marks_failure(qapp, tmp_path):
    """读取失败项：第二行标“读取失败”，仍红字。"""
    from PySide6.QtGui import QColor
    from photoprint.app.main_window import ERROR_COLOR
    w = MainWindow(st=_store(tmp_path))
    w.append_photo(str(tmp_path / "不存在.jpg"))
    item = w.photo_list.item(0)
    assert item.text().split("\n")[-1] == "读取失败"
    assert item.foreground().color() == QColor(ERROR_COLOR)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_app_main_window.py::test_gallery_item_text_is_two_lines_with_size tests/test_app_main_window.py::test_gallery_failed_item_text_marks_failure -q`
Expected: FAIL —`len(lines) == 2` 断言失败（现文字为一行、无 `\n`）。

- [ ] **Step 3: `_photo_item_text` 改两行**

把 `_photo_item_text`（501-506）：

```python
    @staticmethod
    def _photo_item_text(name, img):
        """列表项文字：旋转已移到格上，不再有角度段。"""
        if img is None:
            return f"{name}（读取失败）"
        return f"{name}  {img.width}×{img.height}px"
```

改为：

```python
    @staticmethod
    def _photo_item_text(name, img):
        """网格项文字两行：文件名 / 尺寸（或读取失败）。旋转在格上，不在此体现。"""
        if img is None:
            return f"{name}\n读取失败"
        return f"{name}\n{img.width}×{img.height}px"
```

- [ ] **Step 4: `append_photo` 图标尺寸改用 `GALLERY_THUMB_PX`**

把 `append_photo` 成功分支（498）：

```python
        item.setIcon(QIcon(view.to_thumbnail(img, THUMB_PX)))
```

改为：

```python
        item.setIcon(QIcon(view.to_thumbnail(img, GALLERY_THUMB_PX)))
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest tests/test_app_main_window.py::test_gallery_item_text_is_two_lines_with_size tests/test_app_main_window.py::test_gallery_failed_item_text_marks_failure -q`
Expected: PASS

- [ ] **Step 6: 变异验牙**

逐项临时改坏、各跑 Step 1 测试确认转红，验后还原：

1. `_photo_item_text` 正常分支去掉 `\n`（改回 `f"{name}  {img.width}×{img.height}px"`）→ `len(lines) == 2` 红。
2. 失败分支 `f"{name}\n读取失败"` 改成 `f"{name}（读取失败）"`（无换行、词不同）→ 失败测试末行断言红。

Run（还原后）：`python -m pytest tests/test_app_main_window.py::test_gallery_item_text_is_two_lines_with_size tests/test_app_main_window.py::test_gallery_failed_item_text_marks_failure -q`
Expected：坏时 FAIL、还原后 PASS。

- [ ] **Step 7: 提交**

```bash
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
python -c "open('.superpowers/sdd/_gallery_t2_msg.txt','w',encoding='utf-8').write('app: 网格项文字改两行（文件名 + 尺寸/读取失败），缩略图用 GALLERY_THUMB_PX\n')"
git add photoprint/app/main_window.py tests/test_app_main_window.py
git commit -F .superpowers/sdd/_gallery_t2_msg.txt
```

---

### Task 3: 全量回归 + 重打包收尾

**Files:**
- 无新增改动；验证 Task 1/2 未破坏放置/取消选中/导入既有测试。

**Interfaces:**
- Consumes: Task 1/2 成品。
- Produces: 通过验证的 exe（`dist/PhotoPrint.exe`）。

- [ ] **Step 1: 全量回归（含 IconMode 下选择 API 回归红线）**

Run: `python -m pytest tests/ -q`
Expected: 全部 PASS，`EXIT=0`。重点确认 `test_placement.py`（`_on_photo_clicked`/`_on_cell_clicked`/`row()`/`currentRow()`/`itemClicked`）与 `test_folder_import.py` 仍绿——IconMode 不改这些 API。若有红，多为对 `photo_list` 呈现的旧断言，按新语义忠实迁移，不得改放置内核。

- [ ] **Step 2: 无 MUTATION-TEMP 残留自查**

Run: `$r = Select-String -Path photoprint/app/main_window.py,tests/*.py -Pattern 'MUTATION-TEMP'; echo "residue=$($r.Count)"`
Expected: `residue=0`

- [ ] **Step 3: 重打包**

Run: `powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 2>&1 | Select-Object -Last 4`
Expected: 末行 `OK 产物：…\dist\PhotoPrint.exe（…MB）`（管道 ExitCode 1 是 stderr 假象，以脚本内 `OK 产物` 与新鲜度为准）。

- [ ] **Step 4: smoke 启动**

Run：
```powershell
$exe = Get-Item dist\PhotoPrint.exe; echo "age_min=$([math]::Round(((Get-Date)-$exe.LastWriteTime).TotalMinutes,2))"
$p = Start-Process -FilePath "dist\PhotoPrint.exe" -PassThru; Start-Sleep -Seconds 5
if (Get-Process -Id $p.Id -ErrorAction SilentlyContinue) { echo "SMOKE OK"; Stop-Process -Id $p.Id -Force } else { echo "SMOKE FAIL" }
```
Expected: `age_min` 接近 0 且 `SMOKE OK`。

- [ ] **Step 5: 交用户 exe 手测清单**

告知用户在打包版走查：① 照片库呈多列缩略图网格、图下两行文件名+尺寸、随窗口换行；② 网格与下方设置项左右对齐、左栏未额外拉宽；③ 点选库图→点预览格放置、再点同图取消选中——与改动前一致；④ 坏图仍红字"读取失败"。

---

## Self-Review

**1. Spec coverage：**
- spec §3 四处改动 → Task 1（常量/import/`_build_ui`）+ Task 2（`_photo_item_text`/`append_photo` 图标尺寸）全覆盖。
- spec §4 IconMode 七项配置 → Task 1 Step 4 全含，Step 1 测试断言其中 5 项（viewMode/wrapping/movement/wordWrap/iconSize）。`setResizeMode(Adjust)`/`setUniformItemSizes` 属行为性、无稳定 getter 断言，随 Step 6 变异与手测覆盖，可接受。
- spec §5 两行文字（正常/失败）→ Task 2 两条测试覆盖。
- spec §6 交互保留（回归红线）→ Task 3 Step 1 全量回归兜底。
- spec §8 测试策略与 4 处变异 → Task 1 Step 6（4 项）+ Task 2 Step 6（2 项）覆盖。
- spec §10 验收 → Task 3 收尾对齐。

**2. Placeholder scan：** 无 TBD/TODO；每步含完整代码与命令。通过。

**3. Type consistency：** `GALLERY_THUMB_PX`（Task 1 定义、Task 2 消费）命名一致；`ERROR_COLOR`、`_photo_item_text`、`view.to_thumbnail(img, px)` 签名与现状一致；测试夹具 `_store`/`_make_photos`/`qapp` 均为 `test_app_main_window.py` 既有。通过。
