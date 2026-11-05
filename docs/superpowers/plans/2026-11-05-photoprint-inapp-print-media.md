# App 内直打 + 介质类型选择 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 PhotoPrint GUI 内新增「打印…」——点打印时弹出佳能驱动自己的设置页选介质类型，回填的 DEVMODE 携带介质选择走 GDI 直打全部页。

**Architecture:** 方案 A——介质类型自始至终由驱动持有，本程序从不解析 DEVMODE 私有区，只用 `DocumentProperties(DM_PROMPT)` 让驱动填、再把带介质的 DEVMODE 交 `CreateDC`。纸张几何（自定义 3R/A4）保持权威：弹窗前后各写一次。渲染与预览/导出同源（`render_all(show_mask=False)`）。

**Tech Stack:** PySide6、pywin32（win32print/win32gui/win32con）、Pillow、pytest（offscreen）。

规格：`docs/superpowers/specs/2026-11-05-photoprint-inapp-print-media-design.md`
基线：分支 `feat/photoprint-print-media` @ 455cf28，`python -m pytest tests/` 现应 265 全绿。

## Global Constraints（每个任务都受约束）

- `win/` 是唯一可 `import win32print/win32gui/win32con` 的层；`photoprint/core/` 与 `jobs.py` 禁 Qt/win32，且 `jobs.py` 源码禁出现 `print(` 字样（有扫源守门测试，注释里也不能写出）。
- `app/` 层不得做 mm↔像素换算与裁切几何；打印编排只调 `win` 层，几何交 `devmode`/`core`。
- **`cli.py` 一字不改**；`gdi_print.print_job` 在 `prompt=False` 下与现状逐字段等价（返回 `{'ok','pages','message'}` 同形、异常兜成 `f"打印失败：{exc}"`）。
- **不变量 I-1（纸张几何权威）**：最终交 `CreateDC` 的 DEVMODE，`PaperWidth/PaperLength/PaperSize` 必等于本工具请求尺寸，即使驱动弹窗返回时把它改坏也要盖回。
- **不变量 I-2（渲染同源）**：打印图 = `jobs.render_all(job, dpi, show_mask=False)`，`job` 由 `_rebuild_job` 依当前控件（含 `photo_rotations`）产出；遮罩绝不进相纸。
- 窗口化 exe 无控制台：任何异常收敛成状态栏/返回 message，不外抛、不闪退。
- 提交信息用中文；PowerShell 用 `;` 分隔，不用 `&&`。
- 测试全部脱机 `offscreen`（`conftest.py` 已设），不得执行真实 win32（用 FakeApi + monkeypatch 隔离）。

## File Structure

- `photoprint/win/api.py`：`RealWinApi` 新增 `prompt_devmode`（唯一碰 win32 的新点）。
- `photoprint/win/devmode.py`：新增 `build_with_prompt(...)`；`build(...)` 改为委托 `prompt=False`。
- `photoprint/win/gdi_print.py`：抽出 `_emit(...)`（DC+StretchBlt，win32 唯一入口）；新增 `print_pages(...)`；`print_job(...)` 改薄封装转调 `print_pages(prompt=False)`。
- `photoprint/app/main_window.py`：`__init__` 加可注入 `printer_api`；`_build_ui` 加打印机下拉 + 「打印…」按钮；`_load_printers()`；`_on_print()`。
- 测试：`tests/test_devmode.py`（追加）、`tests/test_gdi_print_media.py`（新建）、`tests/test_app_print_media.py`（新建）、`README.md`（追加打印段）。

---

### Task 1: `RealWinApi.prompt_devmode`（win32 薄封装）

**Files:**
- Modify: `photoprint/win/api.py`
- Test: `tests/test_win32_contract.py`（追加，`importorskip` 守护）

**Interfaces:**
- Produces: `RealWinApi.prompt_devmode(self, handle, printer, dm) -> dm`（弹驱动设置页、返回用户确认后的同一份 DEVMODE 引用）。

