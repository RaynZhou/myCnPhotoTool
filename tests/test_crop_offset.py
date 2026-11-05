"""裁切偏移的轴向语义：界面偏移是纸面方向，crop 吃的是旋转前方向。"""
from photoprint.core import crop


def test_rotate_offset_maps_paper_axes_to_pre_rotation_axes():
    """纸面右 2mm / 下 5mm → 旋转前 (上 -2mm, 右 5mm) 的等价写法。"""
    assert crop.rotate_offset(2.0, 5.0) == (5.0, -2.0)


def test_rotate_offset_is_identity_at_zero():
    assert crop.rotate_offset(0.0, 0.0) == (0.0, 0.0)


def test_rotate_offset_accepts_ints_and_returns_floats():
    got = crop.rotate_offset(1, 2)
    assert got == (2.0, -1.0)
    assert all(isinstance(v, float) for v in got)
