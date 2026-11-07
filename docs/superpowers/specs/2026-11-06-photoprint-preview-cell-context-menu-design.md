# 预览格右键菜单（移除/旋转单格）设计

日期：2026-11-06　基线：`master` @ 5503686（照片库网格画廊 + 选中态样式已合入）

## 0. 背景与决策来源

用户在 exe 实测：右侧布局预览页里，想把某一张已放入布局的照片单独去掉，
目前只能靠"清空"（清全部）或先左键点中该格再用"清空格"按钮（两步、且易点错格）。
期望：在预览页某格上**鼠标右键**弹出菜单，直接对**该格**执行移除/旋转。

与用户逐问确认的决策（本文档不重开这些选择）：

1. **菜单内容**：两项——"移除该照片"（清掉该格放置，照片仍留在左侧库）+
   "旋转 90°"（该格逐格旋转）。
2. **弹出条件**：仅当右键命中的格**已放置照片**时才弹菜单；空格或格外空白区
   不弹（移除/旋转对空格无意义）。
3. **动作落点**：作用于**右键命中的那一格**（`page_index*count + 页内序`），
   而非当前高亮格——所见即所操。
4. **复用既有能力**：移除 = `clear_cell(slot)`、旋转 = `rotate_cell(slot)`，
   二者已存在且各自内部触发 `_debounce` 刷新；本增量不新增放置内核、不碰
   `core`/`jobs`/`render`。
5. **既有"清空格"按钮保留**：右键是新增的直达入口，非替代。
   （2026-11-07 补丁：反过来——按钮已删，右键成了唯一入口；见 `2026-11-07-photoprint-overlay-target-design.md`）

本文档决策完备：实现者不需再做产品选择。

## 1. 范围

做：

- `app/preview_view.py`：新增信号 `cellContextMenuRequested(int, QPoint)`；重写
  `contextMenuEvent` 做命中并发射（几何仍全权交 `render`，本模块不写 mm/像素运算）。
- `app/main_window.py`：连接该信号 → 新增 `_on_cell_context_menu(position, global_pos)`，
  计算全局槽位、空格守卫、构建并弹出 `QMenu`、按选择分派 `clear_cell`/`rotate_cell`；
  补 `QMenu`（QtWidgets）、`QPoint`（QtCore）导入。
- 相应 GUI 冒烟测试（`tests/test_placement.py`，见第 6 节）。

不做（明确排除，实现时不得顺手加）：

- 不改 `core`/`jobs`/`render`/放置内核（`place`/`clear_cell`/`rotate_cell` 原样复用）。
- 不在右键时改变"当前高亮格"（`_current_cell`）或库选中态（`_place_source`）。
- 不加"清空所有"到右键菜单（清空仍走既有按钮）。
- 不做多级子菜单、快捷键、图标。

## 2. 分层与不变量

- `PreviewView` 只知几何/命中，**不知**放置语义：命中到哪个格（页内序）就发信号，
  是否该弹、弹了做什么由 `MainWindow` 决定。延续 app 层禁 mm/像素/裁切几何红线。
- `MainWindow` 负责：页内序 → 全局槽位（`page_index*count + position`，纯放置域
  下标算术，非几何）、空格判定（`slot in self.placements`）、菜单构建与分派。
- **不变量**：`clear_cell`/`rotate_cell` 的既有语义与守卫（未占用格调用为安全 no-op）
  不变；本增量只是新增一个调用它们的入口。

## 3. 组件与改动点

| 文件 | 改动 |
|---|---|
| `app/preview_view.py` | 加 `cellContextMenuRequested = Signal(int, QPoint)`；加 `contextMenuEvent` 重写 |
| `app/main_window.py` | `_build_ui` 连信号；加 `_on_cell_context_menu`；import `QMenu`、`QPoint` |
| `tests/test_placement.py` | 加右键菜单行为测试 |

### 3.1 PreviewView.contextMenuEvent

```python
def contextMenuEvent(self, event):
    idx = self.hit_position(event.pos().x(), event.pos().y())
    if idx is not None:
        self.cellContextMenuRequested.emit(idx, event.globalPos())
```

- `hit_position` 命中格内返回页内序，命中空白返回 None（不发）。
- 是否"已放置"不在此判断（PreviewView 不知 placements），交 MainWindow。

