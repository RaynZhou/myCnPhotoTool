# 驱动表单绑定 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让直打按**驱动自带的真实表单**出纸：打印前实测每个表单码的物理尺寸，按尺寸把预设绑定到表单码，并在校验时以该表单实测尺寸为目标；无匹配时退回今日行为，并把“本机驱动不接受程序化自定义尺寸”说清。

**Architecture:** 新模块 `win/forms.py`（纯编排，经 `api` 注入，无 win32 import）负责“实测 + 匹配 + 文案”；`gdi_print.print_pages` 只多一个 `forms=None` 参数，命中则换 `paper_code` 与校验目标；`app`/`cli` 在打印前测一次并传进来，异常静默降级为 `[]`（= 旧行为）。

**Tech Stack:** pywin32（`win32print`/`win32gui`）、PIL、pytest（FakeApi 全脱机）、PySide6（offscreen）。

## Global Constraints

- 证据基线：`docs/superpowers/specs/2026-11-07-photoprint-driver-form-binding-design.md` §0（真机实测表）。任何尺寸常量必须能在该表里找到出处。
- 分层红线：`win/forms.py` 与 `win/gdi_print.py` 不得 import win32（延时到方法内或由 `api` 提供）；不得做 mm/像素换算以外的几何。
- 向后兼容红线：`print_pages`/`print_job` 新参一律 `forms=None`；未命中表单时返回值**逐字**与今天相同（既有测试零改动）；`probe` 语义不动。
- 容差红线：匹配容差 `MATCH_TOL_MM = 0.6`，只此一处常量，测试与实现共用。
- 诚实红线：驱动不认的表单码不得编造尺寸（回读 `PaperSize != code` 即丢弃）；无匹配就明说无匹配，绝不按名字猜。
- 物理副作用红线：除 Task 7 的可选测试页外，一律只读；测试页必须先得到用户批准。
- PowerShell 用 `;` 分隔；提交消息走 UTF-8 无 BOM 文件 + `git commit -F`。

---

### Task 1: win/forms.py — 逐表单实测 + 尺寸匹配

**Files:**
- Create: `photoprint/win/forms.py`
- Test: `tests/test_driver_forms.py`

**Interfaces:**
- Consumes: `api` 的 `open_printer` / `close_printer` / `get_devmode` / `document_properties` / `create_dc` / `delete_dc` / `get_device_caps` / `device_caps`；`probe.DC_PAPERS` / `probe.DC_PAPERNAMES` / `probe.PHYSICALWIDTH` / `probe.PHYSICALHEIGHT` / `probe.LOGPIXELSX` / `probe.LOGPIXELSY`。
- Produces: `PaperForm`、`MATCH_TOL_MM`、`measure(api, printer, codes=None)`、`find(forms, w_mm, h_mm, tol_mm=MATCH_TOL_MM)`、`binding_note(form)`；Task 2/3/4/6 依赖这五项。

- [x] **Step 1: 追加失败测试**（新建 `tests/test_driver_forms.py`）

```python
"""表单实测与匹配：全脱机（FakeApi 注入），不 import win32。"""
import pytest

from photoprint.win import forms, probe


class FakeApi:
    """按码返回实测尺寸；记录调用。sizes[code] = (w_mm, h_mm) 或 'ERR'。"""

    def __init__(self, names, codes, sizes, dpi=600, reject=()):
        self.names, self.codes, self.sizes = names, codes, sizes
        self.dpi = dpi
        self.reject = set(reject)      # 驱动不认的码：回读 PaperSize 会变
        self.calls = []

    def device_caps(self, printer, field):
        self.calls.append(("device_caps", field))
        if field == probe.DC_PAPERNAMES:
            return tuple(self.names)
        if field == probe.DC_PAPERS:
            return tuple(self.codes)
        return 0

    def open_printer(self, name):
        self.calls.append(("open_printer", name))
        return "H"

    def close_printer(self, handle):
        self.calls.append(("close_printer", handle))

    def get_devmode(self, handle):
        return type("DM", (), {"PaperSize": 9, "PaperWidth": 2100, "PaperLength": 2970})()

    def document_properties(self, handle, printer, mode="size", dm=None):
        self.calls.append(("document_properties", mode))
        if mode == "size":
            return 520
        code = getattr(self, "_want", 9)
        dm.PaperSize = 9 if code in self.reject else code
        return 1

    def create_dc(self, printer, devmode=None):
        self.calls.append(("create_dc", getattr(devmode, "PaperSize", None)))
        if getattr(devmode, "PaperSize", None) == "ERR":
            raise RuntimeError("bad dc")
        self._dc_code = getattr(devmode, "PaperSize", None)
        return f"hdc:{self._dc_code}"

    def delete_dc(self, hdc):
        self.calls.append(("delete_dc", hdc))

    def get_device_caps(self, hdc, field):
        code = int(str(hdc).split(":")[1])
        w, h = self.sizes[code]
        if field == probe.LOGPIXELSX or field == probe.LOGPIXELSY:
            return self.dpi
        if field == probe.PHYSICALWIDTH:
            return round(w / 25.4 * self.dpi)
        if field == probe.PHYSICALHEIGHT:
            return round(h / 25.4 * self.dpi)
        return 0
```

