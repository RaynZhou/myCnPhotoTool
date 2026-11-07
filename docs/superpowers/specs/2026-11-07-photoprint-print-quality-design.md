# 打印质量档：介质类型 + 打印质量（设计）

状态：已完成（T1–T7），2026-11-07。
上一轮：`2026-11-07-photoprint-driver-form-binding-design.md`（驱动表单绑定）。

## 0. 真机实测证据（本机 Canon G3000 series / G3800，只读，未发作业）

### 0.1 驱动提供了什么

```
DeviceCapabilities(DC_MEDIATYPENAMES=34) -> 15 个名字
DeviceCapabilities(DC_MEDIATYPES=35)     -> 15 个数值（与名字逐一对应）

1   普通纸                 303 高级光面照片纸 II      315 Photo Paper Pro Luster
295 亚高光泽照片纸         320 光面照相纸              284 Matte Photo Paper
263 信封                   322 Ink Jet Hagaki (A)      283 Ink Jet Hagaki
323 Hagaki K (A)           307 Hagaki K                324 Hagaki (A)
262 Hagaki                 271 高分辨率纸              291 其他照片纸

DeviceCapabilities(DC_BINS=6)     -> (7,)
DeviceCapabilities(DC_BINNAMES=12)-> ('后端托盘',)
```

默认 DEVMODE：`MediaType=1`（普通纸）、`PrintQuality=-3`（DMRES_MEDIUM）、
`Color=2`、`DefaultSource=7`、`Scale=100`、`Orientation=1`。

### 0.2 什么被接受、什么被夹回

| 试探 | 结果 |
|---|---|
| `MediaType` 设 0…259 | 全部夹回 `1`（这些不是有效值） |
| `MediaType` 设 1/303/315/295/320/284/263/322/283/323/307/324/262/271/291 | **全部精确回读** |
| `PrintQuality` 设 0…5、600、1200 | 夹回 `-3` |
| `PrintQuality` 设 `-1`/`-2` | 夹回 `-2` |
| `PrintQuality` 设 `-4` | **回读 -4**（DMRES_HIGH） |
| `DefaultSource` 设 4/6/7/14/256…258 | 全部夹回 `7`（本机只有一个纸盒） |

### 0.3 两处顺序陷阱（决定实现形状）

1. **介质变了，驱动会把质量重算回 -3**：介质与质量写在同一次
   `DocumentProperties(DM_IN_BUFFER|DM_OUT_BUFFER)` 里，质量丢；先写介质
   （一次 update）、再写质量（再一次 update），两者都钉住。
2. **介质/质量不影响纸张几何**：`MediaType=303`+`Quality=-4`+表单 126 →
   仍 `88.98×127.00mm`、偏移 `3.39/2.96mm`、`600×600dpi`，`PaperSize=126`
   保持不变。表单实测（3R/4R）也不随介质变。

### 0.4 `dmFields` 位常量：仓库从 Win32 头文件抄错了一位

| 名字 | 仓库现值 | 真值（`win32con`） | 仓库现值实际等于 |
|---|---|---|---|
| `DM_PAPERSIZE` | `0x200` | `0x2` | `DM_DEFAULTSOURCE` |
| `DM_PAPERLENGTH` | `0x400` | `0x4` | `DM_PRINTQUALITY` |
| `DM_PAPERWIDTH` | `0x800` | `0x8` | `DM_COLOR` |
| `DM_DEFAULTSOURCE` | `0x1000` | `0x200` | `DM_DUPLEX` |
| `DM_SCALE` | `0x1` | `0x10` | `DM_ORIENTATION` |
| `DMBIN_USER` | `4` | `256` | `DMBIN_MANUAL` |

真机上三种位组合（SDK / 仓库值 / 一位不设）结果**完全一致**——
本驱动不看 `dmFields`，所以这个错误一直没有症状。但别的驱动会看，且
新字段（`DM_MEDIATYPE=0x02000000`、`DM_PRINTQUALITY=0x400`）必须写对位，
否则就是"在错误的位上表达正确的意图"。故本轮一并订正，并以 `win32con`
对拍写成测试。

