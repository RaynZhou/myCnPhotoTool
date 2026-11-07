"""界面冒烟：offscreen 下构造窗口、驱动一次排版与导出，不碰文件对话框。"""
import os
import re

import pytest

pytest.importorskip("PIL", reason="需要 Pillow")
pytest.importorskip("PySide6", reason="需要 Qt 绑定")

from PySide6.QtCore import QElapsedTimer, QEventLoop, Qt  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402

from PIL import Image  # noqa: E402

from photoprint import jobs  # noqa: E402
from photoprint.app import main_window  # noqa: E402
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
    """append 进库后顺序 place 到槽 0..n-1——复现旧“自动填充”对既有测试的意义。"""
    for p in _make_photos(tmp_path, n):
        window.append_photo(p)
    for i in range(n):
        window.place(i, i)
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
def _no_leaked_threads(qapp, destroy_windows):
    """每个用例收尾时停掉 debounce、泵停渲染线程、再关窗口。

    多数用例只 _refresh（经 _render_async 起了渲染线程）却不关窗口；
    线程跑到完成只会把 quit 排队到主线程，没人泵就永远不停；窗口随进程
    退出被析构时线程还在跑→解释器硬崩（0xC0000409），即使 pytest 已打印
    “N passed”，退出码仍非零、CI 会判失败。收尾三步：先停 debounce（否则
    下面泵送会触发新的 250ms 延迟渲染又起一条线程），再泵到现有线程全停，
    最后 close 触发 closeEvent 里的 quit+wait 兜底。close 之后还要就地销毁
    窗口（destroy_test_windows）：只关不删的窗口会拖到 QApplication 拆了以后
    才被循环 GC 析构，同样是一条无 Python 栈的访问违例。
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
    destroy_windows(wins)


def test_window_starts_with_preview_and_status(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    _settle(w, qapp)
    assert not w.preview.pixmap().isNull()
    assert "每页 4 格" in w.statusBar().currentMessage()
    assert w.export_btn.isEnabled()


def test_photo_grid_lays_out_two_columns(qapp, tmp_path):
    """缩略图网格必须排成两列：单列会让照片卡片右侧空掉一半。

    临界点是像素级的：每格 140px（图标 120 + QSS 内边距/描边/委托边距），两列
    要视口 ≥283px。照片列 324 时视口只有 284px，差几像素就全退成一列——所以
    列宽取 344（304 视口）并在此钉住列数。窗口不 show 时几何还是初始值，量不出真列数。
    """
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    w.resize(1400, 960)
    w.show()
    _settle(w, qapp)
    qapp.processEvents(QEventLoop.AllEvents, 200)
    lst = w.photo_list
    assert lst.count() >= 2
    first = lst.visualItemRect(lst.item(0))
    second = lst.visualItemRect(lst.item(1))
    assert second.y() == first.y(), "第二张应和第一张同一行"
    assert second.x() > first.x(), "第二张应在第一张右侧而非下方"


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

    出血量已不暴露到面板（固定用 `modes.DEFAULT_BLEED_MM`），故改为断言
    `_params()` 交出去的那份值，而不是控件的 value。
    """
    w = MainWindow(st=_store(tmp_path))
    assert float(w.dpi_box.currentData()) == jobs.DEFAULT_OUTPUT_DPI
    assert w._params()["bleed_mm"] == modes.DEFAULT_BLEED_MM