并追加断言（同一文件）：

- `test_measure_reads_physical_size_per_form_code`：names `["L 89x127mm"]`、codes `[126]`、sizes `{126: (88.98, 127.0)}` → 一条 `PaperForm(code=126, name="L 89x127mm")`，`w_mm == approx(88.98, abs=0.05)`；`("delete_dc", "hdc:126") in api.calls`。
- `test_measure_skips_code_driver_rejects`：`reject={126}` → `measure(...) == []`（回读码不是 126，不得编造尺寸）。
- `test_measure_one_bad_code_does_not_abort_rest`：codes `[126, 121]`，其中 `create_dc` 抛错（用 sizes 里给 `'ERR'` 的旁路或子类化）→ 返回仅剩的那条，不抛。
- `test_find_matches_swapped_axes`：表单 (54.99, 90.97) 对 91×55 → 命中。
- `test_find_prefers_smallest_delta_then_mm_name`：表单 `[PaperForm(123, '13x18cm 5"x7"', 127.0, 177.8), PaperForm(121, "2L 127x178mm", 127.0, 177.97)]` 对 5R 127×178 → 取 `121`；构造完全并列（两个都 127×178）时仍取名字含 `mm` 的。
- `test_find_returns_none_outside_tolerance`：6R 152×203 对 (101.6,152.4) → None；182×257 对 176×250 → None。
- `test_binding_note_mentions_form_name_and_measured_size`：`"L 89x127mm"` 与 `"88.98"` 都出现在文案里。

- [x] **Step 2: 跑测试确认失败**

Run: `.\.venv-build\Scripts\python.exe -m pytest tests/test_driver_forms.py -q`
Expected: FAIL — `ModuleNotFoundError: photoprint.win.forms`。

- [x] **Step 3: 实现**（`photoprint/win/forms.py`）

要点（照 spec §2/§3）：`_measure_one` 用 `PaperSize=code` 建 DEVMODE、`document_properties(update)` 回填、**回读码必须等于请求码**，再 `create_dc(devmode)` → `get_device_caps` 四值 → `×25.4/dpi`；`measure` 逐码 `try/except`；`find` 先 `fits`（宽高可互换）再按 `(|Δw|+|Δh|, "mm" not in name, code)` 排序取首个。

- [x] **Step 4: 跑测试确认通过**

Run: `.\.venv-build\Scripts\python.exe -m pytest tests/test_driver_forms.py -q`
Expected: PASS。

- [x] **Step 5: 变异验牙**

1. 去掉“回读码必须等于请求码”判断 → `test_measure_skips_code_driver_rejects` 红。
2. 把 `find` 的排序键去掉 `"mm" not in name` → 并列用例红。
3. 把 `fits` 的宽高互换分支删掉 → 卡片用例红。
验后还原，重跑 PASS。

- [x] **Step 6: 提交**

```bash
python -c "open('.superpowers/sdd/_dfb_t1_msg.txt','w',encoding='utf-8').write('win/forms: 逐表单实测尺寸 + 按尺寸匹配驱动表单（只读，不发作业）\n')"; git add photoprint/win/forms.py tests/test_driver_forms.py; git commit -F .superpowers/sdd/_dfb_t1_msg.txt
```

---

### Task 2: gdi_print — 表单码与校验目标切换

**Files:**
- Modify: `photoprint/win/gdi_print.py`
- Test: `tests/test_gdi_print_media.py`

**Interfaces:**
- Consumes: Task 1 的 `forms.find` / `forms.PaperForm`。
- Produces: `print_pages(..., forms=None)` 与 `print_job(..., forms=None)`；`res["paper_form"]`（仅命中时）。

- [x] **Step 1: 追加失败测试**（`tests/test_gdi_print_media.py` 末尾）

断言点：

