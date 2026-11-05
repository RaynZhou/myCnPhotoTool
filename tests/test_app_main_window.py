"""界面冒烟：offscreen 下构造窗口、驱动一次排版与导出，不碰文件对话框。"""
import re

import pytest

pytest.importorskip("PIL", reason="需要 Pillow")
pytest.importorskip("PySide6", reason="需要 Qt 绑定")

from PySide6.QtCore import QElapsedTimer, QEventLoop  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402

from PIL import Image  # noqa: E402

from photoprint import jobs  # noqa: E402
from photoprint.app.main_window import MainWindow  # noqa: E402
from photoprint.core import modes, store  # noqa: E402


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


def test_ui_defaults_match_shared_constants(qapp, tmp_path):
    """界面默认值必须跨层与共享常量同源，否则 jobs/编排改了默认、界面会悄悄漂移。

    导出 dpi 下拉默认（`DPI_CHOICES[1]` → setCurrentIndex(1)）、出血默认都对应到生产
    常量。控件默认值此前无任何断言（parity 脚本只声明“同值不同源”），这条把它们钉住。
    """
    w = MainWindow(st=_store(tmp_path))
    assert float(w.dpi_box.currentData()) == jobs.DEFAULT_OUTPUT_DPI
    assert w.bleed_box.value() == modes.DEFAULT_BLEED_MM


