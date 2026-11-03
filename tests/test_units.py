"""mm 与像素换算的断言：全项目只允许这一套换算。"""
from photoprint.core import units


def test_ppmm_300dpi():
    assert units.ppmm(300) == 300 / 25.4


def test_mm_to_px_rounds_half_up():
    # 89mm @300dpi = 1051.181 像素 → 1051；0.35mm 线宽 @300dpi = 4.134 → 4
    assert units.mm_to_px(89, 300) == 1051
    assert units.mm_to_px(0.35, 300) == 4
    # 恰好 .5 时必须向上：round() 是银行家舍入（round(2.5)==2），
    # 用它会让“dpi=25.4 下 1mm=1px”的像素断言反直觉，Task 9 的几何测试依赖这点
    assert units.mm_to_px(2.5, 25.4) == 3


def test_mm_to_px_at_one_pixel_per_mm():
    # dpi=25.4 时 1 像素 = 1 毫米，几何测试靠这个技巧做像素级断言
    assert units.mm_to_px(210, 25.4) == 210


def test_px_mm_roundtrip_within_half_pixel():
    for dpi in (25.4, 150, 300, 600):
        for mm in (89.0, 127.0, 210.0, 297.0, 3.4):
            back = units.px_to_mm(units.mm_to_px(mm, dpi), dpi)
            assert abs(back - mm) <= 0.5 / units.ppmm(dpi) + 1e-9


def test_win_mm_uses_tenth_of_mm():
    assert units.win_mm(89.0) == 890
    assert units.win_mm(127.0) == 1270
    assert units.win_mm(82.25) == 822  # 0.1mm 向下取整，宁小勿大避免溢出纸张


def test_mm_to_scene_is_tenth_mm():
    assert units.mm_to_scene(89.0) == 890
    assert units.mm_to_scene(3.4) == 34
    assert units.mm_to_scene(0.25) == 3  # 2.5 个 0.1mm 单位，同样 .5 向上
