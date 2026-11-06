"""叠加文字的纯几何：字号 dpi 无关、四角锚点、内缩边距。"""
import os

import pytest

pytest.importorskip("PIL", reason="需要 Pillow")

from PIL import Image  # noqa: E402

from photoprint.core import units  # noqa: E402
from photoprint.core import text_overlay as to  # noqa: E402
from photoprint.core.text_overlay import (Corner, TextSpec, FONT_TABLE,  # noqa: E402
                                          size_px, inset_px, anchor_point)


def test_size_px_scales_with_dpi():
    # 同一 size_mm，dpi 越大像素越多（1px=1mm 时 size_mm 就是像素高）
    assert size_px(4.0, 25.4) == 4
    assert size_px(4.0, 25.4 * 3) == 12


def test_size_px_never_zero():
    assert size_px(0.0, 25.4) == 1


def test_inset_px_is_pct_of_short_edge():
    assert inset_px(10.0, (200, 100)) == 10          # 短边 100 的 10%
    assert inset_px(4.0, (200, 250)) == 8            # 短边 200 的 4%


def test_anchor_point_four_corners():
    cw, ch, tw, th, ins = 100, 80, 30, 20, 4
    assert anchor_point(Corner.TL, (cw, ch), (tw, th), ins) == (4, 4)
    assert anchor_point(Corner.TR, (cw, ch), (tw, th), ins) == (100 - 30 - 4, 4)
    assert anchor_point(Corner.BL, (cw, ch), (tw, th), ins) == (4, 80 - 20 - 4)
    assert anchor_point(Corner.BR, (cw, ch), (tw, th), ins) == (100 - 30 - 4, 80 - 20 - 4)


def test_textspec_defaults_and_font_table_shape():
    s = TextSpec()
    assert s.enabled is False and s.corner == Corner.BR and s.alpha == 255
    for key, (reg, bold) in FONT_TABLE.items():
        assert isinstance(reg, str) and (bold is None or isinstance(bold, str))


def _arial():
    p = os.path.join(r"C:\Windows\Fonts", "arial.ttf")
    return p if os.path.isfile(p) else None


def _spec(**kw):
    base = dict(enabled=True, font_key="t", size_mm=24.0, weight="normal",
                corner=Corner.TL, rgb=(255, 0, 0), alpha=255, margin_pct=4.0)
    base.update(kw)
    return TextSpec(**base)


def test_draw_overlay_solid_glyph_present(monkeypatch):
    arial = _arial()
    if arial is None:
        pytest.skip("无 arial 字体")
    monkeypatch.setattr(to, "FONT_TABLE", {"t": (arial, None)})
    page = Image.new("RGB", (200, 120), (0, 0, 0))
    to.draw_overlay(page, (0, 0, 200, 120), _spec(), "DATE", 25.4)
    assert max(p[0] for p in page.getdata()) == 255      # 实心红


def test_draw_overlay_alpha_is_semi(monkeypatch):
    arial = _arial()
    if arial is None:
        pytest.skip("无 arial 字体")
    monkeypatch.setattr(to, "FONT_TABLE", {"t": (arial, None)})
    page = Image.new("RGB", (200, 120), (0, 0, 0))
    to.draw_overlay(page, (0, 0, 200, 120), _spec(alpha=128), "DATE", 25.4)
    peak = max(p[0] for p in page.getdata())
    assert 0 < peak < 255                                 # 半透明压在黑底上


def test_draw_overlay_clips_to_cell(monkeypatch):
    arial = _arial()
    if arial is None:
        pytest.skip("无 arial 字体")
    monkeypatch.setattr(to, "FONT_TABLE", {"t": (arial, None)})
    page = Image.new("RGB", (300, 300), (0, 0, 0))
    to.draw_overlay(page, (50, 50, 100, 100), _spec(), "MD", 25.4)
    # 格 (50..150,50..150) 之外一律零污染（验逐格 clip + 落位偏移）
    assert page.crop((150, 150, 300, 300)).getbbox() is None
    assert page.crop((0, 0, 50, 300)).getbbox() is None


def test_draw_overlay_missing_font_skips(monkeypatch):
    monkeypatch.setattr(to, "FONT_TABLE", {"t": (r"C:\nope\no.ttf", None)})
    page = Image.new("RGB", (200, 120), (0, 0, 0))
    to.draw_overlay(page, (0, 0, 200, 120), _spec(), "DATE", 25.4)
    assert page.getbbox() is None                           # 未画、未抛