- [ ] **Step 1: 写失败测试（源码契约，不执行真实弹窗）**

追加到 `tests/test_win32_contract.py` 末尾（该文件顶部已有 `pytest.importorskip` 风格；沿用之）：

```python
def test_prompt_devmode_uses_document_properties_with_dm_prompt():
    pytest.importorskip("win32print")
    import inspect

    from photoprint.win import api

    src = inspect.getsource(api.RealWinApi.prompt_devmode)
    assert "win32print.DocumentProperties" in src
    assert "DM_PROMPT" in src
    assert "DM_IN_BUFFER" in src and "DM_OUT_BUFFER" in src
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_win32_contract.py::test_prompt_devmode_uses_document_properties_with_dm_prompt -q`
Expected: FAIL（`AttributeError: type object 'RealWinApi' has no attribute 'prompt_devmode'` 或 getsource 报错）。

- [ ] **Step 3: 实现**

在 `photoprint/win/api.py` 的 `RealWinApi` 里，`document_properties` 方法之后加：

```python
    def prompt_devmode(self, handle, printer, dm):
        """弹驱动自己的设置页（介质类型、无边距等私有项都在里面），返回用户
        确认后的 DEVMODE。介质活在驱动私有扩展区——由驱动自己读写，我们从不
        解析它（这是不随驱动版本碎裂的根基）。DM_PROMPT 与既有 fMode 常量同源。"""
        import win32con
        import win32print
        flag = (win32con.DM_IN_BUFFER | win32con.DM_OUT_BUFFER
                | win32con.DM_PROMPT)
        win32print.DocumentProperties(0, handle, printer, dm, dm, flag)
        return dm
```

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `python -m pytest tests/test_win32_contract.py -q` → 全 PASS。
Run: `python -m pytest tests/ -q` → 266 passed，0 failed。

- [ ] **Step 5: Commit**

```powershell
git add photoprint/win/api.py tests/test_win32_contract.py
git commit -m "feat(win): RealWinApi 增加 prompt_devmode 弹驱动设置页"
```

---

### Task 2: `devmode.build_with_prompt`（I-1 几何权威 + 弹窗降级）

**Files:**
- Modify: `photoprint/win/devmode.py`
- Test: `tests/test_devmode.py`（追加）

**Interfaces:**
- Consumes: `api.open_printer/get_devmode/document_properties/close_printer`；`api.prompt_devmode`（Task 1）；`devmode.modify`。
- Produces: `devmode.build_with_prompt(api, printer, w_mm, h_mm, paper_code=None, prompt=False) -> (dm, size)`；`build(...)` 保持签名、转调 `prompt=False`。

- [ ] **Step 1: 写失败测试（含 I-1 变异牙）**

追加到 `tests/test_devmode.py` 末尾：