## 1. 范围

做：

- `photoprint/win/devmode.py`：`dmFields` 位常量按 `win32con` 订正；
  `build_with_prompt` 接受 `media` / `quality`，先介质、后质量，两遍写入。
- 新增 `photoprint/win/media.py`：枚举驱动介质（名字↔值），按名字/值查找，
  质量档位（驱动默认 / 高），生成状态栏文案。纯编排、经 `api` 注入，全脱机可测。
- `photoprint/win/gdi_print.py`：`print_pages` / `print_job` 透传 `media` / `quality`。
- `photoprint/app/main_window.py`：打印面板新增“介质类型”“打印质量”两个下拉，
  打印后状态栏明示实际生效的介质与质量。
- `photoprint/cli.py`：`--media-type`（名字或数值）与 `--quality {default,high}`；
  不传时 stdout 与今天逐字一致。
- `_lab/dump_driver_papers.py`：追加介质类型/纸盒/默认质量段，便于换机器复验。

不做（明确排除）：

- 不做无边距探测/切换（上一轮已列为不做，仍不做）。
- 不做墨量强度、ICM/色彩意图、`YResolution` 档位、彩色/黑白、双面。
- 不做纸盒选择：本机 `DC_BINS` 只有一个（后端托盘 = 7），写任何值都被夹回 7；
  代码继续沿用现有 `DefaultSource` 写入（会被驱动归一），不新增纸盒 UI。
- 不提供"自动按介质推断质量"：两者各自独立显式选择，默认都不干预。

## 2. 决策

1. **默认不干预**：`media=None`、`quality=None` 时 DEVMODE 与今天逐字节同形，
   命令行输出逐字同句（向后兼容红线）。
2. **介质用驱动的名字驱动**：枚举 `DC_MEDIATYPENAMES` + `DC_MEDIATYPES` 配对，
   GUI 直接显示驱动给的名字，不硬编码 Canon 的 303/320。
3. **质量只给两档**：`驱动默认`（不动字段）与 `高`（`DMRES_HIGH = -4`）。
   证据见 §0.2：`-1/-2` 被夹回 `-2`、正值被夹回 `-3`，`-4` 是唯一可用的更高档。
4. **写入顺序固定**：介质一次 update → 质量再一次 update（§0.3 第 1 条）。
   只设其中一个时只写一遍。
5. **弹窗优先**：`prompt=True` 时介质/质量在弹驱动页**之前**写入，
   让设置页显示我们的选择；用户若在页内改介质，以用户为准（弹窗后只重钉纸张几何，
   与既有 W-2 一致）。
6. **失败不阻断打印**：枚举失败 → 下拉只有“驱动默认”；写入异常 → 打印照旧进行
   （介质是画质增强，不是打印前置条件）。

## 3. 接口

```python
# photoprint/win/media.py
QUALITY_DEFAULT = None          # 不写字段
QUALITY_HIGH = -4               # DMRES_HIGH

@dataclass(frozen=True)
class MediaOption:
    value: int          # dmMediaType 的真实数值（驱动给什么就是什么）
    name: str           # 驱动名（'高级光面照片纸 II' / 'Photo Paper Pro Luster' …）

def enumerate_media(api, printer) -> list[MediaOption]
def find_media(options, query) -> MediaOption | None   # int 按值，str 先全等再包含
def apply(dm, media=None, quality=None) -> bool        # 只写字段与位，不做 update
def note(media, quality) -> str                        # '介质 高级光面照片纸 II · 质量 高'
```

`devmode.build_with_prompt(api, printer, w_mm, h_mm, paper_code=None, prompt=False,
media=None, quality=None)`：几何 →（`media.apply` → update）→（`media.apply` → update）
→（可选弹窗）→ 只重钉几何。返回值形状不变，仍 `(dm, size, degraded)`。

