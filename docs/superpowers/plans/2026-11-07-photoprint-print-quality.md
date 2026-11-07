# Implementation Plan: 打印质量档（介质类型 + 打印质量）

设计见 `docs/superpowers/specs/2026-11-07-photoprint-print-quality-design.md`。
基线（须保持）：不传 `media`/`quality` 时，DEVMODE 内容、CLI stdout、状态栏文案
形状与上一轮逐字一致。

红线：
- 分层：几何/换算在 core；win 只做 win32 薄封装与 DEVMODE 编排；app/cli 只汇参数。
- 物理副作用：除 Task 7 的可选打印外一律只读；打印测试页须先得用户批准。
- PowerShell 用 `;`；提交消息走 UTF-8 无 BOM 文件 + `git commit -F`。

---

### Task 1: devmode 位常量按 win32con 订正

**Files:** Modify `photoprint/win/devmode.py`；Test `tests/test_win32_contract.py`

- [ ] **Step 1** 追加失败测试：`devmode` 的 `DM_PAPERSIZE / DM_PAPERLENGTH /
  DM_PAPERWIDTH / DM_DEFAULTSOURCE / DM_SCALE / DM_MEDIATYPE / DM_PRINTQUALITY`
  逐个与 `win32con` 同名常量相等；`devmode.DMBIN_USER == win32con.DMBIN_USER (256)`。
- [ ] **Step 2** 跑 `tests/test_win32_contract.py` 确认红（现值整体错位一位）。
- [ ] **Step 3** 改常量并加注释说明「旧值整体错位，真机驱动不看 dmFields 故无症状」。
- [ ] **Step 4** 跑 `tests/test_devmode.py` + `test_win32_contract.py` 全绿
  （既有断言按符号引用，不随数值变）。
- [ ] **Step 5** 变异验牙：把 `DM_SCALE` 改回 `0x1` → 对拍用例红。
- [ ] **Step 6** 提交（`win/devmode: dmFields 位常量按 win32con 订正（旧值整体错位一位）`）

---

### Task 2: win/media.py — 介质枚举 + 查找 + 质量档

**Files:** Create `photoprint/win/media.py`；Test `tests/test_media_options.py`

接口（见 spec §3）：`MediaOption`、`QUALITY_DEFAULT/QUALITY_HIGH`、
`enumerate_media(api, printer)`、`find_media(options, query)`、
`apply(dm, media=None, quality=None)`、`note(media, quality)`。

- [ ] **Step 1** 写失败测试（全脱机 FakeApi）：
  - 枚举：`device_caps(printer, 35)`→`(1, 303)`、`(34)`→`('普通纸','高级光面照片纸 II')`
    → `[MediaOption(1,'普通纸'), MediaOption(303,'高级光面照片纸 II')]`；两表长度不等时
    按短表截断；任一调用抛异常→`[]`。
  - 查找：`303`→按值；`'高级光面照片纸 II'`→全等；`'照片纸'`→包含（返回首个）；
    `''`/`None`/查不到→`None`。
  - `apply`：写入 `MediaType`/`PrintQuality` 与对应 `Fields` 位；`media=None` 不动介质、
    `quality=None` 不动质量；返回是否写成功；dm 缺属性→`False` 且不抛。
  - `note`：含介质名与「质量 高」；都 None→`''`。
- [ ] **Step 2** 跑测试确认红。
- [ ] **Step 3** 实现（纯编排，经 api 注入，不 import win32）。
- [ ] **Step 4** 跑 `tests/test_media_options.py` 全绿。
- [ ] **Step 5** 变异验牙三处：枚举错位配对、`find_media` 去掉包含回退、`apply` 少写位
  —— 各转红后还原。
- [ ] **Step 6** 提交（`win/media: 驱动介质枚举/查找 + 质量档（含测试）`）

---

### Task 3: devmode 两遍写入（介质→质量）

**Files:** Modify `photoprint/win/devmode.py`；Test `tests/test_devmode.py`

- [ ] **Step 1** 追加失败测试：
  - `build_with_prompt(..., media=303, quality=-4)`：`api.mode_log` 里 `"update"`
    出现两次，且第一次的 dm 已带 `MediaType=303`、第二次带 `PrintQuality=-4`
    （用记录 dm 快照的 FakeApi 断言顺序）。
  - 只传 `media` → 只多一次 update；只传 `quality` → 多一次 update 且不动 `MediaType`。
  - 两者都 `None` → update 次数与既有断言相同（1 次）。
  - `prompt=True` 且带 media/quality：写入发生在 `prompt_devmode` 之前；
    弹窗后不再重写介质/质量（日志里 prompt 之后没有 media 字段变化）。
  - 介质写入抛异常（FakeApi 让第二次 update 炸）→ 仍返回 dm、`degraded` 语义不变、
    不外抛。
- [ ] **Step 2** 跑测试确认红。
- [ ] **Step 3** 实现：几何 → `media.apply`+update（若 media）→ `media.apply`+update
  （若 quality）→ 弹窗 → 只重钉几何（`default_source=False`）。
