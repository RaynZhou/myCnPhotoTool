# PhotoPrint 拖放排版 · 增量 2a（放置内核）设计

## 0. 背景与总目标

用户想要的工作方式：导入/添加照片进**照片库**，再把库里的某张照片**放到打印布局
的指定格**里（例：A4 一页排 4 张 5 寸，把照片 A 放进 4 个位置之一），可重复放置、
逐格旋转、跨页摆放。

这条需求拆成两个增量：

- **增量①（已完成上线）**：`导入文件夹…` 批量把图片按名排序 append 进照片列表。
  在现有"顺序填充"模型内完成，是过渡桥。
- **增量②（本设计所属）**：拖放放置主体。又内部拆两刀：
  - **2a 放置内核（本文）**：库/放置解耦的数据模型 + "选库图 + 点预览格"的
    非拖拽指派 + 逐格旋转 + 命中几何（新 core 函数）+ `last_job` 新 schema 与
    迁移 + **移除顺序自动填充**。
  - **2b 拖放（另文）**：把 `QDrag`/`dropEvent` 接成 2a 同一个 `place()` 动作的
    手势入口。纯增量，不改 core、不改数据模型。

### 0.1 brainstorm 已敲定的整体决策（终态）

- 交互：纯手动拖放，**替代**现有顺序自动填充（2a 起加入库不再自动进版面）。
- 放置语义：**引用不消耗**，同一张库图可占多格。
- 作用域：拖放/指派只作用**当前页可见格**，多页靠翻页。
- 旋转归属：**逐格**旋转（改掉已上线的逐图旋转——这是行为变更）。
- 保留"添加照片"与"导入文件夹"：两者都**只往库里加**，不再自动排进布局。

## 1. 现状事实（据代码核实，作为改动基线）

- `self.photos`：**PIL 图列表**（读失败占位 `None`，渲染当空格）。
- `self.photo_paths` / `self.photo_rotations`：与 `photos` 严格等长同序的平行列表。
- `Job.photos` 直接收这条 PIL 列表；`render.render_page(plan, photos, …, rotations)`
  按 `enumerate(plan.cells)` 取 `photos[idx]`，`photo is None → continue`（跳过=留白），
  `rotations[idx]` 逐下标取角度。
- `Job.page_count = max(1, needed_sheets(count, len(photos)))`；`Job.render(page)`
  切 `photos[page*count : page*count+count]` 与 `rotations` 同切片。
- `build_job(st, photos, sheet_key, cell_key, *, gap_mm, bleed_mm, mode, offset_pct,
  borderless_active, rotations)`；`build_layout(...) → (plan, mode)`，`plan.count` = 每页格数。
- `_on_rotate` 按 `photo_list.currentRow()` 逐图旋转；`_photo_item_text` 在列表项尾附 `↻{angle}°`。
- `last_job` 现有键：`sheet_key/cell_key/mode_index/gap_mm/bleed_mm/dpi/offset_pct/
  out_dir/photo_paths/rotations`（`rotations` 逐图、与 `photo_paths` 下标对齐）。
- 分层红线：`app/` 禁一切 mm/像素/裁切几何运算，换算只在 `core`。

**关键收获**：现有模型本就是"下标≡格子、None≡空"。placements 只要**物化**成这条
下标列表，`render_page` / `Job` / 导出 / 打印**零改动**。

## 2. 数据模型（`main_window` GUI 态）

替换三平行列表为：

| 字段 | 类型 | 含义 |
|---|---|---|
| `self.pool` | `list[{path:str, img:PIL\|None}]` | 照片库；缩略图/标红/`append_photo` 容错沿用。库只 append、不清个别（2a 不新增单张删除） |
| `self.placements` | `dict[int 槽位 → int 库下标]` | 槽位放了哪张库图；缺省键=空格；引用不消耗（同库下标可多槽） |
| `self.cell_rot` | `dict[int 槽位 → 0/90/180/270]` | 逐格旋转；缺省 0。**取代 `photo_rotations`** |
| `self._pages` | `int ≥ 1` | 当前总页数 |
| `self.page_index` | `int` | 当前页 |
| `self._current_cell` | `int\|None` | 预览中选中的槽位（旋转/清空格作用对象） |
| `self._count_last` | `int\|None` | 上次每页格数，用于检测布局结构性变化 |

