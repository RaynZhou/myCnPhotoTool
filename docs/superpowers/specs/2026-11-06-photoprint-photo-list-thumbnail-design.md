# 照片列表缩略图（GUI 增量）设计

日期：2026-11-06　基线：`master` @ 8eb2f4d（窗口自适应修复已合入）

## 0. 背景与决策来源

用户在 exe 实测：照片列表每项只显示文件名 + 像素尺寸文字，导入多张照片后
无法一眼认出哪张是哪张，感知很弱。希望在列表里给每张图配一个小缩略图。

与用户逐问确认的决策（本文档不重开这些选择）：

1. **缩略图不跟随「旋转 90°」变化**：恒按原图方向显示，旋转状态仍靠列表文字
   里的 `↻90°` 后缀标注（旋转是低频微调，缩略图只承担"认图"职责，不重生成以
   保持简单、避免每次旋转都重算图）；
2. **缩略图尺寸 40×40 px 上限**（等比缩放到该方框内），在"看得清"与"文件名不
   被挤掉、一屏可见数量不减太多"之间取平衡；
3. **主线程同步生成**：导入是低频操作，几十张图 `PIL.thumbnail` 很快，先不做
   异步；超大图批量导入的潜在卡顿作为已知取舍记录在第 9 节。

本文档是决策完备的：实现者不需要再做产品选择，只需按条目落地。

## 1. 范围

做：

- `app/view.py`：新增 `to_thumbnail(img, px)`，PIL 图 → 等比小 `QPixmap`。
- `app/main_window.py`：`photo_list` 设 `setIconSize`；`append_photo` 成功分支
  给列表项挂缩略图图标（`QIcon`）。
- 相应 GUI 冒烟测试（`test_app_main_window.py`）。

不做（明确排除，实现时不得顺手加）：

- 缩略图跟随旋转重生成（第 0 节决策 1 已排除）。
- 缩略图点击放大、双击预览、右键菜单。
- 异步 / 后台线程生成缩略图（第 0 节决策 3）。
- 改变列表文字文案、排版、渲染几何（本增量纯显示层，绝不触碰 jobs/core）。
- 读取失败占位项的缩略图（无原图可缩，维持现状：仅红字）。

## 2. 分层与不变量

本增量严格落在 **界面显示层**，遵守全局约束"本层不含 mm/像素换算与裁切几何"：

- 缩略图生成只在 `view`（PIL→Qt 的唯一转换处）和 `main_window`（挂图标）发生，
  不进入 `jobs` / `core`。
- **I-1**：加缩略图不得改变任何既有列表文字文案——`_photo_item_text` 输出逐字
  不变，故既有断言列表文字、`↻90°` 后缀的测试全部不受扰动。
- **I-2**：缩略图只读 `self.photos[i]`（原图），不复制进 photos 列表、不参与
  排版与渲染，导出/打印结果与加缩略图前逐像素相同。
- **I-3**：`append_photo` 是唯一入口，"添加照片"与"启动恢复上次设置"
  （`_restore_last_job` 逐条 `append_photo`）两条路径都自动带缩略图，无需分别
  处理，杜绝两处漂移。

## 3. 接口改动

```python
# app/view.py  —— 新函数，复用现有 to_pixmap
def to_thumbnail(img, px):
    """PIL 图等比缩到 px×px 方框内转 QPixmap；不动传入的 img。"""
    small = img.convert("RGB").copy()   # 保证 to_pixmap 的 raw RGB 前提，且不改动原图
    small.thumbnail((px, px))           # PIL 原地等比缩放，长边不超过 px
    return to_pixmap(small)
```

```python
# app/main_window.py
THUMB_PX = 40            # 模块级常量，与 DPI_CHOICES 等并列

# _build_ui 里，photo_list 建好后：
self.photo_list.setIconSize(QSize(THUMB_PX, THUMB_PX))

# append_photo 成功分支（img 非 None），建 item 后挂图标：
item = QListWidgetItem(self._photo_item_text(name, img, 0))
item.setIcon(QIcon(view.to_thumbnail(img, THUMB_PX)))
self.photo_list.addItem(item)
```

- `QSize`、`QIcon` 从 `PySide6.QtCore` / `PySide6.QtGui` 补进现有 import。
- **失败分支（img is None）保持原样**：只建红字 item，不 `setIcon`，其 icon 为
  默认空 QIcon（`isNull()` 为 True）。
- `view.to_thumbnail` 对 `img.convert("RGB").copy()` 操作，绝不原地改
  `self.photos[i]`（photos 是渲染共享对象，改了会污染导出）。

## 4. 界面细节

- `setIconSize(40×40)` 后 `QListWidget` 行高随之增大以容纳图标，属预期效果；
  图标在左、文字在右（Qt 默认图标文字并排），无需自定义 delegate。
- 缩略图为等比，长边 40、短边按原比例，不同宽高比图片图标宽度不一，但
  `setIconSize` 统一占位框，行对齐仍整齐。
- 旋转按钮 `_on_rotate` **完全不改**：它只重算文字（`_photo_item_text`），不碰
  icon，符合第 0 节决策 1。

## 5. 持久化

无改动。缩略图是运行期从 `self.photos`（原图）派生的显示产物，不落库。重启后
`_restore_last_job` 重新 `append_photo` 会重新生成缩略图，`last_job` 结构逐字
不变（不新增字段）。

## 6. 错误处理

| 场景 | 处理 |
|---|---|
| 原图 `thumbnail` 过程中 PIL 异常 | 理论不发生（photos[i] 已是 load_photo 成功产物）；不加 try，保持 `append_photo` 成功分支纯粹 |
| 超大图 | 仍等比缩到 40，无特殊分支；性能取舍见第 9 节 |
| 读取失败项（None） | 不生成缩略图，维持红字，不新增异常路径 |

## 7. 测试方案

全部脱机（`offscreen`），进 `tests/test_app_main_window.py`：

- `test_photo_list_has_thumbnail_icon`：
  - `append_photo` 一张真实图（如 200×100）后，对应 `item.icon().isNull()` 为
    **False**；取 `icon.availableSizes()` 或 `pixmap(...)` 断言长边 ≤ 40（有牙：
    删 `setIcon` 则 icon 为空转红）。
- `test_failed_photo_has_no_icon`：
  - `append_photo` 一张读失败的占位（None）→ `item.icon().isNull()` 为 **True**、
    文字仍含"（读取失败）"且标红不变（钉住失败分支不回归）。
- `test_thumbnail_does_not_mutate_photo`：
  - `append_photo` 后 `self.photos[-1].size` 仍为原图尺寸（钉住 I-2：缩略图不改
    共享原图，否则导出会被污染）。
- 既有全部测试（列表文字、`↻90°` 后缀、旋转、导出、持久化）必须不改仍绿（I-1、
  I-3 的保护）。

## 8. 验收标准

1. `python -m pytest tests/ -q` 全绿（现有 + 新增）。
2. 手工核对（用户场景）：exe 导入多张不同照片，列表每项左侧出现可辨认的小缩
   略图；旋转某张 → 文字 `↻` 变、缩略图方向不变；导出 PDF 与加缩略图前一致。

## 9. 遗留与后续

- **异步生成**：几百张超大图一次性导入时主线程可能瞬卡。当前按低频操作取舍不
  做；若成真实痛点，复用现有 `worker.start` + gen 过期丢弃机制起后台生成，不预
  留开关。
- **缩略图跟随旋转 / 点击放大 / 自定义 delegate 排版**：待真实需求再立增量。
