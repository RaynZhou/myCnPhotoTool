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


def print_pages(api, printer, images, sheet, dpi, *, prompt=True, forms=None):
    """打印多页。prompt=True 时弹驱动设置页让用户选介质（I-1 由 devmode 保证
    几何权威），交 `_emit` 建 DC 送图。返回 {'ok','pages','message'}，异常不外抛；
    驱动页取消回 {'cancelled': True}，弹窗降级成功时回 {'degraded': True}。

    forms 是 forms.measure() 的实测表单清单（可为 None/空＝没探测到）：
    命中则用驱动**自带表单码**建 DEVMODE，并把物理校验目标换为该表单实测尺寸。
    未命中时一律沿用静态码与标称尺寸——与本功能上线前逐字一致。
    """
    from photoprint.win import devmode as dm_mod
    from photoprint.win import forms as forms_mod
    from photoprint.win.api import PromptCancelled

    if not images:
        return {"ok": False, "pages": 0, "message": "没有可打印的页面"}
    form = forms_mod.find(forms, sheet.w_mm, sheet.h_mm) if forms else None
    paper_code = form.code if form is not None else sheet.driver_paper_code
    target_mm = (form.w_mm, form.h_mm) if form is not None else None
    try:
        dm_obj, _size, degraded = dm_mod.build_with_prompt(
            api, printer, sheet.w_mm, sheet.h_mm, paper_code,
            prompt=prompt)
    except PromptCancelled:
        # W-1：用户在驱动页取消 → 放弃打印，不是错误（UI 走“已取消”非红字）
        return {"ok": False, "cancelled": True, "pages": 0, "message": "已取消"}
    except Exception as exc:      # 取设置/弹窗阶段失败也要兜住
        # CLI（prompt=False）文案逐字冻结为旧串；GUI 才用更准的分区前缀
        prefix = "读取打印机设置失败" if prompt else "打印失败"
        return {"ok": False, "pages": 0, "message": f"{prefix}：{exc}"}
    # 仅在命中表单时才多传 target_mm：未命中时调用形状与返回值与旧版完全一致
    if target_mm is None:
        res = _emit(api, printer, dm_obj, images, sheet, dpi)
    else:
        res = _emit(api, printer, dm_obj, images, sheet, dpi,
                    target_mm=target_mm)
    if not res.get("ok") and forms_mod.custom_rejected(
            paper_code, getattr(dm_obj, "PaperSize", None)):
        res["message"] = res.get("message", "") + ("；本机驱动不接受程序化"
                                                    "自定义尺寸，请改用驱动自带表单或导出 PDF")
    if form is not None and res.get("ok"):
        res["paper_form"] = form.as_dict()
    if degraded and res.get("ok"):
        res["degraded"] = True      # W-3：降级仍打成功，标记供 UI 附提示
    return res


def _target_size(sheet, target_mm=None):
    """物理尺寸校验的目标：命中驱动表单时用表单实测值，否则用标称值。

    命中时以表单为准：驱动实际按该表单出纸，拿标称值去卡会在相差 0.4mm 的
    同纸异名（如 4R 102×152 对 10x15cm 的 101.6×152.4）上误报失败。
    """
    return tuple(target_mm) if target_mm else (sheet.w_mm, sheet.h_mm)


def _set_halftone(hdc, set_mode=None):
    """把 StretchBlt 的缩放算法设为 HALFTONE（平滑，照片必须用）。

    PyCDC 没有 SetStretchBltMode（win32ui 不转发这个方法），真机首打就是
    在这里抛 AttributeError。改走 win32gui.SetStretchBltMode（同一 gdi32）。
    不设 HALFTONE 时驱动按最近邻放大，照片会出锯齿与色带。
    """
    import win32con

    if set_mode is None:
        import win32gui

        set_mode = win32gui.SetStretchBltMode
    return set_mode(hdc.GetSafeHdc(), win32con.HALFTONE)


def _dib_draw(dib, handle, rect, draw=None):
    """DIB 缩放贴图。Pillow ≥ 10 把 Dib.Draw 改成小写 draw，两者都认。"""
    if draw is None:
        draw = getattr(dib, "draw", None) or dib.Draw
    return draw(handle, rect)


def _emit(api, printer, dm_obj, images, sheet, dpi, target_mm=None):
    """建 DC → 校验物理尺寸 → 逐页 StretchBlt。这是本模块唯一碰 win32 处。
    StartDoc 后异常经 EndDoc/DeleteDC 展开后统一转 message（打印不得崩）。"""
    from PIL import ImageWin

    import win32ui

    from photoprint.core import units
    from photoprint.win import probe

    try:
        hdc = win32ui.CreateDCFromHandle(_as_dc_ref(_create_dc(printer, dm_obj)))
        try:
            result = probe.probe(api, printer, dc=_as_dc_ref(hdc))
            tw, th = _target_size(sheet, target_mm)
            ok, msg = verify_physical_size(result.physical_w_mm,
                                           result.physical_h_mm,
                                           tw, th)
            if not ok:
                return {"ok": False, "pages": 0, "message": msg}
            # 目标矩形必须按**驱动** dpi 换算：DC 的设备单位是驱动像素（本机
            # 600dpi），用渲染 dpi 换算会只贴上四分之一的面积。dpi 参数只
            # 决定源图分辨率，交给 StretchBlt 放大正是本函数存在的意义。
            dev_dpi_x = getattr(result, "dpi_x", 0) or dpi
            dev_dpi_y = getattr(result, "dpi_y", 0) or dpi
            hdc.StartDoc(f"PhotoPrint {sheet.label}")
            try:
                for img in images:
                    hdc.StartPage()
                    try:
                        dib = ImageWin.Dib(img)
                        w = units.mm_to_px(sheet.w_mm, dev_dpi_x)
                        h = units.mm_to_px(sheet.h_mm, dev_dpi_y)
                        _set_halftone(hdc)
                        _dib_draw(dib, hdc.GetHandleOutput(), (0, 0, w, h))
                    finally:
                        hdc.EndPage()
            finally:
                hdc.EndDoc()
            return {"ok": True, "pages": len(images), "message": ""}
        finally:
            hdc.DeleteDC()
    except Exception as exc:  # 打印阶段不得崩溃：统一转成可读消息
        return {"ok": False, "pages": 0, "message": f"打印失败：{exc}"}


def print_job(api, printer, port, images, sheet, dpi, dm=None, forms=None):
    """CLI 冻结入口：等价 print_pages(prompt=False)。port/dm 为兼容旧签名保留，
    不参与建 DC（现代驱动走默认端口，CreateDC 只收 printer 名与 devmode）。"""
    return print_pages(api, printer, images, sheet, dpi, prompt=False,
                       forms=forms)


def _create_dc(printer, dm_obj):
    """建打印机 DC。port 不参与：win32gui.CreateDC 用驱动默认端口。"""
    import win32gui

    return win32gui.CreateDC("WIN32", printer, dm_obj)


def _as_dc_ref(hdc):
    """统一成 int HDC：PyCDC 走 GetSafeHdc()，int(PyCDC) 会 TypeError。"""
    from photoprint.win.api import as_hdc

    return as_hdc(hdc)