槽位编号：`slot = page_index * count + 格内序`，`count = plan.count`（每页格数），
`格内序 ∈ [0, count)`。

### 2.1 物化成交给 `Job` 的列表

`_rebuild_job` 内：先用 `build_layout` 得 `count`（见 §4 检测），再

```
n = self._pages * count
photos = [None] * n
for slot, pi in self.placements.items():
    if 0 <= slot < n and 0 <= pi < len(self.pool):
        photos[slot] = self.pool[pi]["img"]        # img 可能为 None（坏图）→ 留白
rotations = [self.cell_rot.get(i, 0) for i in range(n)]
```

交给 `build_job`。因 `len(photos) = _pages*count`，`Job.page_count =
needed_sheets(count, _pages*count) = _pages`，页数自洽；空槽 `None` 由 `render_page`
原样留白。**core 渲染、导出、打印全部不改**。

## 3. 页数：派生 + 翻页到末尾自动增页

- 初值 `_pages = 1`。
- `_go_page(+1)` 已在末页 → `_pages += 1`（追加一个空页），再进 `page_index`。
- 放置/旋转使 `_pages = max(_pages, 该槽所在页 + 1)`（指派总在已有页内进行，故此为上界保护）。
- **收缩**：`_go_page(-1)` 或指派后，若末页（`_pages-1`）整页无 placement 且
  `page_index < 末页` → `_pages -= 1`（可反复，直到剩 1 页）。
- **翻页增页 / 收缩 / `_go_page(±1)` 任一页码变化时重置 `_current_cell = None`**
  （否则旋转/清空格会作用到上一页的陈旧槽位）。
- 物化始终按 `_pages*count`，故空白末页在 `photos` 尾部留 `None` 段被 `Job` 保留。

## 4. 布局结构性变更 → 清空放置

`_rebuild_job` 每次算 `count`：

- `count != self._count_last`（换纸张/格子规格、或间距/出血改了每页格数）→
  槽位物理含义失效：**`placements.clear()`、`cell_rot.clear()`、`_pages=1`、
  `page_index=0`、`_current_cell=None`**，状态栏黄字"布局已变，请重新摆放"；
  更新 `_count_last`。
- `count` 未变（仅 offset / dpi / mode 等非结构参数变动，或格矩形平移）→
  placement 按槽位下标仍成立，**保留**，`render_page` 依新 plan 重画。

## 5. 命中几何：新增 core 纯函数（几何全留 core）

三函数，无 Qt、可 headless 单测：

- `render.page_cells_px(plan, sheet, dpi) → (image_wh, [格矩形])`
  返回整页图像像素尺寸与各格在**该图像像素坐标**下的矩形 `(x, y, w, h)`。
  **从 `render_page` 内部既有的 mm→px 装箱坐标抽出复用**，不重复实现、不产生第二套几何真相源。
- `render.cell_index_at(cell_rects_px, image_wh, view_wh, pos) → 格内序 | None`
  把视图坐标 `pos` 映回图像坐标（内含 KeepAspectRatio 信箱缩放逆变换：
  `scale = min(view_w/img_w, view_h/img_h)`，居中偏移），落在哪个格矩形返回其格内序，否则 `None`。
- `render.cell_rects_view(cell_rects_px, image_wh, view_wh) → [视图px 矩形]`
  供描格框/高亮，套用同一 fit 变换；与 `cell_index_at` 共用 fit 计算，保证命中与绘制零偏差。

`dpi` 用预览的 `PREVIEW_DPI`：几何用图像坐标、显示走 `scaled(KeepAspectRatio)`，
两者对同一 `image_wh` 做同一 fit，命中与所见一致（几何与 dpi 无关地自洽）。

## 6. 预览交互控件（新模块 `photoprint/app/preview_view.py`）

