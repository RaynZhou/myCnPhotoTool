"""win32 调用的薄封装层。

真实实现在方法内部才 import win32，这样 tests 可以完全脱机跑 FakeApi；
本机没有连接 G3800，任何在 import 期就拉 win32 的设计都会让测试假死。

真实契约（本机 pywin32 实测，见 .superpowers/sdd/spike_win32.py）：
- DEVMODE 的 fMode 常量在 win32con（DM_IN_BUFFER/DM_OUT_BUFFER），win32print 里
  既没有 DM_INQUIRE 也没有 DM_GETMODE；
- DocumentProperties(fMode=0, 输入输出皆 None) 只回结构总长（含驱动私有区，本机
  5428 字节）；要改动必须把 GetPrinter 回的结构作输入+输出，fMode 非 0 时传
  None 会报 pywintypes.error 87；
- 建 DC 用 win32gui.CreateDC("WIN32", printer, devmode)（返回 int HDC），
  win32print 没有 CreateDC；取能力用 win32print.GetDeviceCaps(int hdc, field)，
  win32gui 没有 GetDeviceCaps。
"""
from __future__ import annotations


def as_hdc(hdc):
    """int HDC 与 PyCDC 都接受。

    PyCDC 传给 int() 会 TypeError（`CreateDCFromHandle(PyCDC)` 也因此失败），
    必须先走 GetSafeHdc()；反之 int 没有任何属性，直接返回。
    """
    return hdc.GetSafeHdc() if hasattr(hdc, "GetSafeHdc") else int(hdc)


class RealWinApi:
    def enum_printers(self):
        import win32print
        return [p[2] for p in win32print.EnumPrinters(
            win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)]

    def device_caps(self, printer, field):
        # 端口必须是字符串：pywin32 会做 "None is not a valid string" 检查，
        # 传 None 直接 TypeError（本机实测，空串等价于用驱动默认端口）
        import win32print
        return win32print.DeviceCapabilities(printer, "", field, None)

    def open_printer(self, name):
        import win32print
        return win32print.OpenPrinter(name)

    def close_printer(self, handle):
        import win32print
        win32print.ClosePrinter(handle)

    def get_devmode(self, handle):
        """驱动当前 DEVMODE（含私有扩展区）。改结构必须基于它，不能新建空的。"""
        import win32print
        return win32print.GetPrinter(handle, 2)["pDevMode"]

    def document_properties(self, handle, printer, mode="size", dm=None):
        """mode="size" 只问结构总长；mode="update" 让驱动校验/回填修改后的 dm。"""
        import win32con
        import win32print
        if mode == "size":
            return win32print.DocumentProperties(0, handle, printer, None, None, 0)
        flag = win32con.DM_IN_BUFFER | win32con.DM_OUT_BUFFER
        return win32print.DocumentProperties(0, handle, printer, dm, dm, flag)

    def prompt_devmode(self, handle, printer, dm):
        """弹驱动自己的设置页（介质类型、无边距等私有项都在里面），返回用户
        确认后的 DEVMODE。介质活在驱动私有扩展区——由驱动自己读写，我们从不
        解析它（这是不随驱动版本碎裂的根基）。DM_PROMPT 与既有 fMode 常量同源。"""
        import win32con
        import win32print
        flag = (win32con.DM_IN_BUFFER | win32con.DM_OUT_BUFFER
                | win32con.DM_PROMPT)
        win32print.DocumentProperties(0, handle, printer, dm, dm, flag)
        return dm

    def create_dc(self, printer, devmode=None):
        import win32gui
        return win32gui.CreateDC("WIN32", printer, devmode)

    def delete_dc(self, hdc):
        import win32gui
        win32gui.DeleteDC(as_hdc(hdc))

    def get_device_caps(self, hdc, field):
        import win32print
        return win32print.GetDeviceCaps(as_hdc(hdc), field)