def test_draw_overlay_disabled_or_empty_noop(monkeypatch):
    arial = _arial()
    if arial is None:
        pytest.skip("无 arial 字体")
    monkeypatch.setattr(to, "FONT_TABLE", {"t": (arial, None)})
    page = Image.new("RGB", (200, 120), (0, 0, 0))
    to.draw_overlay(page, (0, 0, 200, 120), _spec(enabled=False), "DATE", 25.4)
    to.draw_overlay(page, (0, 0, 200, 120), _spec(), "", 25.4)
    assert page.getbbox() is None


def test_draw_overlay_bold_stroke_fallback_when_no_bold_file(monkeypatch):
    arial = _arial()
    if arial is None:
        pytest.skip("无 arial 字体")
    monkeypatch.setattr(to, "FONT_TABLE", {"t": (arial, None)})   # 无粗体文件
    page = Image.new("RGB", (200, 120), (0, 0, 0))
    to.draw_overlay(page, (0, 0, 200, 120), _spec(weight="bold"), "WWW", 25.4)
    assert max(p[0] for p in page.getdata()) == 255               # stroke 合成仍画出


def test_textspec_rotation_default_and_presets():
    assert TextSpec().rotation == 0
    assert to.ROTATION_PRESETS == (0, 45, 90, 135, 180, 225, 270, 315)


def test_draw_overlay_rotation_zero_equals_direct(monkeypatch):
    arial = _arial()
    if arial is None:
        pytest.skip("无 arial 字体")
    monkeypatch.setattr(to, "FONT_TABLE", {"t": (arial, None)})
    a = Image.new("RGB", (200, 120), (0, 0, 0))
    to.draw_overlay(a, (0, 0, 200, 120), _spec(rotation=0), "DATE", 25.4)
    b = Image.new("RGB", (200, 120), (0, 0, 0))
    to.draw_overlay(b, (0, 0, 200, 120), _spec(), "DATE", 25.4)
    assert a.tobytes() == b.tobytes()                    # 0° 逐像素等于直绘


def test_draw_overlay_rotation_90_changes_pixels(monkeypatch):
    arial = _arial()
    if arial is None:
        pytest.skip("无 arial 字体")
    monkeypatch.setattr(to, "FONT_TABLE", {"t": (arial, None)})
    base = Image.new("RGB", (200, 120), (0, 0, 0))
    to.draw_overlay(base, (0, 0, 200, 120), _spec(corner=Corner.TL), "WIDE", 25.4)
    rot = Image.new("RGB", (200, 120), (0, 0, 0))
    to.draw_overlay(rot, (0, 0, 200, 120),
                    _spec(corner=Corner.TL, rotation=90), "WIDE", 25.4)
    assert rot.tobytes() != base.tobytes()               # 非对称长文字：旋转有牙
    assert max(p[0] for p in rot.getdata()) == 255       # 仍实心红


def test_draw_overlay_rotation_clips_to_cell(monkeypatch):
    arial = _arial()
    if arial is None:
        pytest.skip("无 arial 字体")
    monkeypatch.setattr(to, "FONT_TABLE", {"t": (arial, None)})
    page = Image.new("RGB", (300, 300), (0, 0, 0))
    to.draw_overlay(page, (50, 50, 100, 100),
                    _spec(corner=Corner.BR, rotation=45), "MD", 25.4)
    assert page.crop((150, 150, 300, 300)).getbbox() is None
    assert page.crop((0, 0, 50, 300)).getbbox() is None


def test_draw_overlay_rotation_overflow_skips(monkeypatch):
    arial = _arial()
    if arial is None:
        pytest.skip("无 arial 字体")
    monkeypatch.setattr(to, "FONT_TABLE", {"t": (arial, None)})
    ok = Image.new("RGB", (200, 60), (0, 0, 0))
    to.draw_overlay(ok, (0, 0, 200, 60), _spec(rotation=0), "WATERMARK", 25.4)
    assert ok.getbbox() is not None                      # 不旋转塞得下（对照）
    page = Image.new("RGB", (200, 60), (0, 0, 0))
    to.draw_overlay(page, (0, 0, 200, 60), _spec(rotation=45), "WATERMARK", 25.4)
    assert page.getbbox() is None                        # 旋转后包围盒超格→不画不抛
