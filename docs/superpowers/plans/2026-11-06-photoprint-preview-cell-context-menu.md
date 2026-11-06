# 预览格右键菜单（移除/旋转单格）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在右侧预览页对已放置照片的格右键弹出"移除该照片/旋转 90°"菜单，直接对该格调用既有 `clear_cell`/`rotate_cell`，实现单格移除而非清空全部。

**Architecture:** `PreviewView` 只做几何/命中——重写 `contextMenuEvent` 命中格即发 `cellContextMenuRequested(页内序, 全局坐标)`；`MainWindow._on_cell_context_menu` 算全局槽位、空格不弹、弹 `QMenu` 并按选择分派到既有 `clear_cell`/`rotate_cell`。零改动 `core`/`jobs`/`render`/放置内核。

**Tech Stack:** PySide6（QMenu/QContextMenuEvent/QPoint/Signal）、pytest-qt（offscreen）、monkeypatch（QMenu.exec 打桩避开模态阻塞）。

## Global Constraints

- 移除=`clear_cell(slot)`、旋转=`rotate_cell(slot)`，二者原样复用，不改其内部（含各自 `_debounce.start()`）。
- 仅当 `slot in self.placements` 才弹菜单；空格/无布局（`count==0`）提前 return。
- 目标槽位 = `page_index * count + position`（页内序→全局槽，纯放置域下标算术）。
- 不改 `_current_cell`/`_place_source`；不碰 `core`/`jobs`/`render`；`PreviewView` 不写 mm/像素几何（命中仍走 `hit_position`→`render`）。
- 测试加在既有 `tests/test_placement.py`（自带 autouse `_no_leaked_threads`），不新建 GUI 测试文件。
- 提交消息：先 `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8`，python 写 UTF8 无 BOM 消息文件后 `git commit -F`。PowerShell 用 `;` 非 `&&`。

---

### Task 1: PreviewView 右键命中发信号

**Files:**
- Modify: `photoprint/app/preview_view.py`（import 第 8 行；信号声明 ~21；`mousePressEvent` 之后加 `contextMenuEvent`）
- Test: `tests/test_placement.py`

**Interfaces:**
- Consumes: 既有 `PreviewView.hit_position(x, y) -> int|None`。
- Produces: 信号 `PreviewView.cellContextMenuRequested = Signal(int, QPoint)`（页内序 + 全局 QPoint）；`contextMenuEvent` 命中格即发射。Task 2 依赖该信号名与参数序。

- [ ] **Step 1: 写失败测试**

在 `tests/test_placement.py` 末尾追加：

```python
def test_preview_emits_context_menu_signal(qapp):
    """右键命中格 → 发 cellContextMenuRequested(页内序, 全局坐标)；命中空白不发。"""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent
    from photoprint.app.preview_view import PreviewView
    pv = PreviewView()
    pv.resize(400, 300)
    pv.set_geometry([(0, 0, 200, 150), (200, 0, 200, 150)], (400, 300))
    got = []
    pv.cellContextMenuRequested.connect(lambda pos, gp: got.append((pos, gp)))
    pv.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Mouse,
                                          QPoint(50, 50), QPoint(50, 50)))
    assert got and got[0][0] == 0
    got.clear()
    pv.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Mouse,
                                          QPoint(390, 290), QPoint(390, 290)))
    assert got == []                            # 空白区不发
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_placement.py::test_preview_emits_context_menu_signal -q`
Expected: FAIL — `AttributeError: 'PreviewView' object has no attribute 'cellContextMenuRequested'`（或无 `contextMenuEvent` 走默认实现、`got==[]`）。

- [ ] **Step 3: 补 `QPoint` 导入 + 信号 + `contextMenuEvent`**

`preview_view.py` 第 8 行 import 加 `QPoint`：

```python
from PySide6.QtCore import QPoint, QRectF, Qt, Signal
```

信号声明（`cellClicked = Signal(int)` 之后）加：

```python
    cellContextMenuRequested = Signal(int, QPoint)   # 页内序 + 菜单全局坐标
```

`mousePressEvent` 之后加：

```python
    def contextMenuEvent(self, event):
        """右键命中某格 → 发页内序 + 全局坐标；命中空白不发。放置语义交 MainWindow。"""
        idx = self.hit_position(event.pos().x(), event.pos().y())
        if idx is not None:
            self.cellContextMenuRequested.emit(idx, event.globalPos())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_placement.py::test_preview_emits_context_menu_signal -q`
Expected: PASS

- [ ] **Step 5: 变异验牙**

