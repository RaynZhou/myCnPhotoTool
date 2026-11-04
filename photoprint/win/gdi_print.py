"""GDI 直打：CreateDC → BeginDoc → 逐页 StretchBlt → EndDoc。

内存纪律：G3800 标称 4800×1200 dpi，按驱动 dpi 直出 A4 会是约 40000×25000
像素，必然爆内存。因此渲染固定在 300/600 dpi，送图时用 StretchBlt 交给驱动放大。

建 DC 的真实契约（本机 pywin32 实测，终审 C2）：win32print 没有 CreateDC，
要 win32gui.CreateDC("WIN32", printer, devmode)，返回 int HDC；端口参数在
现代驱动下无用，print_job 保留签名但不参与建 DC。
"""
from __future__ import annotations

DEFAULT_DPI = 300
DPI_FLOOR = 150


def verify_physical_size(phys_w_mm, phys_h_mm, req_w_mm, req_h_mm, tol_mm=0.5):
    """回读驱动认定的物理纸张尺寸与请求值比对。

    超限说明驱动忽略了程序化设置的自定义尺寸（部分佳能驱动要求先在
    驱动内建立表单），此时必须中止直打并指向 PDF 兜底。
    """
    dw = abs(phys_w_mm - req_w_mm)
    dh = abs(phys_h_mm - req_h_mm)
    if dw <= tol_mm and dh <= tol_mm:
        return True, ""
    return False, (f"驱动忽略了自定义尺寸：请求 {req_w_mm:.2f}×{req_h_mm:.2f}mm，"
                   f"设备实际 {phys_w_mm:.2f}×{phys_h_mm:.2f}mm"
                   f"（偏差 宽{dw:.2f}/高{dh:.2f}mm，容差 {tol_mm}mm）。"
                   f"请在驱动首选项中建立同名自定义纸张表单，或改用 PDF 导出打印。")


def pick_dpi(driver_dpi, cap=600):
    """取驱动与用户上限中较小者，异常回报时回落 300。"""
    if not driver_dpi or driver_dpi <= 0:
        return DEFAULT_DPI
    return max(DPI_FLOOR, min(int(driver_dpi), int(cap)))


def print_job(api, printer, port, images, sheet, dpi, dm=None):
    """打印多页。返回 {'ok': bool, 'pages': int, 'message': str}。"""
    from PIL import ImageWin

    import win32con
    import win32ui

    from photoprint.core import units
    from photoprint.win import devmode as dm_mod
    from photoprint.win import probe

    if not images:
        return {"ok": False, "pages": 0, "message": "没有可打印的页面"}

    hprinter = api.open_printer(printer)
    try:
        # T12 派前拦截②：原写法把 _take_devmode 的整条返回（即 build 的
        # (dm, size) 元组）赋给了 dm_obj，真机 CreateDC 拿到 tuple 必错；
        # build 内部已含"先问长度再取回"两步，这里直接解包它的返回
        dm_obj, _size = dm_mod.build(api, printer, sheet.w_mm, sheet.h_mm,
                                     sheet.driver_paper_code)
        hdc = win32ui.CreateDCFromHandle(_as_dc_ref(_create_dc(printer, dm_obj)))
        try:
            result = probe.probe(api, printer, dc=_as_dc_ref(hdc))
            ok, msg = verify_physical_size(result.physical_w_mm,
                                           result.physical_h_mm,
                                           sheet.w_mm, sheet.h_mm)
            if not ok:
                return {"ok": False, "pages": 0, "message": msg}
            hdc.StartDoc(f"PhotoPrint {sheet.label}")
            try:
                for img in images:
                    hdc.StartPage()
                    try:
                        dib = ImageWin.Dib(img)
                        w = units.mm_to_px(sheet.w_mm, dpi)
                        h = units.mm_to_px(sheet.h_mm, dpi)
                        hdc.SetStretchBltMode(win32con.HALFTONE)
                        dib.Draw(hdc.GetHandleOutput(), (0, 0, w, h))
                    finally:
                        hdc.EndPage()
            finally:
                hdc.EndDoc()
            return {"ok": True, "pages": len(images), "message": ""}
        finally:
            hdc.DeleteDC()
    except Exception as exc:  # 打印阶段不得崩溃：统一转成可读消息
        return {"ok": False, "pages": 0, "message": f"打印失败：{exc}"}
    finally:
        api.close_printer(hprinter)


def _create_dc(printer, dm_obj):
    """建打印机 DC。port 不参与：win32gui.CreateDC 用驱动默认端口。"""
    import win32gui

    return win32gui.CreateDC("WIN32", printer, dm_obj)


def _as_dc_ref(hdc):
    """统一成 int HDC：PyCDC 走 GetSafeHdc()，int(PyCDC) 会 TypeError。"""
    from photoprint.win.api import as_hdc

    return as_hdc(hdc)
