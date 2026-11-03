"""尺寸表与可打印矩形：数值取自佳能中国 G3800 官方规格页。"""
import pytest

from photoprint.core import specs


def test_3r_exists_and_is_custom_no_borderless():
    s = specs.find_spec("3R")
    assert (s.w_mm, s.h_mm) == (89.0, 127.0)
    assert s.role == "paper"
    assert s.origin == "custom"
    assert s.borderless is False
    assert s.margin_source == "spec"


def test_3r_printable_rect_subtracts_physical_margins():
    s = specs.find_spec("3R")
    r = specs.printable_rect(s)
    assert r.w_mm == pytest.approx(82.2, abs=1e-6)   # 89 - 3.4 - 3.4
    assert r.h_mm == pytest.approx(119.0, abs=1e-6)  # 127 - 3 - 5
    assert (r.x_mm, r.y_mm) == (3.4, 3.0)


def test_a4_borderless_active_zeroes_margins():
    """规格 7.4：实测无边距生效时目标矩形等于整张纸。"""
    s = specs.find_spec("A4")
    assert s.borderless is True
    off = specs.printable_rect(s, borderless_active=False)
    on = specs.printable_rect(s, borderless_active=True)
    assert off.w_mm == pytest.approx(203.2)
    assert on.w_mm == pytest.approx(210.0)
    assert on.h_mm == pytest.approx(297.0)
    assert (on.x_mm, on.y_mm) == (0.0, 0.0)


def test_source_spec_never_assumes_zero_margins():
    """margin_source=spec 时，即使尺寸有边框能力也必须按规格边距处理。"""
    s = specs.find_spec("4R")
    assert s.borderless is True
    assert s.margin_source == "spec"
    r = specs.printable_rect(s)  # 未声明 borderless_active
    assert r.w_mm < s.w_mm


def test_ltr_uses_exception_margins():
    s = specs.find_spec("LTR")
    assert (s.margins.left, s.margins.right) == (6.4, 6.3)


def test_cell_presets_cannot_be_used_as_paper():
    for s in specs.CELL_PRESETS:
        assert s.role == "cell"
    for s in specs.PAPER_PRESETS:
        assert s.role == "paper"


def test_id_photo_sizes_are_unchanged():
    assert specs.find_spec("ID1").w_mm == 25.0
    assert specs.find_spec("ID1").h_mm == 32.0
    assert specs.find_spec("ID2").w_mm == 35.0
    assert specs.find_spec("ID2").h_mm == 49.0


def test_custom_legal_accepts_3r_both_orientations():
    ok, _ = specs.custom_size_is_legal(89.0, 127.0)
    assert ok
    ok, _ = specs.custom_size_is_legal(127.0, 89.0)
    assert ok


def test_custom_illegal_12inch_is_blocked():
    """12寸 254×305：宽 254 > 215.9，两向都不合法 —— 必须阻断。"""
    ok, msg = specs.custom_size_is_legal(254.0, 305.0)
    assert ok is False
    assert "215.9" in msg


def test_custom_illegal_below_length_floor():
    """80×70：两个方向当宽度都 ∈ 55–215.9，但当长度都 < 89 ⇒ 只违反长度下限。

    不得用 100×80 做这个用例：允许横竖交换后 80 当宽、100 当长完全合法，
    而卡片 91×55 结构同形（只能靠交换才合法），任何“让 100×80 不合法”的改法都会误判死卡片。
    """
    ok, msg = specs.custom_size_is_legal(80.0, 70.0)
    assert ok is False
    assert "89" in msg


def test_12inch_is_not_a_preset():
    keys = {s.key for s in specs.ALL_PRESETS}
    assert not any(s.w_mm >= 254 for s in specs.ALL_PRESETS if s.role == "paper")
    assert "12INCH" not in keys