- `test_matched_form_code_reaches_devmode_and_verify_target`：`forms` 给一条 `PaperForm(126, "L 89x127mm", 88.98, 127.0)`，`Sheet` 为 89×127 / `driver_paper_code=None` → `fake_build` 收到的 `code == 126`；`fake_emit` 收到的校验目标或 `res["paper_form"]["code"] == 126`（`_emit` 被 monkeypatch 时验 `res`）。
- `test_unmatched_form_falls_back_to_sheet_code`：`forms=[]` → `code == Sheet.driver_paper_code`，且 `res` 里**没有** `paper_form` 键（冻结口径）。
- `test_custom_size_reset_gets_explicit_reason`：模拟 `_emit` 返回失败且 `dm.PaperSize != DMPAPER_USER` → 文案含“不接受程序化自定义尺寸”。

- [x] **Step 2: 跑测试确认失败**

Run: `.\.venv-build\Scripts\python.exe -m pytest tests/test_gdi_print_media.py -q`
Expected: FAIL — `print_pages() got an unexpected keyword argument 'forms'`。

- [x] **Step 3: 实现**

`print_pages` 内：`form = forms.find(forms, sheet.w_mm, sheet.h_mm) if forms else None`；`code = form.code if form else sheet.driver_paper_code`；`target = (form.w_mm, form.h_mm) if form else (sheet.w_mm, sheet.h_mm)`；把 `target` 传给 `_emit`（新增关键字参数 `target_mm=`，默认 `None` 时用 `sheet` 标称，保持既有调用形状）；成功时 `res["paper_form"]`。`_emit` 的 `verify_physical_size` 用 `target_mm`。自定义尺寸被重置的判断放在 `_emit` 失败分支后（需要 `dm_obj.PaperSize`），文案由 `_custom_rejected_note()` 统一生成。

- [x] **Step 4: 跑测试确认通过**

Run: `.\.venv-build\Scripts\python.exe -m pytest tests/test_gdi_print_media.py -q`
Expected: PASS（新增 3 条 + 既有 9 条全绿）。

- [x] **Step 5: 变异验牙**

1. 让 `code` 永远取 `sheet.driver_paper_code` → 第一条红。
2. 让 `target` 永远用标称 → 命中表单时的校验目标用例红。
3. 命中时也写 `paper_form` 键为 `None` → 第二条（冻结口径）红。
验后还原。

- [x] **Step 6: 提交**

```bash
python -c "open('.superpowers/sdd/_dfb_t2_msg.txt','w',encoding='utf-8').write('gdi_print: 命中的驱动表单码进 DEVMODE，校验目标切到表单实测尺寸\n')"; git add photoprint/win/gdi_print.py tests/test_gdi_print_media.py; git commit -F .superpowers/sdd/_dfb_t2_msg.txt
```

---

### Task 3: app — 打印前探测 + 状态栏明示

**Files:**
- Modify: `photoprint/app/main_window.py`（`_on_print`）
- Test: `tests/test_app_main_window.py`

- [x] **Step 1: 追加失败测试**

- `test_print_passes_measured_forms`：monkeypatch `forms.measure` 返回一条 126 表单、`gdi_print.print_pages` 收参断言 `forms` 非空。
- `test_print_status_mentions_driver_form`：`print_pages` 回 `{"ok": True, "pages": 1, "paper_form": {...}}` → 状态栏含 `L 89x127mm`。
- `test_print_survives_form_probe_failure`：`forms.measure` 抛异常 → 仍调用 `print_pages`（`forms == []`），状态栏为正常“已发送”。

- [x] **Step 2: 跑测试确认失败** → `.\.venv-build\Scripts\python.exe -m pytest tests/test_app_main_window.py -q`

- [x] **Step 3: 实现**（`_on_print` 内，`QApplication.setOverrideCursor` 之前）

```python
try:
    measured = forms_mod.measure(self.api, printer)
except Exception:
    measured = []            # 探测失败＝退回旧行为，绝不让打印崩
```

`print_pages(..., forms=measured)`；成功文案：

```python
form = res.get("paper_form")
if form:
    msg += f"（{forms_mod.binding_note(form)}）"
```

- [x] **Step 4: 跑测试确认通过** → 同上，PASS。
- [x] **Step 5: 变异验牙**：删 `forms=` 传参 → 第 1 条红；删状态栏拼接 → 第 2 条红；把 `except` 改成上抛 → 第 3 条红。验后还原。
- [x] **Step 6: 提交**（消息：`app: 打印前实测驱动表单并明示所用表单`）

---

### Task 4: cli — `--print` 走同一探测

**Files:**
- Modify: `photoprint/cli.py`（`args.do_print` 分支）
- Test: `tests/test_cli.py`

