# 驱动表单绑定（Driver Form Binding）设计

日期：2026-11-07　基线：`master` @ 8d7b077（文字叠加逐张已合入）
真机：Canon G3800（驱动名 "Canon G3000 series Printer"，端口 USB001，dpi 600×600）

## 0. 背景：三条真机实测结论（本节是全部决策的证据来源）

采证手段：`OpenPrinter → GetPrinter(2).pDevMode → 写 Fields|DM_PAPERSIZE → `
`DocumentProperties(DM_IN_BUFFER|DM_OUT_BUFFER) → CreateDC(devmode) → `
`GetDeviceCaps(PHYSICALWIDTH/HEIGHT)` **只读回读，不发任何打印作业**。

1. **`DeviceCapabilities(DC_PAPERSIZE)` 在本机驱动上恒不可用**。pywin32 返回 `270`
   （非 30 对），ctypes 直调 `winspool.drv.DeviceCapabilitiesW`、512 个 `POINT` 的大
   缓冲、真实端口 `USB001` 三种方式都试过，缓冲区**全为 0**。故 `probe.paper_sizes_mm`
   恒空不是解析写错，而是驱动不回。**尺寸只能靠逐表单实测得到。**
2. **30 个表单逐个实测总耗时 0.68s**，逐码实测尺寸稳定、可重复。即表单尺寸完全
   可以现场测，不需要任何硬编码表。
3. **本驱动拒绝程序化自定义尺寸**。写 `PaperSize=DMPAPER_USER(259)` +
   `PaperWidth/PaperLength` 后交回驱动校验，读回 `PaperSize=9`、
   `210.0×297.0mm`——被直接重置成 A4。三种尺寸（89×127、100×150、152×203）均如此。

### 0.1 实测表单尺寸（本机，单位 mm）

| 码 | 驱动表单名 | 实测物理尺寸 | 对应预设 | 判定 |
|---|---|---|---|---|
| 126 | `L 89x127mm` | 88.98 × 127.00 | 3R 89×127 | 精确命中 |
| 121 | `2L 127x178mm` | 127.00 × 177.97 | 5R 127×178 | 精确命中 |
| 123 | `13x18cm 5"x7"` | 127.00 × 177.80 | 5R 127×178 | 同纸异名，次选 |
| 122 | `10x15cm 4"x6"` | 101.60 × 152.40 | 4R 102×152 | 偏差 0.4/0.4 |
| 124 | `20x25cm 8"x10"` | 203.20 × 254.00 | 7R 203×254 | 精确命中 |
| 127 | `正方形 13x13cm 5"x5"` | 127.00 × 127.00 | SQ55 127×127 | 精确命中 |
| 125 | `Card 55x91mm 2.17"x3.58"` | 54.99 × 90.97 | CARD 91×55 | 精确命中（宽高互换） |
| 9 | `A4` | 209.97 × 296.97 | A4 | 精确命中 |
| 11 | `A5` | 148.00 × 209.97 | A5 | 精确命中 |
| 13 | `B5` | **181.99 × 256.96** | B5 **176×250** | **预设与驱动不符** |
| 1 | `Letter 22x28cm 8.5"x11"` | 215.90 × 279.40 | LTR | 精确命中 |
| 5 | `Legal 22x36cm 8.5"x14"` | 215.90 × 355.60 | LGL | 精确命中 |
| 20 | `信封 Com 10` | 104.73 × 241.30 | ENV_10 105×241 | 偏差 0.27/0.30 |
| 27 | `信封 DL` | 109.98 × 219.96 | ENV_DL 110×220 | 精确命中 |
| — | （无 152×203 表单） | — | 6R 152×203 | 无命中 |

### 0.2 已上线的真实缺陷（本次要修的）

用项目**现有生产代码**跑真机只读复验：

```
devmode.build(api, "Canon G3000 series Printer", 89.0, 127.0, None)
  → dm.PaperSize 回读 9（A4），实测 209.97×296.97
  → gdi_print.verify_physical_size(...) == False
```

即：**今天选 3R 直打必然在 `_emit` 里被判“驱动忽略了自定义尺寸”而中止**，一页都出
不来。换成表单码 126 后 `verify=True`、实测 88.98×127.00。6R 同理且无表单可退。

`B5` 是第二处：预设 176×250（ISO B5）与驱动 182×257（JIS B5，即 G3800 官方规格）
差 6–7mm，远超 `verify_physical_size` 的 0.5mm 容差。

## 1. 范围

做：

