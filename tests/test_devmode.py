"""DEVMODE 铁律：继承驱动私有扩展区，只改纸张相关字段。

FakeDM 必须用 PyDEVMODEW 的真实字段名（Fields / PaperSize / PaperWidth /
PaperLength / DefaultSource / Scale / Size）：旧 fake 用 dmFields、dmPaperSize
那套名字，于是 `dm.dmFields = ...` 在真机上 AttributeError，测试却全绿——
这正是终审 C2 判定的"契约性错误"。
"""
import pytest

from photoprint.win import devmode


class FakeDM:
    def __init__(self):
        self.Size = 220           # 真机里结构长度叫 Size，不是 cbSize
        self.Fields = 0
        self.PaperSize = 9
        self.PaperLength = 2970
        self.PaperWidth = 2100
        self.DefaultSource = 1
        self.Scale = 100
        self.Duplex = 300         # 驱动私有区被建模为一个不得改动的字段
        self.MediaType = 700


class FakeApi:
    def __init__(self, size=520):
        self.size = size
        self.mode_log = []
        self.dm = FakeDM()

    def open_printer(self, name):
        return f"hnd:{name}"

    def close_printer(self, handle):
        pass

    def get_devmode(self, handle):
        """驱动当前 DEVMODE：真机走 GetPrinter(2)["pDevMode"]。"""
        self.mode_log.append("devmode")
        return self.dm

    def document_properties(self, handle, printer, mode, dm=None):
        """mode="size" 只问长度；mode="update" 交回 dm 让驱动校验/回填。"""
        self.mode_log.append(mode)
        if mode == "size":
            return self.size
        assert dm is self.dm, "update 必须交回驱动取到的那份结构，不能新建"
        return 1


def test_modify_sets_custom_size_in_tenth_mm():
    dm = FakeDM()
    devmode.modify(dm, 520, 89.0, 127.0)
    assert dm.PaperSize == devmode.DMPAPER_USER
    assert dm.PaperWidth == 890    # 0.1mm 单位：89mm × 10
    assert dm.PaperLength == 1270  # 127mm × 10


def test_modify_uses_preset_code_when_given():
    """preset 尺寸必须走驱动预设码，才可能继承无边距标志。"""
    dm = FakeDM()
    devmode.modify(dm, 520, 102.0, 152.0, paper_code=259 + 1)
    assert dm.PaperSize != devmode.DMPAPER_USER
    assert dm.PaperWidth == 1020  # 单位是 0.1mm：102mm → 1020


def test_preset_code_path_does_not_need_user_dims():
    dm = FakeDM()
    devmode.modify(dm, 520, 210.0, 297.0, paper_code=9)
    assert dm.PaperSize == 9


def test_fields_bits_are_set():
    dm = FakeDM()
    devmode.modify(dm, 520, 89.0, 127.0)
    for bit in (devmode.DM_PAPERSIZE, devmode.DM_PAPERLENGTH,
                devmode.DM_PAPERWIDTH, devmode.DM_DEFAULTSOURCE,
                devmode.DM_SCALE):
        assert dm.Fields & bit, f"缺少位 {bit}"


def test_scale_is_forced_to_100():
    dm = FakeDM()
    dm.Scale = 85  # 驱动被设成 85% 缩放，必须被纠回 1:1
    devmode.modify(dm, 520, 89.0, 127.0)
    assert dm.Scale == 100


def test_modify_returns_size_unchanged():
    """modify 的返回值是 size：build 里若把它的返回当 dm 用就会出错。"""
    dm = FakeDM()
    assert devmode.modify(dm, 5428, 89.0, 127.0) == 5428


def test_size_and_private_area_untouched():
    dm = FakeDM()
    before = (dm.Size, dm.Duplex, dm.MediaType)
    devmode.modify(dm, 520, 89.0, 127.0)
    assert (dm.Size, dm.Duplex, dm.MediaType) == before, "私有区被改动会丢失无边距设置"


def test_build_asks_size_then_gets_filled_struct():
    api = FakeApi(size=520)
    dm, size = devmode.build(api, "Canon G3800 series", 89.0, 127.0)
    assert size == 520
    # T11 评审 Important：必须钉住第一元素是已填好的 dm 本体——
    # 曾写 `return modify(...), size` 而 modify 返回 size，元组实为 (520, 520)
    assert dm.PaperWidth == 890 and dm.PaperSize == devmode.DMPAPER_USER
    # 真实契约：先问长度 → 取驱动当前结构 → 改完交回驱动校验
    assert api.mode_log == ["size", "devmode", "update"], \
        "顺序必须是 size → pDevMode → DM_IN_BUFFER|DM_OUT_BUFFER"


def test_build_rejects_zero_size():
    api = FakeApi(size=0)
    with pytest.raises(RuntimeError, match="DocumentProperties"):
        devmode.build(api, "P", 89.0, 127.0)
