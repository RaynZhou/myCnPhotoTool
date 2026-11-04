"""回读校验与 dpi 选取是纯函数：这两条决定直打会不会被驱动偷偷缩放。"""
import pytest

from photoprint.win import gdi_print


def test_accepts_within_half_mm():
    ok, msg = gdi_print.verify_physical_size(89.4, 127.3, 89.0, 127.0)
    assert ok is True
    assert msg == ""


def test_rejects_beyond_half_mm_and_explains():
    ok, msg = gdi_print.verify_physical_size(102.0, 152.0, 89.0, 127.0)
    assert ok is False
    assert "驱动忽略了自定义尺寸" in msg
    assert "102.00" in msg and "89.00" in msg


def test_tolerance_boundary_is_inclusive():
    assert gdi_print.verify_physical_size(89.5, 127.0, 89.0, 127.0)[0] is True
    assert gdi_print.verify_physical_size(89.51, 127.0, 89.0, 127.0)[0] is False


def test_pick_dpi_caps_4800_to_600():
    assert gdi_print.pick_dpi(4800) == 600
    assert gdi_print.pick_dpi(300) == 300
    assert gdi_print.pick_dpi(150) == 150
    assert gdi_print.pick_dpi(0) == 300  # 驱动没回报时的安全默认


def test_pick_dpi_respects_user_cap():
    assert gdi_print.pick_dpi(1200, cap=300) == 300
