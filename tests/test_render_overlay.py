"""渲染集成：叠加开启改变目标角、关闭逐像素等于基线、默认参零影响。"""
import os

import pytest

pytest.importorskip("PIL", reason="需要 Pillow")

from PIL import Image  # noqa: E402

from photoprint.core import modes, pack, render, specs, text_overlay as to  # noqa: E402
from photoprint.core import units  # noqa: E402
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


def test_date_cells_gate_each_cell(real_font):
    """逐格开关：只给打了勾的格加字，其余格逐像素等于基线。

    界面层“只对蓝框那张生效”最终就落在这一层：光标对不代表没写错，
    所以这里按格子外框逐区比对（字若溢出到邻格也会被抓到）。
    """
    a4, plan = _a4_id1()
    ph = _photo()
    spec = TextSpec(enabled=True, font_key="t", size_mm=6.0, corner=Corner.TL,
                    rgb=(255, 255, 255), alpha=255)
    base = _render(a4, plan, [ph] * plan.count)
    flags = [True] + [False] * (plan.count - 1)
    got = _render(a4, plan, [ph] * plan.count, date_overlay=spec,
                  date_texts=["2025-01-02"] * plan.count, date_cells=flags)
    assert got.tobytes() != base.tobytes()               # 第 1 格真多出了字
    px_w, px_h = got.size
    for c in plan.cells[1:4]:                           # 关掉的那几格：一尘不染
        box = (max(0, units.mm_to_px(c.x_mm, DPI)),
               max(0, units.mm_to_px(c.y_mm, DPI)),
               min(px_w, units.mm_to_px(c.x_mm + c.w_mm, DPI)),
               min(px_h, units.mm_to_px(c.y_mm + c.h_mm, DPI)))
        assert got.crop(box).tobytes() == base.crop(box).tobytes()


def test_wm_cells_gate_is_independent_from_date(real_font):
    """日期与水印各有一套逐格开关：只勾水印不会把日期也带上。"""
    a4, plan = _a4_id1()
    ph = _photo()
    d_spec = TextSpec(enabled=True, font_key="t", size_mm=6.0, corner=Corner.TL,
                      rgb=(255, 255, 255), alpha=255)
    w_spec = TextSpec(enabled=True, text="W", font_key="t", size_mm=6.0,
                      corner=Corner.BR, rgb=(255, 255, 255), alpha=255)
    only_wm = _render(a4, plan, [ph] * plan.count, date_overlay=d_spec,
                      watermark_overlay=w_spec,
                      date_texts=["2025-01-02"] * plan.count,
                      wm_cells=[True] + [False] * (plan.count - 1))
    neither = _render(a4, plan, [ph] * plan.count, date_overlay=d_spec,
                      watermark_overlay=w_spec,
                      date_texts=["2025-01-02"] * plan.count,
                      date_cells=[False] * plan.count,
                      wm_cells=[False] * plan.count)
    assert only_wm.tobytes() != neither.tobytes()
    assert only_wm.tobytes() != _render(
        a4, plan, [ph] * plan.count, date_overlay=d_spec,
        watermark_overlay=w_spec, date_texts=["2025-01-02"] * plan.count).tobytes()
