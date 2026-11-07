"""print_pages 编排层测试：只验数据/控制流交接，DC+StretchBlt 交真机。
_emit 被 monkeypatch，故本文件全程不 import win32（gdi_print 顶部也不 import）。"""
import types

from photoprint.win import devmode, forms, gdi_print, media
from photoprint.win.api import PromptCancelled


class Sheet:
    w_mm, h_mm, label, driver_paper_code = 89.0, 127.0, "3R", None


class SheetWithCode:
    """带静态表单码的纸：用来证“无匹配表单时退回静态码”。"""

    w_mm, h_mm, label, driver_paper_code = 152.0, 203.0, "6R", 42


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


# ---------- 驱动表单绑定（spec 2026-11-07） ----------

L_89x127 = forms.PaperForm(126, "L 89x127mm", 88.98, 127.0)
TEN_BY_FIFTEEN = forms.PaperForm(122, '10x15cm 4"x6"', 101.6, 152.4)


def _capture(monkeypatch):
    """替换 build 与 emit，只记录交接参数。"""
    seen = {}

    def fake_build(api, printer, w, h, code, prompt=False):
        seen["code"] = code
        return (types.SimpleNamespace(PaperSize=code or 259), 520, False)

    def fake_emit(api, printer, dm, images, sheet, dpi, **kw):
        seen["target"] = kw.get("target_mm")
        return {"ok": True, "pages": len(images), "message": ""}

    monkeypatch.setattr(devmode, "build_with_prompt", fake_build)
    monkeypatch.setattr(gdi_print, "_emit", fake_emit)
    return seen


def test_matched_form_code_reaches_devmode_and_verify_target(monkeypatch):
    """命中表单：DEVMODE 用真实表单码，物理校验目标取表单实测尺寸。"""
    seen = _capture(monkeypatch)
    res = gdi_print.print_pages(object(), "P", _imgs(1), Sheet, 300,
                                forms=[L_89x127])
    assert seen["code"] == 126                 # 不是 None（旧行为是自定义尺寸）
    assert seen["target"] == (88.98, 127.0)    # 不是标称 89×127
    assert res["paper_form"] == {"code": 126, "name": "L 89x127mm",
                                 "w_mm": 88.98, "h_mm": 127.0}


def test_unmatched_form_falls_back_to_sheet_code(monkeypatch):
    """无匹配：退回静态码，且调用形状/返回值与升级前逐字一致。"""
    seen = _capture(monkeypatch)
    res = gdi_print.print_pages(object(), "P", _imgs(1), SheetWithCode, 300,
                                forms=[TEN_BY_FIFTEEN])
    assert seen["code"] == 42
    assert seen["target"] is None          # 不传 target_mm ⇒ 旧调用形状
    assert "paper_form" not in res
    assert res == {"ok": True, "pages": 1, "message": ""}


def test_no_forms_keeps_today_behaviour(monkeypatch):
    seen = _capture(monkeypatch)
    res = gdi_print.print_pages(object(), "P", _imgs(2), Sheet, 300)
    assert seen["code"] is None and seen["target"] is None
    assert "paper_form" not in res


def test_custom_size_reset_gets_explicit_reason(monkeypatch):
    """驱动把自定义尺寸重置成别的表单时必须点名原因，而不是笼统说“忽略了尺寸”。"""
    monkeypatch.setattr(devmode, "build_with_prompt",
                        lambda *a, **k: (types.SimpleNamespace(PaperSize=9), 520, False))
    monkeypatch.setattr(gdi_print, "_emit", lambda *a, **k: {
        "ok": False, "pages": 0,
        "message": "驱动忽略了自定义尺寸：请求 89.00×127.00mm，设备实际 209.97×296.97mm"})
    res = gdi_print.print_pages(object(), "P", _imgs(1), Sheet, 300)
    assert res["ok"] is False
    assert "不接受程序化自定义尺寸" in res["message"]
    assert "导出 PDF" in res["message"]


def test_custom_rejected_note_absent_when_form_used(monkeypatch):
    """用了驱动表单就不该再提自定义尺寸被拒（避免误报）。"""
    monkeypatch.setattr(devmode, "build_with_prompt",
                        lambda *a, **k: (types.SimpleNamespace(PaperSize=126), 520, False))
    monkeypatch.setattr(gdi_print, "_emit", lambda *a, **k: {
        "ok": False, "pages": 0, "message": "纸没放好"})
    res = gdi_print.print_pages(object(), "P", _imgs(1), Sheet, 300,
                                forms=[L_89x127])
    assert "不接受程序化自定义尺寸" not in res["message"]


def test_target_size_helper_defaults_to_nominal():
    assert gdi_print._target_size(Sheet, None) == (89.0, 127.0)
    assert gdi_print._target_size(Sheet, (88.98, 127.0)) == (88.98, 127.0)


# ---- 介质类型 / 打印质量透传（spec 2026-11-07）--------------------------

def _capture_build(monkeypatch):
    """记录 build_with_prompt 收到的全部参数，并让 _emit 成功。"""
    seen = {}

    def fake_build(*args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return ("DM", 520, False)

    monkeypatch.setattr(devmode, "build_with_prompt", fake_build)
    monkeypatch.setattr(gdi_print, "_emit", lambda *a, **k: {
        "ok": True, "pages": 1, "message": ""})
    return seen


def test_media_and_quality_reach_build(monkeypatch):
    seen = _capture_build(monkeypatch)
    opt = media.MediaOption(303, "高级光面照片纸 II")
    res = gdi_print.print_pages(object(), "P", _imgs(1), Sheet, 300,
                                media=opt, quality=media.QUALITY_HIGH)
    assert seen["kwargs"]["media"] is opt
    assert seen["kwargs"]["quality"] == -4
    assert res["media_note"] == "介质 高级光面照片纸 II · 质量 高"


def test_default_call_shape_is_unchanged(monkeypatch):
    """不传 media/quality 时不得把它们作为 None 塞给 build（调用形状冻住）。"""
    seen = _capture_build(monkeypatch)
    res = gdi_print.print_pages(object(), "P", _imgs(1), Sheet, 300, prompt=False)
    assert set(seen["kwargs"]) == {"prompt"}
    assert len(seen["args"]) == 5, "位置参数仍是 api/printer/w/h/code，未增"
    assert "media_note" not in res      # 返回值形状也不变


def test_media_note_absent_when_only_defaults(monkeypatch):
    _capture_build(monkeypatch)
    res = gdi_print.print_pages(object(), "P", _imgs(1), Sheet, 300)
    assert "media_note" not in res


def test_print_job_forwards_media_and_quality(monkeypatch):
    seen = _capture_build(monkeypatch)
    gdi_print.print_job(object(), "P", None, _imgs(1), Sheet, 300,
                        media=303, quality=-4)
    assert seen["kwargs"]["media"] == 303
    assert seen["kwargs"]["quality"] == -4
    assert seen["kwargs"]["prompt"] is False

