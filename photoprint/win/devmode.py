"""DEVMODE 的读取与最小化改写。

四条不可变语义：
  1. buffer 按驱动回报的 size 分配（含私有扩展区），不得按 sizeof(DEVMODE) 截断
  2. 必须先向驱动取回当前默认设置再改，以继承无边距/介质类型等私有开关
  3. 不得改 cbSize
  4. 只写纸张相关字段与 dmScale
常量在此自持，避免测试期强绑 win32；真机调用由 api.RealWinApi 提供。
"""
from __future__ import annotations

DMPAPER_USER = 259

DM_PAPERSIZE = 0x00000200
DM_PAPERLENGTH = 0x00000400
DM_PAPERWIDTH = 0x00000800
DM_DEFAULTSOURCE = 0x00001000
DM_SCALE = 0x00000001

DMBIN_USER = 4


def modify(dm, size, w_mm, h_mm, paper_code=None, default_source=True):
    """就地改 DEVMODE 的纸张字段，返回驱动给的 size（含私有区）。"""
    from photoprint.core import units

    dm.dmFields = getattr(dm, "dmFields", 0) | DM_PAPERSIZE | DM_PAPERLENGTH | DM_PAPERWIDTH | DM_SCALE
    if paper_code and paper_code != DMPAPER_USER:
        dm.dmPaperSize = int(paper_code)
    else:
        dm.dmPaperSize = DMPAPER_USER
    # 0.1mm 单位；preset 路径同样写入，避免驱动沿用旧的表单尺寸
    dm.dmPaperWidth = units.win_mm(w_mm)
    dm.dmPaperLength = units.win_mm(h_mm)
    if default_source:
        dm.dmFields |= DM_DEFAULTSOURCE
        dm.dmDefaultSource = DMBIN_USER
    dm.dmScale = 100
    return size


def build(api, printer, w_mm, h_mm, paper_code=None):
    """取驱动默认 devmode 后改纸张字段。返回 (dm, size)。

    两步调用不可合并：先以 mode="size" 问出含私有区的总长，
    再按该长度分配 buffer 并以 mode="get" 取回已填充的结构。
    RealWinApi 负责把 buffer 与 PyDEVMODE 的绑定包在内部。
    """
    handle = api.open_printer(printer)
    try:
        size = api.document_properties(handle, printer, "size")
        if not size:
            raise RuntimeError("DocumentProperties 返回 0，无法取得 DEVMODE")
        dm = api.document_properties(handle, printer, "get")
    finally:
        api.close_printer(handle)
    # 先就地改再返回 dm 本体：写成 `return modify(...), size` 会把
    # modify 的返回值（size）当成 dm，下游 T12 拿到的第一元素是 int（T11 评审 I-1）
    modify(dm, size, w_mm, h_mm, paper_code)
    return dm, size
