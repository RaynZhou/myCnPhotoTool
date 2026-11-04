"""win32 调用的薄封装层。

真实实现在方法内部才 import win32，这样 tests 可以完全脱机跑 FakeApi；
本机没有连接 G3800，任何在 import 期就拉 win32 的设计都会让测试假死。
"""
from __future__ import annotations


class RealWinApi:
    def enum_printers(self):
        import win32print
        return [p[2] for p in win32print.EnumPrinters(
            win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)]

    def device_caps(self, printer, field):
        import win32print
        return win32print.DeviceCapabilities(printer, None, field, None)

    def open_printer(self, name):
        import win32print
        return win32print.OpenPrinter(name)

    def close_printer(self, handle):
        import win32print
        win32print.ClosePrinter(handle)

    def document_properties(self, handle, printer, mode="get"):
        import win32print
        return win32print.DocumentProperties(0, handle, printer, None, None,
                                             _mode_flag(mode))

    def get_device_caps(self, hdc, field):
        import win32con
        import win32ui
        return win32ui.CreateDCFromHandle(int(hdc)).GetDeviceCaps(field)


def _mode_flag(mode):
    import win32print
    # "size" 仅询问总长（含驱动私有扩展区）；"get" 才取回填充好的结构
    return {"size": win32print.DM_INQUIRE, "get": win32print.DM_GETMODE}[mode]
