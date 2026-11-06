# 照片叠加文字（日期标签 + 文字水印）设计

日期：2026-11-06　基线：`master` @ 74cd445（预览格右键菜单已合入）

## 0. 背景与决策来源

用户新增需求：给排好的照片叠加文字。经 brainstorming 逐问确认，本增量**只做"叠加文字"两类**，
标题横幅（带背景色的版面区、会改装箱）留作下一增量单独设计。

与用户逐问确认的决策（本文档不重开这些选择）：

1. **范围拆分**：先做叠加文字（日期标签 + 文字水印），标题横幅随后单独增量。
2. **叠加对象**：逐张照片各自叠加（每张洗出来的图都带自己的日期/水印），非整页一次。
3. **日期来源**：优先读照片 EXIF 拍摄日期（`DateTimeOriginal`），无 EXIF 回退文件修改时间，
   格式化成 `年-月-日`；每张用自己的日期。都取不到则不画该张的日期。
4. **共存方式**：日期标签与文字水印是两个独立叠加层，可同时开、各自选角、各配样式。
5. **字体方案**：内置常见 Windows 字体下拉（黑体/微软雅黑/宋体/Arial 等），映射系统字体文件。
6. **水印透明度**：水印不透明度可调（0–100%），日期保持实心。
7. **实现路线**：方案 A——core 渲染层逐格叠加，预览与导出共用 `render_page`。

可调属性（两类各自独立）：颜色、字体、大小、粗细、位置（四角）。水印另有：自定义文字、不透明度。

## 1. 分层与不变量

- **几何/像素全部落 `core`**：字号 mm→px、四角锚点、透明度合成、加粗——app 层禁做几何（既有红线）。
- **`render_page` 是唯一渲染真相源**：预览（96dpi）与导出（300/600dpi）走同一条路径，
  所见即所得是构造出来的，不靠两边各写一套。
- **`jobs` 纯编排透传**：不 import Qt/win32，不碰 stdout。
- **向后兼容红线**：`render_page`/`Job`/`build_job` 的新参数一律带默认值（`None`＝不叠加），
  既有全部测试与 CLI 零改动、逐像素不变。
- **异常一律收敛**：字体缺失、日期解析失败、超长文字——该格不画 + 状态栏提示，绝不把整页
  渲染或导出打死（与 store"任何损坏降级成没有"同口径）。

## 2. 新增模块 `core/text_overlay.py`

纯数据 + PIL，无 Qt/win32 依赖。

### 2.1 数据结构

```python
class Corner:                      # 四角（字符串常量，便于持久化/比较）
    TL, TR, BL, BR = "tl", "tr", "bl", "br"

@dataclass(frozen=True)
class TextSpec:
    enabled: bool = False
    text: str = ""                 # 水印用；日期渲染时按格注入，忽略此字段
    font_key: str = "yahei"        # 见 FONT_TABLE
    size_mm: float = 4.0           # 文字名义高度（mm），dpi 无关
    weight: str = "normal"         # "normal" | "bold"
    corner: str = Corner.BR
    rgb: tuple = (255, 255, 255)   # 文字颜色
    alpha: int = 255               # 0–255；日期恒 255，水印按不透明度滑条
    margin_pct: float = 4.0        # 内缩边距占格短边百分比
```

### 2.2 字体表

`FONT_TABLE: dict[str, tuple[str, str | None]]`，`font_key → (常规字体路径, 粗体字体路径或 None)`，
指向 `C:\Windows\Fonts`（本 app 为 Windows 专用 exe，与既有 `win/` 层同源假设）：

| font_key | 名称 | 常规 | 粗体 |
|---|---|---|---|
| `yahei` | 微软雅黑 | `msyh.ttc` | `msyhbd.ttc` |
| `heiti` | 黑体 | `simhei.ttf` | `None`（→ stroke 合成） |
| `songti` | 宋体 | `simsun.ttc` | `None`（→ stroke 合成） |
| `arial` | Arial | `arial.ttf` | `arialbd.ttf` |

路径缺失（文件不存在）→ 该次叠加安全跳过、不抛。UI 下拉列出"名称"，`_params` 存 `font_key`。

### 2.3 渲染函数

```python
def draw_overlay(page, cell_rect_px, spec, text):
    """在 page（RGB 整页位图）上的 cell_rect_px=(x,y,w,h) 格内画 text。
    逐格 clip：建与格等大 RGBA 层，画字后 alpha_composite 回 page，绝不溢出邻格。
    任何前置条件不满足（格尺寸非法 / 字体缺失 / 缩到放不下）→ 静默返回（不抛）。"""
```

内部步骤：
1. `size_px = units.mm_to_px(spec.size_mm, dpi)`；`dpi` 由调用方（render_page）传入，
   或 `draw_overlay` 直接收 `size_px`。字体 `ImageFont.truetype(path, size_px)`；粗体有文件用文件。
