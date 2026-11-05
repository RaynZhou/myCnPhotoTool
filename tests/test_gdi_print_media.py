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