```python
class PromptApi(FakeApi):
    """prompt_devmode 模拟驱动：把用户可能改坏的自定义尺寸留下（重置成 9 号
    Letter 的 PaperSize、宽高清零），但保留私有区的介质选择——正是要验证
    build_with_prompt 会盖回几何、却不碰介质。可切换为抛错以测降级。"""

    def __init__(self, size=520, raise_on_prompt=False):
        super().__init__(size)
        self.prompt_calls = 0
        self.raise_on_prompt = raise_on_prompt

    def prompt_devmode(self, handle, printer, dm):
        self.prompt_calls += 1
        if self.raise_on_prompt:
            raise RuntimeError("driver has no config page")
        # 驱动弹窗后：尺寸被用户改成 Letter，介质私有字段保留
        dm.PaperSize = 9
        dm.PaperWidth = 2159
        dm.PaperLength = 2794
        return dm


def test_build_with_prompt_off_equals_build():
    api = PromptApi()
    dm1, size1 = devmode.build(api, "P", 89.0, 127.0)
    api2 = PromptApi()
    dm2, size2 = devmode.build_with_prompt(api2, "P", 89.0, 127.0, prompt=False)
    assert api2.prompt_calls == 0            # 不弹
    assert dm2.PaperWidth == 890 and dm2.PaperLength == 1270  # 与 build 同


def test_geometry_reapplied_after_prompt_keeps_media():
    """I-1：弹窗把尺寸改坏也必须盖回；介质私有字段（Duplex/MediaType 建模）
    不得被 modify 触碰。删掉"弹窗后再 modify"本测试即红。"""
    api = PromptApi()
    dm, _size = devmode.build_with_prompt(api, "P", 89.0, 127.0, prompt=True)
    assert api.prompt_calls == 1
    assert dm.PaperWidth == 890 and dm.PaperLength == 1270   # 盖回成功
    assert dm.PaperSize == devmode.DMPAPER_USER
    assert dm.MediaType == 700 and dm.Duplex == 300          # 私有区原样保留


def test_prompt_devmode_exception_degrades_to_inherited_media():
    """驱动不支持弹窗：不外抛、降级为按继承介质直打，几何仍按请求写入。"""
    api = PromptApi(raise_on_prompt=True)
    dm, _size = devmode.build_with_prompt(api, "P", 89.0, 127.0, prompt=True)
    assert api.prompt_calls == 1
    assert dm.PaperWidth == 890 and dm.PaperLength == 1270
    assert "update" in api.mode_log          # 仍走完驱动校验回填


def test_build_delegates_to_build_with_prompt():
    api = FakeApi()
    dm, size = devmode.build(api, "P", 210.0, 297.0)
    assert size == 520
    assert dm.PaperWidth == 2100 and dm.PaperLength == 2970
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_devmode.py -q -k "prompt or delegates or geometry"`
Expected: FAIL（`AttributeError: module 'photoprint.win.devmode' has no attribute 'build_with_prompt'`）。

- [ ] **Step 3: 实现**

把 `photoprint/win/devmode.py` 末尾的 `build(...)` 整体替换为：

```python
def build_with_prompt(api, printer, w_mm, h_mm, paper_code=None, prompt=False):
    """取驱动默认 DEVMODE → 写纸张几何 →（可选）弹驱动页选介质 → 再盖一次
    几何 → 交回驱动校验回填。返回 (dm, size)。

    I-1：弹窗返回的 dm 可能被用户/驱动改成别的表单尺寸，故 prompt 之后再
    `modify` 一次把几何钉回请求值；`modify` 只动纸张字段、从不碰私有区，
    所以用户选的介质（活在私有扩展区）原样保留。弹窗抛错则静默降级为
    "用驱动当前介质"（几何已在弹窗前写好，继续走 update 即可），不外抛。
    """
    handle = api.open_printer(printer)
    try:
        size = api.document_properties(handle, printer, "size")
        if not size:
            raise RuntimeError("DocumentProperties 返回 0，无法取得 DEVMODE")
        dm = api.get_devmode(handle)
        modify(dm, size, w_mm, h_mm, paper_code)
        if prompt:
            try:
                dm = api.prompt_devmode(handle, printer, dm)
            except Exception:
                pass          # 驱动无配置页：降级为继承当前介质，不中断打印
            modify(dm, size, w_mm, h_mm, paper_code)   # 几何以请求为准（I-1）
        api.document_properties(handle, printer, "update", dm)
    finally:
        api.close_printer(handle)
    return dm, size


def build(api, printer, w_mm, h_mm, paper_code=None):
    """旧入口：等价 prompt=False。CLI / print_job 行为逐字不变。"""
    return build_with_prompt(api, printer, w_mm, h_mm, paper_code, prompt=False)
```

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `python -m pytest tests/test_devmode.py -q` → 全 PASS（既有 build 用例不回归）。
Run: `python -m pytest tests/ -q` → 270 passed，0 failed。

- [ ] **Step 5: Commit**

```powershell
git add photoprint/win/devmode.py tests/test_devmode.py
git commit -m "feat(win): devmode 增加 build_with_prompt，弹窗后盖回几何保介质选择"
```

---

### Task 3: `gdi_print.print_pages` + `_emit` 抽取 + `print_job` 薄封装