- [ ] **Step 4** 跑 `tests/test_devmode.py` + `test_gdi_print_media.py` 全绿。
- [ ] **Step 5** 变异验牙：把两遍合成一遍 → 「质量丢失」用例红；把写入挪到弹窗后 →
  「弹窗优先」用例红。
- [ ] **Step 6** 提交（`win/devmode: 介质先于质量的两次写入（驱动会重算质量默认值）`）

---

### Task 4: gdi_print 透传 media/quality

**Files:** Modify `photoprint/win/gdi_print.py`；Test `tests/test_gdi_print_media.py`

- [ ] **Step 1** 追加失败测试：`print_pages(..., media=303, quality=-4)` 时
  `build_with_prompt` 收到这两个参数；两者都 None 时调用形状（位置参数+关键字）
  与今天一致（既有 9 条断言即回归锁，不改）。
- [ ] **Step 2** 跑测试确认红。
- [ ] **Step 3** 实现：`print_pages(..., media=None, quality=None)` 透传；
  `print_job(..., media=None, quality=None)` 透传；成功时把生效档位放进返回值
  （`res["media_note"]`），未设置时不加该键（返回值形状不变）。
- [ ] **Step 4** 跑 `tests/test_gdi_print_media.py` 全绿。
- [ ] **Step 5** 变异验牙：不透传 media → 用例红。
- [ ] **Step 6** 提交（`win/gdi_print: 透传介质类型与打印质量`）

---

### Task 5: app 面板两个下拉 + 状态栏明示

**Files:** Modify `photoprint/app/main_window.py`；Test `tests/test_app_print_media.py`

- [ ] **Step 1** 追加失败测试（沿用既有 FakeApi 注入）：
  - 面板存在“介质类型”“打印质量”两个 `QComboBox`；介质的第 0 项是“驱动默认”，
    其后是驱动给的名字；`enumerate_media` 抛异常时只剩第 0 项且能正常打印。
  - 选中介质/质量后，打印调用收到对应 `media`/`quality`。
  - 状态栏含介质名与“质量 高”；都不选时文案与今天相同（既有断言即回归锁）。
- [ ] **Step 2** 跑测试确认红。
- [ ] **Step 3** 实现：初始化时 `enumerate_media` 填充（异常静默）；`_on_print` 取选中值
  → `print_pages(..., media=, quality=)`；成功文案按 `media.note` 追加。
- [ ] **Step 4** 跑 `tests/test_app_print_media.py` + `tests/test_app_main_window.py` 全绿
  （offscreen）。
- [ ] **Step 5** 变异验牙：下拉值不传 → 用例红；枚举失败直接抛 → 降级用例红。
- [ ] **Step 6** 提交（`app: 介质类型/打印质量下拉 + 状态栏明示`）

---

### Task 6: cli --media-type / --quality

**Files:** Modify `photoprint/cli.py`；Test `tests/test_cli.py`

- [ ] **Step 1** 追加失败测试：`--media-type 303`、`--media-type 高级光面照片纸 II`、
  `--quality high` 分别/组合传到 `print_job`；`--quality` 只接受 `default|high`；
  不传时 stdout 与既有冻结断言逐字一致。
- [ ] **Step 2** 跑测试确认红。
- [ ] **Step 3** 实现：参数解析（`--media-type` 字符串→int 或名字，交给
  `find_media`；`--quality` 映射 `default→None`、`high→QUALITY_HIGH`）；
  枚举失败/查不到→`None` + stderr 一行提示（stdout 不动）。
- [ ] **Step 4** 跑 `tests/test_cli.py` 全绿。
- [ ] **Step 5** 变异验牙：不传质量（丢弃参数）→ 对应用例红。
- [ ] **Step 6** 提交（`cli: --media-type / --quality（不传时输出逐字不变）`）

---

### Task 7: dump 脚本补介质表 + 全量回归 + 真机复验

- [ ] **Step 1** `_lab/dump_driver_papers.py` 追加：介质名字/数值表、纸盒表、
  默认 `MediaType`/`PrintQuality`，并标出默认项。
- [ ] **Step 2** 真机只读跑一遍，核对 spec §0.1/§0.2。
- [ ] **Step 3** 全量回归 `pytest -q` 全绿；`Select-String MUTATION-TEMP` 为 0。
- [ ] **Step 4** 真机只读复验：`MediaType=303`+`Quality=-4`+表单 126 → 尺寸/偏移不变。
- [ ] **Step 5** 打印验证（**需用户批准**）：同一张 3R 测试图，分别用“驱动默认”与
  “高级光面照片纸 II + 质量高”各打一张，比较墨量。
- [ ] **Step 6** 提交（`lab: 介质/纸盒/质量采证`），并把 plan 勾成完成。

## Self-Review

- 向后兼容：`media=None, quality=None` 时 update 次数、DEVMODE 内容、CLI stdout、
  状态栏文案形状均不变（各有专门用例）。
- 证据可追：§0.2 的夹取值、§0.3 的两遍写入、§0.4 的位常量错位都来自本机实测。
- 未覆盖项（诚实记账）：墨量强度/ICM/无边距/多纸盒明确不做；「出片更深」只能由
  人眼在 Task 7 Step 5 判定，自动化测试只保证“选了就写进 DEVMODE”。
