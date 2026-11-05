import pytest

from PySide6.QtCore import QElapsedTimer, QEventLoop

from photoprint.app.main_window import MainWindow
from photoprint.core import store
from photoprint.win import gdi_print


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
    def __init__(self, names=("Canon G3800", "Microsoft Print to PDF"), raise_enum=False):
        self._names = names
        self.raise_enum = raise_enum

    def enum_printers(self):
        if self.raise_enum:
            raise RuntimeError("no spooler")
        return list(self._names)


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

    def fake_print_pages(api, printer, images, sheet, dpi, *, prompt=True):
        seen["n"] = len(images)
        seen["printer"] = printer
        seen["prompt"] = prompt
        return {"ok": True, "pages": len(images), "message": ""}

    monkeypatch.setattr(gdi_print, "print_pages", fake_print_pages)
    w = _win(tmp_path, photos=5)      # 5 张 3R 上 A4 会多页
    w._on_print()
    assert seen["prompt"] is True
    assert seen["n"] == w.job.page_count            # I-2：全部页
    assert seen["n"] >= 1
    assert "已发送" in w.statusBar().currentMessage()


def test_on_print_failure_red_status(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(gdi_print, "print_pages",
                        lambda *a, **k: {"ok": False, "pages": 0, "message": "缺纸"})
    w = _win(tmp_path)
    w._on_print()
    assert "缺纸" in w.statusBar().currentMessage()


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
