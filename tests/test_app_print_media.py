import pytest

from PySide6.QtCore import QElapsedTimer, QEventLoop
from PySide6.QtWidgets import QApplication

from photoprint import jobs
from photoprint.app.main_window import MainWindow
from photoprint.core import store
from photoprint.win import forms, gdi_print


@pytest.fixture(autouse=True)
def _no_leaked_threads(qapp):
    """与 test_app_main_window 同构：MainWindow.__init__ 会经 _refresh 起一条
    渲染线程，用例不关窗则线程随进程退出被析构→解释器硬崩（0xC0000409）。
    收尾先停 debounce（否则泵送会再触发延迟渲染），泵到现有线程全停，再 close。"""
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


class FakePrinterApi:
    def __init__(self, names=("Canon G3800", "Microsoft Print to PDF"),
                 raise_enum=False, default=None, raise_default=False):
        self._names = names
        self.raise_enum = raise_enum
        self._default = default
        self.raise_default = raise_default

    def enum_printers(self):
        if self.raise_enum:
            raise RuntimeError("no spooler")
        return list(self._names)

    def get_default_printer(self):
        """模拟 win32print.GetDefaultPrinter：None/抛错都代表取不到系统默认。"""
        if self.raise_default:
            raise RuntimeError("no default")
        return self._default


def _store(tmp_path):
    s = store.Store(tmp_path / "papers.json")     # 与既有测试同构：只读纸型表
    s.load()
    return s


def _landscape(tmp_path, name):
    from PIL import Image

    p = tmp_path / name
    Image.new("RGB", (400, 200), (255, 0, 0)).save(p)   # 横图、非正方（规避正方无牙陷阱）
    return str(p)


def _win(tmp_path, api=None, photos=1):
    w = MainWindow(st=_store(tmp_path), printer_api=api or FakePrinterApi())
    for i in range(photos):
        w.append_photo(_landscape(tmp_path, f"p{i}.png"))
        w.place(i, i)                    # 增量②：入库后需显式放置才进版面可打印
    return w


def test_print_combo_filled_from_enum(qapp, tmp_path):
    w = _win(tmp_path)
    names = [w.printer_box.itemText(i) for i in range(w.printer_box.count())]
    assert names == ["Canon G3800", "Microsoft Print to PDF"]


def test_enum_failure_leaves_combo_empty_not_crash(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path), printer_api=FakePrinterApi(raise_enum=True))
    assert w.printer_box.count() == 0
    assert not w.printer_box.isEnabled()


def test_on_print_sends_all_pages_and_ok_status(qapp, tmp_path, monkeypatch):
    seen = {}
    real_render = jobs.render_all

    def spy_render(job, dpi, show_mask=None):
        seen["show_mask"] = show_mask
        seen["render_dpi"] = dpi
        return real_render(job, dpi, show_mask=show_mask)

    def fake_print_pages(api, printer, images, sheet, dpi, *, prompt=True, forms=None):
        seen["n"] = len(images)
        seen["printer"] = printer
        seen["dpi"] = dpi
        seen["prompt"] = prompt
        seen["forms"] = forms
        return {"ok": True, "pages": len(images), "message": ""}

    monkeypatch.setattr(jobs, "render_all", spy_render)
    monkeypatch.setattr(gdi_print, "print_pages", fake_print_pages)
    w = _win(tmp_path, photos=5)      # 5 张 3R 上 A4 会多页
    w.dpi_box.setCurrentIndex(2)      # 改选 600：钉 dpi 跟随所选而非默认
    w._on_print()
    assert seen["prompt"] is True
    assert seen["show_mask"] is False          # I-2：遮罩绝不进相纸
    assert seen["render_dpi"] == 600.0 and seen["dpi"] == 600.0   # dpi 同源透传
    assert seen["printer"] == "Canon G3800"    # 打向选中的那台，不写死
    assert seen["n"] == w.job.page_count       # I-2：全部页
    assert seen["n"] >= 1
    assert seen["forms"] == []                # 探测失败（无 device_caps）⇒ 退旧行为
    assert "已发送" in w.statusBar().currentMessage()