**Files:**
- Modify: `photoprint/win/gdi_print.py`
- Test: `tests/test_gdi_print_media.py`（新建）

**Interfaces:**
- Consumes: `devmode.build_with_prompt`（Task 2）、`probe.probe`、`verify_physical_size`、`_create_dc`、`_as_dc_ref`。
- Produces: `gdi_print.print_pages(api, printer, images, sheet, dpi, *, prompt=True) -> {'ok','pages','message'}`；`_emit(api, printer, dm_obj, images, sheet, dpi) -> dict`；`print_job(api, printer, port, images, sheet, dpi, dm=None)` 转调 `print_pages(prompt=False)`。

- [ ] **Step 1: 写失败测试（monkeypatch 隔离，绝不执行 win32）**

新建 `tests/test_gdi_print_media.py`：

```python
"""print_pages 编排层测试：只验数据/控制流交接，DC+StretchBlt 交真机。
_emit 被 monkeypatch，故本文件全程不 import win32（gdi_print 顶部也不 import）。"""
import types

import pytest

from photoprint.win import devmode, gdi_print


class Sheet:
    w_mm, h_mm, label, driver_paper_code = 89.0, 127.0, "3R", None


def _imgs(n):
    return [types.SimpleNamespace(name=f"p{i}") for i in range(n)]


def test_empty_images_early_return_no_build(monkeypatch):
    called = []
    monkeypatch.setattr(devmode, "build_with_prompt",
                        lambda *a, **k: called.append(1))
    res = gdi_print.print_pages(object(), "P", [], Sheet, 300)
    assert res["ok"] is False and res["pages"] == 0 and res["message"]
    assert not called          # 空图不进准备阶段


def test_prompt_flag_propagates(monkeypatch):
    seen = {}

    def fake_build(api, printer, w, h, code, prompt=False):
        seen["prompt"] = prompt
        return ("DM", 520)

    def fake_emit(api, printer, dm, images, sheet, dpi):
        seen["dm"] = dm
        seen["n"] = len(images)
        return {"ok": True, "pages": len(images), "message": ""}

    monkeypatch.setattr(devmode, "build_with_prompt", fake_build)
    monkeypatch.setattr(gdi_print, "_emit", fake_emit)
    res = gdi_print.print_pages(object(), "P", _imgs(3), Sheet, 300, prompt=True)
    assert seen == {"prompt": True, "dm": "DM", "n": 3}
    assert res["pages"] == 3


def test_print_job_is_prompt_false_wrapper(monkeypatch):
    seen = {}

    def fake_build(api, printer, w, h, code, prompt=False):
        seen["prompt"] = prompt
        return ("DM", 520)

    monkeypatch.setattr(devmode, "build_with_prompt", fake_build)
    monkeypatch.setattr(gdi_print, "_emit",
                        lambda *a, **k: {"ok": True, "pages": 1, "message": ""})
    gdi_print.print_job(object(), "P", None, _imgs(1), Sheet, 300)
    assert seen["prompt"] is False       # CLI 冻结：绝不弹窗


def test_build_failure_contained_no_raise(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("printer offline")

    monkeypatch.setattr(devmode, "build_with_prompt", boom)
    res = gdi_print.print_pages(object(), "P", _imgs(2), Sheet, 300)
    assert res["ok"] is False and "printer offline" in res["message"]


def test_emit_source_does_not_regress_to_win32print_create_dc():
    import inspect

    src = inspect.getsource(gdi_print._emit)
    assert "win32ui.CreateDCFromHandle" in src
    assert "win32print.CreateDC" not in src        # 终审 C2 契约
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_gdi_print_media.py -q`
Expected: FAIL（`AttributeError: module 'photoprint.win.gdi_print' has no attribute 'print_pages'` / `_emit`）。

- [ ] **Step 3: 实现**

把 `photoprint/win/gdi_print.py` 中 `print_job(...)` 整个函数替换为：

