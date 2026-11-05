"""界面冒烟：offscreen 下构造窗口、驱动一次排版与导出，不碰文件对话框。"""
import re

import pytest

pytest.importorskip("PIL", reason="需要 Pillow")
pytest.importorskip("PySide6", reason="需要 Qt 绑定")

from PySide6.QtCore import QElapsedTimer, QEventLoop  # noqa: E402

from PIL import Image  # noqa: E402

from photoprint import jobs  # noqa: E402
from photoprint.app.main_window import MainWindow  # noqa: E402
from photoprint.core import store  # noqa: E402


def _store(tmp_path):
    s = store.Store(tmp_path / "papers.json")
    s.load()
    return s


def _make_photos(tmp_path, n=4):
    paths = []
    for i in range(n):
        p = tmp_path / f"{i}.jpg"
        Image.new("RGB", (400, 200), (200 - 30 * i, 30, 40)).save(p)
        paths.append(str(p))
    return paths


def _fill(window, tmp_path, n=4):
    for p in _make_photos(tmp_path, n):
        window.append_photo(p)
    window._refresh()


def _settle(window, qapp, timeout_ms=5000):
    """offscreen 下没有自转的事件循环，手动泵到渲染线程停下、信号投递完。

    必须给 processEvents 传 maxTime：无参忙轮询不会等跨线程事件送达，
    慢机上几百次空转都可能还没轮到子线程 quit 的回投（计划原 rounds=60
    正是栽在这）。带超时就变成「事件一到立刻返回」，用墙钟兜底判定真挂了。
    """
    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < timeout_ms:
        qapp.processEvents(QEventLoop.AllEvents, 50)
        if window._thread is None:
            return
        if not window._thread.isRunning():
            qapp.processEvents(QEventLoop.AllEvents, 50)
            return
    pytest.fail("预览线程未在预期时间内停下")


@pytest.fixture(autouse=True)
def _no_leaked_threads(qapp):
    """每个用例收尾时停掉 debounce、泵停渲染线程、再关窗口。

    多数用例只 _refresh（经 _render_async 起了渲染线程）却不关窗口；
    线程跑到完成只会把 quit 排队到主线程，没人泵就永远不停；窗口随进程
    退出被析构时线程还在跑→解释器硬崩（0xC0000409），即使 pytest 已打印
    “N passed”，退出码仍非零、CI 会判失败。收尾三步：先停 debounce（否则
    下面泵送会触发新的 250ms 延迟渲染又起一条线程），再泵到现有线程全停，
    最后 close 触发 closeEvent 里的 quit+wait 兜底。
    """
    yield
    wins = [w for w in qapp.topLevelWidgets() if isinstance(w, MainWindow)]
    for w in wins:
        w._debounce.stop()
    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < 3000:
        qapp.processEvents(QEventLoop.AllEvents, 50)
        if not any(w._thread is not None and w._thread.isRunning() for w in wins):
            break
    for w in wins:
        w.close()
    qapp.processEvents(QEventLoop.AllEvents, 100)


def test_window_starts_with_preview_and_status(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    _settle(w, qapp)
    assert not w.preview.pixmap().isNull()
    assert "每页 4 格" in w.statusBar().currentMessage()
    assert w.export_btn.isEnabled()


def test_export_writes_equal_size_pdf(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    out = w.export_to(str(tmp_path / "page.pdf"))
    m = re.search(rb"MediaBox\s*\[([\d.\s]+)\]", out.read_bytes())
    vals = [float(x) for x in m.group(1).split()]
    assert vals[2] == pytest.approx(595.276, abs=1.0)   # A4 宽 210mm
    assert vals[3] == pytest.approx(841.89, abs=1.0)    # A4 高 297mm


def test_exported_page_has_no_unprintable_mask(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    page = jobs.render_all(w.job, 25.4, show_mask=False)[0]
    assert page.getpixel((3, page.height // 2)) != (210, 210, 210)


def test_too_big_cell_reports_instead_of_crashing(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    w.sheet_box.setCurrentIndex(w.sheet_box.findData("3R"))
    w.cell_box.setCurrentIndex(w.cell_box.findData("A4"))
    w._refresh()
    assert "放不下" in w.statusBar().currentMessage()
    assert not w.export_btn.isEnabled()


def test_unreadable_photo_is_marked_and_does_not_block(qapp, tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    w = MainWindow(st=_store(tmp_path))
    w.append_photo(str(bad))
    assert w.photos[-1] is None
    assert "无法读取" in w.statusBar().currentMessage()
    assert "读取失败" in w.photo_list.item(0).text()


def test_last_job_roundtrip_through_two_windows(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    w.gap_box.setValue(2.5)
    w.cell_box.setCurrentIndex(w.cell_box.findData("ID1"))
    w.save_last_job(out_dir=str(tmp_path))

    again = MainWindow(st=_store(tmp_path))
    assert again.gap_box.value() == 2.5
    assert again.cell_box.currentData() == "ID1"


def test_offset_sliders_reach_jobs(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    w.h_slider.setValue(50)
    w._refresh()
    assert w.job.offset_pct == (50.0, 0.0)


def test_page_navigation_clamps_at_edges(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path, n=5)          # 5 张亍 A4+3R 是 2 页
    assert w.job.page_count == 2
    w._go_page(1)
    assert w.page_index == 1
    w._go_page(1)
    assert w.page_index == 1         # 越界不得变页码
    w._go_page(-1)
    assert w.page_index == 0