临时删 `contextMenuEvent` 里的 `self.cellContextMenuRequested.emit(...)`（改成 `pass`）→
`test_preview_emits_context_menu_signal` 断言 `got` 红。验后还原。
Run：`python -m pytest tests/test_placement.py::test_preview_emits_context_menu_signal -q`
Expected：坏时 FAIL、还原后 PASS。

- [ ] **Step 6: 提交**

```bash
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
python -c "open('.superpowers/sdd/_ctxmenu_t1_msg.txt','w',encoding='utf-8').write('app: PreviewView 右键命中格发 cellContextMenuRequested(页内序, 全局坐标)\n')"
git add photoprint/app/preview_view.py tests/test_placement.py
git commit -F .superpowers/sdd/_ctxmenu_t1_msg.txt
```

---

### Task 2: MainWindow 右键菜单分派

**Files:**
- Modify: `photoprint/app/main_window.py`（QtCore import 第 11 行加 `QPoint`；QtWidgets import 加 `QMenu`；`_build_ui` 连信号；加 `_on_cell_context_menu`）
- Test: `tests/test_placement.py`

**Interfaces:**
- Consumes: Task 1 的 `PreviewView.cellContextMenuRequested(int, QPoint)`；既有 `clear_cell(slot)` / `rotate_cell(slot)` / `place(slot, pool_idx)` / `_count_last` / `placements` / `cell_rot` / `page_index`。
- Produces: `MainWindow._on_cell_context_menu(position, global_pos)`；`preview.cellContextMenuRequested` 已连到它。

- [ ] **Step 1: 写失败测试**

在 `tests/test_placement.py` 末尾追加：

```python
def _patch_menu_exec(monkeypatch, pick):
    """把 QMenu.exec 打桩为返回第 pick 个动作，模拟用户选择（避开模态阻塞）。"""
    from photoprint.app import main_window as mw

    def fake_exec(self, *a, **k):
        return self.actions()[pick]
    monkeypatch.setattr(mw.QMenu, "exec", fake_exec)


def test_right_click_occupied_cell_removes_photo(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QPoint
    _patch_menu_exec(monkeypatch, 0)              # 选“移除该照片”
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path, n=2)                       # slot 0,1 已放置
    w.preview.cellContextMenuRequested.emit(1, QPoint(0, 0))   # 走信号→槽位1
    assert 1 not in w.placements


def test_right_click_occupied_cell_rotates(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QPoint
    _patch_menu_exec(monkeypatch, 1)              # 选“旋转 90°”
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path, n=2)
    w._on_cell_context_menu(1, QPoint(0, 0))
    assert w.cell_rot.get(1) == 90


def test_right_click_empty_cell_no_menu(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QPoint
    from photoprint.app import main_window as mw
    called = []

    def boom_exec(self, *a, **k):
        called.append(1)
        return None
    monkeypatch.setattr(mw.QMenu, "exec", boom_exec)
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path, n=2)                       # slot 0,1 占；slot 2 空
    before = dict(w.placements)
    w._on_cell_context_menu(2, QPoint(0, 0))      # 空格
    assert called == []                           # 未弹菜单
    assert w.placements == before


def test_right_click_uses_page_offset(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QPoint
    _patch_menu_exec(monkeypatch, 0)
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path, n=1)                       # slot 0 占
    count = w._count_last
    w.place(2, 0)                                 # 第 1 页页内序 2
    w.place(count + 2, 0)                         # 第 2 页页内序 2（全局槽 count+2）
    w._refresh()
    w.page_index = 1
    w._on_cell_context_menu(2, QPoint(0, 0))      # 第 2 页 pos2 → 全局槽 count+2
    assert count + 2 not in w.placements          # 移除的是第 2 页那格
    assert 2 in w.placements                      # 第 1 页同页内序未误伤
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_placement.py -k right_click -q`
Expected: FAIL — `AttributeError: 'MainWindow' object has no attribute '_on_cell_context_menu'`（及 `mw` 无 `QMenu`）。

- [ ] **Step 3: 补 `QPoint` / `QMenu` 导入**

`main_window.py` QtCore 行（11）加 `QPoint`：

```python
from PySide6.QtCore import QPoint, Qt, QSize, QTimer
```

QtWidgets 块加 `QMenu`（字母序插在 `QMainWindow` 后、`QMessageBox` 前）：

```python
from PySide6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QListWidget,
                               QListView, QListWidgetItem, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QSlider, QVBoxLayout, QWidget)
```

- [ ] **Step 4: `_build_ui` 连接信号**

在 `self.preview.cellClicked.connect(self._on_cell_clicked)` 之后加：

```python
        self.preview.cellContextMenuRequested.connect(self._on_cell_context_menu)
```

- [ ] **Step 5: 新增 `_on_cell_context_menu`**

