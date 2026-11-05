# App 内直打 + 介质类型选择（打印增量）设计

日期：2026-11-05　基线：`master` @ 40e33f4（逐图旋转已整枝合入）
分支：`feat/photoprint-print-media`

## 0. 背景与决策来源

用户实测：当前"导出 PDF → 用外部阅读器打印"出的照片，与佳能官方 App 打印同一张
照片仍有观感差异。定位差异来源不是排版/像素（拼版已由 `check_gui_cli_parity.py`
逐像素证明一致），而是**打印介质类型（Media Type）不同**——驱动按介质套不同的墨量
与色彩表（ICC/优化曲线）。佳能 App 打印时会自动选定照片纸介质并套用其色彩；当前
流程没有介质选择入口，PDF 落进阅读器后多半停在"普通纸"或上一个驱动默认介质。

**关键事实（已核实代码）**：

1. GUI 当前**只有「导出 PDF…」**（`main_window.py`），无 App 内直打；PDF 交给外部
   阅读器打印后，介质下拉在那个阅读器/驱动弹窗里，本程序进程**够不着**。
2. 程序里已有 GDI 直打（仅挂 `cli.py --print`），`devmode.py` **故意继承**驱动的
   "介质类型/无边距"私有开关（注释第 5 行）——取驱动默认 DEVMODE 再只改纸张几何。
3. 佳能的"介质类型"落在 DEVMODE 的**驱动私有扩展区**（本机 `DocumentProperties`
   回报总长 5428 字节，含私有区），布局无公开文档、随驱动版本变；程序化写它极脆、
   且本机未连 G3800 无法验证。

与用户逐问确认的决策（本文档不重开）：

1. 目标 = **在 App 内能选介质且真正生效**；
2. 实现范式取**方案 A**：点打印时弹**驱动自己的设置页**（`DocumentProperties` +
   `DM_PROMPT`），用户在其中选介质，回填的 DEVMODE 携带介质选择（私有区由驱动填、
   我们不解析），再据此走 GDI 直打。否决方案 B（自绘介质下拉写私有字节，脆弱不可验）
   与方案 C（XPS/Print Schema，工程量大、收益不比 A 高）；
3. **打印范围**：点打印即打**全部页**（拼版本就是整版产出；"仅当前页/自定义区间"
   经评审按 YAGNI 砍掉，待真实需求再立增量）；
4. **驱动设置页时机**：每次点打印都弹；
5. **范围限于 GUI**，`cli.py` 行为保持逐字冻结、不改动。

本文档决策完备：实现者不需再做产品选择。

## 1. 范围

做：

- `win/api.py`：`RealWinApi` 新增 `prompt_devmode(handle, printer, dm)`——用
  `DocumentProperties(fMode=DM_IN_BUFFER|DM_OUT_BUFFER|DM_PROMPT)` 弹驱动设置页，
  返回用户确认后的 DEVMODE；`FakeApi` 同名方法原样返回入参 dm（脱机不弹窗）。
- `win/gdi_print.py`：把"准备 DEVMODE + 弹窗"与"用给定 DEVMODE 打印"拆成两步，
  新增 `print_pages(api, printer, images, sheet, dpi)`：`build` 纸张几何 → `prompt`
  介质 → 重新盖回纸张几何 → `CreateDC` → `verify_physical_size` → 逐页 StretchBlt。
- `app/main_window.py`：加**打印机下拉**（`enum_printers` 填充）+ **「打印…」按钮**；
  点打印走 win 层直打**全部页**，沿用 `_on_export` 调 win 的模式。
- 相应脱机测试（FakeApi 管道）与桌面验收步骤。

不做（明确排除，实现时不得顺手加）：

- 自绘介质类型下拉、程序化解析/写 DEVMODE 私有字段（方案 B，已否决）。
- 在 PDF 里嵌入介质/ICC 提示或色彩管理（PDF 导出路径不改）。
- CLI `--print` 的任何改动（含新开关）——逐字冻结。
- 无边距开关的界面化（仍由驱动设置页内选，继承即可）。
- 打印预览缩略图、后台打印队列、双面/份数等驱动项——一概交驱动页，不自建。
- 记住上次介质选择、默认不弹直打（本次定为每次都弹，不做偏好持久化）。
- 页码范围选择对话框（仅当前页 / 自定义区间）——点打印即打全部页，YAGNI 砍掉。