def test_exported_page_has_no_unprintable_mask(qapp, tmp_path):
    """导出（show_mask=False）产物四边必须纯白——不可印区标记只属于预览。

    旧版在 dpi 25.4 下用负断言 `!= (210,210,210)`：A4 遮罩带在该 dpi 只覆盖 0..2px，
    探针 (3, ·) 落带外 → 导出即使误开遮罩也报不了（恒真零牙）。改用与界面导出同源的
    `DEFAULT_OUTPUT_DPI`，整条左带逐像素比对，纯白断言才有牙。

    带子自 2026-11-07 起是「白纸 + 浅灰斜纹」而不是实心块（实心灰会把整圈白边
    遮死，用户无法目测留多宽），所以正对照改为“预览在带内确实有墨、且占比远小于
    一半”。
    """
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    dpi = jobs.DEFAULT_OUTPUT_DPI
    page = jobs.render_all(w.job, dpi, show_mask=False)[0]
    wpx, hpx = page.size
    probes = [(3, hpx // 2), (wpx // 2, 3), (wpx - 4, hpx // 2), (wpx // 2, hpx - 4)]
    assert [page.getpixel(xy) for xy in probes] == [(255, 255, 255)] * 4

    band_w = int(3.4 * dpi / 25.4)          # 左带 3.4mm 宽
    rows = range(0, hpx, 7)

    def ink(img):
        return sum(1 for x in range(1, band_w) for y in rows
                   if img.getpixel((x, y)) != (255, 255, 255))

    total = (band_w - 1) * len(list(rows))
    assert ink(page) == 0                    # 导出：带内一尘不染
    masked = jobs.render_all(w.job, dpi, show_mask=True)[0]
    assert ink(masked) > 0                   # 正对照：预览确实做了标记
    assert ink(masked) < total * 0.4         # 但是斜纹不是实心块：白边看得见


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


def test_export_syncs_pending_debounce_before_render(qapp, tmp_path):
    """B-1：导出前必须把挂着的防抖控件值同步进 job，否则拿陈旧 job 配新参数导出。

    _fill 同步刷一次（水印开着、文字还是空的）；随后往输入框里打字只起
    debounce、不即时重排（offscreen 不泵事件、定时器不会 fire）。export_to 顶部
    那次 _rebuild_job 才把新文案落进 job。删那两行同步 → self.job 仍是空文案，
    导出的 PDF 里就少了一个水印。
    """
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path, n=2)
    w.wm_enabled.setChecked(True)                 # 防抖挂着
    w._rebuild_job()                              # 手动同步一次作为基线
    assert w.job.watermark_overlay.text == ""
    w.wm_text.setText("样片")                    # 防抖挂着：self.job 仍是旧文案
    assert w.job.watermark_overlay.text == ""
    w.export_to(str(tmp_path / "sync.pdf"))
    assert w.job.watermark_overlay.text == "样片"  # 导出前已把待防抖值同步进 job


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
    assert w.pool[-1]["img"] is None
    assert "无法读取" in w.statusBar().currentMessage()
    assert "读取失败" in w.photo_list.item(0).text()


def test_last_job_roundtrip_through_two_windows(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    w.margin_cb.setChecked(True)
    w.cell_box.setCurrentIndex(w.cell_box.findData("ID1"))
    w.save_last_job(out_dir=str(tmp_path))

    again = MainWindow(st=_store(tmp_path))
    assert again.margin_cb.isChecked() is True
    assert again.cell_box.currentData() == "ID1"


def test_margin_is_a_switch_not_a_number(qapp, tmp_path):
    """边距只给有/无：不勾=0（照片之间紧贴、自动铺满），勾上=2.0mm（够下刀）。

    面板不得再出现毫米数值框，也不得再用“间距”这个词——单张照片没有相邻格，
    那个属性只在多格时成立（用户 2026-11-07：统一为边距）。
    """
    w = MainWindow(st=_store(tmp_path))
    assert not hasattr(w, "gap_box") and not hasattr(w, "bleed_box")
    assert not hasattr(w, "gap_cb")
    w.sheet_box.setCurrentIndex(w.sheet_box.findData("A4"))
    w.cell_box.setCurrentIndex(w.cell_box.findData("ID1"))
    w._refresh()
    assert w.margin_cb.isChecked() is False     # 默认无额外边距
    assert w._params()["gap_mm"] == 0.0
    full = w.job.count                          # 无边距：铺满

    w.margin_cb.setChecked(True)
    w._refresh()
    assert w._params()["gap_mm"] == main_window.MARGIN_ON_MM == 2.0
    assert 0 < w.job.count < full               # 有边距：必然少几格


def test_single_cell_margin_turns_into_uniform_border(qapp, tmp_path):
    """一页只有一格时，“边距”那一行变成“四周留白 ≥5.1mm”。

    单张没有相邻格，间距无从谈起；但四周白边是真实需求（用户 2026-11-07）。
    切回多格时文案与含义都回到“留边距 2mm”，留白值不生效。
    文案用“≥”而不是“等宽”：铺满档才是严格相等，完整放入档某边会更宽。
    """
    w = MainWindow(st=_store(tmp_path))
    w.sheet_box.setCurrentIndex(w.sheet_box.findData("3R"))
    w.cell_box.setCurrentIndex(w.cell_box.findData("3R"))
    w._refresh()
    assert w.job.count == 1
    assert w.margin_cb.isEnabled() is True       # 不置灰：这一档现在真有用
    assert "四周留白" in w.margin_cb.text()
    assert "物理极限" in w.margin_cb.toolTip()
    assert "铺满可打印区" in w.margin_cb.toolTip()   # 要严格等宽指路模式下拉
    assert w.margin_cb.isChecked() is False
    assert w._params()["uniform_mm"] is None

    w.margin_cb.setChecked(True)
    w._refresh()
    assert w._params()["uniform_mm"] == main_window.UNIFORM_MARGIN_MM == 5.1
    assert w.job.uniform_mm == 5.1
    assert "上5.1/下5.1/左5.1/右5.1mm" in w.job.note

    w.sheet_box.setCurrentIndex(w.sheet_box.findData("A4"))
    w._refresh()
    assert w.job.count > 1
    assert "留边距" in w.margin_cb.text()
    assert w.job.uniform_mm is None       # 多格：留白值不生效，留给格间缝


def test_bleed_is_fixed_at_default(qapp, tmp_path):
    """出血量不再暴露：选出血拼版就固定用 modes.DEFAULT_BLEED_MM。"""
    w = MainWindow(st=_store(tmp_path))
    assert w._params()["bleed_mm"] == modes.DEFAULT_BLEED_MM


def test_legacy_gap_mm_restores_as_checked(qapp, tmp_path):
    """旧配置里的任意毫米数（如 2.5）按“留边距”一档恢复，不得卡启动。"""
    s = _store(tmp_path)
    s.set_last_job({"sheet_key": "A4", "cell_key": "3R",
                    "gap_mm": 2.5, "bleed_mm": 5.0})
    s.save()
    w = MainWindow(st=_store(tmp_path))
    assert w.margin_cb.isChecked() is True


def test_page_navigation_extends_forward_and_clamps_backward(qapp, tmp_path):
    """增量②：末页点“下一页”自动增页；越向前仍夹在第一页。"""
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path, n=5)          # 5 张于 A4+3R 是 2 页
    assert w.job.page_count == 2
    w._go_page(1)
    assert w.page_index == 1
    w._go_page(1)                    # 已在末页 → 自动追加空页
    assert w._pages == 3 and w.page_index == 2
    w._go_page(-1)                   # 离开空末页 → 收缩回 2 页
    assert w._pages == 2 and w.page_index == 1
    w._go_page(-1)
    assert w.page_index == 0
    w._go_page(-1)                   # 首页向前越界不动
    assert w.page_index == 0


def test_close_event_stops_debounce(qapp, tmp_path):
    """关窗必须停掉 debounce：否则“改参数后 250ms 内关窗”时，debounce 会在
    关窗之后 fire → _refresh → _render_async 另起一条线程，绕过 closeEvent
    的全部收尾 → 退出时残留线程被析构硬崩（round-1 评审 C1）。"""
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    w.margin_cb.setChecked(True)     # 触发 debounce，还没到期
    w.close()
    assert not w._debounce.isActive()


def test_bad_photo_paths_and_out_dir_do_not_block_startup(qapp, tmp_path):
    """I5：与 dpi 同函数、同全局约束（异常一律收敛不外抛）——坏
    photo_paths（不可迭代）不卡 __init__；坏 out_dir（非字符串）不卡写回。"""
    s = _store(tmp_path)
    s.set_last_job({"sheet_key": "A4", "cell_key": "3R", "photo_paths": 5,
                    "out_dir": 123})
    s.save()
    w = MainWindow(st=_store(tmp_path))       # photo_paths=5 不应抛
    assert w.pool == []
    w.save_last_job()                          # 坏 out_dir 走 _last_out_dir 降级，不应抛


def test_huge_dpi_in_config_does_not_block_startup(qapp, tmp_path):
    """I5/W1：数值字段超大值一律不得卡启动。

    store.save 默认 allow_nan，所以 JSON 里能落个 400 位整数；`float(10**400)`
    抛 OverflowError，必须被 _restore_last_job 的降级护栏接住。删护栏则本条在
    __init__ 直接抛（窗口化 exe 就是静默闪退）。
    """
    s = _store(tmp_path)
    s.set_last_job({"sheet_key": "A4", "cell_key": "3R", "dpi": int("9" * 400)})
    s.save()
    w = MainWindow(st=_store(tmp_path))       # 不应抛
    assert w.dpi_box.currentIndex() == 1      # 保持默认 300


def test_huge_overlay_alpha_in_config_does_not_block_startup(qapp, tmp_path):
    """I5/W1：alpha_pct=1e19 → QSlider.setValue(int(1e19)) 让 shiboken 抛
    OverflowError（而不是 ValueError）；_safe 必须兼到 OverflowError，
    删掉它这条就变红。"""
    s = _store(tmp_path)
    s.set_last_job({"sheet_key": "A4", "cell_key": "3R",
                    "watermark_overlay": {"enabled": True, "alpha_pct": 1e19}})
    s.save()
    w = MainWindow(st=_store(tmp_path))       # 不应抛
    assert w.wm_alpha.value() == 50           # 默认值没被顶坏


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


def _rotate_btn(w):
    return w.findChild(type(w.export_btn), "rotate_btn")


def test_rotate_then_refresh_changes_preview_pixels(qapp, tmp_path):
    """所见即所得的构造保证：按钮 → rotate_cell/cell_rot → build_job → 渲染层，
    全链路走通后当前页像素必须真的变了（断言像素，不断言中间变量）。

    不用 _fill 的纯色图：纯色（含仅角上小标记、标记被裁切/缩采样抹平的情形）
    转 90° 画面可以逐像素不变，"!=" 断言无牙（探针实测）——用左右双色图，
    居中取景（默认档与 FIT/FILL 同为中心取景）后采样区域必然跨到两色。"""
    twotone = tmp_path / "twotone.jpg"
    img = Image.new("RGB", (400, 200), (170, 30, 40))
    img.paste(Image.new("RGB", (200, 200), (30, 170, 40)), (0, 0))
    img.save(twotone)
    w = MainWindow(st=_store(tmp_path))
    w.append_photo(str(twotone))
    w.place(0, 0)                                 # 入版面，_current_cell 置 0
    w._refresh()
    before = w.job.render(0, 25.4).tobytes()
    _rotate_btn(w).click()                        # 逐格旋转当前格（0）
    w._refresh()
    assert w.job.render(0, 25.4).tobytes() != before


def test_clear_resets_rotations(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    _rotate_btn(w).click()                        # _current_cell==3（_fill 末次 place）
    assert w.cell_rot                             # 已有一格角度
    w._on_clear_photos()
    assert w.cell_rot == {}


def test_rotations_roundtrip_through_two_windows(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    _rotate_btn(w).click()                        # _current_cell==3（_fill 末次 place）
    w.save_last_job(out_dir=str(tmp_path))
    again = MainWindow(st=_store(tmp_path))
    assert again.cell_rot == {3: 90}              # 角度按格落库并回读
    assert again.placements == {0: 0, 1: 1, 2: 2, 3: 3}


@pytest.mark.parametrize("bad", ["[90]", "90", [90, "x"], [90, None]])
def test_bad_rotations_config_degrades_to_all_zero(qapp, tmp_path, bad):
    """形状坏 / 含不可转 int 的条目：整体不恢复（全 0），其余字段照常——
    逐项降级会让角度错位到别的照片上，比全不恢复更糟（规格第 5 节）。
    "90" 与 "[90]" 同档：删掉 isinstance 形状闸后逐字符转会错位出 [9, 0]，
    纯坏串只有数字形才能杀闸（T4 评审 M-建议）。"""
    s = _store(tmp_path)
    s.set_last_job({"sheet_key": "A4", "cell_key": "ID1",
                    "photo_paths": _make_photos(tmp_path, 2),
                    "rotations": bad})
    s.save()
    w = MainWindow(st=_store(tmp_path))                   # 不应抛
    assert w.cell_rot == {}


def test_rotations_length_mismatch_truncates_or_pads(qapp, tmp_path):
    s = _store(tmp_path)
    s.set_last_job({"sheet_key": "A4", "cell_key": "ID1",
                    "photo_paths": _make_photos(tmp_path, 2),
                    "rotations": [90, 180, 270, 45]})     # 超长：截到 2
    s.save()
    w = MainWindow(st=_store(tmp_path))
    assert w.cell_rot == {0: 90, 1: 180}                 # 超长：截到库长 2
    # 45 不在 {0,90,180,270}，core 归一按 0 渲染；界面原样保留，不在此层换算


def test_rotations_short_list_pads_to_equal_length(qapp, tmp_path):
    """不足补 0 是承重钉：删补 0 则启动刷新循环 IndexError 直出 __init__
    （窗口化 exe 静默闪退），且落盘 rotations 短于 photo_paths（T4 评审 I-1）。"""
    s = _store(tmp_path)
    s.set_last_job({"sheet_key": "A4", "cell_key": "ID1",
                    "photo_paths": _make_photos(tmp_path, 3),
                    "rotations": [90]})                # 不足：补 0 到等长
    s.save()
    w = MainWindow(st=_store(tmp_path))                 # 删补 0 则此处 IndexError
    assert w.cell_rot == {0: 90}                        # 不足：补 0，仅非 0 角度入库


def test_rotations_out_of_range_still_renderable(qapp, tmp_path):
    """-90 存得下、渲染等价于 270：归一只在 core 做，界面不换算。"""
    s = _store(tmp_path)
    s.set_last_job({"sheet_key": "A4", "cell_key": "ID1",
                    "photo_paths": _make_photos(tmp_path, 1),
                    "rotations": [-90]})
    s.save()
    w = MainWindow(st=_store(tmp_path))
    assert w.cell_rot == {0: -90}                       # 原样存、core 归一
    w._refresh()
    assert w.job is not None                              # 渲染路径不被坏角度打死


def test_photo_list_stretches_vertically(qapp, tmp_path):
    """照片库网格不钉死宽度、纵向可伸展：窗口拉高时列表随之变长（旧代码
    高度上限 150 卡死才是 bug 根因）；宽度改为填满左侧字段列、与设置项对齐，
    但仍限于左栏、不吃掉右侧预览区。"""
    w = MainWindow(st=_store(tmp_path))
    w.resize(1400, 1000)
    qapp.processEvents(QEventLoop.AllEvents, 50)
    assert w.photo_list.width() < w.width() // 2   # 仍在左栏，未吞掉预览区
    assert w.photo_list.maximumHeight() >= w.photo_list.minimumHeight()
    # 无高度封顶时才能吃到面板拉伸出的空间（旧代码上限 150 卡死）
    assert w.photo_list.height() > 150


def test_preview_rescales_on_window_resize(qapp, tmp_path):
    """预览缩放必须在 resize 后重新适配：放大窗口后 pixmap 应填满新的
    预览区高度（KeepAspectRatio 下以高为限），而不是停在旧尺寸被裁/留白。
    牙在 resizeEvent 重缩放这一步——删掉它 pixmap 保持旧尺寸，断言转红。"""
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    _settle(w, qapp)
    w.showFullScreen()
    qapp.processEvents(QEventLoop.AllEvents, 50)
    w.showNormal()
    qapp.processEvents(QEventLoop.AllEvents, 50)
    w.resize(1400, 1000)
    qapp.processEvents(QEventLoop.AllEvents, 50)
    pm = w.preview.pixmap()
    assert not pm.isNull()
    avail = w.preview.size()
    # 等比缩放后 pixmap 的长边（此处竖向：高）应贴合可用区，容差 1px
    assert pm.height() == pytest.approx(avail.height(), abs=1)
    assert pm.height() > 480        # 大于初始最小预览区，钉住“确实变大了”


def test_photo_list_has_thumbnail_icon(qapp, tmp_path):
    """加载成功的条目须带非空缩略图图标，且长边 ≤ GALLERY_THUMB_PX（删 setIcon 则转红）。"""
    from photoprint.app.main_window import GALLERY_THUMB_PX
    w = MainWindow(st=_store(tmp_path))
    paths = _make_photos(tmp_path, n=1)          # 400×200 横图
    w.append_photo(paths[0])
    icon = w.photo_list.item(0).icon()
    assert not icon.isNull()
    sizes = icon.availableSizes()
    assert sizes and max(max(s.width(), s.height()) for s in sizes) <= GALLERY_THUMB_PX


def test_failed_photo_has_no_icon(qapp, tmp_path):
    """读取失败占位项不挂图标，仍红字（钉住失败分支不回归）。"""
    bad = tmp_path / "missing.jpg"
    bad.write_bytes(b"not an image")
    w = MainWindow(st=_store(tmp_path))
    w.append_photo(str(bad))
    item = w.photo_list.item(0)
    assert item.icon().isNull()
    assert "读取失败" in item.text()


def test_thumbnail_does_not_mutate_shared_photo(qapp, tmp_path):
    """I-2 界面侧：挂完缩略图 pool[-1]["img"] 仍是原图尺寸，未被 thumbnail 改小。"""
    w = MainWindow(st=_store(tmp_path))
    paths = _make_photos(tmp_path, n=1)          # 400×200
    w.append_photo(paths[0])
    assert w.pool[-1]["img"].size == (400, 200)


def test_photo_list_is_wrapping_grid(qapp, tmp_path):
    """照片库须是随栏宽换行的 IconMode 网格（图标在上、文字在下）。

    `wrapping` 管的是网格换行成多列；`wordWrap` 管的是标签文字自己折行——后者必须
    关掉：折出来的第三行会越过算死的单元格高度，把文件名裁掉（旧版就这样丢了后缀）。
    """
    from PySide6.QtWidgets import QListView
    from photoprint.app.main_window import GALLERY_THUMB_PX
    w = MainWindow(st=_store(tmp_path))
    pl = w.photo_list
    assert pl.viewMode() == QListView.IconMode
    assert pl.isWrapping() is True
    assert pl.movement() == QListView.Static
    assert pl.wordWrap() is False
    assert pl.textElideMode() == Qt.ElideMiddle
    assert pl.iconSize().width() == GALLERY_THUMB_PX
    assert pl.iconSize().height() == GALLERY_THUMB_PX


def test_gallery_item_text_is_two_lines_with_size(qapp, tmp_path):
    """网格项文字两行：第一行文件名，第二行像素尺寸。"""
    w = MainWindow(st=_store(tmp_path))
    w.append_photo(_make_photos(tmp_path, 1)[0])   # 400×200 横图
    text = w.photo_list.item(0).text()
    lines = text.split("\n")
    assert len(lines) == 2
    assert lines[0].endswith(".jpg")
    assert "400" in lines[1] and "200" in lines[1] and "px" in lines[1]


def test_gallery_cell_fits_two_text_lines(qapp, tmp_path):
    """网格项自己占 166px 高（图标 120 + 两行 30 + 内边距），第二行才不会被裁。

    委托在窗口级 QSS 下只按「一行文字」报 sizeHint（139px），依赖它就把「5184×3888px」
    那行以及折行后的文件名裁掉/压到下一行图标上——用户上眼就是一排被遮住的文件名。
    """
    from PySide6.QtGui import QFontMetrics
    from photoprint.app.main_window import GALLERY_THUMB_PX
    w = MainWindow(st=_store(tmp_path))
    w.append_photo(_make_photos(tmp_path, 1)[0])
    item = w.photo_list.item(0)
    line_h = QFontMetrics(w.photo_list.font()).height()
    assert item.sizeHint().height() >= GALLERY_THUMB_PX + 2 * line_h
    assert item.text().count("\n") == 1


@pytest.mark.parametrize("name", [
    "P2120041.jpg",
    "2019-08-16_112233_海边合影照片_原始尺寸_导出用.jpg",
])
def test_long_photo_name_is_elided_one_line(qapp, tmp_path, name):
    """再长的文件名也只占一行：中部省略保留后缀，完整名进悬停提示。

    中部省略而非末尾：`….jpg` 看得见，才知道还是图片、是什么格式。
    """
    from photoprint.app.main_window import GALLERY_NAME_PX
    w = MainWindow(st=_store(tmp_path))
    path = tmp_path / name
    Image.new("RGB", (40, 20), (10, 20, 30)).save(path)
    w.append_photo(str(path))
    item = w.photo_list.item(0)
    shown = item.text().split("\n")[0]
    assert len(item.text().split("\n")) == 2, "文件名不许折行成第三行"
    assert item.toolTip() == name
    if len(name) > 20:
        assert shown != name, "长名字应该被省略"
        assert shown.endswith(".jpg") and shown.startswith("2019")
        assert w.photo_list.fontMetrics().horizontalAdvance(shown) <= GALLERY_NAME_PX


def test_gallery_failed_item_text_marks_failure(qapp, tmp_path):
    """读取失败项：第二行标“读取失败”，仍红字。"""
    from PySide6.QtGui import QColor
    from photoprint.app.main_window import ERROR_COLOR
    w = MainWindow(st=_store(tmp_path))
    w.append_photo(str(tmp_path / "不存在.jpg"))
    item = w.photo_list.item(0)
    assert item.text().split("\n")[-1] == "读取失败"
    assert item.foreground().color() == QColor(ERROR_COLOR)


def test_params_builds_two_text_specs(qapp, tmp_path):
    from photoprint.core.text_overlay import TextSpec
    w = MainWindow(st=_store(tmp_path))
    p = w._params()
    assert isinstance(p["date_overlay"], TextSpec)
    assert isinstance(p["watermark_overlay"], TextSpec)
    assert p["date_overlay"].enabled is False          # 默认关


def test_enabling_watermark_reaches_job(qapp, tmp_path):
    """勾「文字水印」只改蓝框那张：job.enabled 由逐张开关派生。"""
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path, n=1)
    assert w._current_cell == 0            # place 留下的蓝框
    w.wm_enabled.setChecked(True)
    w.wm_text.setText("样片")
    w._rebuild_job()
    assert w.job.watermark_overlay.enabled is True
    assert w.job.watermark_overlay.text == "样片"
    assert w.job.wm_cells[0] is True


def test_append_photo_stores_date_text(qapp, tmp_path):
    import time
    w = MainWindow(st=_store(tmp_path))
    p = _make_photos(tmp_path, 1)[0]
    w.append_photo(p)
    got = w.pool[0]["date"]
    want = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(p)))
    assert got == want                                   # 无 EXIF→mtime 日期