- 新增 `photoprint/win/forms.py`：逐表单**实测**尺寸（只读）、按尺寸匹配预设、
  给出绑定结果与偏差；纯编排、经 `api` 注入，全脱机可测。
- `photoprint/win/gdi_print.py`：`print_pages` 接受表单绑定，绑定命中则用真实
  **表单码**建 DEVMODE，并把**物理尺寸校验目标**切到该表单的实测尺寸；返回值带上
  绑定信息与"自定义尺寸被驱动重置"的明确原因。
- `photoprint/app/main_window.py`：打印前探测表单（异常静默降级），打印后的状态栏
  明示“已用驱动表单 X（实测 W×H）”或“驱动无匹配表单，按自定义尺寸提交”。
- `photoprint/cli.py`：`--print` 走同一探测（文案形状不变）。
- `photoprint/core/specs.py`：B5 校准为 182×257（依据 §0.1 实测 + G3800 官方规格）。
- `_lab/dump_driver_papers.py`：改用实测尺寸，并标出每个表单命中/未命中哪个预设。

不做（明确排除）：

- 不改 `modes`/装箱/渲染几何：排版仍按预设标称尺寸，绑定只在**打印阶段**决定用哪个
  表单码与校验目标（偏差上限 0.6mm/边，见 §3.3）。
- 不改 `origin` 语义（3R 仍是 `custom`：驱动表单存在与否随机器而变，属运行时事实）。
- 不做无边距探测/切换（表单实测偏移 3.39/2.96mm 是无边距关闭态，`5x5` 为 5.97mm；
  边距档位与 `margin_source` 升级留后续增量）。
- 不做 6R 的替代方案（无表单且驱动拒绝自定义尺寸，只能 A4 拼版或导出 PDF；本次只
  把失败原因说清）。
- 不改 `DeviceCapabilities(DC_PAPERSIZE)` 的既有语义（`probe.paper_sizes_mm` 可空）。

## 2. 决策

1. **尺寸来源 = 逐表单实测**，不用表单名解析、不用 `DC_PAPERSIZE`。名字里有
   `10x15cm 4"x6"` 这类双单位，按名解析会猜错（实测 101.6×152.4 而非 100×150）。
2. **测量口径**：`PaperSize=码` 建 DEVMODE → 驱动回填 → 回读 `PaperSize` **不等于**
   请求码则丢弃该条（驱动不认此码，不得编造尺寸）；再 `CreateDC(dm)` 读
   `PHYSICALWIDTH/PHYSICALHEIGHT ÷ LOGPIXELS×25.4`。
3. **匹配口径**：宽高**可互换**比对（卡片 55×91 对 91×55），逐边容差 `0.6mm`；
   多命中选择 `|Δw|+|Δh|` 最小者作稳定仲裁；并列时优先表单名含 `mm` 的（命名更精确，
   如 `2L 127x178mm` 优于 `13x18cm 5"x7"`），再按码升序。
4. **几何权威不变**：排版/渲染始终按 `spec.w_mm/h_mm`；绑定只决定①用哪个表单码
   ②物理校验拿什么当目标。偏差 ≤0.6mm 属驱动量化与命名换算误差，不得因此改版面。
5. **无匹配即退回现状**：沿用 `sheet.driver_paper_code`（可能为 None →
   `DMPAPER_USER`），并沿用标称尺寸做校验——行为与今天逐字一致（向后兼容红线）。
6. **失败要说因**：自定义尺寸被驱动重置（请求 `DMPAPER_USER` 但回读码变了）时，
   文案必须点名“本机驱动不接受程序化自定义尺寸”，而不是笼统的“驱动忽略了自定义尺寸”。

## 3. 接口

### 3.1 `photoprint/win/forms.py`（新模块，纯编排，无 win32 import）

```python
@dataclass(frozen=True)
class PaperForm:
    code: int
    name: str
    w_mm: float          # 实测物理宽
    h_mm: float          # 实测物理高
    def fits(self, w_mm, h_mm, tol_mm=MATCH_TOL_MM) -> bool: ...

MATCH_TOL_MM = 0.6

def measure(api, printer, codes=None) -> list[PaperForm]:
    """逐表单码实测尺寸；取不到名字/码或驱动不认码的条目跳过；单条失败不影响其余。"""

def find(forms, w_mm, h_mm, tol_mm=MATCH_TOL_MM) -> PaperForm | None:
    """按尺寸（宽高可互换）找绑定表单；确定性仲裁见 §2.3。"""

def binding_note(form) -> str:
    """界面文案：如「已用驱动表单 L 89x127mm（实测 88.98×127.0mm）」。"""
```