```python
def print_pages(api, printer, images, sheet, dpi, *, prompt=True):
    """打印多页。prompt=True 时弹驱动设置页让用户选介质（I-1 由 devmode 保证
    几何权威），交 `_emit` 建 DC 送图。返回 {'ok','pages','message'}，异常不外抛。"""
    from photoprint.win import devmode as dm_mod

    if not images:
        return {"ok": False, "pages": 0, "message": "没有可打印的页面"}
    try:
        dm_obj, _size = dm_mod.build_with_prompt(
            api, printer, sheet.w_mm, sheet.h_mm, sheet.driver_paper_code,
            prompt=prompt)
    except Exception as exc:      # 取设置/弹窗阶段失败也要兜住
        return {"ok": False, "pages": 0, "message": f"读取打印机设置失败：{exc}"}
    return _emit(api, printer, dm_obj, images, sheet, dpi)


def _emit(api, printer, dm_obj, images, sheet, dpi):
    """建 DC → 校验物理尺寸 → 逐页 StretchBlt。这是本模块唯一碰 win32 处。
    StartDoc 后异常经 EndDoc/DeleteDC 展开后统一转 message（打印不得崩）。"""
    from PIL import ImageWin

    import win32con
    import win32ui

    from photoprint.core import units
    from photoprint.win import probe

    try:
        hdc = win32ui.CreateDCFromHandle(_as_dc_ref(_create_dc(printer, dm_obj)))
        try:
            result = probe.probe(api, printer, dc=_as_dc_ref(hdc))
            ok, msg = verify_physical_size(result.physical_w_mm,
                                           result.physical_h_mm,
                                           sheet.w_mm, sheet.h_mm)
            if not ok:
                return {"ok": False, "pages": 0, "message": msg}
            hdc.StartDoc(f"PhotoPrint {sheet.label}")
            try:
                for img in images:
                    hdc.StartPage()
                    try:
                        dib = ImageWin.Dib(img)
                        w = units.mm_to_px(sheet.w_mm, dpi)
                        h = units.mm_to_px(sheet.h_mm, dpi)
                        hdc.SetStretchBltMode(win32con.HALFTONE)
                        dib.Draw(hdc.GetHandleOutput(), (0, 0, w, h))
                    finally:
                        hdc.EndPage()
            finally:
                hdc.EndDoc()
            return {"ok": True, "pages": len(images), "message": ""}
        finally:
            hdc.DeleteDC()
    except Exception as exc:  # 打印阶段不得崩溃：统一转成可读消息
        return {"ok": False, "pages": 0, "message": f"打印失败：{exc}"}


def print_job(api, printer, port, images, sheet, dpi, dm=None):
    """CLI 冻结入口：等价 print_pages(prompt=False)。port/dm 为兼容旧签名保留，
    不参与建 DC（现代驱动走默认端口，CreateDC 只收 printer 名与 devmode）。"""
    return print_pages(api, printer, images, sheet, dpi, prompt=False)
```

- [ ] **Step 4: 跑测试确认通过 + 全量回归 + CLI 冻结**

Run: `python -m pytest tests/test_gdi_print_media.py -q` → 全 PASS。
Run: `python -m pytest tests/ -q` → 275 passed，0 failed。
Run: `python _lab/check_gui_cli_parity.py` → 全 True、exit 0（证明 CLI/PDF 路径零回归）。

- [ ] **Step 5: Commit**

```powershell
git add photoprint/win/gdi_print.py tests/test_gdi_print_media.py
git commit -m "feat(win): gdi_print 增加 print_pages 与 _emit 抽取，print_job 转薄封装"
```

---

### Task 4: GUI 打印机下拉 + 「打印…」按钮

**Files:**
- Modify: `photoprint/app/main_window.py`
- Test: `tests/test_app_print_media.py`（新建）

**Interfaces:**
- Consumes: `api.RealWinApi`（`enum_printers`/`prompt_devmode`）、`gdi_print.print_pages`、`jobs.render_all`、既有 `_rebuild_job`/`_set_status`/`photo_rotations`。
- Produces: `MainWindow.__init__(self, st=None, printer_api=None)`；`MainWindow.printer_box`、`MainWindow.print_btn`、`_load_printers()`、`_on_print()`。