def test_rebuild_materializes_date_texts(qapp, tmp_path):
    """日期文本与逐格开关同时物化：勾上之后 date_cells 才为 True。"""
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path, n=2)                # 覆盖后蓝框＝槽 1
    w.date_enabled.setChecked(True)
    w._rebuild_job()
    assert w.job.date_texts[0] is not None
    assert w.job.date_overlay.enabled is True
    assert w.job.date_cells[:2] == (False, True)   # 只给蓝框那张


def test_overlay_persist_roundtrip(qapp, tmp_path):
    st = _store(tmp_path)
    w = MainWindow(st=st)
    _fill(w, tmp_path, n=1)
    w.date_enabled.setChecked(True)
    w.date_size.setValue(9.0)
    w.date_corner.setCurrentIndex(1)                     # 右上
    w.save_last_job()
    w2 = MainWindow(st=_store(tmp_path))                 # 同 store 路径
    assert w2.pool[0]["date_on"] is True                 # 开关逐张落盘（pool_on）
    assert abs(w2.date_size.value() - 9.0) < 1e-6
    w2._on_cell_clicked(0)                               # 点蓝框 → 面板回灌那张
    assert w2.date_enabled.isChecked() is True
    assert w2.date_corner.currentData() == "tr"


def test_new_photo_seeds_overlay_from_base(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    w.date_corner.setCurrentIndex(3)                     # 无选中→写 base=右下
    w.date_rot.setCurrentIndex(1)                       # 45°
    w.append_photo(_make_photos(tmp_path, 1)[0])
    assert w.pool[0]["date_corner"] == "br"
    assert w.pool[0]["date_rot"] == 45


def test_clicking_cell_loads_that_photo_overlay(qapp, tmp_path):
    """点预览格（蓝框）：面板回灌那张照片的勾选、角标与角度。"""
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path, n=2)
    w.pool[1]["date_corner"] = "bl"
    w.pool[1]["date_on"] = True
    w._on_cell_clicked(1)
    assert w._current_cell == 1
    assert w.date_corner.currentData() == "bl"
    assert w.date_enabled.isChecked() is True
    assert w.overlay_group.isEnabled() is True