def test_exported_page_has_no_unprintable_mask(qapp, tmp_path):
    """导出（show_mask=False）产物四边必须纯白——不可印区灰遮罩只属于预览。

    旧版在 dpi 25.4 下用负断言 `!= (210,210,210)`：A4 遮罩带在该 dpi 只覆盖 0..2px，
    探针 (3, ·) 落带外 → 导出即使误开遮罩也报不了（恒真零牙）。改用与界面导出同源的
    `DEFAULT_OUTPUT_DPI`（遮罩带 0..39px 把四边探针包住），四边正断言纯白，并加一层
    `show_mask=True` 正对照先钉四边确为合成灰，断言才有牙。
    """
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    dpi = jobs.DEFAULT_OUTPUT_DPI
    page = jobs.render_all(w.job, dpi, show_mask=False)[0]
    wpx, hpx = page.size
    probes = [(3, hpx // 2), (wpx // 2, 3), (wpx - 4, hpx // 2), (wpx // 2, hpx - 4)]
    assert [page.getpixel(xy) for xy in probes] == [(255, 255, 255)] * 4
    # 正对照：同图开遮罩必须先看到灰遮罩色，否则上面的纯白可能因整体渲染坏掉而恒真。
    masked = jobs.render_all(w.job, dpi, show_mask=True)[0]
    assert [masked.getpixel(xy) for xy in probes] == [(210, 210, 210)] * 4


def test_export_passes_selected_dpi_and_no_mask(qapp, tmp_path, monkeypatch):
    """界面层是唯一会写错导出参数的地方：必须钉住 export_to 用所选 dpi 且关遮罩。

    `test_export_writes_equal_size_pdf` 只查 MediaBox（与 dpi 无关），结构上
    守不到导出路径的 dpi/show_mask。这里 spy 拦一层 jobs.render_all 看真参数。
    """
    seen = {}
    real = jobs.render_all

    def spy(job, dpi, show_mask=None):
        seen["dpi"] = dpi
        seen["show_mask"] = show_mask
        return real(job, dpi, show_mask=show_mask)

    monkeypatch.setattr(jobs, "render_all", spy)
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    w.dpi_box.setCurrentIndex(2)         # 改选 600：钉的是“跟随所选”而非硬编码默认 300
    w.export_to(str(tmp_path / "page.pdf"))
    assert seen["show_mask"] is False     # 导出不带灰遮罩（全局约束）
    assert seen["dpi"] == 600.0           # 取的是下拉所选值，不是预览 96、也不是默认 300


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


def test_bad_offset_pct_in_config_does_not_block_startup(qapp, tmp_path):
    """坏配置不得卡住启动（与 store 自己的降级原则一致）：offset_pct 元素不可
    转 int 时静默保持默认 0，不让 ValueError 抛出 __init__。"""
    s = _store(tmp_path)
    s.set_last_job({"sheet_key": "A4", "cell_key": "3R",
                    "offset_pct": ["a", None]})
    s.save()
    w = MainWindow(st=_store(tmp_path))       # 不应抛
    assert w.h_slider.value() == 0 and w.v_slider.value() == 0


def test_offset_sliders_reach_jobs(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    w.h_slider.setValue(50)
    w._refresh()
    assert w.job.offset_pct == (50.0, 0.0)


def test_page_navigation_clamps_at_edges(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path, n=5)          # 5 张于 A4+3R 是 2 页
    assert w.job.page_count == 2
    w._go_page(1)
    assert w.page_index == 1
    w._go_page(1)
    assert w.page_index == 1         # 越界不得变页码
    w._go_page(-1)
    assert w.page_index == 0


def test_close_event_stops_debounce(qapp, tmp_path):
    """关窗必须停掉 debounce：否则“改参数后 250ms 内关窗”时，debounce 会在
    关窗之后 fire → _refresh → _render_async 另起一条线程，绕过 closeEvent
    的全部收尾 → 退出时残留线程被析构硬崩（round-1 评审 C1）。"""
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    w.h_slider.setValue(10)          # 触发 debounce，还没到期
    w.close()
    assert not w._debounce.isActive()


def test_bad_photo_paths_and_out_dir_do_not_block_startup(qapp, tmp_path):
    """I5：与 offset_pct 同函数、同全局约束（异常一律收敛不外抛）——坏
    photo_paths（不可迭代）不卡 __init__；坏 out_dir（非字符串）不卡写回。"""
    s = _store(tmp_path)
    s.set_last_job({"sheet_key": "A4", "cell_key": "3R", "photo_paths": 5,
                    "out_dir": 123})
    s.save()
    w = MainWindow(st=_store(tmp_path))       # photo_paths=5 不应抛
    assert w.photos == []
    w.save_last_job()                          # 坏 out_dir 走 _last_out_dir 降级，不应抛


def test_offset_pct_infinity_does_not_block_startup(qapp, tmp_path):
    """I5：store.save 默认 allow_nan，offset_pct=[Infinity, 0] 能落盘；
    int(inf) 抛 OverflowError，必须在 (TypeError, ValueError, OverflowError) 里兼到。"""
    s = _store(tmp_path)
    s.set_last_job({"sheet_key": "A4", "cell_key": "3R",
                    "offset_pct": [float("inf"), 0]})
    s.save()
    w = MainWindow(st=_store(tmp_path))       # 不应抛
    assert w.h_slider.value() == 0 and w.v_slider.value() == 0


@pytest.mark.filterwarnings("error::RuntimeWarning")
@pytest.mark.parametrize("key,value", [
    ("gap_mm", int("9" * 400)),        # float(huge int) → OverflowError
    ("bleed_mm", int("9" * 400)),
    ("dpi", int("9" * 400)),
    ("offset_pct", [1e19, 0]),         # int(1e19) 能转，但 setValue 喂给 C int 溢出
])
def test_bad_numeric_configs_do_not_block_startup(qapp, tmp_path, key, value):
    """I5/W1：数值字段超大值一律不得卡启动——写入控件的 OverflowError 必须被
    _restore_last_job 的降级护栏接住。删护栏则本用例在 __init__ 抛。

    标 filterwarnings=error::RuntimeWarning：`offset_pct=1e19` 走的是
    `int(1e19)` 能转、但 `slider.setValue` 喂给 shiboken C int 溢出只发
    RuntimeWarning（默认不抛），升成 error 后该用例才真踩到护栏。
    """
    s = _store(tmp_path)
    s.set_last_job({"sheet_key": "A4", "cell_key": "3R", key: value})
    s.save()
    w = MainWindow(st=_store(tmp_path))       # 不应抛
    if key == "offset_pct":
        assert w.h_slider.value() == 0 and w.v_slider.value() == 0
    elif key == "dpi":
        assert w.dpi_box.currentIndex() == 1   # 保持默认 300
    else:
        box = w.gap_box if key == "gap_mm" else w.bleed_box
        assert box.minimum() <= box.value() <= box.maximum()   # 超大值被护栏挡下，控件仍在量程内


def test_stale_generation_preview_frame_is_dropped(qapp, tmp_path):
    """I6：代际守卫是纯函数式调用，不需造竞态就能钉。删 `_on_preview` 的
    `if gen != self._gen: return` 则过期帧也会落 pixmap，本用例变红。"""
    w = MainWindow(st=_store(tmp_path))
    img = Image.new("RGB", (20, 20), (1, 2, 3))
    w.preview.setPixmap(QPixmap())            # 空哨兵
    w._on_preview(img, w._gen - 1)            # 过期帧：不得上屏
    assert w.preview.pixmap().isNull()
    w._on_preview(img, w._gen)                # 当代帧：应落 pixmap
    assert not w.preview.pixmap().isNull()


def test_stale_generation_render_failed_is_dropped(qapp, tmp_path):
    """S2：_on_render_failed 的 gen 判断同为纯函数式守卫（非竞态）。删
    `if gen == self._gen` 则过期失败帧也会改状态栏，第一条断言变红。"""
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    _settle(w, qapp)
    w._set_status("当前状态", error=False)
    w._on_render_failed("boom", w._gen - 1)   # 过期失败帧：不得改状态栏
    assert w.statusBar().currentMessage() == "当前状态"
    w._on_render_failed("boom", w._gen)       # 当代失败帧：应回写状态栏
    assert "boom" in w.statusBar().currentMessage()


class _FakeThread:
    """不 start 的假线程，专测 _retire_threads 的引用留存/释放与 wait 传参。"""
    def __init__(self, stops):
        self._running, self._stops, self.wait_args = True, stops, []
        self.quit_calls = 0

    def isRunning(self):
        return self._running

    def quit(self):
        self.quit_calls += 1
        if self._stops:
            self._running = False

    def wait(self, timeout=None):
        self.wait_args.append(timeout)
        return not self._running


def test_retire_threads_keeps_then_clears_stale_reference(qapp, tmp_path):
    """I6：wait 超时的线程必须留在 _stale（丢引用→在跑线程被回收→硬崩）；
    线程自己跑完后下轮退休应被踢出，防 _stale 无界增长。假线程注进 _stale，
    不动 w._thread（那是 __init__ 起的真线程，_settle 已泵停，换引用会孤儿它）。"""
    w = MainWindow(st=_store(tmp_path))
    _settle(w, qapp)                             # 泵停 __init__ 的真线程，保持被 w._thread 引用
    stuck = _FakeThread(stops=False)
    w._stale = [stuck]
    w._retire_threads()                        # 默认 2000ms 超时
    assert w._stale == [stuck]                 # 删 keep.append → 此处变红
    assert stuck.wait_args == [2000]
    assert stuck.quit_calls == 1               # S1：不先 quit 则事件循环永不退，无上限 wait 会永挂
    stuck._running = False                     # 模拟那条线程随后自己跑完
    w._retire_threads()
    assert w._stale == []                       # 停干净后不留


def test_close_event_retires_threads_without_timeout(qapp, tmp_path):
    """I8：closeEvent 收尾必须走无上限 wait(None)，不因 2000ms 超时把线程
    留进随窗口析构即失效的 _stale（那时丢引用同样会崩）。经真 close 触发。"""
    w = MainWindow(st=_store(tmp_path))
    _settle(w, qapp)                             # 泵停 __init__ 的真线程，不动 w._thread
    th = _FakeThread(stops=True)
    w._stale = [th]
    w.close()                                    # 触发 closeEvent → _retire_threads(timeout=None)
    assert th.wait_args == [None]                # closeEvent 改用默认超时 → 此处变红
    assert w._stale == []
