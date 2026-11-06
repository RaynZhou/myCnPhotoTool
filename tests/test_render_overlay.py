"""渲染集成：叠加开启改变目标角、关闭逐像素等于基线、默认参零影响。"""
import os

import pytest

pytest.importorskip("PIL", reason="需要 Pillow")

from PIL import Image  # noqa: E402

from photoprint.core import modes, pack, render, specs, text_overlay as to  # noqa: E402
from photoprint.core.text_overlay import Corner, TextSpec  # noqa: E402

DPI = 25.4


def _a4_id1():
    a4 = specs.find_spec("A4")
    plan = pack.pack(a4, specs.find_spec("ID1"), gap_mm=2.0, allow_rotate=False,
                     printable=specs.printable_rect(a4))
    return a4, plan


def _photo():
    return Image.new("RGB", (200, 100), (10, 20, 30))


def _render(a4, plan, photos, **kw):
    return render.render_page(plan, photos, a4, DPI, modes.FIT_TO_PRINTABLE,
                              show_mask=False, show_cut_lines=False, **kw)


@pytest.fixture
def real_font(monkeypatch):
    arial = os.path.join(r"C:\Windows\Fonts", "arial.ttf")
    if not os.path.isfile(arial):
        pytest.skip("无 arial 字体")
    monkeypatch.setattr(to, "FONT_TABLE", {"t": (arial, None)})


def test_no_overlay_params_equals_baseline(real_font):
    a4, plan = _a4_id1()
    ph = _photo()
    base = _render(a4, plan, [ph] * plan.count)
    got = _render(a4, plan, [ph] * plan.count, date_overlay=None,
                  watermark_overlay=None, date_texts=())
    assert got.tobytes() == base.tobytes()


def test_date_overlay_enabled_changes_pixels(real_font):
    a4, plan = _a4_id1()
    ph = _photo()
    base = _render(a4, plan, [ph] * plan.count)
    spec = TextSpec(enabled=True, font_key="t", size_mm=6.0, corner=Corner.TL,
                    rgb=(255, 255, 255), alpha=255)
    got = _render(a4, plan, [ph] * plan.count, date_overlay=spec,
                  date_texts=["2025-01-02"] * plan.count)
    assert got.tobytes() != base.tobytes()


def test_date_overlay_disabled_equals_baseline(real_font):
    a4, plan = _a4_id1()
    ph = _photo()
    base = _render(a4, plan, [ph] * plan.count)
    spec = TextSpec(enabled=False, font_key="t")
    got = _render(a4, plan, [ph] * plan.count, date_overlay=spec,
                  date_texts=["2025-01-02"] * plan.count)
    assert got.tobytes() == base.tobytes()


def test_date_text_none_skips_that_photo(real_font):
    a4, plan = _a4_id1()
    ph = _photo()
    base = _render(a4, plan, [ph] * plan.count)
    spec = TextSpec(enabled=True, font_key="t", size_mm=6.0, corner=Corner.TL,
                    rgb=(255, 255, 255), alpha=255)
    got = _render(a4, plan, [ph] * plan.count, date_overlay=spec,
                  date_texts=[None] * plan.count)
    assert got.tobytes() == base.tobytes()


def test_date_overrides_apply_per_cell(real_font):
    a4, plan = _a4_id1()
    ph = _photo()
    spec = TextSpec(enabled=True, font_key="t", size_mm=6.0, corner=Corner.TL,
                    rgb=(255, 255, 255), alpha=255)
    # 同一份 spec（TL）：不带 override 画在 TL，带 override 逐格改 BR
    at_tl = _render(a4, plan, [ph] * plan.count, date_overlay=spec,
                    date_texts=["2025-01-02"] * plan.count)
    ov = [(Corner.BR, 0)] * plan.count
    at_br = _render(a4, plan, [ph] * plan.count, date_overlay=spec,
                    date_texts=["2025-01-02"] * plan.count, date_overrides=ov)
    assert at_br.tobytes() != at_tl.tobytes()            # 逐格覆盖真的挪了角


def test_overrides_default_empty_equals_base(real_font):
    a4, plan = _a4_id1()
    ph = _photo()
    spec = TextSpec(enabled=True, font_key="t", size_mm=6.0, corner=Corner.TL,
                    rgb=(255, 255, 255), alpha=255)
    none = _render(a4, plan, [ph] * plan.count, date_overlay=spec,
                   date_texts=["2025-01-02"] * plan.count)
    empty = _render(a4, plan, [ph] * plan.count, date_overlay=spec,
                    date_texts=["2025-01-02"] * plan.count, date_overrides=())
    assert none.tobytes() == empty.tobytes()             # 默认空＝向后兼容


def test_override_none_element_uses_base(real_font):
    a4, plan = _a4_id1()
    ph = _photo()
    spec = TextSpec(enabled=True, font_key="t", size_mm=6.0, corner=Corner.TL,
                    rgb=(255, 255, 255), alpha=255)
    ov = [None] * plan.count
    got = _render(a4, plan, [ph] * plan.count, date_overlay=spec,
                  date_texts=["2025-01-02"] * plan.count, date_overrides=ov)
    assert got.tobytes() == _render(a4, plan, [ph] * plan.count,
                                    date_overlay=spec,
                                    date_texts=["2025-01-02"] * plan.count).tobytes()