def test_editing_selected_photo_writes_only_that_photo(qapp, tmp_path):
    """默认只影响蓝框那张；另一张不动（用户 2026-11-07：去掉全局开关语义）。"""
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path, n=2)
    w._on_cell_clicked(0)
    w.date_corner.setCurrentIndex(3)                    # 右下
    assert w.pool[0]["date_corner"] == "br"
    assert w.pool[1]["date_corner"] != "br"             # 另一张不动
    assert w._ov_base["date_corner"] == "br"            # 新增照片仍继承最近这套


def test_no_blue_frame_disables_overlay_panel(qapp, tmp_path):
    """没蓝框：整组置灰 + 提示，且勾选不写进任何照片（不偷偷全页生效）。"""
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path, n=2)
    w._current_cell = None                              # 模拟翻页丢弃选中
    w._highlight_current_cell()
    assert w.overlay_group.isEnabled() is False
    assert "蓝框" in w.overlay_group.toolTip()
    w.date_enabled.setChecked(True)                     # 程序化勾选：无目标
    assert [e["date_on"] for e in w.pool] == [False, False]
    w._rebuild_job()
    assert w.job.date_overlay.enabled is False          # 派生口径：没人勾就没开
    w._on_cell_clicked(1)                               # 点选一格 → 面板复活
    assert w.overlay_group.isEnabled() is True
    assert w.overlay_group.toolTip() == ""


