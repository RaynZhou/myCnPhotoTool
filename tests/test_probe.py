"""探测逻辑必须能在没有打印机的开发机上测：win32 调用全部经 api 注入。"""
import pytest

pytest.importorskip("PIL", reason="需要 Pillow")

from photoprint.core import specs  # noqa: E402
from photoprint.win import probe  # noqa: E402


class FakeApi:
    """按 key 返回预设值，记录调用顺序。"""

    def __init__(self, caps=None, dc_caps=None, papers=None, sizes=None):
        self.caps = caps or {}
        self.dc_caps = dc_caps or {}
        self.papers = papers or []
        self.sizes = sizes or []
        self.calls = []

    def device_caps(self, printer, field):
        self.calls.append(("device_caps", field))
        if field == probe.DC_PAPERNAMES:
            return self.papers
        if field == probe.DC_PAPERS:
            return list(range(1, len(self.papers) + 1))
        if field == probe.DC_PAPERSIZE:
            return self.sizes
        return self.caps.get(field, 0)

    def create_dc(self, name):
        """真实 api 的建 DC 缝：win32gui.CreateDC 回 int HDC。"""
        self.calls.append(("create_dc", name))
        return f"hdc:{name}"

    def delete_dc(self, handle):
        self.calls.append(("delete_dc", handle))

    def get_device_caps(self, handle, field):
        self.calls.append(("dc", field))
        return self.dc_caps.get(field, 0)


def test_probe_reads_paper_table_in_tenth_mm_and_device_in_px():
    api = FakeApi(
        papers=["A4", "4x6"],
        sizes=[(2100, 2970), (1020, 1520)],  # DeviceCapabilities 单位 0.1mm
        dc_caps={probe.PHYSICALWIDTH: 2480, probe.PHYSICALHEIGHT: 3508,
                 probe.PHYSICALOFFSETX: 34, probe.PHYSICALOFFSETY: 30,
                 probe.HORZRES: 2412, probe.VERTRES: 3448,
                 probe.LOGPIXELSX: 300, probe.LOGPIXELSY: 300})
    r = probe.probe(api, "Canon G3800 series")
    # 纸张表按 0.1mm 换算 ⇒ A4 为 210×297mm
    assert r.paper_sizes_mm[0] == (210.0, 297.0)
    assert r.paper_sizes_mm[1] == (102.0, 152.0)
    assert r.paper_codes == [1, 2]
    # 设备物理尺寸是像素 ⇒ 2480 / 300 × 25.4 = 209.97mm（A4 在 300dpi 下是
    # 2480px 而非整 210mm，驱动本就留了 0.03mm 量化余量）
    assert r.physical_w_mm == pytest.approx(209.97, abs=0.05)
    assert r.dpi_x == 300


def test_probe_unit_conventions_are_isolated():
    """GetDeviceCaps 返回的是设备像素，需除以 LOGPIXELS 乘 25.4 得 mm。"""
    api = FakeApi(dc_caps={probe.PHYSICALWIDTH: 2480, probe.PHYSICALHEIGHT: 3508,
                           probe.PHYSICALOFFSETX: 34, probe.PHYSICALOFFSETY: 30,
                           probe.HORZRES: 2412, probe.VERTRES: 3448,
                           probe.LOGPIXELSX: 300, probe.LOGPIXELSY: 300})
    r = probe.probe(api, "P")
    assert r.physical_w_mm == pytest.approx(209.97, abs=0.05)
    assert r.offset_x_mm == pytest.approx(2.88, abs=0.01)   # 34/300*25.4
    assert r.offset_y_mm == pytest.approx(2.54, abs=0.01)   # 30/300*25.4
    assert r.res_w_px == 2412


