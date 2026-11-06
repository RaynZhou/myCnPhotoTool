# 导入文件夹（增量①，GUI）设计

日期：2026-11-06　基线：`master` @ 692b3f2（照片列表缩略图已合入）

关联：本增量是"文件夹导入 + 拖拽到指定格"大需求的**第一部分**。大需求的整体
决策已在下方第 0 节记全；本增量只落地其中可独立验收的"导入文件夹"，拖拽放置
模型（库/放置解耦、命中几何、逐格旋转、`last_job` 重构）留待**增量②**另立本
设计文档。

## 0. 背景与已确认的整体决策

用户在 exe 实测提出：希望支持导入文件夹、显示该文件夹下所有照片，用户可把某
张拖到打印布局的指定格（如 A4 已排 4 张 5 寸，拖照片 A 到 4 格之一）。

逐问确认的**整体（终态）决策**（增量②继续采纳，本文不重开）：

1. **放置模型 = 纯手动拖放**，取代现有"添加照片→自动顺序填充"（终态）。
2. **可重复放置**：同一张候选图可放进多个格子，库为"引用"不消耗。
3. **拖拽只作用于当前页可见格**，多页仍靠上一页/下一页切换。
4. **旋转归属"放置格"**（同一图多处放置可各自不同朝向），这是对已上线逐图旋
   转的行为变更。
5. **实现拆两个增量**：①文件夹导入（本设计）②拖拽放置 + 逐格旋转 + 持久化。

**本增量必须遵守的过渡约束**：在增量②把"顺序填充"换成"手动放置"之前，本增
量**不得**移除或改动"添加照片→顺序填充"这一既有排版路径——否则在拖拽尚未存
在的阶段，导入的文件夹照片无法进入布局，应用功能退化。故增量①定位为：**在
现有顺序模型内，新增一个"批量把文件夹图片加进照片列表"的入口**，与"添加照
片…"共用同一条 `append_photo` 顺序追加路径。

## 1. 范围

做：

- `app/main_window.py`：按钮行新增「导入文件夹…」；新增
  `import_folder(dir_path) -> int`（返回成功识别并入列的图片数），及一个内部
  枚举函数 `list_folder_images(dir_path) -> list[str]`。
- 相应 GUI 测试（`test_app_main_window.py`）。

不做（明确排除，实现时不得顺手加，全部留增量②或永不）：

- 照片库 / 放置解耦、拖拽、命中几何、逐格旋转、`last_job` 结构变更（增量②）。
- 子目录递归、跨来源去重、导入数量上限（YAGNI，无真实需求）。
- 非图片文件的类型嗅探（只看扩展名，读不了的交给 `append_photo` 现有容错）。
- 拖放系统原生文件进窗口（`dropEvent`）——本增量只做"选目录→批量加"。

## 2. 行为规格

### 2.1 入口

- 按钮行由 `[添加照片…] [清空] [旋转 90°]` 变为
  `[添加照片…] [导入文件夹…] [清空] [旋转 90°]`。
- 「导入文件夹…」点击 → `QFileDialog.getExistingDirectory(self, "选择照片文件夹", self._start_dir())`；
  取消（空串）→ 什么都不做，不改列表、不刷新。
- 选定目录 → 调 `self.import_folder(dir_path)`。

### 2.2 `list_folder_images(dir_path)`（纯函数，无 Qt）

- 仅取 `dir_path` **顶层**条目中的**文件**（`Path.is_file()`），目录跳过（不递归）。
- 扩展名判定：属于 `IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}`，
  **大小写不敏感**（`.JPG` 算数）。扩展名取自 `Path.suffix.lower()`。
- 返回**按文件名不区分大小写排序**的字符串路径列表（`sorted(..., key=lambda p: p.lower())`
  以完整路径小写为键即可，同目录内等价于按文件名；键必须确定，避免依赖文件系统
  原始枚举顺序）。
- 目录不存在 / 无权限 → 返回 `[]`（不抛；窗口化 exe 无控制台，异常即静默闪退）。

### 2.3 `import_folder(dir_path)`

- `paths = list_folder_images(dir_path)`。
- 逐个 `self.append_photo(p)`（复用既有读图/失败标红/占位逻辑，坏图不阻塞其余）。
- 循环结束后调一次 `self._debounce.start()`（**一次**刷新，非每张一次）。
- 返回 `len(paths)`。
- 目录为空/无图片（`paths == []`）：不调 `append_photo`、不起 debounce，状态栏
  提示"该文件夹没有可导入的图片"（正常色，非错误——与"请先选中照片"同档）。
- 成功导入 N 张：状态栏提示"已导入 N 张图片"（正常色）。

### 2.4 与既有语义的关系

- 不改 `append_photo`、`_on_add_photos`、`_on_clear_photos`、`_on_rotate` 行为。
- 导入的照片与手动添加的**混排无别**：都进同一 `photos` 顺序列表，照常自动填充
  到布局格子（本增量维持顺序模型）。