def test_apply_all_checkbox_covers_current_page(qapp, tmp_path):
    """勾「文字叠加效果应用到所有照片」：本页已放的照片全套这套值与开关。"""
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path, n=2)
    w._on_cell_clicked(0)
    w.date_enabled.setChecked(True)
    w.date_corner.setCurrentIndex(3)                    # 右下
    w.apply_all_cb.setChecked(True)
    assert [e["date_on"] for e in w.pool] == [True, True]
    assert w.pool[1]["date_corner"] == "br"
    w._rebuild_job()
    assert w.job.date_cells[:2] == (True, True)


def test_apply_all_does_not_touch_other_pages(qapp, tmp_path):
    """勾选框只覆盖当前预览页：第 2 页的照片保持原样（用户裁决：范围＝当前页）。"""
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path, n=5)                             # A4+3R 每页 4 格
    assert w.job.page_count == 2
    w._on_cell_clicked(0)
    w.date_enabled.setChecked(True)
    w.apply_all_cb.setChecked(True)
    assert [e["date_on"] for e in w.pool] == [True, True, True, True, False]


def test_rebuild_materializes_overrides(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path, n=2)
    w.date_enabled.setChecked(True)
    w.pool[0]["date_corner"] = "br"
    w._rebuild_job()
    assert w.job.date_overrides[0] == ("br", w.pool[0]["date_rot"])
    assert w.job.date_overrides[1] is not None


def test_overlay_per_photo_persist_roundtrip(qapp, tmp_path):
    st = _store(tmp_path)
    w = MainWindow(st=st)
    _fill(w, tmp_path, n=2)
    w._on_cell_clicked(1)                              # 点第 2 格（库 1）
    w.date_corner.setCurrentIndex(3)                    # photo1→右下
    w.date_rot.setCurrentIndex(2)                       # 90°
    w.save_last_job()
    w2 = MainWindow(st=_store(tmp_path))
    assert w2.pool[1]["date_corner"] == "br"
    assert w2.pool[1]["date_rot"] == 90
    assert w2.pool[0]["date_corner"] != "br"            # photo0 保自己的


def test_overlay_base_persist_roundtrip(qapp, tmp_path):
    st = _store(tmp_path)
    w = MainWindow(st=st)
    w.date_corner.setCurrentIndex(1)                    # 无选中→base=右上
    w.save_last_job()
    w2 = MainWindow(st=_store(tmp_path))
    assert w2._ov_base["date_corner"] == "tr"
    assert w2.date_corner.currentData() == "tr"         # 未选中态即编辑默认