### 3.2 `gdi_print.print_pages(api, printer, images, sheet, dpi, *, prompt=True, forms=None)`

- `form = forms.find(...)` 命中 → `paper_code = form.code`；否则 `paper_code =
  sheet.driver_paper_code`（可能 None）。
- `devmode.build_with_prompt(..., paper_code, prompt=...)` 不变。
- 校验目标：命中表单时为 `(form.w_mm, form.h_mm)`；否则 `(sheet.w_mm, sheet.h_mm)`。
- 成功时 `res["paper_form"] = {"code", "name", "w_mm", "h_mm"}`（未命中则不含该键，
  保证既有返回值逐字不变）。
- 自定义尺寸被重置（`paper_code in (None, DMPAPER_USER)` 且建出的 `dm.PaperSize`
  变了）→ 失败文案追加“本机驱动不接受程序化自定义尺寸，请改用驱动自带表单或导出 PDF”。
- `print_job(..., forms=None)` 同口径转发（CLI 冻结入口，默认不传 = 旧行为）。

### 3.3 容差取 0.6mm 的依据

本机实测偏差：3R 0.02、7R 0.00–0.20、5R 0.03–0.20、4R 0.40、ENV_10 0.30；
下一个更大的错配是 6R 对 `10x15cm`（50.4mm）与 B5 对 ISO（6mm）。0.6mm 落在“同纸
异名”与“不同纸”之间，且小于 G3800 官方给的 3.4mm 边距一个量级，不会跨过纸种。

## 4. 错误处理

| 场景 | 处理 |
|---|---|
| `EnumPrinters`/`DeviceCapabilities` 失败 | `measure` 返回 `[]`；打印退回旧行为，不崩 |
| 某表单码建 DC 失败 / 驱动不认该码 | 该条跳过，其余照测 |
| 无匹配表单 | 用 `sheet.driver_paper_code`；校验仍对标称尺寸（= 今天行为） |
| 自定义尺寸被驱动重置 | 失败文案点名原因（§2.6），并给出“导出 PDF”兜底 |
| 驱动表单实测尺寸落在容差内但排版标称略异 | 照打，界面明示实测尺寸，不改版面 |
| 探测耗时 | 30 表单 0.68s，仅在点“打印”时做一次；不做缓存（缓存会让“改了驱动设置”读旧值） |

## 5. 测试方案（全脱机，FakeApi 注入）

`tests/test_driver_forms.py`（新）：

- `measure` 按码建 DEVMODE+DC 并回读 `PHYSICALWIDTH/HEIGHT ÷ dpi ×25.4`，尺寸与
  FakeApi 给的一致；`calls` 含 `delete_dc`（不得漏删 DC）。
- 驱动不认码（回读 `PaperSize != code`）→ 该条被丢弃。
- 单码 `create_dc` 抛异常 → 其余照测、不抛。
- `find` 宽高互换命中（91×55 对 55×91）。
- `find` 在两个几乎同尺寸表单间按 `|Δ|` 选 121 而非 123；并列时选名字含 `mm` 者。
- `find` 超容差返回 None（6R 152×203 对 101.6×152.4、B5 182×257 对 176×250）。

`tests/test_gdi_print_media.py`（扩）：

- 命中表单 → `build_with_prompt` 收到的是 `126` 而非 `None`；校验目标是表单实测尺寸。
- 未命中 → 传 `sheet.driver_paper_code`，校验目标为标称（等于旧行为）。
- 不回传 `paper_form` 键时既有断言原样成立（冻结口径）。
- 自定义尺寸被重置 → 失败文案含“不接受程序化自定义尺寸”。

`tests/test_app_main_window.py`（扩）：打印前探测被调用、成功后状态栏含表单名、
探测抛异常时仍能打印（降级）。

`tests/test_specs.py`（扩）：B5 == 182×257（钉住校准值）。

## 6. 验收标准

1. `python -m pytest -q` 全绿（现有 393 + 新增）。
2. 真机只读复验脚本（`_lab/check_driver_forms.py` 或 `dump_driver_papers.py`）：
   3R/4R/5R/7R/SQ55/CARD/A4/A5/LTR/LGL/ENV_* 全部命中，6R 明确“无匹配表单”。
3. 真机打印一张 3R 测试页：不再报“驱动忽略了自定义尺寸”，实际纸张为 89×127。
   **（需用户批准后才发作业，属唯一有物理副作用的步骤。）**
4. B5 直打不再因 6–7mm 偏差中止。