2. `bbox = font.getbbox(text)` → `tw, th`。
3. `inset = units.round_px(spec.margin_pct / 100 * min(cw, ch))`。
4. 按 `corner` 定锚点（见 §3.2）。
5. 超长降级：`tw > cw - 2*inset` 时按比例减 `size_px` 重算（最多 3 次）；仍放不下 → 返回不画。
6. RGBA 层填充色 `spec.rgb + (spec.alpha,)`；`weight=='bold'` 且无粗体文件时
   `stroke_width = max(1, size_px // 12)`、`stroke_fill` 同色。
7. `layer.paste`/`Image.alpha_composite` 合成回 `page` 对应位置。

## 3. 渲染集成（`core/render.py`）

### 3.1 签名扩展（带默认，向后兼容）

`render_page(..., date_overlay=None, watermark_overlay=None, date_texts=())`：
- `date_overlay`/`watermark_overlay`：`TextSpec | None`。`None` 或 `.enabled==False` → 该层不画。
- `date_texts`：与 `photos` 等长的字符串列表（每格日期，`None`＝该张无日期、日期层跳过），
  切片方式与既有 `rotations` 完全一致（`date_chunk = date_texts[i:i+count]`）。

### 3.2 绘制时机与坐标

在现有 `for idx, cell in enumerate(plan.cells)` 循环内、`page.paste(piece, ...)` 之后追加：

- 该格落位矩形（像素）：`cell_x = mm_to_px(ox + dx, dpi)`、`cell_y = mm_to_px(oy + dy, dpi)`、
  `cell_w = mm_to_px(dw, dpi)`、`cell_h = mm_to_px(dh, dpi)`（ox/oy 为模式内/外框原点，dx/dy 落位偏移，
  均为既有已算量）。
- 若 `watermark_overlay` 开启：`draw_overlay(page, (cell_x,cell_y,cell_w,cell_h), wm_spec, wm_spec.text)`。
- 若 `date_overlay` 开启且 `date_texts[idx]` 非空：`draw_overlay(page, rect, date_spec, date_texts[idx])`。
- 角锚点公式（`tw/th` 为文字宽高，均在格局部坐标）：
  - TL：`(inset, inset)`
  - TR：`(cw - tw - inset, inset)`
  - BL：`(inset, ch - th - inset)`
  - BR：`(cw - tw - inset, ch - th - inset)`

叠加在照片之上、遮罩/切缝之下（遮罩警告仍要可见）。

## 4. 编排层（`jobs.py`）

- `Job` 增字段：`date_overlay`、`watermark_overlay`（`TextSpec|None`，默认 `None`）、
  `date_texts: tuple = ()`。
- `Job.render` 把 `self.date_overlay/watermark_overlay` 原样传 `render_page`，并把
  `date_texts` 按页切片（`i:i+count`）传 `date_texts=`。
- `build_job(..., date_overlay=None, watermark_overlay=None, date_texts=())` 透传进 `Job`。
- 新增 `photo_date_text(path) -> str | None`：`Image.open(path)` → `getexif()`；
  优先 ExifIFD `DateTimeOriginal`(36867)，退 `DateTime`(306)，解析 `"YYYY:MM:DD HH:MM:SS"` →
  `"YYYY-MM-DD"`；EXIF 无/坏 → `os.path.getmtime(path)` 本地时间格式化；全失败 → `None`。
  纯 PIL/标准库，不 import Qt。

## 5. 界面层（`app/main_window.py`）

### 5.1 控件（可折叠"文字叠加"分组）

左栏 `QFormLayout` 已较满，新增一个 `QGroupBox("文字叠加")`（`setCheckable` 仅作视觉分组，
两类各自另有独立 enabled 勾选），内含两行子面板：

- **日期标签**：`QCheckBox(enabled)` + 字体 `QComboBox` + 字号 `QDoubleSpinBox`(mm) +
  粗细 `QComboBox(常规/加粗)` + 颜色 `QPushButton`(色块) + 位置 `QComboBox(四角)`。
- **文字水印**：`QCheckBox(enabled)` + 文字 `QLineEdit` + 字体/字号/粗细/颜色/位置（同上）+
  不透明度 `QSlider(0–100)`。

颜色按钮：点击 `QColorDialog.getColor`，存 `rgb` 三元组，按钮背景实时反映当前色。

### 5.2 参数汇集

`_params()` 增 `date_overlay`、`watermark_overlay` 两个 `TextSpec`（读上述控件）。
所有相关控件值变更统一接既有 `self._debounce.start`（`_connect_param_changed` 覆盖
`valueChanged`/`currentIndexChanged`；`QLineEdit.textChanged`、`QCheckBox.toggled`、
颜色按钮 `clicked` 各显式连到 `_debounce.start`）→ 走既有防抖刷新，预览即时更新。

### 5.3 日期物化

