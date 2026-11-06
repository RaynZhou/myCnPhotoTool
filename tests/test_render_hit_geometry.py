"""core 命中几何：page_cells_px / cell_index_at / cell_rects_view。
全 headless；用非正方图像/视图，防无牙断言（fit 逆变换错也须转红）。"""
import tempfile
import pathlib

from photoprint import jobs
from photoprint.core import render, store


def _cell_rects():
    # 图像像素下 2×1 格：整页 400×200，两格各 200×200（非正方页 400×200）
    return [(0, 0, 200, 200), (200, 0, 200, 200)]


def _store_a4():
    d = pathlib.Path(tempfile.mkdtemp()) / "papers.json"
    st = store.Store(path=d)
    st.load()
    return st


def test_page_cells_px_counts_and_within_image():
    job = jobs.build_job(_store_a4(), [], "A4", "5R")
    image_wh, rects = render.page_cells_px(job.plan, job.sheet, 300)
    assert len(rects) == job.count
    iw, ih = image_wh
    for (x, y, w, h) in rects:
        assert x >= 0 and y >= 0
        assert x + w <= iw + 1 and y + h <= ih + 1


def test_hit_center_of_each_cell():
    rects = _cell_rects()
    # 视图与图像同尺寸：scale=1、零偏移
    assert render.cell_index_at(rects, (400, 200), (400, 200), (100, 100)) == 0
    assert render.cell_index_at(rects, (400, 200), (400, 200), (300, 100)) == 1


def test_hit_respects_letterbox_offset():
    # 图像 400×200 放进 400×400 视图 → scale=1、上下各留白 100（非正方才有位移）
    rects = _cell_rects()
    assert render.cell_index_at(rects, (400, 200), (400, 400), (100, 150)) == 0
    assert render.cell_index_at(rects, (400, 200), (400, 400), (100, 50)) is None


def test_hit_gap_between_cells_is_none():
    rects = [(0, 0, 100, 100), (200, 0, 100, 100)]
    assert render.cell_index_at(rects, (300, 100), (300, 100), (150, 50)) is None


def test_scaled_view_hit_matches_unscaled():
    # 图像放大一倍显示：图像点 (100,100)→视图 (200,200) 仍命中第 0 格
    rects = _cell_rects()
    assert render.cell_index_at(rects, (400, 200), (800, 400), (200, 200)) == 0


def test_rects_view_covers_hit_point():
    rects = _cell_rects()
    view = render.cell_rects_view(rects, (400, 200), (400, 400))
    vx, vy, vw, vh = view[0]
    assert vx <= 100 < vx + vw and vy <= 150 < vy + vh   # 与命中同一 fit