`gdi_print.print_pages(..., media=None, quality=None)`、`print_job(..., media=None,
quality=None)`：透传；`media`/`quality` 都为 `None` 时调用形状与返回值与今天一致。

## 4. 错误处理

- `enumerate_media` 任何异常/空表 → `[]`（GUI 下拉退化为只有“驱动默认”）。
- `find_media` 查不到 → `None`（等价于不干预）。
- `apply` 写字段失败（无该属性）→ 返回 `False`，调用方跳过该字段，不抛。
- `build_with_prompt` 的介质/质量写入异常 → 吞掉并继续（打印不因此中止），
  但保留弹窗取消（`PromptCancelled`）与几何校验的既有语义。

### 4.1 已知局限（诚实记账）

- `media_note` 报的是**我们写进 DEVMODE 的值**。GUI 走 `prompt=True` 时，用户
  可在驱动设置页内改介质/质量，以用户为准，此时状态栏这句会与实际出片不一致。
- 不做回读比对：回读值反查名字依赖“这台驱动当时枚举出的表”，换驱动后名字可能
  对不上；宁可报“设了什么”，也不拿枚举表去猜“驱动最后用了什么”。

### 4.2 GUI 直打（默认不弹驱动设置页）

几何、介质、质量问题全部能由面板钉进 DEVMODE 之后，驱动设置页从“必要条件”
降为“想改无边距/灰度这类驱动私有开关时才需要”。所以：

- GUI 默认 `prompt=False`：点“打印”直接出纸，与 CLI（一直是 `prompt=False`）
  行为对齐。
- 面板底部一个「打印前打开驱动设置页」开关，默认不勾；勾上才走旧弹窗路径。
  勾选状态随 `last_job` 落盘，下次启动保持。
- 不勾时 `degraded`/`cancelled` 分支自然不会发生，状态栏只报“已发送”与表单/
  介质信息。

## 5. 测试

`tests/test_win32_contract.py`（扩）：位常量与 `win32con` 对拍（含 `DMBIN_USER`）。

`tests/test_media_options.py`（新）：FakeApi 返回名字/数值对 → 枚举配对；按值/全等/
包含查找；查不到 None；`note` 文案；`apply` 写入的字段与位；缺属性时返回 False。

`tests/test_devmode.py`（扩）：两遍写入顺序（介质 update → 质量 update，日志顺序钉死）；
只设其一时只写一遍；`prompt=True` 时写入发生在弹窗之前；弹窗后不重写介质/质量；
`media=None, quality=None` 时 update 次数与今天一致。

`tests/test_gdi_print_media.py`（扩）：`print_pages` 把 media/quality 交给
`build_with_prompt`；两者都 None 时调用形状逐字不变。

`tests/test_app_print_media.py`（扩）：下拉选中项进入打印调用；状态栏含介质名与质量档；
枚举抛异常时仍能打印；默认 `prompt=False` 直打、勾上开关才是 `True`、开关状态
落盘后能恢复。

`tests/test_cli.py`（扩）：`--media-type 高级光面照片纸 II`/`--media-type 303`/
`--quality high` 传到 `print_job`；不传时 stdout 逐字不变（既有断言即回归锁）。

## 6. 验收标准

1. 全量回归绿（421 + 新增），无 `MUTATION-TEMP` 残留。
2. 真机只读复验：`MediaType=303` + `Quality=-4` + 表单 126 →
   `PaperSize=126`、`88.98×127.00mm`、`600dpi`（本机已实测）。
3. 真机打印一张 3R 相纸（**需用户批准**）：选择介质“高级光面照片纸 II”后，
   出片墨量明显比“普通纸”更足（颜色更深、无水痕）。
4. 不选介质/质量时，打印行为与上一轮逐字相同（含 CLI 输出、状态栏文案形状）。