def test_borderless_active_only_when_offsets_zero():
    zero = FakeApi(dc_caps={probe.PHYSICALOFFSETX: 0, probe.PHYSICALOFFSETY: 0,
                             probe.PHYSICALWIDTH: 2480, probe.PHYSICALHEIGHT: 3508,
                             probe.HORZRES: 2480, probe.VERTRES: 3508,
                             probe.LOGPIXELSX: 300, probe.LOGPIXELSY: 300})
    assert probe.borderless_active(probe.probe(zero, "P")) is True
    nonzero = FakeApi(dc_caps={probe.PHYSICALOFFSETX: 34, probe.PHYSICALOFFSETY: 30,
                               probe.PHYSICALWIDTH: 2480, probe.PHYSICALHEIGHT: 3508,
                               probe.HORZRES: 2412, probe.VERTRES: 3448,
                               probe.LOGPIXELSX: 300, probe.LOGPIXELSY: 300})
    assert probe.borderless_active(probe.probe(nonzero, "P")) is False


def test_paper_size_table_survives_non_pair_shape():
    """DC_PAPERSIZE 在本机某驱动上只回 int（张数）：探测不得因此崩。"""
    api = FakeApi(papers=["A4"], sizes=90)
    r = probe.probe(api, "P")
    assert r.paper_sizes_mm == []
    assert r.paper_names == ["A4"]


def test_borderless_not_inferred_from_failed_probe():
    """探测失败（物理宽度 0）时不得把"没读到"当成"无边距生效"。"""
    failed = probe.ProbeResult(printer="P", physical_w_mm=0.0,
                               physical_h_mm=0.0, offset_x_mm=0.0,
                               offset_y_mm=0.0)
    assert probe.borderless_active(failed) is False


def test_match_driver_paper_is_case_and_space_insensitive():
    names = ["ISO A4", "Letter", "4 X 6", "5 x 7"]
    code, hit = probe.match_driver_paper(names, "4x6")
    assert hit == "4 X 6"
    assert code == 3
    missing_code, missing = probe.match_driver_paper(names, "8x10")
    assert missing is None and missing_code is None


def test_diff_report_surfaces_driver_vs_spec_conflict():
    r = probe.ProbeResult(printer="P", paper_names=["4x6"], paper_codes=[1],
                          paper_sizes_mm=[(102.0, 152.0)], physical_w_mm=102.0,
                          physical_h_mm=152.0, offset_x_mm=5.0, offset_y_mm=6.0,
                          res_w_px=1200, res_h_px=1800, dpi_x=300, dpi_y=300)
    lines = probe.diff_report(specs.find_spec("4R"), r)
    assert any("3.4" in ln and "5.0" in ln for ln in lines), lines
    assert any("左边距" in ln for ln in lines)


def test_diff_report_empty_when_consistent():
    r = probe.ProbeResult(printer="P", paper_names=["4x6"], paper_codes=[1],
                          paper_sizes_mm=[(102.0, 152.0)], physical_w_mm=102.0,
                          physical_h_mm=152.0, offset_x_mm=3.4, offset_y_mm=3.0,
                          res_w_px=1204, res_h_px=1785, dpi_x=300, dpi_y=300)
    assert probe.diff_report(specs.find_spec("4R"), r) == []


def test_probe_releases_own_dc():
    """自开路径必须删掉自己建的 DC；打印机句柄不是 DC，拿它读能力只会得 0。"""
    api = FakeApi(dc_caps={probe.LOGPIXELSX: 300, probe.LOGPIXELSY: 300})
    r = probe.probe(api, "P")
    assert ("create_dc", "P") in api.calls
    assert ("delete_dc", "hdc:P") in api.calls
    assert r.dpi_x == 300


def test_probe_with_dc_reads_device_values():
    """dc 复用路径与自开句柄路径回读一致（T12 的 0.5mm 校验依赖这条）。"""
    api = FakeApi(dc_caps={probe.PHYSICALWIDTH: 2480, probe.PHYSICALHEIGHT: 3508,
                           probe.PHYSICALOFFSETX: 34, probe.PHYSICALOFFSETY: 30,
                           probe.HORZRES: 2412, probe.VERTRES: 3448,
                           probe.LOGPIXELSX: 300, probe.LOGPIXELSY: 300})
    r = probe.probe(api, "P", dc="hdc:X")
    assert r.physical_w_mm == pytest.approx(209.97, abs=0.05)
    assert r.offset_x_mm == pytest.approx(2.88, abs=0.01)
    # dc 模式不得自建/删除 DC（那是调用方的，直打时它与 hdc 是同一个）
    assert not any(k in ("create_dc", "delete_dc") for k, _ in api.calls)
