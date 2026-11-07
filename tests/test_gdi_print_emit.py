"""真机首打暴露的 DC 缺陷：PyCDC 没有 SetStretchBltMode。

脱机回归：用桩替换 win32ui / ImageWin.Dib / probe，钉住
1) 半色调必须经 win32gui.SetStretchBltMode 打到 DC 句柄上；
2) StartDoc → 逐页 StartPage/Draw/EndPage → EndDoc 的顺序与页数；
3) 物理尺寸不符时**不得**开 StartDoc（一页都不发）。
"""
import sys
import types

import pytest

pytest.importorskip("PIL", reason="需要 Pillow")

from photoprint.core import specs  # noqa: E402
from photoprint.win import gdi_print  # noqa: E402


class FakeHdc:
    """记录作画顺序的 CDC 桩。"""

    def __init__(self, handle=0x1234):
        self.handle = handle
        self.calls = []

    def GetSafeHdc(self):
        return self.handle

    def GetHandleOutput(self):
        return self          # 真机是 int HDC；桩返回自身，Draw 才能记到 calls 上

    def StartDoc(self, name):
        self.calls.append(("StartDoc", name))

    def StartPage(self):
        self.calls.append(("StartPage",))

    def EndPage(self):
        self.calls.append(("EndPage",))

    def EndDoc(self):
        self.calls.append(("EndDoc",))

    def DeleteDC(self):
        self.calls.append(("DeleteDC",))


class FakeDib:
    """Pillow 12 只有小写 draw（老版只有 Draw）——用新版形状当默认。"""

    def __init__(self, img):
        self.img = img

    def draw(self, hdc, rect, src=None):
        hdc.calls.append(("Draw", tuple(rect)))


class OldFakeDib:
    """老 Pillow 的驼峰 API，用来钉兼容分支。"""

    def __init__(self, img):
        self.img = img

    def Draw(self, hdc, rect):
        hdc.calls.append(("Draw", tuple(rect)))


def test_dib_draw_accepts_both_pillow_api_shapes():
    """Pillow ≥ 10 只有 draw、旧版只有 Draw：两条都得能贴图。"""
    hdc = FakeHdc()
    gdi_print._dib_draw(FakeDib(None), hdc, (0, 0, 1, 1))
    gdi_print._dib_draw(OldFakeDib(None), hdc, (0, 0, 2, 2))
    assert hdc.calls == [("Draw", (0, 0, 1, 1)), ("Draw", (0, 0, 2, 2))]


def test_set_halftone_goes_through_win32gui_with_dc_handle():
    """PyCDC 上没有 SetStretchBltMode——必须走 win32gui 并把句柄传对。"""
    hdc = FakeHdc(0x7ABC)
    seen = []
    gdi_print._set_halftone(hdc, set_mode=lambda h, mode: seen.append((h, mode)))
    assert seen == [(0x7ABC, 4)]          # win32con.HALFTONE == 4


@pytest.fixture
def pipeline(monkeypatch):
    """把 _emit 的 win32 依赖换成桩，返回 (hdc, probe 结果可改的 dict)。"""
    hdc = FakeHdc()
    stub = types.ModuleType("win32ui")
    stub.CreateDCFromHandle = lambda handle: hdc
    monkeypatch.setitem(sys.modules, "win32ui", stub)

    from PIL import ImageWin

    monkeypatch.setattr(ImageWin, "Dib", FakeDib)

    state = {"phys": (89.0, 127.0), "dpi": (25.4, 25.4), "halftone": []}
    monkeypatch.setattr(gdi_print, "_create_dc", lambda printer, dm: hdc.handle)
    monkeypatch.setattr(
        gdi_print, "_set_halftone",
        lambda h: state["halftone"].append(h.GetSafeHdc()))

    from photoprint.win import probe

    monkeypatch.setattr(
        probe, "probe",
        lambda api, printer, dc=None: types.SimpleNamespace(
            physical_w_mm=state["phys"][0], physical_h_mm=state["phys"][1],
            dpi_x=state["dpi"][0], dpi_y=state["dpi"][1]))
    return hdc, state


def test_emit_paints_pages_in_order_and_sets_halftone(pipeline):
    from PIL import Image

    hdc, state = pipeline
    imgs = [Image.new("RGB", (8, 8), (1, 2, 3))] * 2
    res = gdi_print._emit(None, "P", None, imgs, specs.find_spec("3R"), 25.4)

    assert res == {"ok": True, "pages": 2, "message": ""}
    assert state["halftone"] == [hdc.handle, hdc.handle]   # 每页都设一次
    names = [c[0] for c in hdc.calls]
    assert names == ["StartDoc", "StartPage", "Draw", "EndPage",
                     "StartPage", "Draw", "EndPage", "EndDoc", "DeleteDC"]
    # 25.4 dpi 下 1px=1mm：画布必须正好是纸的毫米数
    assert hdc.calls[2][1] == (0, 0, 89, 127)


def test_emit_scales_dst_by_driver_dpi_not_render_dpi(pipeline):
    """贴图矩形要按驱动 dpi（本机 600）换算，而不是渲染 dpi（300）。

    DC 的设备单位就是驱动像素；拿 300dpi 的目标矩形去 600dpi 设备上贴，
    实际只占纸面四分之一（89×127 会打成 44.5×63.5 一角）。
    """
    from PIL import Image

    hdc, state = pipeline
    state["dpi"] = (600, 600)
    res = gdi_print._emit(None, "P", None, [Image.new("RGB", (8, 8))],
                          specs.find_spec("3R"), 300)

    assert res["ok"] is True
    assert hdc.calls[2][1] == (0, 0, 2102, 3000)   # 89/127mm @ 600dpi


def test_emit_does_not_start_doc_when_physical_size_mismatch(pipeline):
    from PIL import Image

    hdc, state = pipeline
    state["phys"] = (209.97, 296.97)          # 驱动把纸重置成 A4
    res = gdi_print._emit(None, "P", None, [Image.new("RGB", (8, 8))],
                          specs.find_spec("3R"), 25.4)

    assert res["ok"] is False
    assert "驱动忽略了自定义尺寸" in res["message"]
    assert [c[0] for c in hdc.calls] == ["DeleteDC"]       # 一页都没发
