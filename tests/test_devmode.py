"""DEVMODE 铁律：继承驱动私有扩展区，只改纸张相关字段。"""
import pytest

from photoprint.win import devmode


class FakeDM:
    def __init__(self):
        self.cbSize = 220
        self.dmFields = 0
        self.dmPaperSize = 9
        self.dmPaperLength = 2970
        self.dmPaperWidth = 2100
        self.dmDefaultSource = 1
        self.dmScale = 100
        self.duplex = 300  # 驱动私有区被建模为一个不得改动的字段
        self.mediaType = 700


class FakeApi:
    def __init__(self, size=520):
        self.size = size
        self.mode_log = []
        self.dm = FakeDM()

    def open_printer(self, name):
        return f"hnd:{name}"

    def close_printer(self, handle):
        pass

    def document_properties(self, handle, printer, mode):
        """mode="size" 只问结构大小；mode="get" 取回含私有区的已填结构。"""
        self.mode_log.append(mode)
        return self.size if mode == "size" else self.dm


def test_modify_sets_custom_size_in_tenth_mm():
    dm = FakeDM()
    devmode.modify(dm, 520, 89.0, 127.0)
    assert dm.dmPaperSize == devmode.DMPAPER_USER
    assert dm.dmPaperWidth == 890    # 0.1mm 单位：89mm × 10
    assert dm.dmPaperLength == 1270  # 127mm × 10


def test_modify_uses_preset_code_when_given():
    """preset 尺寸必须走驱动预设码，才可能继承无边距标志。"""
    dm = FakeDM()
    devmode.modify(dm, 520, 102.0, 152.0, paper_code=259 + 1)
    assert dm.dmPaperSize != devmode.DMPAPER_USER
    assert dm.dmPaperWidth == 1020  # 单位是 0.1mm：102mm → 1020


def test_preset_code_path_does_not_need_user_dims():
    dm = FakeDM()
    devmode.modify(dm, 520, 210.0, 297.0, paper_code=9)
    assert dm.dmPaperSize == 9


def test_dmfields_bits_are_set():
    dm = FakeDM()
    devmode.modify(dm, 520, 89.0, 127.0)
    for bit in (devmode.DM_PAPERSIZE, devmode.DM_PAPERLENGTH,
                devmode.DM_PAPERWIDTH, devmode.DM_DEFAULTSOURCE,
                devmode.DM_SCALE):
        assert dm.dmFields & bit, f"缺少位 {bit}"


def test_scale_is_forced_to_100():
    dm = FakeDM()
    dm.dmScale = 85  # 驱动被设成 85% 缩放，必须被纠回 1:1
    devmode.modify(dm, 520, 89.0, 127.0)
    assert dm.dmScale == 100


def test_cbsize_and_private_area_untouched():
    dm = FakeDM()
    before = (dm.cbSize, dm.duplex, dm.mediaType)
    devmode.modify(dm, 520, 89.0, 127.0)
    assert (dm.cbSize, dm.duplex, dm.mediaType) == before, "私有区被改动会丢失无边距设置"


def test_build_asks_size_then_gets_filled_struct():
    api = FakeApi(size=520)
    dm, size = devmode.build(api, "Canon G3800 series", 89.0, 127.0)
    assert size == 520
    assert api.mode_log == ["size", "get"], "必须先按驱动回报的 size 分配再取回，不得新建空结构"


def test_build_rejects_zero_size():
    api = FakeApi(size=0)
    with pytest.raises(RuntimeError, match="DocumentProperties"):
        devmode.build(api, "P", 89.0, 127.0)
