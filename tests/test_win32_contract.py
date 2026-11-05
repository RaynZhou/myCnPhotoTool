"""真机 win32 契约钉子（终审 C2 的复现脚本）。

只在 pywin32 可用的机器上跑；不依赖任何具体打印机名，因此本机与 CI 都稳定。
旧实现依赖的 win32print.DM_INQUIRE / DM_GETMODE / CreateDC 在真实 pywin32 里
根本不存在——这些断言就是把"跑起来才知道"变成"提交前就知道"。
"""
import pytest

win32print = pytest.importorskip("win32print", reason="需要 pywin32")
win32con = pytest.importorskip("win32con")
win32gui = pytest.importorskip("win32gui")

from photoprint.win import api  # noqa: E402


def test_document_properties_lives_in_win32print():
    assert hasattr(win32print, "DocumentProperties")
    # DEVMODE 的 fMode 不在 win32print 里，旧实现 _mode_flag 取不到就是 KeyError/AttributeError
    assert not hasattr(win32print, "DM_INQUIRE")
    assert not hasattr(win32print, "DM_GETMODE")


def test_create_dc_lives_in_win32gui():
    assert not hasattr(win32print, "CreateDC")
    assert hasattr(win32gui, "CreateDC")
    # 取设备能力用 win32print.GetDeviceCaps(int hdc, field)
    assert hasattr(win32print, "GetDeviceCaps")


def test_devmode_flags_are_win32con_constants():
    for name in ("DM_IN_BUFFER", "DM_OUT_BUFFER", "DM_PAPERSIZE",
                 "DM_PAPERLENGTH", "DM_PAPERWIDTH", "DM_SCALE"):
        assert hasattr(win32con, name), f"win32con 缺少 {name}"
    # DocumentProperties 修改必须同时置输入与输出位（本机实测 = 0x0A）
    assert (win32con.DM_IN_BUFFER | win32con.DM_OUT_BUFFER) == 0x0A


def test_as_hdc_accepts_int_and_pycdc():
    class FakeCDC:
        def GetSafeHdc(self):
            return 4242

    assert api.as_hdc(7) == 7
    assert api.as_hdc(FakeCDC()) == 4242
    with pytest.raises(TypeError):
        int(FakeCDC())  # PyCDC 不能直接 int()：这正是 CreateDCFromHandle 失败的原因


def test_real_api_routes_through_the_verified_calls():
    import inspect

    create_src = inspect.getsource(api.RealWinApi.create_dc)
    assert "win32gui.CreateDC" in create_src
    caps_src = inspect.getsource(api.RealWinApi.get_device_caps)
    assert "win32print.GetDeviceCaps" in caps_src
    props_src = inspect.getsource(api.RealWinApi.document_properties)
    assert "DM_IN_BUFFER" in props_src and "win32con" in props_src


def test_prompt_devmode_uses_document_properties_with_dm_prompt():
    import inspect

    src = inspect.getsource(api.RealWinApi.prompt_devmode)
    # 只认代码里独有的限定写法：裸 "DM_PROMPT" 会被 docstring 同词喂饱（永真断言）
    assert "win32print.DocumentProperties" in src
    assert "win32con.DM_PROMPT" in src
    assert "win32con.DM_IN_BUFFER" in src and "win32con.DM_OUT_BUFFER" in src
    # win32 必须在方法体内 import（顶层 import 会让脱机机器 import 期就炸）
    assert "import win32" in src


def test_prompt_devmode_inspects_return_for_cancel():
    """W-1：DocumentProperties 取消时返回 0（不报错），旧实现丢弃返回值直接
    照打。真机契约：必须接住返回值、为 0 时抛 PromptCancelled（否则取消不生效）。"""
    import inspect

    src = inspect.getsource(api.RealWinApi.prompt_devmode)
    assert "= win32print.DocumentProperties" in src   # 接住返回值，不能丢弃
    # 只认代码独有写法：裸 "PromptCancelled" 会被 docstring 同词喂饱（永真断言）
    assert "raise PromptCancelled" in src              # docstring 写“抛”非“raise”
    assert "if ret == 0" in src                         # 钉住取消码判定这一行


def test_get_default_printer_routes_through_win32print():
    """W-4：默认打印机取 win32print.GetDefaultPrinter（真实 API），方法体内 import。"""
    import inspect

    assert hasattr(win32print, "GetDefaultPrinter")
    src = inspect.getsource(api.RealWinApi.get_default_printer)
    assert "win32print.GetDefaultPrinter" in src
    assert "import win32" in src
