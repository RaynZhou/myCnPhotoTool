# PhotoPrint 图形界面与单文件 exe 设计（M3-GUI）

日期：2026-11-04　分支基线：`feat/photoprint-core` @ c0d84a2（145 tests passed）

## 0. 背景与决策来源

内核计划（`2026-11-03-photoprint-core-print-pipeline.md`）交付的是无界面流水线，其架构段写明
"界面（M3）与校准页（M4）在第二份计划中实现"。总设计文档第 8 节给的是完整 QGraphicsView 编辑
器（四图层、逐格拖拽、mm 标尺、三档缩放）。

本次与用户逐问确认的范围是**轻量表单式界面 + 只出 PDF + 全局裁切微调 + 记住上次设置 + 单文
件 exe**。总设计文档第 8 节的拖拽编辑器与 M4 校准页**不在本范围内**，本文档不实现它们，也不
修改第 8 节的设计（它仍是将来 M3 完整版的依据）。

本文档是决策完备的：实现者不需要再做产品选择，只需按条目落地。

## 1. 范围

做：

- `photoprint/app/`：单窗口 PySide6 界面（表单 + 整页预览 + 导出 PDF）。
- `photoprint/jobs.py`：从 `cli.py` 抽出的共用编排层，CLI 与 GUI 同一真相源。
- `core/render.py` 增加 `offset_pct` 透传（逐格按本格尺寸换算）；`core/crop.py` 增加旋转偏移换算纯函数；旋转格落位
  映射由转置改为真旋转映射。
- 导出路径关闭不可印区遮罩（含 CLI 同步修正）。
- `core/store.py` 增加 `last_job` 读写。
- PyInstaller 单文件打包（`--onefile --windowed`）+ 崩溃日志。

不做（明确排除，实现时不得顺手加）：

- QGraphicsView 编辑器、逐格拖拽、mm 标尺、缩放三档。
- 界面直打按钮（`cli.py --print` 保留，界面不接）。
- 驱动探测面板、M4 校准页、probe_report 导出。
- 自建尺寸录入界面（`store.add_user_size` 已有能力，本次不给入口）。
- 文件拖拽入选、自定义图标、安装器、代码签名、自动更新。

## 2. 架构与依赖方向

```
photoprint/app/       PySide6，唯一有窗口的层
   ↓ 只依赖
photoprint/jobs.py    编排层：无 PySide6、无 win32，可脱机全量测试
   ↓
photoprint/core/      纯函数（禁则不变）      photoprint/win/pdf_export.py
```

禁则（违反即视为架构缺陷，与内核计划同口径）：

- `photoprint/core/**` 禁止 import `PySide6`、`win32print`、`win32ui`、`win32con`。
- `photoprint/jobs.py` 同上禁则，并额外禁止 `print`：`--windowed` 下 `sys.stdout is None`。
- `app/` 不得出现任何 mm↔像素换算、不得出现裁切几何；数值一律经 `core/units` 与 `core/crop`。
- 直接 `import` 的运行时包必须在 `requirements.txt` 显式声明。PyInstaller 是构建工具、不被
  import，写进新建的 `requirements-build.txt`，不进 `requirements.txt`。

## 3. 界面

单窗口，无对话框链（只有一个"另存为"文件对话框）。

```
┌─────────────────────────────┬──────────────────────────┐
│ 照片          [+ 添加] [清空] │                          │
│ 列表（文件名 / 像素尺寸）      │      整页预览             │
│ 纸张     [A4 ▼]              │  QLabel + QPixmap        │
│ 格子     [3R  ▼]             │  等比适应窗口             │
│ 模式     [自动 ▼]            │                          │
│ 格间距   [0.0] mm            │                          │
│ 出血     [3.0] mm            │                          │
│ 输出 dpi [300 ▼]             │                          │
│ 裁切微调  水平 [−50 … +50] % │                          │
│          垂直 [−50 … +50] %  │                          │
├─────────────────────────────┴──────────────────────────┤
│ 状态栏：每页 N 格 · 共 M 页 · 边距来源「依规格推定，未经真机校准」│
│                                    [导出 PDF…]          │
└────────────────────────────────────────────────────────┘
```