## 2. 语义模型与不变量

**介质选择的所有权**：介质类型自始至终由**驱动**持有与解释。本程序不读取、不假设、
不写入 DEVMODE 私有区里"哪个字节是介质"。我们唯一做的是把用户确认过的 DEVMODE
原样交给 `CreateDC`。这是方案 A 成立、且不随驱动版本碎裂的根基。

**纸张几何权威（核心不变量 I-1）**：

> 我们的自定义纸张尺寸（A4/3R 等，由 `devmode.modify` 写入 `PaperSize/PaperWidth/
> PaperLength/Scale`）在驱动弹窗**之前**写入一次、并在弹窗**之后**再盖回一次；
> 最终交给 `CreateDC` 的 DEVMODE，其纸张几何字段必须等于本工具请求的尺寸，与用户在
> 弹窗里对纸张做的任何改动无关。

理由：弹窗返回的 dm 可能把自定义尺寸重置成驱动已存表单名；介质活在私有区不受盖写
影响，故"盖回纸张几何"既保住尺寸、又保住用户选的介质。实现上即"弹窗后再次
`modify(dm, ..., w_mm, h_mm, paper_code)`"，且 `modify` 不得触碰私有区（现状已如此）。

**渲染等价（不变量 I-2）**：打印送出的每一页图，与预览/导出同源——
`images = render_all(job, dpi, show_mask=False)`，其中 `job` 由 `_rebuild_job` 依当前
控件值（含 `photo_rotations`）构建。故旋转、偏移、裁切模式对打印自动生效，打印路径
不引入第二套渲染。`show_mask` 必须为 False（灰遮罩是调试用，不得进相纸）。

**打印 dpi**：渲染固定 300（与导出同），送图时 StretchBlt 交驱动放大（受
`gdi_print.py` 既有的内存纪律约束，不新增高分辨率直出路径）。

## 3. 接口改动

```python
# win/api.py —— 唯一 import win32 的层
class RealWinApi:
    def prompt_devmode(self, handle, printer, dm):
        """弹驱动设置页（含介质类型），返回用户确认后的 DEVMODE。"""
        # DocumentProperties(0, handle, printer, dm, dm,
        #     DM_IN_BUFFER | DM_OUT_BUFFER | DM_PROMPT)
        ...

class FakeApi:            # tests
    def prompt_devmode(self, handle, printer, dm):
        return dm         # 脱机不弹窗，原样回传

# win/gdi_print.py
def print_pages(api, printer, images, sheet, dpi, *, prompt=True):
    """build 纸张几何 → prompt 选介质 → 盖回几何 → CreateDC → 校验物理尺寸 →
    逐页 StretchBlt。返回 {'ok','pages','message'}；任何异常转 message 不外抛。"""
    ...
```

- 旧 `print_job` 保留或改为薄封装转调 `print_pages`（`prompt=False` 即等价旧行为），
  以免 `cli.py --print` 行为漂移——**`cli.py` 一字不改**，它调到的入口在 `prompt=False`
  下与现状逐字段等价。
- `prompt_devmode` 的 `DM_PROMPT` 常量取自 `win32con`（与既有 fMode 常量同源）。

## 4. 界面

- **打印机下拉**：`__init__` 构建时调 `api.enum_printers()` 填充；空列表时置灰并提示
  "未检测到打印机"。默认选中系统默认打印机（取不到就选第一项）。脱机 `FakeApi` 返回
  固定两台。填充失败（win32 异常）→ 下拉留空、不崩、状态栏提示。
- **「打印…」按钮**（objectName `print_btn`，与 `rotate_btn`/`export_btn` 同风格）：
  启用条件同导出（job 有效才允许）。点击流程：
  1. 同步 `_rebuild_job` 出最新 job。
  2. `images = render_all(job, PRINT_DPI, show_mask=False)`——**全部页**，不切片。
  3. `api = RealWinApi()`；`gdi_print.print_pages(api, 选中打印机, images, job.sheet,
     PRINT_DPI, prompt=True)`。
  4. 返回 `ok` → 状态栏"已发送 N 页到 <打印机>"（N=`job.page_count`）；否则红字 `message`。
