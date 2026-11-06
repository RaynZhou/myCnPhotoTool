# 照片库网格画廊（GUI 增量）设计

日期：2026-11-06　基线：`master` @ c674fff（放置内核 + 取消选中修复已合入）

## 0. 背景与决策来源

用户在 exe 实测后反馈：左侧照片库目前是窄竖排列表（每项 40px 小图标 + 一行
"文件名 宽×高px"），导入多张后识别度低、不够美观。用户给出一张网格画廊截图
（大缩略图换行排布、图下显示文件名），期望照片库照此呈现。

与用户逐问确认的决策（本文档不重开这些选择）：

1. **版式占地**：保持左/右分栏不变，把左栏那一格控件从竖排列表换成**缩略图网格**；
   预览页仍在右侧不动。
2. **列数与对齐**：不写死列数、也不额外拉宽左栏。网格填满表单"字段列"宽度
   （该列宽由下方按钮/设置项撑出），左右边缘**与下方设置项对齐**；列数 =
   栏宽 ÷ 缩略图尺寸，随窗口宽度自动重排。
3. **图下文字**：两行——第一行文件名（过长自动换行），第二行像素尺寸 `宽×高px`。
4. **实现路线**：方案 A —— 直接把现有 `QListWidget` 切到 `IconMode`。`QListWidget`
   即 `QListView` 子类，IconMode 原生就是"图标在上、文字在下、自动换行"的网格，
   改动最小且**不改** `currentRow()` / `row()` / `itemClicked` 等 API，故放置与
   取消选中交互零回归。排除方案 B（自绘 delegate，过度设计）与方案 C（自建卡片
   流，需重实现滚动/选中模型，回归风险最大）。

本增量是 `2026-11-06-photoprint-photo-list-thumbnail-design.md`（列表 40px 缩略图）
的后续：把该 40px 方框尺寸提升为画廊级 120px，并从 ListMode 升到 IconMode。

本文档决策完备：实现者不需再做产品选择。

## 1. 范围

做：

- `app/main_window.py`：
  - 新增常量 `GALLERY_THUMB_PX = 120`，替换原 `THUMB_PX` 在照片列表处的两处用途。
  - `_build_ui` 里给 `photo_list` 设 IconMode 网格配置（见第 4 节），并**移除**
    `setFixedWidth(260)`，让其填满表单字段列以与下方设置项对齐。
  - `append_photo`：图标改用 `to_thumbnail(img, GALLERY_THUMB_PX)`；item 文字改两行。
  - `_photo_item_text`：返回带换行的两行文本。
  - 补 `QListView` 导入。
- 相应 GUI 冒烟测试（`test_app_main_window.py`，见第 8 节）。

不做（明确排除，实现时不得顺手加）：

- 缩略图跟随逐格旋转重生成（旋转状态仍只在版面/预览体现，库缩略图恒按原图方向）。
- 缩略图点击放大、双击预览、右键菜单、拖拽重排（`movement=Static`）。
- 异步 / 后台线程生成缩略图（导入低频，主线程同步生成，取舍记于第 9 节）。
- 触碰 `core` / `jobs` / `render` / `preview_view` / 放置与取消选中逻辑。
- 改变窗口整体分栏结构（仍是左设置+库、右预览）。

## 2. 分层与不变量

- 纯显示层改动，落在 `app` 层；`jobs`/`core` 不感知，无 mm/像素/裁切几何下沉。
- **不变量**：IconMode 只改视图呈现，不改数据模型与选择 API。以下既有行为必须
  原样保留，作为回归红线：
  - `photo_list.row(item)` 仍返回池下标；
  - `itemClicked` → `_on_photo_clicked` 的"点选=设放置源 / 再点同张=取消"仍生效；
  - `_place_source` 仍是放置源唯一真相；
  - 读取失败项仍 `setForeground(ERROR_COLOR)` 标红。

## 3. 组件与改动点

单一文件 `photoprint/app/main_window.py`，四处：

| 位置 | 改动 |
|---|---|
| 模块常量 | 新增 `GALLERY_THUMB_PX = 120`；`THUMB_PX` 若无其它引用则移除 |
| `_build_ui` | `photo_list` 设 IconMode 配置 + 去 `setFixedWidth(260)` |
| `append_photo` | 图标尺寸参数 `THUMB_PX → GALLERY_THUMB_PX` |
| `_photo_item_text` | 文案改两行（文件名 `\n` 尺寸 / 读取失败） |

## 4. 网格配置（IconMode）