- [ ] **Step 1: 写失败测试（FakeApi + monkeypatch，不执行 win32）**

新建 `tests/test_app_print_media.py`：

```python
from photoprint.app.main_window import MainWindow
from photoprint.core import store
from photoprint.win import gdi_print


class FakePrinterApi:
    def __init__(self, names=("Canon G3800", "Microsoft Print to PDF"), raise_enum=False):
        self._names = names
        self.raise_enum = raise_enum

    def enum_printers(self):
        if self.raise_enum:
            raise RuntimeError("no spooler")
        return list(self._names)


def _store(tmp_path):
    s = store.Store(tmp_path / "papers.json")     # 与既有测试同构：只读纸型表
    s.load()
    return s


def _landscape(tmp_path, name):
    from PIL import Image

    p = tmp_path / name
    Image.new("RGB", (400, 200), (255, 0, 0)).save(p)   # 横图、非正方（规避正方无牙陷阱）
    return str(p)


def _win(tmp_path, api=None, photos=1):
    w = MainWindow(st=_store(tmp_path), printer_api=api or FakePrinterApi())
    for i in range(photos):
        w.append_photo(_landscape(tmp_path, f"p{i}.png"))
    return w


def test_print_combo_filled_from_enum(qapp, tmp_path):
    w = _win(tmp_path)
    names = [w.printer_box.itemText(i) for i in range(w.printer_box.count())]
    assert names == ["Canon G3800", "Microsoft Print to PDF"]


def test_enum_failure_leaves_combo_empty_not_crash(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path), printer_api=FakePrinterApi(raise_enum=True))
    assert w.printer_box.count() == 0
    assert not w.printer_box.isEnabled()


def test_on_print_sends_all_pages_and_ok_status(qapp, tmp_path, monkeypatch):
    seen = {}

    def fake_print_pages(api, printer, images, sheet, dpi, *, prompt=True):
        seen["n"] = len(images)
        seen["printer"] = printer
        seen["prompt"] = prompt
        return {"ok": True, "pages": len(images), "message": ""}

    monkeypatch.setattr(gdi_print, "print_pages", fake_print_pages)
    w = _win(tmp_path, photos=5)      # 5 张 3R 上 A4 会多页
    w._on_print()
    assert seen["prompt"] is True
    assert seen["n"] == w.job.page_count            # I-2：全部页
    assert seen["n"] >= 1
    assert "已发送" in w.statusBar().currentMessage()


def test_on_print_failure_red_status(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(gdi_print, "print_pages",
                        lambda *a, **k: {"ok": False, "pages": 0, "message": "缺纸"})
    w = _win(tmp_path)
    w._on_print()
    assert "缺纸" in w.statusBar().currentMessage()


def test_on_print_no_printer_selected_does_not_call(qapp, monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(gdi_print, "print_pages",
                        lambda *a, **k: called.append(1))
    w = _win(tmp_path, api=FakePrinterApi(names=()), photos=1)  # 有图但无打印机
    w._on_print()
    assert not called
    assert "打印机" in w.statusBar().currentMessage()


def test_on_print_exception_contained_no_raise(qapp, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("driver exploded")

    monkeypatch.setattr(gdi_print, "print_pages", boom)
    w = _win(tmp_path)
    w._on_print()                    # 不得抛（窗口化 exe 静默闪退防线）
    assert "driver exploded" in w.statusBar().currentMessage()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_app_print_media.py -q`
Expected: FAIL（`MainWindow.__init__() got an unexpected keyword argument 'printer_api'` / 无 `printer_box`）。

- [ ] **Step 3a: 实现——imports 与 `__init__` 注入**

`photoprint/app/main_window.py` 顶部 QtWidgets import 列表加入 `QApplication`（按字母序，`QApplication` 置于 `QComboBox` 前）：