把现于 `main_window` 的预览显示/缩放职责迁入一个 `QLabel` 子类 `PreviewView`，
避免 `main_window` 继续膨胀：

- 承 `_on_preview`/`_rescale_preview`/`resizeEvent` 的缩放显示。
- 持当前页 `cell_rects_px` + `image_wh`（由 main_window 每 `_rebuild_job` 算好注入）；
  在 `paintEvent` 里用 `cell_rects_view` 叠加：所有格细描边、`_current_cell` 高亮框、
  （2b 复用）拖放悬停目标高亮。
- `mousePressEvent`：由点击点 + 控件尺寸调 `cell_index_at` → 发信号
  `cellClicked(int 格内序)`（格内序；main_window 加 `page_index*count` 成槽位）。
- 无几何写在 GUI：所有矩形/命中来自 §5 三函数。

## 7. 指派 / 旋转 / 擦除交互（统一规则）

- **点预览格**（`cellClicked(格内序)` → 槽位 `slot`）：
  1. 设 `_current_cell = slot`（刷新高亮）。
  2. **若此刻库有选中项**（判据 = `photo_list.currentRow()` 落在 `[0, len(pool))`；
     用户先点库行即选中，点预览格不改库选中态）→ `place(slot, pool_idx)`：
     `placements[slot] = pool_idx`，并保 `_pages ≥ slot页+1`，`_debounce.start()`。
     （无有效库选中时纯选中该格，供随后旋转/清空格；放置后库选中态保留，点下一格
     即再次放入——这就是"引用不消耗、同图可多格"的入口。）
- `place(slot, pool_idx)` 是**唯一写放置的入口**——2b 的 `dropEvent` 调它，
  迁移重放也经它，杜绝多真相源。
- **旋转 90°**：作用于 `_current_cell`（`cell_rot[slot] = (old+90)%360`），
  不再读 `photo_list.currentRow()`；无当前格→状态栏引导"请先点选版面中的格"。
  旋转不改库图，直接 `_debounce.start()` 重渲。
- **新增"清空格"按钮**：`placements.pop(slot)`、`cell_rot.pop(slot)` → 该格留白，
  触发收缩/重渲。
- 列表项文字：库图不再有逐图角度，`_photo_item_text` 去掉 `↻{angle}°` 段（旋转已移到格上）。

## 8. 库操作与清空语义

- **清空按钮** `_on_clear_photos`：清 `pool` + `photo_list` + `placements` +
  `cell_rot`，`_pages=1`、`page_index=0`、`_current_cell=None`，`_refresh()`。
- **单张从库删除**：现状本无此功能 → **2a 不新增**（YAGNI）。库只 append，
  库下标因此稳定，placement 引用无需重排簿记。
- "添加照片"/"导入文件夹"：仍只 `append_photo` 进 `pool`（增量① 逻辑不变），
  但**不再自动进版面**——用户需手动 `place`。这是 §0.1 的行为变更落地点。

## 9. 持久化（`last_job` 新 schema + 向后迁移）

### 9.1 写 `save_last_job`

保留现有参数键不变，替换照片相关段：

```
"pool_paths":  [e["path"] for e in self.pool],              # 有序，库下标即序
"placements":  {str(slot): pool_idx, ...},                  # JSON 键须字符串
"cell_rot":    {str(slot): angle, ...},                     # 仅非 0 项
"pages":       self._pages,
```

移除 `photo_paths` / `rotations`（被 `pool_paths`/`placements`/`cell_rot` 取代）。

### 9.2 读 `_restore_last_job`

- 参数键恢复沿用现有 `_safe` 逐项降级。
- 逐 `pool_paths` `append_photo`（坏图→`None` 占位，保留库下标对齐，不丢引用）。
- `placements`/`cell_rot`：键转 int、值转 int；**槽越界、库下标越界、角度非法**
  的条目逐条丢弃（引用完整性优先，不因一条坏数据牵连其余）。
- `pages`：`int`，`<1` 或非数 → 兜 `1`；且 `pages = max(pages, 最高 placement 页+1)`。
- 任一整体形状错（`placements` 不是 dict 等）→ 放置段整体降级为"没有放置"，
  仍恢复库图（用户重摆），不闪退。