- 可重复导入同一文件夹 → 产生重复条目（与"添加照片"可重复同口径，增量①不去重）。

## 3. 接口

```python
# 模块级新常量（与 IMAGE_FILTER 同源口径，避免"能筛出但列不出"的错配）
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp")

def list_folder_images(dir_path) -> list[str]:
    """顶层、按扩展名（大小写不敏感）筛选、按路径小写排序的图片路径；
    目录不存在/不可读返回 []。无 Qt 依赖，纯函数便于单测。"""

class MainWindow:
    def import_folder(self, dir_path) -> int:
        """枚举 dir_path 下图片并逐张 append_photo，末尾一次 debounce，返回识别数。"""
    def _on_import_folder(self):
        """QFileDialog.getExistingDirectory → import_folder；取消即 no-op。"""
```

> 注：`IMAGE_FILTER` 与 `IMAGE_EXTS` 扩展名集合必须一致——前者管对话框筛选、
> 后者管文件夹枚举，两处不同步会出现"对话框能选但批量导入漏掉"或反之。测试
> 里钉一处二者扩展名集合相等，防漂移。

## 4. 错误处理

| 场景 | 处理 |
|---|---|
| 目录不存在 / 无权限 | `list_folder_images` 返回 `[]`，不抛，状态栏"没有可导入的图片" |
| 目录无图片 | 同上，不动列表不起 debounce |
| 某图损坏读不了 | 走 `append_photo` 既有标红分支，其余照常，不阻塞 |
| 对话框取消 | `_on_import_folder` 直接返回，无任何副作用 |
| 超大目录（成百上千图） | 全量 `append_photo` 会读图占内存/耗时——增量①按"用户自担批量规模"处理，不设上限；性能与"库解耦+懒加载"留增量②一并解决 |

## 5. 持久化

无改动。`last_job` 已有 `photo_paths`，导入的照片本就是普通照片条目，随现有
机制一并持久化/恢复（恢复走 `_restore_last_job` 的逐条 `append_photo`）。本增量
不新增字段。

## 6. 测试方案

全部脱机（`offscreen`），进 `tests/test_app_main_window.py`，直接调
`import_folder(tmp_dir)` 绕开目录对话框：

- `test_import_folder_adds_images_sorted`：目录放 3 张图（如 `c.jpg b.png a.tif`）
  → 返回 3；`photo_list.count() == 3`、`len(photos) == 3`，且顺序为排序后
  `a.tif, b.png, c.jpg`（钉住"仅顶层 + 大小写不敏感排序"，用不同扩展名制造
  非字母前缀以证明真按名排序而非按类型）。
- `test_import_folder_ignores_non_images_and_subdirs`：目录含 `notes.txt`、子目录
  `sub/pic.jpg` → 均不纳入，只收顶层合法图。
- `test_import_folder_bad_image_still_flags_and_continues`：目录含一张好图 + 一张
  写坏字节的 `.jpg` → 返回 2（两张都入列），坏项 `photos` 里为 `None`、列表项
  标红，好项正常（复用 `append_photo` 容错）。
- `test_import_folder_empty_dir_no_change`：空目录 → 返回 0，`photo_list.count()`
  不变、无异常、不起 debounce（可用状态栏文案"没有可导入的图片"侧证）。
- `test_import_folder_missing_dir_returns_zero`：传不存在路径 → 返回 0，不抛。
- `test_image_exts_match_filter`：`set(IMAGE_EXTS)` 与从 `IMAGE_FILTER` 解析出的
  扩展名集合相等（防两处漂移）。
- `list_folder_images` 另加一条纯函数单测（不经窗口）：给定临时目录断言返回顺序
  与筛选，钉住"纯函数可独立测"。

变异验牙（每断言至少一处）：删排序键 → 顺序测试转红；加递归/去递归反向；把扩展名
判定改成大小写敏感 → 大写扩展名用例转红；`import_folder` 里把单次 debounce 改成
循环内 → 用计数或调用次数侧证（如可断言）至少证明"末尾一次"。

## 7. 验收标准

1. `python -m pytest tests/ -q` 全绿（现有 + 新增）。
2. 手工核对：exe 点「导入文件夹…」选一个含多张照片的目录 → 列表按名出现这些
   照片（带缩略图），预览按现有顺序模型自动填充；含子目录/非图片/坏图时表现符
   合第 6 节。
3. 既有 `_on_add_photos` / 顺序填充 / 旋转 / 导出 / 持久化测试不改仍绿（过渡约束）。

## 8. 增量②预告（不在本增量实现）

本增量合入后，增量②将引入：照片库与放置解耦、拖拽命中放置（需新增 core 命中
函数 `render.cell_index_at`）、旋转由逐图改逐格、`last_job` 结构升级、并在终态
移除"顺序自动填充"。届时"添加照片…/导入文件夹…"从"进布局列表"改为"进候选库"，
本增量的顺序填充角色由手动放置取代。
