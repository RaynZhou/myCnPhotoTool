"""均匀网格：公式 n = floor((W + gap) / (cw + gap))，间隔不计外圈。"""
from photoprint.core import pack, specs


def test_counts_3r_on_a4_no_gap():
    assert pack.grid_counts(210.0, 297.0, 89.0, 127.0, 0.0) == (2, 2)
    # 横向放：127 宽 × 89 高 → 1 列 3 行，少于竖放的 4
    assert pack.grid_counts(210.0, 297.0, 127.0, 89.0, 0.0) == (1, 3)


def test_counts_with_gap_uses_plus_gap_formula():
    # 1寸 25×32 gap=2：floor(212/27)=7、floor(299/34)=8 ⇒ 56
    assert pack.grid_counts(210.0, 297.0, 25.0, 32.0, 2.0) == (7, 8)
    # 2寸 35×49 gap=2：floor(212/37)=5、floor(299/51)=5 ⇒ 25
    assert pack.grid_counts(210.0, 297.0, 35.0, 49.0, 2.0) == (5, 5)
    # 上面两例的尾量（21、25、25、42mm）都大于 gap，去掉分子的 +gap 也不改变
    # 结果，杀不掉变异；只有尾量不足 gap 的临界排版能区分两种公式。180 与 256
    # 恰好等于两张加一个间隔（89×2+2、127×2+2），间隔不计外圈 ⇒ 两维都必须是 2。
    assert pack.grid_counts(180.0, 256.0, 89.0, 127.0, 2.0) == (2, 2)


def test_counts_zero_when_cell_bigger_than_region():
    # 两个方向都放不下：127×200 的格子对 102×152 的区域两向都超
    assert pack.grid_counts(102.0, 152.0, 127.0, 200.0, 0.0) == (0, 0)
    # 列与行各自独立算：宽放不下不代表高也放不下（89 在 152 里能竖下一张）。
    # 总数为零靠的是 place_uniform“任一维为 0 就不放”，不是靠 grid_counts 返回 (0, 0)。
    assert pack.grid_counts(102.0, 152.0, 127.0, 89.0, 0.0) == (0, 1)


def test_bleed_enlarges_cell_effectively():
    # 3mm 出血把 89×127 抬到 95×133：仍为 2×2 ⇒ 出血不损失 A4 产能
    cw, ch = pack.cell_wh(89.0, 127.0, False)
    cw += 2 * 3.0
    ch += 2 * 3.0
    assert pack.grid_counts(210.0, 297.0, cw, ch, 0.0) == (2, 2)


def test_place_uniform_is_centered_and_counted():
    cells = pack.place_uniform(210.0, 297.0, 89.0, 127.0, 0.0, 0.0, False)
    assert len(cells) == 4
    xs = sorted({c.x_mm for c in cells})
    ys = sorted({c.y_mm for c in cells})
    assert xs == [(210.0 - 178.0) / 2, (210.0 - 178.0) / 2 + 89.0]
    assert ys == [(297.0 - 254.0) / 2, (297.0 - 254.0) / 2 + 127.0]


def test_place_uniform_inner_shrinks_by_bleed():
    cells = pack.place_uniform(210.0, 297.0, 89.0, 127.0, 0.0, 3.0, False)
    c = cells[0]
    assert (c.w_mm, c.h_mm) == (95.0, 133.0)
    x, y, w, h = c.inner_mm()
    assert (round(x - c.x_mm, 6), round(y - c.y_mm, 6)) == (3.0, 3.0)
    assert (w, h) == (89.0, 127.0)


def test_place_uniform_empty_when_no_fit():
    assert pack.place_uniform(89.0, 127.0, 102.0, 152.0, 0.0, 0.0, False) == []