### 9.3 向后迁移（顺序模型 → 放置模型）

旧 `last_job` 有 `photo_paths`+`rotations` 而**无 `placements`** 时：

- 按旧法逐 `photo_paths` 入 `pool`；
- 顺序填充重放：`placements = {i: i for i in range(len(pool))}`、
  `cell_rot = {i: rotations[i] for i in range(len(rotations)) if rotations[i]}`、
  `pages = ceil(len(pool)/count)`（`count` 取恢复后 layout 的格数）——
  **升级不丢上次布局**，与增量① 的"顺序填充"表现一致。

## 10. 错误处理

全部走状态栏，绝不裸抛（窗口化 exe 无控制台，异常外抛即静默闪退）：

- 命中越界 / 未选中就旋转 / 未选中就清空格：正常色引导文案，no-op。
- 库图 `load` 失败：`pool` 存 `img=None` 占位（与 `append_photo` 现容错一致），
  placement 引用它时物化成 `None` 空格。
- 配置损坏：见 §9 逐项/整体降级。
- `build_layout` 抛 `ValueError`（放不下）：`_rebuild_job` 现分支已置 `job=None` +
  红字，保留。

## 11. 测试策略（TDD + 变异验牙）

**core 纯函数（无 Qt，headless）**：

- `page_cells_px`：格数与 `plan.cells` 一致、矩形在图像像素范围、非退化尺寸。
- `cell_index_at`：命中中心→正确格内序；信箱留白区→`None`；相邻格边界不串；
  **用非正方格 + 非正方视图**验证 fit 逆变换（防"无牙断言"，沿旋转测试教训）；
  改 view 尺寸后命中随缩放自洽。
- `cell_rects_view`：与 `cell_index_at` 同一 fit，绘制矩形能覆盖命中点。

**GUI（offscreen + 复刻 `_no_leaked_threads` 收尾夹具）**：

- `place(slot, pool_idx)` 后物化 `photos[slot]` = 该库 `img`、其余 `None`。
- 同库图放多格 → 多槽非 `None`（引用不消耗）。
- 点空格设 `_current_cell`、旋转只改该格 `cell_rot`、邻格不受影响。
- 加入库**不再自动进版面**（append 后未 place 则 `photos` 全 `None`）——行为变更关键牙。
- 清空格 → 该槽回 `None`；末页清空并离开 → `_pages` 收缩。
- `_go_page(+1)` 到末页 → 追加页；`photos` 长度 = `_pages*count`。
- `count` 变（换 paper/cell）→ 放置清空 + 警告；仅 offset 变 → 放置保留。
- 迁移：旧 `photo_paths`+`rotations`、无 `placements` → 顺序重放等价旧表现。
- 新"清空格"按钮存在（objectName）且触发清除。
- 预览控件描格框/高亮：给定 `cell_rects` 时 `cell_index_at` 驱动指派（可用信号直连测）。

**变异验牙**：对命中 `None` 分支、越界丢弃、count 变化清空、迁移重放、引用不消耗
各造一处破坏，确认对应测试转红；还原后全量 `pytest tests/` 绿。

## 12. 与增量 2b 的衔接（不在本增量实现）

2b 仅在 2a 就位之物上加手势入口，**不改 core、不改数据模型**：

- 库列表 `setDragEnabled` + `startDrag`（mime 带库下标）。
- `PreviewView` `setAcceptDrops` + `dragMoveEvent`（用 `cell_index_at` 高亮悬停格）
  + `dropEvent`（命中 → `place(slot, pool_idx)`）。
- 点击指派（2a）与拖放（2b）共用 `place()` 与同一命中几何，行为逐字一致。

## 13. 不做（YAGNI / 明确排除）

- 不做单张库图删除、不做撤销栈、不做跨页复制布局。
- 不做网格之外的自由摆放（位置仍由 `pack` 格子决定）。
- 不改 core 渲染/装箱几何、不改导出与打印路径。
- 递归子目录导入（增量① 已排除，本增量沿用）。