```python
from PySide6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QFileDialog,
                               QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QPushButton, QSlider,
                               QVBoxLayout, QWidget)
```

`__init__` 签名与建 UI 前，加入 api 注入（懒导入，避免无谓拉 win.api）：

```python
    def __init__(self, st=None, printer_api=None):
        super().__init__()
        if printer_api is None:
            from photoprint.win.api import RealWinApi
            printer_api = RealWinApi()
        self.api = printer_api
        self.st = st if st is not None else store.Store()
```

（其余原 `__init__` 体不动；在 `self._build_ui()` 之后、`self._debounce` 建立之前，加一行 `self._load_printers()`。）

- [ ] **Step 3b: 实现——`_build_ui` 打印机下拉与打印按钮**

把导航行 `nav` 段（现有 `export_btn` 附近）替换为：

```python
        nav = QHBoxLayout()
        self.prev_btn = QPushButton("上一页")
        self.next_btn = QPushButton("下一页")
        self.prev_btn.clicked.connect(lambda: self._go_page(-1))
        self.next_btn.clicked.connect(lambda: self._go_page(1))
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.next_btn)
        nav.addStretch(1)
        self.printer_box = QComboBox()
        self.printer_box.setObjectName("printer_box")
        nav.addWidget(self.printer_box)
        self.print_btn = QPushButton("打印…")
        self.print_btn.setObjectName("print_btn")
        self.print_btn.clicked.connect(self._on_print)
        nav.addWidget(self.print_btn)
        self.export_btn = QPushButton("导出 PDF…")
        self.export_btn.clicked.connect(self._on_export)
        nav.addWidget(self.export_btn)
        outer.addLayout(nav)
```

- [ ] **Step 3c: 实现——`_load_printers` 与 `_on_print`**

在"导出"段（`_on_export` 之后）追加：

```python
    # ---------- 打印 ----------

    def _load_printers(self):
        """填充打印机下拉。win32 异常（无后台打印程序/未装 pywin32）→ 留空、
        禁用、不崩——窗口化 exe 无控制台，抛出去即静默闪退。"""
        self.printer_box.clear()
        try:
            names = list(self.api.enum_printers())
        except Exception:
            names = []
        for n in names:
            self.printer_box.addItem(n)
        self.printer_box.setEnabled(bool(names))

    def _on_print(self):
        """直打全部页：先同步落最新 job（含旋转/偏移），渲染交 render_all（关遮罩，
        I-2），走 gdi_print.print_pages(prompt=True) 弹驱动页选介质。异常全兜成
        状态栏，不外抛。"""
        from photoprint.win import gdi_print

        self._debounce.stop()
        try:
            self._rebuild_job()
        except Exception as exc:
            self._set_status(f"排版失败：{exc}", error=True)
            return
        if self.job is None or not any(ph is not None for ph in self.photos):
            self._set_status("没有可打印的照片", error=True)
            return
        printer = self.printer_box.currentText()
        if not printer:
            self._set_status("未检测到可用打印机", error=True)
            return
        dpi = self._params()["dpi"]
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            images = jobs.render_all(self.job, dpi, show_mask=False)   # I-2
            res = gdi_print.print_pages(self.api, printer, images,
                                        self.job.sheet, dpi, prompt=True)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            self._set_status(f"打印失败：{exc}", error=True)
            return
        QApplication.restoreOverrideCursor()
        if res["ok"]:
            self._set_status(f"已发送 {res['pages']} 页到 {printer}")
        else:
            self._set_status(f"未打印：{res['message']}", error=True)
```

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `python -m pytest tests/test_app_print_media.py -q` → 全 PASS。
Run: `python -m pytest tests/ -q` → 281 passed，0 failed（既有用例因 `__init__` 新增懒导入 RealWinApi 仍全绿：默认打印机枚举被 `_load_printers` try 兜住）。

- [ ] **Step 5: Commit**

```powershell
git add photoprint/app/main_window.py tests/test_app_print_media.py
git commit -m "feat(gui): 增加打印机下拉与「打印…」按钮，点打印弹驱动页选介质直打全部页"
```