控件规则：

- 纸张下拉只列 `role == "paper"`；格子下拉列 `role == "cell"` 加全部 `role == "paper"`。这条
  结构约束来自总设计 4.3，用于杜绝"选了一寸纸"这类不可能输出。
- 模式下拉四项：`自动`、`fit_to_printable`、`fill_printable`、`bleed_trim`。`自动` 走
  `modes.default_mode`。界面显示的是中文标签 + 括注内部值，内部值是唯一真相。
- `bleed_trim` 选中时状态栏必须显示"需人工裁切"，不得写"无边距打印"；`fill_printable` 的文案
  不得写"铺满整张纸"（`modes.py` 已立的诚实性约束）。
- 参数变化 250ms 防抖后重算预览；预览渲染在 QThread 内完成。
- 照片列表为空、或排版结果为 0 格时，导出按钮禁用。
- 预览默认显示第 1 页；页数大于 1 时提供"上一页/下一页"两个按钮（只切预览，不切导出）。

## 4. 接口与数据流

```python
# photoprint/jobs.py
@dataclass
class Job:
    plan: PackPlan
    photos: list             # 与 plan.cells 一一对应的 PIL 图，长度可小于格数
    mode: str
    count: int
    page_count: int
    offset_pct: tuple[float, float]      # 纸面方向偏移（百分比），逐格由渲染层换算
    note: str                        # 供状态栏显示的诚实性说明
    def render(self, page_index: int, dpi: float,
               show_mask: bool) -> Image.Image: ...

def render_all(job, dpi, show_mask) -> list[Image.Image]:
    """CLI 用：等价于逐页调用 job.render。"""
    return [job.render(i, dpi, show_mask) for i in range(job.page_count)]

def build_jobs(st, photos, sheet_key, cell_key, *, gap_mm=0.0, bleed_mm=3.0,
               mode=None, offset_pct=(0.0, 0.0), borderless_active=False) -> Job
```

- `build_jobs` 承接现 `cli.build_plan_jobs` 的全部逻辑，含两条既有分支：证件照格
  `allow_rotate = cell.role != "cell"`、以及格子与纸同尺寸时的"整纸一格"退化重排。
- `Job.render` 承接现 `cli._pages` 的按 `plan.count` 切页逻辑，`photos` 由 Job 持有；页内空格
  （照片数不足）沿用 `render_page` 的 `None` 留白语义。
- GUI 只调 `Job.render` 渲当前页；CLI 需要全部页，走 `render_all`，避免两边各写一套切页。
- `cli.py` 改为调用 `jobs.build_jobs`，输出的三行文案与 return code 保持逐字不变，现有
  `tests/test_cli.py` 必须继续全绿。
- 预览：`dpi=96`、`show_mask=True`。导出：`dpi` 取界面值、`show_mask=False`，逐页渲染后交
  `win/pdf_export.export_pdf`。
- `core/render.py` 签名扩展为
  `render_page(plan, photos, sheet, dpi, mode, show_mask=True, show_cut_lines=True,`
  `borderless_active=False, offset_pct=(0.0, 0.0))`；渲染层逐格把百分比换成 mm 后传给
  `crop.cell_crop_box`（该函数早已支持 `dx_mm/dy_mm`，本次只是渲染层此前没有传）。

## 5. 裁切偏移几何（本次唯一的几何改动）

偏移在界面上是**纸面方向**：水平正 = 画面在纸上向右移，垂直正 = 向下移。单位换算：
`ox_mm = pct_x / 100 * 目标格宽`，`oy_mm = pct_y / 100 * 目标格高`（目标格取渲染层实际使用的
`(ow, oh)`）。

`crop.cell_crop_box` 的 `dx_mm/dy_mm` 工作在**旋转前坐标系**，所以旋转格必须换算：

```python
# core/crop.py 新增纯函数
def rotate_offset(ox_mm, oy_mm):
    """纸面偏移 → 旋转前偏移：顺时针 90° 时 x' = H-(y+h), y' = x。"""
    return oy_mm, -ox_mm
```

