"""默认映射逐条对应规格 7.2；文案禁则对应 7.3。"""
import pytest

from photoprint.core import crop, modes, specs


def test_id_photo_always_fit():
    """证件照丢头即废片，无论纸张如何都用 fit。"""
    m = modes.default_mode(specs.find_spec("A4"), specs.find_spec("ID1"), 56)
    assert m == modes.FIT_TO_PRINTABLE
    assert modes.crop_mode(m) == crop.FIT


def test_custom_sheet_falls_back_to_fill_printable():
    """3R 只能自定义送纸 ⇒ 无法无边距，默认铺满可打印区。"""
    m = modes.default_mode(specs.find_spec("3R"), specs.find_spec("3R"), 1)
    assert m == modes.FILL_PRINTABLE


def test_borderless_sheet_multi_cell_uses_bleed_trim():
    m = modes.default_mode(specs.find_spec("A4"), specs.find_spec("3R"), 4)
    assert m == modes.BLEED_TRIM
    assert modes.crop_mode(m) == crop.FILL


def test_borderless_sheet_single_cell_no_trim_needed():
    """单格满版本身就铺满可打印区，不必裁切。"""
    m = modes.default_mode(specs.find_spec("A4"), specs.find_spec("A4"), 1)
    assert m == modes.FILL_PRINTABLE


def test_non_borderless_multi_cell_never_bleed_trim():
    """A5 无边距能力 ⇒ 不得推荐需要无边距的裁切模式。"""
    m = modes.default_mode(specs.find_spec("A5"), specs.find_spec("ID1"), 20)
    assert m != modes.BLEED_TRIM


def test_bleed_trim_target_is_full_sheet_and_others_are_printable():
    a4 = specs.find_spec("A4")
    p = specs.printable_rect(a4, borderless_active=True)
    t_bleed = modes.target_rect(a4, specs.find_spec("3R"), modes.BLEED_TRIM,
                                specs.RectMM(0, 0, 210, 297), True)
    t_fill = modes.target_rect(a4, specs.find_spec("3R"), modes.FILL_PRINTABLE,
                               p, True)
    assert (t_bleed.w_mm, t_bleed.h_mm) == (210.0, 297.0)
    assert (t_fill.w_mm, t_fill.h_mm) == (210.0, 297.0)  # 无边距生效时同为整纸


def test_bleed_trim_requires_borderless_capable_sheet():
    with pytest.raises(ValueError, match="无边距"):
        modes.assert_mode_legal(specs.find_spec("3R"), modes.BLEED_TRIM)


def test_default_bleed_is_three_mm():
    assert modes.DEFAULT_BLEED_MM == 3.0


def test_unknown_mode_rejected():
    with pytest.raises(ValueError, match="mode"):
        modes.crop_mode("fit_page")