def test_on_print_failure_red_status(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(gdi_print, "print_pages",
                        lambda *a, **k: {"ok": False, "pages": 0, "message": "缺纸"})
    w = _win(tmp_path)
    w._on_print()
    assert w.statusBar().currentMessage() == "未打印：缺纸"
    assert "color:#b00000" in w.statusBar().styleSheet()   # 钉住红色 error 态
    assert QApplication.overrideCursor() is None           # 游标已配平释放


def test_on_print_no_printer_selected_does_not_call(qapp, monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(gdi_print, "print_pages",
                        lambda *a, **k: called.append(1))
    w = _win(tmp_path, api=FakePrinterApi(names=()), photos=1)  # 有图但无打印机
    w._on_print()
    assert not called
    assert "打印机" in w.statusBar().currentMessage()


def test_on_print_exception_contained_no_raise(qapp, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("driver exploded")

    monkeypatch.setattr(gdi_print, "print_pages", boom)
    w = _win(tmp_path)
    w._on_print()                    # 不得抛（窗口化 exe 静默闪退防线）
    assert "driver exploded" in w.statusBar().currentMessage()
    assert QApplication.overrideCursor() is None   # 异常路径也要释放游标


def test_default_printer_selected(qapp, tmp_path):
    """§4：下拉默认选中系统默认打印机（不是枚举首项）。"""
    w = _win(tmp_path, api=FakePrinterApi(default="Microsoft Print to PDF"))
    assert w.printer_box.currentText() == "Microsoft Print to PDF"


def test_default_unavailable_falls_back_to_first(qapp, tmp_path):
    """§4：取不到默认（返回 None）时回退第一项；不崩。"""
    w = _win(tmp_path, api=FakePrinterApi(default=None))
    assert w.printer_box.currentText() == "Canon G3800"


def test_default_raise_falls_back_to_first(qapp, tmp_path):
    """§4：get_default_printer 抛异常也不能崩，回退第一项。"""
    w = _win(tmp_path, api=FakePrinterApi(raise_default=True))
    assert w.printer_box.currentText() == "Canon G3800"


def test_default_not_in_list_falls_back_to_first(qapp, tmp_path):
    """默认打印机不在枚举列表（离线/网络打印机） → 回退第一项。"""
    w = _win(tmp_path, api=FakePrinterApi(default="Ghostwriter 9000"))
    assert w.printer_box.currentText() == "Canon G3800"


def test_on_print_cancelled_shows_idle_status(qapp, tmp_path, monkeypatch):
    """§5：驱动页取消→不发作业、状态栏“已取消”、非红字。"""
    monkeypatch.setattr(gdi_print, "print_pages",
                        lambda *a, **k: {"ok": False, "cancelled": True,
                                         "pages": 0, "message": "已取消"})
    w = _win(tmp_path)
    w._on_print()
    assert w.statusBar().currentMessage() == "已取消"
    assert w.statusBar().styleSheet() == ""        # 非 error 态
    assert QApplication.overrideCursor() is None


def test_on_print_degraded_appends_hint(qapp, tmp_path, monkeypatch):
    """§5：DM_PROMPT 不可用降级直打仍成功，但状态栏附“未能打开驱动设置页”提示。"""
    monkeypatch.setattr(gdi_print, "print_pages",
                        lambda *a, **k: {"ok": True, "pages": 2, "message": "",
                                         "degraded": True})
    w = _win(tmp_path)
    w._on_print()
    msg = w.statusBar().currentMessage()
    assert "已发送 2 页" in msg
    assert "未能打开驱动设置页" in msg
    assert "#b00000" not in w.statusBar().styleSheet()   # 降级仍成功，不红


# ---------- 驱动表单绑定（spec 2026-11-07） ----------

L_89x127 = forms.PaperForm(126, "L 89x127mm", 88.98, 127.0)


def test_on_print_passes_measured_forms(qapp, tmp_path, monkeypatch):
    """打印前实测一次表单，并把结果交给 print_pages。"""
    seen = {}
    monkeypatch.setattr(forms, "measure", lambda api, printer: [L_89x127])

    def fake_print_pages(api, printer, images, sheet, dpi, *, prompt=True, forms=None):
        seen["forms"] = forms
        return {"ok": True, "pages": len(images), "message": ""}

    monkeypatch.setattr(gdi_print, "print_pages", fake_print_pages)
    w = _win(tmp_path)
    w._on_print()
    assert seen["forms"] == [L_89x127]


def test_on_print_status_mentions_driver_form(qapp, tmp_path, monkeypatch):
    """用了驱动表单必须在状态栏明示，不得让用户以为还是自定义尺寸。"""
    monkeypatch.setattr(forms, "measure", lambda api, printer: [L_89x127])
    monkeypatch.setattr(gdi_print, "print_pages", lambda *a, **k: {
        "ok": True, "pages": 1, "message": "", "paper_form": L_89x127.as_dict()})
    w = _win(tmp_path)
    w._on_print()
    msg = w.statusBar().currentMessage()
    assert "已发送 1 页" in msg
    assert "L 89x127mm" in msg
    assert "88.98" in msg
    assert "#b00000" not in w.statusBar().styleSheet()   # 成功不红


def test_on_print_survives_form_probe_failure(qapp, tmp_path, monkeypatch):
    """探测表单抛异常：仍要打（传空表＝旧行为），不得让打印崩。"""
    def boom(api, printer):
        raise RuntimeError("device caps failed")

    seen = {}
    monkeypatch.setattr(forms, "measure", boom)

    def fake_print_pages(api, printer, images, sheet, dpi, *, prompt=True, forms=None):
        seen["forms"] = forms
        return {"ok": True, "pages": len(images), "message": ""}

    monkeypatch.setattr(gdi_print, "print_pages", fake_print_pages)
    w = _win(tmp_path)
    w._on_print()                    # 不得抛
    assert seen["forms"] == []
    assert "已发送" in w.statusBar().currentMessage()
    assert QApplication.overrideCursor() is None