即 `dx_pre = +oy`、`dy_pre = -ox`。

旋转格落位映射必须从转置改为真旋转。当前 `render.py` 写的是
`dx, dy, dw, dh = dy, dx, dh, dw`，它只在落位居中时与 90° 旋转等价；偏移非零时会把水平偏移的
符号弄反。改为：

```python
if cell.rotated:
    # TH 为旋转前目标矩形高（即 target_h），与 crop 调用时传入的高一致
    dx, dy, dw, dh = (TH - dh) - dy, dx, dh, dw
```

居中情形验算：`dy = (TH - dh) / 2` 代入得 `x' = (TH - dh)/2 = dy`，与旧式一致，因此
`offset=(0,0)` 时新旧结果必须逐像素相同——这条写成回归测试。

偏移会被 `crop` 内部 clamp（裁框不得越出原图）。滑块推到端点而画面不再移动属正常物理结果，
不视为缺陷，界面不做额外提示。

## 6. 输出正确性：遮罩只出现在预览

现状证据：`cli.py` 调 `render_page` 未传 `show_mask`，默认 `True`，导致 `_mask_bands` 把物理
不可印区画成 150 灰 × alpha 110，叠白底后实测像素为 `(210, 210, 210)`；`_lab/out` 的 A4+3R 产
物四边即为此值。这些灰边会随页面一起打进相纸。

规定：

- 预览：`show_mask=True`（界面诚实性，让用户在打之前看到"这条边打不出来"）。
- 导出（GUI 的 PDF、CLI 的 `--out` 与 `--pdf`）：一律 `show_mask=False`。
- `cli.py` 增加调试开关 `--mask`，显式要求时才导出带遮罩的版本。
- 裁切线（`show_cut_lines`）在导出中保留：它是成品的一部分。
- `render_page` 的 `show_mask` 默认值保持 `True` 不改：`_lab/m1m2_check.py` 直接调 `render_page`
  而不经 CLI，其像素比对处已显式传 `show_mask=False`，因此本改动只影响 CLI/GUI 的输出分支。

## 7. 错误处理与状态反馈

| 场景 | 处理 |
|---|---|
| `core` 抛 `ValueError`（放不下 / 非法模式组合 / 未知尺寸） | 状态栏红字显示异常原文，不弹窗、不崩，导出按钮禁用 |
| 读图失败（文件被删、非图像、EXIF 转置异常） | 列表该项标红，状态栏列出文件名；异常在 `app/` 收敛，不外抛 |
| 渲染线程抛异常 | 通过信号回主线程，预览保留上一帧，状态栏显示错误原文 |
| 导出失败（无权限 / 磁盘满 / img2pdf 异常） | 状态栏 + 一次 `QMessageBox.warning` |
| `store.save()` 返回 `False` | 状态栏提示"本次设置未持久化"，不得静默丢弃 |
| `margin_source == "spec"` | 状态栏固定显示"依规格推定，未经真机校准" |
| 未捕获异常（含 Qt 槽内） | 全局钩子写 `%APPDATA%\PhotoPrint\error.log`，见第 9 节 |

## 8. 持久化：记住上次设置

- `last_job` 字段：`sheet_key`、`cell_key`、`mode`、`gap_mm`、`bleed_mm`、`dpi`、
  `offset_pct`（水平/垂直）、`out_dir`、`photo_paths`。
- `core/store.py` 新增两个方法：`get_last_job() -> dict`（缺字段返回 `{}`，形状错降级为
  `{}`）、`set_last_job(d: dict) -> None`（只写入 `raw["last_job"]`，不触碰 overrides 与
  user_sizes）。`_empty_raw()` 与 `load()` 已有 `last_job` 槽位与形状校验，沿用不改。
- 写盘时机：导出成功时、窗口关闭时。不做参数级防抖写盘。
- 启动时逐个校验 `photo_paths` 是否存在：存在的正常载入，缺失的在列表里标红并保留文件名，不
  阻塞其余项。