- [x] **Step 1: 追加失败测试**：monkeypatch `forms.measure` 与 `gdi_print.print_job`，断言 `--print` 路径把非空 `forms` 传下去；`measure` 抛异常时传 `[]` 且不外抛。
- [x] **Step 2: 跑测试确认失败** → `python -m pytest tests/test_cli.py -q`
- [x] **Step 3: 实现**：`forms_mod.measure(...)` 包 `try/except`，`print_job(..., forms=measured)`。stdout 文案不动（既有输出行必须逐字不变）。
- [x] **Step 4: 跑测试确认通过**；并跑 `python -m photoprint.cli --photos ... --out _lab/out/x.png` 确认无回归。
- [x] **Step 5: 变异验牙**：删 `forms=` → 新断言红；把异常改成上抛 → 降级断言红。还原。
- [x] **Step 6: 提交**（消息：`cli: --print 复用驱动表单探测`）

---

### Task 5: specs — B5 按实测校准

**Files:**
- Modify: `photoprint/core/specs.py`（`_paper("B5", ...)`）
- Test: `tests/test_specs.py`

- [x] **Step 1: 追加失败测试**：`test_b5_matches_driver_jis_form`：`s = specs.find_spec("B5"); assert (s.w_mm, s.h_mm) == (182.0, 257.0)`。
- [x] **Step 2: 跑测试确认失败**（现为 176×250）。
- [x] **Step 3: 实现**：改值并在注释里写清依据（真机实测 181.99×256.96，JIS B5；G3800 官方规格同为 182×257；ISO 176×250 不是本驱动的 B5）。
- [x] **Step 4: 跑测试确认通过** → `python -m pytest tests/test_specs.py -q`。
- [x] **Step 5: 变异验牙**：改回 176×250 → 用例红。
- [x] **Step 6: 提交**（消息：`core/specs: B5 校准为 JIS 182x257（真机实测 + 官方规格）`）

---

### Task 6: _lab/dump_driver_papers.py — 改用实测

**Files:**
- Modify: `_lab/dump_driver_papers.py`

- [x] **Step 1: 改造输出**：尺寸列改为 `forms.measure` 的实测值；每行追加“命中哪个预设”（用 `forms.find` 对 `specs.PAPER_PRESETS` 逐个反查）；保留“只读、不发作业”的声明与 `sys.path` 引导。
- [x] **Step 2: 真机只读运行**：`.\.venv-build\Scripts\python.exe _lab/dump_driver_papers.py` → 目视核对 §0.1 表格：126/121/122/124/127/125/9/11/13/1/5/20/27 有尺寸且命中对应预设，6R 行显示无匹配。
- [x] **Step 3: 提交**（消息：`lab: 纸张采证改用逐表单实测并标出预设命中`）。

---

### Task 7: 全量回归 + 真机收尾

- [x] **Step 1: 全量回归**：`.\.venv-build\Scripts\python.exe -m pytest -q` → 全绿（393 + 新增）。
- [x] **Step 2: 残留自查**：`git status --short` 干净；`.superpowers/sdd/_dfb_*` 不入库。
- [x] **Step 3: 真机只读复验**：跑 `_lab/app_path_check` 等价脚本（3R 现状 vs 表单 126），确认现状 False / 修复后 True（证据已在本 plan 落地前取得，复验一次留档）。
- [x] **Step 4: 打印测试页（需用户批准）**：单页 3R 直打，确认不再报“驱动忽略了自定义尺寸”且实际出纸为 89×127。
  - 用户已批准；作业 6 已下发并回读 `pDevMode`：`PaperSize=126`、`890×1270`(0.1mm)。
  - 机器当时 `PaperOut`，未出纸；装 3R 相纸后保留中的作业会续打，待目视确认。
  - 首打又抓出三处 `_emit` 缺陷（半色调 / Pillow `draw` / 驱动 dpi 缩放），已修并入 spec §0.3。
- [ ] **Step 5: 交用户手测清单**：3R/4R/5R/7R/卡片 五种，各看“状态栏是否明示表单名”与出纸尺寸；6R 看是否给出“无匹配表单 + 导出 PDF”提示。

## Self-Review

- 证据可追：§0.1 每个尺寸都来自本机实测；B5 校准、容差 0.6mm 均有对照错配值。
- 向后兼容：`forms=None`/未命中时返回值逐字不变，既有 9 条 `test_gdi_print_media` 断言不改。
- 未覆盖项（诚实记账）：无边距（偏移 3.39/2.96 与 5.97 的差异）未纳入、`origin` 未改、6R 无替代方案——均已写入 spec §1 “不做”。
