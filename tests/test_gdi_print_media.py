"""print_pages 编排层测试：只验数据/控制流交接，DC+StretchBlt 交真机。
_emit 被 monkeypatch，故本文件全程不 import win32（gdi_print 顶部也不 import）。"""
import types

from photoprint.win import devmode, gdi_print
from photoprint.win.api import PromptCancelled


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
        return ("DM", 520, False)

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
        return ("DM", 520, False)

    monkeypatch.setattr(devmode, "build_with_prompt", fake_build)
    monkeypatch.setattr(gdi_print, "_emit",
                        lambda *a, **k: {"ok": True, "pages": 1, "message": ""})
    res = gdi_print.print_job(object(), "P", None, _imgs(1), Sheet, 300)
    assert seen["prompt"] is False       # CLI 冻结：绝不弹窗
    assert res == {"ok": True, "pages": 1, "message": ""}   # 返回值原样透传


def test_build_failure_cli_keeps_legacy_prefix(monkeypatch):
    """CLI（prompt=False）取设置失败的文案必须逐字冻结为旧串“打印失败：”，
    不得因为 print_pages 新增分区前缀而改变（全局约束 L18）。"""
    def boom(*a, **k):
        raise RuntimeError("dm size 0")

    monkeypatch.setattr(devmode, "build_with_prompt", boom)
    res = gdi_print.print_job(object(), "P", None, _imgs(1), Sheet, 300)
    assert res["ok"] is False and res["pages"] == 0
    assert res["message"] == "打印失败：dm size 0"


def test_build_failure_gui_uses_media_prompt_prefix(monkeypatch):
    """GUI（prompt=True）取设置失败用更准的分区前缀“读取打印机设置失败：”。"""
    def boom(*a, **k):
        raise RuntimeError("offline")

    monkeypatch.setattr(devmode, "build_with_prompt", boom)
    res = gdi_print.print_pages(object(), "P", _imgs(1), Sheet, 300, prompt=True)
    assert res["message"].startswith("读取打印机设置失败：")


def test_build_failure_contained_no_raise(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("printer offline")

    monkeypatch.setattr(devmode, "build_with_prompt", boom)
    res = gdi_print.print_pages(object(), "P", _imgs(2), Sheet, 300)
    assert res["ok"] is False and "printer offline" in res["message"]


def test_prompt_cancel_returns_cancelled_not_error(monkeypatch):
    """W-1：build 阶段抛 PromptCancelled → print_pages 返回 cancelled=True、
    不发作业（不调 _emit），区别于普通失败。"""
    def cancel(*a, **k):
        raise PromptCancelled("cancelled")

    emit_calls = []
    monkeypatch.setattr(devmode, "build_with_prompt", cancel)
    monkeypatch.setattr(gdi_print, "_emit",
                        lambda *a, **k: emit_calls.append(1))
    res = gdi_print.print_pages(object(), "P", _imgs(2), Sheet, 300, prompt=True)
    assert res["cancelled"] is True and res["ok"] is False
    assert not emit_calls                    # 取消后不建 DC 不送图


def test_degraded_flag_propagates_on_success(monkeypatch):
    """W-3：build 回报 degraded=True 且打印成功 → 结果携 degraded 标志供 UI 提示。"""
    monkeypatch.setattr(devmode, "build_with_prompt",
                        lambda *a, **k: ("DM", 520, True))
    monkeypatch.setattr(gdi_print, "_emit",
                        lambda *a, **k: {"ok": True, "pages": 2, "message": ""})
    res = gdi_print.print_pages(object(), "P", _imgs(2), Sheet, 300, prompt=True)
    assert res["ok"] is True and res.get("degraded") is True


def test_emit_and_module_never_use_win32print_create_dc():
    """终审 C2：建 DC 走 win32gui（_create_dc），全模块不得出现 win32print。"""
    import inspect

    emit_src = inspect.getsource(gdi_print._emit)
    assert "win32ui.CreateDCFromHandle" in emit_src
    create_src = inspect.getsource(gdi_print._create_dc)
    assert "win32gui.CreateDC" in create_src
    mod_src = inspect.getsource(gdi_print)
    assert "win32print.CreateDC" not in mod_src   # 不得走不存 win32print.CreateDC
    assert "import win32print" not in mod_src      # 模块不拉 win32print（docstring 叙事不算）
