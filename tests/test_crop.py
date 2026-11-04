"""裁放置：用 dpi=25.4 让 1 像素 = 1 毫米，便于逐位核对。"""
import pytest

from photoprint.core import crop, units

PPMM = 1.0  # dpi 25.4


def test_fill_minimal_cover_crops_sides():
    p = crop.cell_crop_box(200, 100, 100, 100, crop.FILL, ppmm=PPMM)
    assert p.crop_px == (50, 0, 150, 100)
    assert p.dest_mm == (0.0, 0.0, 100.0, 100.0)


def test_fill_zoom_2_shrinks_crop():
    p = crop.cell_crop_box(200, 100, 100, 100, crop.FILL, zoom=2.0, ppmm=PPMM)
    assert p.crop_px == (75, 25, 125, 75)


def test_fill_dx_moves_crop_and_clamps_inside_photo():
    p = crop.cell_crop_box(200, 100, 100, 100, crop.FILL, zoom=2.0, dx_mm=10.0,
                           ppmm=PPMM)
    assert p.crop_px == (80, 25, 130, 75)
    far = crop.cell_crop_box(200, 100, 100, 100, crop.FILL, zoom=2.0, dx_mm=500.0,
                             ppmm=PPMM)
    # 钳制在原图内 ⇒ 绝不出现白边
    assert far.crop_px[2] == 200
    assert far.crop_px[0] == 150


def test_fill_never_exceeds_photo_bounds_at_min_zoom():
    p = crop.cell_crop_box(200, 100, 100, 100, crop.FILL, zoom=1.0, dx_mm=-999,
                           dy_mm=-999, ppmm=PPMM)
    l, t, r, b = p.crop_px
    assert l == 0 and t == 0
    assert r <= 200 and b <= 100


def test_fit_keeps_whole_image_and_letterboxes():
    p = crop.cell_crop_box(200, 100, 100, 100, crop.FIT, ppmm=PPMM)
    assert p.crop_px == (0, 0, 200, 100)
    x, y, w, h = p.dest_mm
    assert (w, h) == pytest.approx((100.0, 50.0))
    assert x == pytest.approx(0.0)
    assert y == pytest.approx(25.0)  # 上下各留 25mm 白边


def test_fit_zoom_half_shrinks_dest():
    p = crop.cell_crop_box(200, 100, 100, 100, crop.FIT, zoom=0.5, ppmm=PPMM)
    x, y, w, h = p.dest_mm
    assert (w, h) == pytest.approx((50.0, 25.0))
    assert (x, y) == pytest.approx((25.0, 37.5))


def test_fit_dx_clamped_inside_target():
    p = crop.cell_crop_box(200, 100, 100, 100, crop.FIT, zoom=0.5, dx_mm=999,
                           ppmm=PPMM)
    assert p.dest_mm[0] == pytest.approx(50.0)  # 100 - 50，不得越出目标区


def test_zoom_bounds_are_enforced():
    with pytest.raises(ValueError, match="zoom"):
        crop.cell_crop_box(200, 100, 100, 100, crop.FILL, zoom=0.5, ppmm=PPMM)
    with pytest.raises(ValueError, match="zoom"):
        crop.cell_crop_box(200, 100, 100, 100, crop.FIT, zoom=1.5, ppmm=PPMM)


def test_default_ppmm_accepted():
    """解析结果对 ppmm 不变（分子分母同现被约掉），本条钉不住「默认=300dpi」；
    它钉的是默认值不为 None 也能算完、不触守卫（评审 I-3，原名
    test_default_ppmm_is_300dpi 名不副实）。"""
    p = crop.cell_crop_box(200, 100, 100, 100, crop.FILL)
    assert p.crop_px == (50, 0, 150, 100)


def test_unknown_mode_rejected():
    with pytest.raises(ValueError, match="mode"):
        crop.cell_crop_box(200, 100, 100, 100, "stretch", ppmm=PPMM)


def test_fill_zoom_upper_bound_enforced():
    # 评审 I-2：原 test_zoom_bounds_are_enforced 只钉了 FILL 下界与 FIT 上界
    with pytest.raises(ValueError, match="zoom"):
        crop.cell_crop_box(200, 100, 100, 100, crop.FILL, zoom=4.5, ppmm=PPMM)


def test_fit_zoom_lower_bound_enforced():
    with pytest.raises(ValueError, match="zoom"):
        crop.cell_crop_box(200, 100, 100, 100, crop.FIT, zoom=0.1, ppmm=PPMM)


def test_fit_aspect_ratio_preserved_on_non_square_target():
    """评审 I-2：正方形目标下 min() 两支数值相等，钉不住退化为只按宽缩放。"""
    p = crop.cell_crop_box(200, 100, 400, 50, crop.FIT, ppmm=PPMM)
    x, y, w, h = p.dest_mm
    assert (w, h) == pytest.approx((100.0, 50.0))  # 按宽缩放会得 400×200 越格
    assert (x, y) == pytest.approx((150.0, 0.0))


def test_fill_crop_box_uses_half_up_rounding():
    """评审 I-1：未取整的 l 恰为 36.5，必须按全项目 round_px 口径得 37，
    而非银行家舍入的 36。"""
    p = crop.cell_crop_box(100, 80, 100, 152, crop.FILL, zoom=2,
                           dx_mm=-1.3, ppmm=units.ppmm(300))
    assert p.crop_px == (37, 20, 63, 60)


def test_zero_area_crop_box_keeps_at_least_one_pixel():
    """终审 Minor：极端长宽比会让裁框取整成零宽/零高（r == l），

    那会 crop 出一张空图、整格留白。4000x1 的照片塞进 25x32mm 的格子，
    未加守卫时 round_px(l) == round_px(r) == 2000。
    """
    p = crop.cell_crop_box(4000, 1, 25.0, 32.0, crop.FILL,
                           ppmm=units.ppmm(25.4))
    x0, y0, x1, y1 = p.crop_px
    assert x1 > x0 and y1 > y0
    assert (x0, x1) == (2000, 2001)