- `append_photo`：读图成功后调 `jobs.photo_date_text(path)` 存进 `pool[i]["date"]`（失败存 `None`）。
- `_rebuild_job`：像物化 `photos`/`rotations` 那样，按槽位物化 `date_texts`（与 `photos` 等长、
  空格/无日期为 `None`），连同两个 `TextSpec` 传 `build_job`。

### 5.4 持久化

`save_last_job` 的 dict 增 `date_overlay`、`watermark_overlay`（`TextSpec` 转 dict：
enabled/font_key/size_mm/weight/corner/rgb/alpha/text/margin_pct）。
`_restore_last_job` 回填控件；非法/缺字段/坏形状一律降级成默认，不抛（与既有降级同口径）。

### 5.5 导出

`export_to` 已走 `_rebuild_job` + `render_all`，叠加配置随 job 自动生效，无需改导出代码。

## 6. 边界与降级

| 情况 | 行为 |
|---|---|
| 无照片 / 空格（`photos[idx]` 为 `None`） | 该格无贴图，自然不叠加 |
| 日期解析失败（无 EXIF 且 mtime 取不到） | `date_texts[idx]=None`，日期层跳过该张 |
| 字体文件缺失 | `draw_overlay` 安全返回，不画该层、不抛 |
| 文字超长（宽/高超格） | 缩字号重算 ≤3 次；仍放不下则不画 |
| 水印文字为空 | 水印层不画（enabled 但 text 空视为无内容） |
| 导出/预览 dpi 不同 | `size_mm` 恒定 → 物理字号一致，预览所见即导出所得 |

## 7. 测试策略

### 7.1 core 单元（新增 `tests/test_text_overlay.py`，无 Qt）

- **字号 dpi 无关**：同 `size_mm` 在 96/300dpi 下 `size_px` 随 `ppmm` 线性放大。
- **四角锚点**：给定格宽高与文字 bbox，四个 corner 各算出正确锚点（含 inset 公式），不越界。
- **加粗兜底**：桩字体表——有粗体文件走粗体路径；无粗体文件走 `stroke_width` 合成。两分支各测。
- **透明度合成**：`alpha<255` 结果像素介于底图与纯色之间；`alpha=255` 等于实心。
- **超长降级**：文字宽超格宽 → 缩字号重算；仍放不下 → 不画且不抛。
- **字体缺失**：FONT_TABLE 指不存在路径 → 安全跳过、不崩。

### 7.2 渲染集成（`tests/test_render.py` 追加）

- 纯色/非对称可辨图 + 日期开启 → 目标角像素变化（**规避"纯色旋转不变"式无牙断言**，
  用方向可辨图）；日期关闭 → 与基线逐像素一致（回归红线：默认 `None` 零影响）。
- 水印半透明 → 该角像素被混合但非纯色覆盖。
- 邻格不受污染：一格叠字，相邻格像素不变（验逐格 clip）。

### 7.3 EXIF/日期（`tests/` 新增或并入 jobs 测试）

- 造带 `DateTimeOriginal` 的临时图 → 得该日期；无 EXIF → 回退 mtime；都坏 → `None` 不抛。

### 7.4 app 层（`tests/test_app_main_window.py`，复用既有 `_no_leaked_threads` 夹具）

- `_params()` 组装出两个 `TextSpec`，控件默认值正确；切开关/改字号 → debounce → job 带上配置。
- 持久化往返：设配置→存→新建窗口→`_restore_last_job` 回填一致；塞坏数据 → 降级默认不抛。

### 7.5 变异验牙（每关键断言配一处）

1. 删逐格 clip → 邻格污染测试转红。
2. corner 锚点写反（如 TL 用 BR 公式）→ 定位测试转红。
3. 去掉 alpha 合成分支（当实心）→ 透明度测试转红。
4. 默认 `None` 不短路（照画）→ 回归基线测试转红。

## 8. 验收

1. 全量 `pytest tests/` EXIT=0（既有 297+ 用例零回归）。
2. 重打包 `dist\PhotoPrint.exe`、smoke 启动不崩。
3. exe 手测清单：① 逐张照片在所选角显示各自 EXIF/文件日期；② 水印半透明、不透明度可调；
   ③ 改字号/颜色/字体/粗细/位置预览即时更新；④ 日期与水印同开、各占一角互不干扰；
   ⑤ 导出 PDF 与预览一致；⑥ 坏图/缺字体/超长文字不崩。

## 9. 取舍与备注

- **主线程读 EXIF**：`append_photo` 内同步读日期，与既有同步读图同档（增量①已确立），不额外起线程。
- **`size_mm` 而非 pt**：贴合本仓库物理 mm 口径，跨 dpi 一致；UI 标注"字号(mm 高)"。
- **加粗用粗体文件优先、stroke 兜底**：黑体/宋体无独立粗体文件，用 `stroke_width` 合成，视觉够用。
- **标题横幅不在本增量**：其带背景色、需占用版面区并改 `build_layout`/`pack`，复杂度与风险独立，
  另开 spec。