## 9. 打包：PyInstaller 单文件

- 入口是真实文件 `photoprint/app/__main__.py`（`python -m` 形式不能被 PyInstaller 当入口）；
  它只做三件事：装异常钩子、建 `QApplication`、进事件循环。
- 异常钩子：`sys.excepthook` + `threading.excepthook` 双钩，traceback 追加写入
  `%APPDATA%\PhotoPrint\error.log`（目录由 `store.default_path()` 的父目录推导，不另起一套路
  径规则），并在状态栏提示"已记录错误日志"。
- 打包参数：`--onefile --windowed --name PhotoPrint`。`PySide6` 的 `platforms/qwindows.dll`
  由 PyInstaller 官方 hook 自动收集；`img2pdf`、`Pillow` 需实测确认无遗漏。
- 新建 `requirements-build.txt` 写入 `pyinstaller`；`requirements.txt` 不动。
- 新建 `build_exe.ps1`（项目根）：建 venv → 装两份 requirements → 跑 PyInstaller → 打印产物
  路径与体积。
- 预期与已知代价：单文件约 100–180MB，冷启动 3–10 秒（解包临时目录）；无控制台，崩溃只留日
  志。
- 验证脚本 `_lab/check_exe.ps1`：构建 → 启动 exe → 断言进程存活且窗口标题正确 → 打印体积与启
  动耗时。属需手工比对类，按项目约定放 `_lab/`，输出进 `_lab/out/`。

## 10. 测试方案

新增脱机测试（全部进 `tests/`，不需要打印机、不需要窗口）：

- `test_jobs.py`：`build_jobs` 与重构前 `cli.build_plan_jobs` 同参数结果等价；0 格退化分支；
  `offset_pct` 原样透传到 `Job.render`（编排层不得自己换算成 mm）。
- `test_crop_rotate_offset.py`：`rotate_offset` 的轴与符号；**回归保护**——`offset=(0,0)` 时
  新落位映射与旧转置逐像素相同。
- `test_render_offset.py`：偏移传入后贴图位移方向正确；旋转格与非旋转格各一组；
  同一页两种朝向混排时必须逐格换算（拿首格或整纸尺寸算的写法都要被挡住）。
- `test_mask_export.py`：`show_mask=False` 时页面四边像素为纯白 `(255,255,255)`。
- `test_store_last_job.py`：读写往返、坏形状降级为 `{}`、`save()` 返回 `False` 的传播。
- `test_app_smoke.py`：`QT_QPA_PLATFORM=offscreen` 下构造主窗口、设参数、断言预览 QPixmap 非
  空、导出按钮使能状态正确。不引入 `pytest-qt`，直接手工驱动 Qt 对象。

约束：现有 145 项测试必须保持全绿；`cli.py` 重构不得改变其输出文案与 return code。

## 11. 验收标准

1. `python -m pytest tests/ -q` 全绿（145 + 新增）。
2. `python _lab/m1m2_check.py` 仍 12 条全 OK、exit 0。
3. `python -m photoprint.cli ... --pdf` 产物四边为纯白（无 210 灰边），`--mask` 时才带遮罩。
4. `build_exe.ps1` 产出的 `PhotoPrint.exe` 双击可开、能选图、能看预览、能出 PDF；崩溃时
   `error.log` 有 traceback。
5. 同一组照片与同一参数下，exe 导出的 PDF 与 CLI 导出的 PDF 页面像素一致（抽样比对首页）。

## 12. 遗留与后续

- 界面直打、驱动探测、M4 校准页：待有 G3800 真机后另立计划。
- 逐张裁切微调与拖拽编辑器：总设计第 8 节仍是依据，本设计不覆盖它。
- 内核计划遗留的 4 条不阻塞项（`--print` 异常收敛 `return 2`、`Store` 注入、契约测试文本匹
  配、`port` 形参清理）本设计不处理，其中 `Store` 注入会影响 `test_jobs.py` 的写法：本次以
  "测试内构造 `Store(path=临时路径)`"绕过，不改 `Store` 签名。