### 3.2 MainWindow._on_cell_context_menu

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

- `count` 兜底：布局错误（job=None）时几何未注入，`hit_position` 本就返回 None，
  信号不会触发；此处 `not count` 再兜一层，防御性提前返回。
- 分派后 `clear_cell`/`rotate_cell` 内部各自 `_debounce.start()` → 刷新预览与页数。

## 4. 数据流

右键某格 → `PreviewView.contextMenuEvent` 命中 → 发 `(页内序, 全局坐标)` →
`MainWindow` 算全局槽位 → 空格则返回；非空格弹菜单 → 用户选择 → `clear_cell`/
`rotate_cell` 改 `placements`/`cell_rot` → debounce → `_refresh` 重算排版、重渲预览。

## 5. 错误处理与边界

- 窗口化 exe 无控制台：`menu.exec` 为 Qt 模态弹窗，正常；无新增异常面。
- 命中空白/格外：`hit_position` 返回 None → 不发信号 → 无菜单。
- 命中空格（几何在内但未放置）：`slot not in placements` → 直接返回，不弹。
- 越界槽位（多页翻页后 position 仍受 count 限界）：`slot not in placements` 自然拦截。

## 6. 测试策略（TDD）

在既有 `tests/test_placement.py` 新增（自带 autouse `_no_leaked_threads` 收尾夹具）：

- `test_right_click_occupied_cell_removes_photo`：放置 slot 1 后，monkeypatch
  `QMenu.exec` 返回菜单第 0 项（移除），调 `_on_cell_context_menu(1, QPoint())` →
  断言 `1 not in w.placements and 1 not in w.cell_rot`。
- `test_right_click_occupied_cell_rotates`：同上但 `QMenu.exec` 返回第 1 项（旋转）→
  断言 `w.cell_rot[1] == 90`。
- `test_right_click_empty_cell_no_menu`：`QMenu.exec` 打桩为"被调用即置标志/抛断"，
  对未放置的 slot 调 `_on_cell_context_menu` → 断言未弹菜单、`placements` 不变。
- `test_right_click_uses_page_offset`：多页（count 已知）在 `page_index=1` 命中页内序
  2 → 目标全局槽 = `count+2`；放置该槽后走移除，断言该全局槽被清、页内序 2 的
  当前页槽未误伤（钉住页偏移）。
- `test_preview_emits_context_menu_signal`：注入几何后（`_fill` 已 place+refresh），
  用 `QContextMenuEvent(Mouse, 格内点, 全局点)` 触发 `preview.contextMenuEvent` →
  以信号 spy/连接旗标断言 `cellContextMenuRequested` 发射且页内序正确。

变异验牙（逐项确认对应断言转红后还原）：

1. 删 `if slot not in self.placements: return` 空格守卫 → 空菜单测试红（会弹）。
2. 去掉 `page_index * count` 页偏移 → 页偏移测试红。
3. 删 `contextMenuEvent` 里的 `emit` → 信号测试红。
4. 分派里把 `clear_cell` 换成 `rotate_cell`（或删一项）→ 移除测试红。

全量回归：`pytest tests/` 退出码 0，无 `MUTATION-TEMP` 残留。收尾重打包
`build_exe.ps1` + smoke 启动；右键弹菜单的观感由用户在 exe 手测。

## 7. 取舍与已知限制

- **模态 `menu.exec` 测试需打桩**：offscreen 下无法真弹模态菜单，测试以 monkeypatch
  `QMenu.exec` 返回预设 `QAction` 模拟用户选择——这是标准 Qt 测试手法，代价是菜单
  项文案/顺序的变更不会被这三条测试直接钉死（由信号测试 + 手测兜底）。
- **空格不弹**：满足"移除/旋转只对已放图有意义"；若日后想对空格提供"从此格放置
  当前库选中图"，属新交互，另开增量。

## 8. 验收标准

1. 预览页右键某已放图格 → 弹出含"移除该照片""旋转 90°"的菜单；选移除 → 该格清空
   （照片仍在左侧库），其余格不受影响。
2. 选旋转 → 该格照片转 90°，仅影响该格。
3. 右键空格或格外空白 → 无菜单弹出。
4. 多页时对第 N 页某格操作，命中正确的全局槽位（不误伤当前页同页内序）。
5. 全量测试通过、无残留；exe 重打包启动正常。