在 `_on_cell_clicked` 方法之后加：

```python
    def _on_cell_context_menu(self, position, global_pos):
        """预览格右键：命中已放置的格 → 弹“移除/旋转”菜单，作用于该格全局槽位。"""
        count = self._count_last or (self.job.count if self.job else 0)
        if not count:
            return
        slot = self.page_index * count + position
        if slot not in self.placements:
            return                              # 空格不弹
        menu = QMenu(self)
        act_remove = menu.addAction("移除该照片")
        act_rotate = menu.addAction("旋转 90°")
        chosen = menu.exec(global_pos)
        if chosen is act_remove:
            self.clear_cell(slot)
        elif chosen is act_rotate:
            self.rotate_cell(slot)
```

- [ ] **Step 6: 跑测试确认通过**

Run: `python -m pytest tests/test_placement.py -k right_click -q`
Expected: PASS（4 条）

- [ ] **Step 7: 变异验牙**

逐项临时改坏、各跑对应测试确认转红，验后还原：

1. 删 `if slot not in self.placements: return` → `test_right_click_empty_cell_no_menu` 红（空格也弹、`called` 非空）。
2. `slot = self.page_index * count + position` 改成 `slot = position` → `test_right_click_uses_page_offset` 红（误伤第 1 页槽 2）。
3. 分派把 `self.clear_cell(slot)` 换成 `self.rotate_cell(slot)` → `test_right_click_occupied_cell_removes_photo` 红（未移除）。

Run（还原后）：`python -m pytest tests/test_placement.py -k right_click -q`
Expected：坏时 FAIL、还原后 PASS。

- [ ] **Step 8: 提交**

```bash
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
python -c "open('.superpowers/sdd/_ctxmenu_t2_msg.txt','w',encoding='utf-8').write('app: 预览格右键菜单分派 clear_cell/rotate_cell，空格不弹、按页偏移定位全局槽\n')"
git add photoprint/app/main_window.py tests/test_placement.py
git commit -F .superpowers/sdd/_ctxmenu_t2_msg.txt
```

---

### Task 3: 全量回归 + 重打包收尾

**Files:**
- 无新增改动；验证 Task 1/2 未破坏既有放置/旋转/翻页/预览。

**Interfaces:**
- Consumes: Task 1/2 成品。
- Produces: 通过验证的 exe（`dist/PhotoPrint.exe`）。

- [ ] **Step 1: 全量回归**

Run: `python -m pytest tests/ -q`
Expected: 全部 PASS，`EXIT=0`。重点确认 `test_placement.py` 其余用例与 `test_app_main_window.py` 预览/翻页不受影响。

- [ ] **Step 2: 无 MUTATION-TEMP 残留自查**

Run: `$r = Select-String -Path photoprint/app/main_window.py,photoprint/app/preview_view.py,tests/*.py -Pattern 'MUTATION-TEMP'; echo "residue=$($r.Count)"`
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

告知用户在打包版走查：① 右键已放图格弹出"移除该照片/旋转 90°"；② 移除→仅该格清空、照片仍在库、其余格不受影响；③ 旋转→仅该格转 90°；④ 右键空格/格外空白无菜单；⑤ 多页时对第 2 页某格操作命中正确格。

---

## Self-Review

**1. Spec coverage：**
- spec §3.1 `PreviewView.contextMenuEvent` + 信号 → Task 1 全覆盖（含发射测试 + 变异 3）。
- spec §3.2 `_on_cell_context_menu`（页偏移、空格守卫、菜单两项、分派）→ Task 2 全覆盖（4 条测试 + 变异 1/2/4）。
- spec §2 分层红线（PreviewView 不写几何、MainWindow 算槽位）→ Task 1/2 代码体现，未新增几何运算。
- spec §5 边界（count=0、命中空白、越界槽）→ Task 1 空白不发 + Task 2 空格不弹 + `not count` 兜底。
- spec §6 测试策略与 4 处变异 → Task 1 Step5 + Task 2 Step7 覆盖。
- spec §8 验收 → Task 3 收尾对齐。

**2. Placeholder scan：** 无 TBD/TODO；每步含完整代码与命令。通过。

**3. Type consistency：** 信号名 `cellContextMenuRequested`（Task 1 定义、Task 2 连接）一致；参数序 `(int position, QPoint global_pos)` 与 `_on_cell_context_menu(self, position, global_pos)` 一致；`clear_cell`/`rotate_cell`/`place`/`_count_last`/`placements`/`cell_rot`/`page_index` 均为既有名；测试助手 `_store`/`_fill`/`_make_photos`/`qapp` 为 `test_placement.py` 既有。通过。