- 打印期间置等待光标；打印是用户显式发起、且中间本就有一个模态驱动弹窗，故走
  同步执行即可，不接异步线程（避免与模态对话框的线程交互复杂化）。异常一律被
  `print_pages` 兜成 message，UI 不外抛（窗口化 exe 无控制台）。

## 5. 错误处理

| 场景 | 处理 |
|---|---|
| 未选打印机 / 无打印机 | 下拉置灰 + 提示，「打印…」禁用或点击即提示，不发起 |
| 驱动不支持 `DM_PROMPT` 弹窗报错 | 降级为按继承介质直打（`prompt=False` 语义）并状态栏提示"未能打开驱动设置页，已用驱动当前介质" |
| 用户在驱动页点了取消 | 视为放弃打印，不发作业、状态栏"已取消" |
| 驱动忽略自定义尺寸（`verify_physical_size` 不过） | 中止，红字沿用现有文案，指向"驱动内建同名表单或改用 PDF 导出" |
| 打印阶段任何异常 | `print_pages` 兜成 `{ok:False,message}`，UI 红字显示，不崩、不闪退 |

## 6. 测试方案（脱机 `offscreen`，进 `tests/`）

**可脱机验证的是管道，不是驱动真身。** 断言围绕"数据与控制流的正确交接"：

- `test_gdi_print_media.py`（FakeApi）：
  - `print_pages(prompt=True)` 调用序：`build`（写几何）→ `prompt_devmode` → 再次
    `modify` 盖回几何 → `create_dc` 收到的 dm，其 `PaperWidth/PaperLength` 等于请求
    尺寸（**即便 `FakeApi.prompt_devmode` 故意把几何改坏，也必须被盖回**——这是
    I-1 的变异牙，用会篡改 dm 的 FakeApi 才测得出）。
  - `prompt_devmode` 确实被调一次（计数哨兵）；`prompt=False` 时不调（守护 CLI 等价）。
  - `images` 为空 / `create_dc` 抛异常 / `verify_physical_size` 不过 → 返回
    `ok=False` 且带 message，**不抛异常**。
- `test_app_print_media.py`（FakeApi，`main_window`）：
  - 打印机下拉由 `enum_printers` 填充；`enum_printers` 抛异常时下拉为空且不崩。
  - 点打印 → 送出的 `images` 数 = `job.page_count`（全部页），且渲染取自
    `render_all`（含当前 `photo_rotations`，用方向可辨横图断言打印图非空、页数对）。
  - `print_pages` 返回 `ok=False` → 状态栏红字；`ok=True` → 正常色提示。
  - 全程异常安全：让 FakeApi 的 `prompt_devmode`/`create_dc` 抛错，点打印不外抛。
- 既有 `test_cli_frozen`、`_lab/m1m2_check.py`、`_lab/check_gui_cli_parity.py`
  必须不改仍绿（证明 CLI 与导出路径零回归）。

**只能真机验收（用户在连了 G3800 的桌面做）**：驱动设置页里 8 个介质选项确实出现、
选不同介质出片色彩/墨量随驱动变化、与佳能 App 比色接近。此环境未连打印机，无法验证。

## 7. 验收标准

1. `python -m pytest tests/ -q` 全绿（现有 + 新增）。
2. `python _lab/m1m2_check.py` 仍全 OK、exit 0。
3. `python _lab/check_gui_cli_parity.py` 仍 OK（CLI/PDF 路径不受影响）。
4. 手工核对（真机，用户）：GUI 选照片与纸张 → 点「打印…」→ 驱动页出现且能选
   "高级光面照片纸 II"等介质 → 打印出片，与同介质下佳能 App 观感一致；驱动页选
   取消则不打印；自定义 3R 尺寸仍被正确打出（I-1 生效）。

## 8. 遗留与后续

- 若将来要做"记住介质/默认不弹"（偏好持久化），需另立增量并解决 DEVMODE 私有区
  的存取序列化——本增量明确不做（第 1 节）。
- 若驱动页在某些 Windows/驱动组合下 `DM_PROMPT` 不可用，第 5 节已给降级路径；届时
  可评估方案 C（Print Schema）作为增强，不在本增量预埋。