---

### Task 5: 全量验收 + README + 真机手工

**Files:**
- Modify: `README.md`
- 无代码改动；任一步变红回到对应 Task 修复后重跑。

- [ ] **Step 1: 全量测试**

Run: `python -m pytest tests/ -q`
Expected: 281 passed，0 failed。

- [ ] **Step 2: 内核比对脚本（不改动、必须仍绿）**

Run: `python _lab/m1m2_check.py`
Expected: 全 OK、exit 0。

- [ ] **Step 3: GUI/CLI parity 脚本（不改动、必须仍 OK）**

Run: `python _lab/check_gui_cli_parity.py`
Expected: 全 True、exit 0（`print_job(prompt=False)` 与 CLI/PDF 路径零回归）。

- [ ] **Step 4: README 增补 GUI 打印段**

在 `README.md` 的"### 图形界面"段之后插入：

```markdown
### 在界面里直接打印（选介质）
选中打印机 → 调好纸张/格子/模式 → 点「打印…」→ 弹出佳能驱动设置页，在其中选
「介质类型」（如 高级光面照片纸 II）→ 确定即直打全部页。本工具保证自定义纸张尺寸
不被驱动页重置；介质与无边距等由驱动自身管理、色彩走驱动对应的墨量/ICC 曲线。
仍建议先在驱动"打印首选项"里建好 3R 自定义纸张表单（见下）。
```

- [ ] **Step 5: Commit**

```powershell
git add README.md
git commit -m "docs: README 增补界面直打与介质选择说明"
```

- [ ] **Step 6: 真机手工核对（需交互桌面 + 已连 G3800，与用户同做）**

1. `powershell -File build_exe.ps1` 重建 exe（本增量改了 win/app，必须重打包）。
2. 启动 `dist\PhotoPrint.exe`，加那张 1870×1071 横图，A4 + 3R + 完整放入，选中点「旋转 90°」（横转竖占格更高）。
3. 打印机下拉选到 G3800，点「打印…」→ 确认驱动设置页弹出、介质下拉里能看到并选"高级光面照片纸 II"等 8 项 → 确定。
4. 观察出片：色彩/墨量随所选介质变化，与同介质佳能 App 比色接近；纸张尺寸仍是请求的 3R/A4 未被重置（I-1）。
5. 驱动页点"取消"→ 应不打印、状态栏提示；无可用打印机 → 「打印…」点击即提示、不崩。

（步骤 4–5 只能在真机验证，是本增量验收的必要组成。）

---

## Self-Review 记录

- **规格覆盖**：spec §1 做/不做 → Task 1–4 逐项（prompt_devmode/build_with_prompt/print_pages/GUI）；§2 I-1 → Task 2 `test_geometry_reapplied_after_prompt_keeps_media`，I-2 → Task 4 `test_on_print_sends_all_pages_and_ok_status`；§3 接口签名逐条对应；§4 界面 → Task 4；§5 错误处理表 6 行 → Task 2（弹窗降级）/3（异常兜 message/空图）/4（无打印机/枚举失败/打印异常/无照片）；§6 测试方案 → 三个新测试文件 + 既有冻结回归；§7 验收 → Task 5。
- **占位符扫描**：无 TBD/TODO；各 Step 均给完整代码。
- **类型一致性**：`print_pages(api, printer, images, sheet, dpi, *, prompt=True)` 在 Task 3 定义、Task 4 引用一致；`build_with_prompt(...) -> (dm, size)` Task 2 定义、Task 3 解包一致；`prompt_devmode(self, handle, printer, dm)` Task 1 定义、Task 2 FakeApi 契约一致；`printer_box`/`print_btn`/`_load_printers`/`_on_print` 命名跨 Task 统一；`render_all(job, dpi, show_mask)` 与既有 `jobs.py` 签名一致。
- **测试图有牙**：GUI/打印相关断图一律用 400×200 非对称图（旋转/页数可辨），规避"纯色/正方图无牙"陷阱。