```python
self.photo_list.setViewMode(QListView.IconMode)   # 图标在上、文字在下、自动换行
self.photo_list.setMovement(QListView.Static)     # 格子固定，不可拖拽重排
self.photo_list.setWrapping(True)                 # 随栏宽换行成多列
self.photo_list.setResizeMode(QListView.Adjust)   # 宽度变化时重排列数
self.photo_list.setWordWrap(True)                 # 长文件名换行
self.photo_list.setUniformItemSizes(True)         # 网格整齐 + 大数据性能
self.photo_list.setIconSize(QSize(GALLERY_THUMB_PX, GALLERY_THUMB_PX))
```

- 移除 `setFixedWidth(260)`：QFormLayout 字段列宽取各行的最大尺寸（下方那排
  按钮行最宽），去掉列表固定宽后，列表填满该字段列 → 网格与下方设置项左右对齐。
- 列数由字段列宽 ÷（缩略图 + 内边距）自然决定；120px 缩略图在典型栏宽下约 2 列。
- `to_thumbnail(img, 120)` 等比缩进 120×120 方框：横屏截图 → 宽≈120、高更小，
  与截图观感一致。

## 5. item 文字（两行）

`_photo_item_text(name, img)`：

- 正常：`f"{name}\n{img.width}×{img.height}px"`
- 读取失败：`f"{name}\n读取失败"`

配合 `setWordWrap(True)`，第一行过长自动折行，第二行为尺寸/失败提示。

## 6. 交互保留

- 选中/取消选中：`itemClicked` 信号与 `_on_photo_clicked` 逻辑不改；IconMode 下
  点击 item 仍触发该信号，`row(item)` 仍给池下标。
- 选中视觉：采用 IconMode 默认选中高亮（蓝底），本增量不自定义描边（YAGNI）。
- 坏图：仍红字 + "读取失败"，无缩略图图标（无原图可缩，维持现状）。

## 7. 错误处理与边界

- 无照片：空网格，无碍。
- 读取失败项：文字两行 + 红字，图标缺省。
- 大量照片：`setUniformItemSizes(True)` + 纵向滚动；每张 120px 缩略图为导入时
  一次性主线程生成成本（取舍见第 9 节）。
- 窗口化 exe 无控制台：本改动不新增异常面；沿用既有 `append_photo` 的 try/except
  收敛。

## 8. 测试策略（TDD）

在既有 `test_app_main_window.py` 新增（该文件已自带 `_no_leaked_threads` 收尾夹具，
不新建文件以免漏配夹具致 0xC0000409 硬崩）：

- `test_photo_list_is_wrapping_grid`：断言
  `viewMode()==QListView.IconMode`、`isWrapping() is True`、
  `movement()==QListView.Static`、`wordWrap() is True`、
  `iconSize().width()==GALLERY_THUMB_PX`。
- `test_gallery_item_text_is_two_lines_with_size`：`append_photo` 后取
  `photo_list.item(0).text()`，断言含 `\n` 且第二行含 `px`。
- 回归红线：现有 `test_placement.py` / `test_folder_import.py` 依赖 `row()` /
  `currentRow()` / `itemClicked` 的断言在 IconMode 下应仍绿——全量跑兜底。

变异验牙（逐项确认对应断言转红后还原）：

1. 还原 `setViewMode(ListMode)` 或删该行 → 第 1 条测试红。
2. 删 `setWrapping(True)` → `isWrapping()` 断言红。
3. `_photo_item_text` 去掉 `\n`（改回一行）→ 第 2 条测试红。
4. 图标尺寸参数改回小值 → `iconSize().width()` 断言红。

全量回归：`pytest tests/` 退出码 0，无 `MUTATION-TEMP` 残留。收尾重打包
`build_exe.ps1` + smoke 启动，布局对齐/美观由用户在 exe 手测。

## 9. 取舍与已知限制

- **主线程同步生成 120px 缩略图**：延续上一增量决策，导入低频可接受；超大图
  批量导入的潜在卡顿为已知取舍，不在本增量解决。
- **对齐属视觉**：QFormLayout 字段列宽由最宽行撑出，网格是否恰好与下方设置项
  边缘对齐依赖运行时布局，交 exe 手测，不写脆弱的像素断言。
- **选中高亮用默认蓝底**：不自定义样式，保持改动最小。

## 10. 验收标准

1. 照片库呈多列缩略图网格、纵向滚动、随窗口换行重排，图下两行显示文件名与尺寸。
2. 网格左右边缘与下方设置项对齐，左栏总宽未被额外拉大。
3. 点选库图 → 点预览格放置、再点同图取消选中——行为与改动前完全一致（零回归）。
4. 读取失败项仍红字标"读取失败"。
5. 全量测试通过、无残留；exe 重打包启动正常。
