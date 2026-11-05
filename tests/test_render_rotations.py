"""逐图旋转：渲染时转必须与读图时预转好逐像素等价（规格 I-1），坏角度降级为 0。"""
import pytest

pytest.importorskip("PIL", reason="需要 Pillow")

from PIL import Image  # noqa: E402

from photoprint.core import modes, pack, render, specs  # noqa: E402

DPI = 25.4  # 1 像素 = 1 毫米，便于直接按 mm 取点

# 与 render._ANGLE_TRANSPOSE 同表：测试自带一份，实现漂移时对拍当场变红
_ANGLE_OPS = {90: Image.ROTATE_270, 180: Image.ROTATE_180, 270: Image.ROTATE_90}


def pre_rotated(photo, angle):
    # 与 render._apply_rotation 同款单次查表转置：while 递减 90 会让 180°
    # 连转两次（净 270°）、270° 三次，对拍基准自身漂移就不是基准了
    op = _ANGLE_OPS.get(int(angle) % 360)
    img = photo.copy()
    return img if op is None else img.transpose(op)


def _landscape():
    """四象限异色的 200×100 横图：左上红、右上绿、左下蓝、右下白。"""
    img = Image.new("RGB", (200, 100), (255, 255, 255))
    img.paste(Image.new("RGB", (100, 50), (255, 0, 0)), (0, 0))
    img.paste(Image.new("RGB", (100, 50), (0, 255, 0)), (100, 0))
    img.paste(Image.new("RGB", (100, 50), (0, 0, 255)), (0, 50))
    return img


def _a4_id1():
    a4 = specs.find_spec("A4")
    plan = pack.pack(a4, specs.find_spec("ID1"), gap_mm=2.0, allow_rotate=False,
                     printable=specs.printable_rect(a4))
    return a4, plan


def _render(a4, plan, photos, **kw):
    return render.render_page(plan, photos, a4, DPI, modes.FIT_TO_PRINTABLE,
                              show_mask=False, show_cut_lines=False, **kw)


@pytest.mark.parametrize("angle", [90, 180, 270])
def test_rotation_equals_pre_rotated_pixelwise(angle):
    """I-1 主不变量：rotations=[angle] 与"先把图转好"逐像素相同。"""
    a4, plan = _a4_id1()
    photo = _landscape()
    got = _render(a4, plan, [photo] * plan.count, rotations=[angle] + [0] * (plan.count - 1))
    want = _render(a4, plan, [pre_rotated(photo, angle)] +
                   [photo] * (plan.count - 1))
    assert got.tobytes() == want.tobytes()


def test_empty_rotations_equals_explicit_zeros():
    a4, plan = _a4_id1()
    photo = _landscape()
    assert (_render(a4, plan, [photo] * plan.count).tobytes() ==
            _render(a4, plan, [photo] * plan.count,
                    rotations=[0] * plan.count).tobytes())


def test_rotated_landscape_fills_portrait_cell_taller():
    """用户场景：200×100 横图进 25×32mm 竖格，FIT 高仅 12.5mm；转 90° 后填满 32mm。

    生效照片 100×200 的宽高比（1:2）比格子（25:32）更高，FIT 按高夹：
    画面 16×32mm 水平居中。探针取纸面右上红块（不转时那里是留白）：
    断言用像素取点，不复刻 crop 几何公式。
    """
    a4, plan = _a4_id1()
    ix, iy, iw, ih = plan.cells[0].inner_mm()
    assert (iw, ih) == pytest.approx((25.0, 32.0))
    photo = _landscape()
    probe = (int(ix + iw / 2 + 5), int(iy + 4))     # 右上红块区（画面居中后 x 16..31）
    assert _render(a4, plan, [photo] * plan.count).getpixel(probe) == (255, 255, 255)
    turned = _render(a4, plan, [photo] * plan.count, rotations=[90])
    assert turned.getpixel(probe) == (255, 0, 0)


def test_cw90_quadrant_lands_top_right():
    """顺时针 90° 的方向锁：四象限必须按 原左上→右上、原左下→左上、
    原右上→右下 落位（ROTATE_90 方向反了则红蓝互换、绿不在右下）。

    生效照片 100×200 按高夹 FIT 后是 16×32mm 水平居中（1px=1mm），
    探针取四象限中心点：右上红、左上蓝、右下绿、左下白。
    """
    a4, plan = _a4_id1()
    ix, iy, iw, ih = plan.cells[0].inner_mm()
    photo = _landscape()
    turned = _render(a4, plan, [photo] * plan.count, rotations=[90])
    assert turned.getpixel((int(ix + iw / 2 + 5), int(iy + 4))) == (255, 0, 0)   # 右上红
    assert turned.getpixel((int(ix + iw / 2 - 5), int(iy + 4))) == (0, 0, 255)   # 左上蓝
    assert turned.getpixel((int(ix + iw / 2 + 5), int(iy + ih - 4))) == (0, 255, 0)  # 右下绿
    assert turned.getpixel((int(ix + iw / 2 - 5), int(iy + ih - 4))) == (255, 255, 255)  # 左下白


@pytest.mark.parametrize("bad", [45, 120, None, "abc", []])
def test_illegal_angles_degrade_to_zero_without_raising(bad):
    """归一后仍非法 / 转不了 int：按 0 渲染，不抛错，与不转逐像素相同。"""
    a4, plan = _a4_id1()
    photo = _landscape()
    got = _render(a4, plan, [photo] * plan.count, rotations=[bad])
    assert got.tobytes() == _render(a4, plan, [photo] * plan.count).tobytes()


def test_negative_90_normalizes_to_270():
    a4, plan = _a4_id1()
    photo = _landscape()
    got = _render(a4, plan, [photo] * plan.count, rotations=[-90])
    assert got.tobytes() == _render(a4, plan, [photo] * plan.count,
                                    rotations=[270]).tobytes()


def test_rotations_shorter_than_photos_pads_zero():
    a4, plan = _a4_id1()
    photo = _landscape()
    got = _render(a4, plan, [photo] * plan.count, rotations=[0])
    assert got.tobytes() == _render(a4, plan, [photo] * plan.count).tobytes()


def test_photo_rotation_on_rotated_cell_still_pixelwise_parity():
    """格子旋转（装箱朝向）与照片旋转可叠加：叠加时先转照片、后走格子旋转路径。

    A4+4R 两格都是旋转格；对拍等式在旋转格上同样必须成立。
    """
    a4 = specs.find_spec("A4")
    plan = pack.pack(a4, specs.find_spec("4R"), gap_mm=0.0, allow_rotate=True,
                     printable=specs.printable_rect(a4))
    assert all(c.rotated for c in plan.cells)
    photo = _landscape()
    args = (plan, [photo] * plan.count, a4, DPI, modes.FIT_TO_PRINTABLE)
    got = render.render_page(*args, show_mask=False, show_cut_lines=False,
                             rotations=[90, 270])
    pre = [pre_rotated(photo, 90), pre_rotated(photo, 270)]
    want = render.render_page(plan, pre + [photo] * (plan.count - 2), a4, DPI,
                              modes.FIT_TO_PRINTABLE, show_mask=False,
                              show_cut_lines=False)
    assert got.tobytes() == want.tobytes()
