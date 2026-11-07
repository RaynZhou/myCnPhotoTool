"""驱动表单实测与绑定：把预设尺寸对到驱动自带纸张表单（真实表单码）。

为什么不用 DeviceCapabilities(DC_PAPERSIZE)：本机 Canon G3800 驱动（"Canon G3000
series Printer"）在该字段上回 270 而缓冲区全 0（pywin32 与 ctypes 直调 winspool.drv
都试过），拿不到任何 (宽,高)。所以尺寸只能逐码实测：

    PaperSize=码 → DocumentProperties(IN|OUT) 让驱动回填
      → 必须回读码仍等于请求码（驱动不认就当没有，绝不编造尺寸）
      → CreateDC(devmode) → GetDeviceCaps(PHYSICALWIDTH/HEIGHT) ÷ LOGPIXELS × 25.4

只读纪律：全程不发任何打印作业；每建一个 DC 必须删掉。

分层纪律：本模块不 import win32，全部 win32 调用经 api 注入，故可全脱机测。
"""
from __future__ import annotations

from dataclasses import dataclass

from photoprint.win import probe

# 逐边匹配容差。真机实测偏差：3R 0.02 / 5R 0.03 / 7R 0.00–0.20 / 4R 0.40 /
# 信封 COM10 0.30mm；最近的不同纸是 6R 对 10x15cm（50.4mm）与 ISO B5 对 JIS B5
# （6mm）。0.6 落在两者之间：够容纳驱动量化与寸/厘米命名的换算误差，又跨不过纸种。
MATCH_TOL_MM = 0.6

DM_PAPERSIZE = 0x00000200

# 与 devmode 同值；在此自持避免 win 层模块互相 import 出环
DMPAPER_USER = 259


@dataclass(frozen=True)
class PaperForm:
    """驱动里一个纸张表单的实测结果。w_mm/h_mm 是驱动回报的物理尺寸。"""

    code: int
    name: str
    w_mm: float
    h_mm: float

    def fits(self, w_mm, h_mm, tol_mm=MATCH_TOL_MM) -> bool:
        """宽高可互换比对（卡片 91×55 与驱动的 55×91 是同一张纸）。"""
        dw, dh = _delta(self.w_mm, self.h_mm, w_mm, h_mm)
        return dw <= tol_mm and dh <= tol_mm

    def as_dict(self) -> dict:
        return {"code": self.code, "name": self.name,
                "w_mm": self.w_mm, "h_mm": self.h_mm}


def _delta(fw, fh, w_mm, h_mm):
    """表单与请求的逐边绝对偏差，取正向/互换两种对应关系里更小的那组。"""
    direct = (abs(fw - w_mm), abs(fh - h_mm))
    swapped = (abs(fw - h_mm), abs(fh - w_mm))
    return direct if sum(direct) <= sum(swapped) else swapped


def _clean(name) -> str:
    """驱动返回的纸张名可能带内嵌 \\0 与尾随空白。"""
    return str(name).split("\x00", 1)[0].strip()


def _measure_one(api, printer, code, name):
    """测一个表单码；驱动不认码/读不到能力值时返回 None。"""
    handle = api.open_printer(printer)
    try:
        dm = api.get_devmode(handle)
        dm.Fields = getattr(dm, "Fields", 0) | DM_PAPERSIZE
        dm.PaperSize = int(code)
        api.document_properties(handle, printer, "update", dm)
        if int(getattr(dm, "PaperSize", -1)) != int(code):
            return None          # 驱动把这个码重置成别的表单 ⇒ 此码不成立
    finally:
        api.close_printer(handle)

    hdc = api.create_dc(printer, dm)
    try:
        dpi_x = api.get_device_caps(hdc, probe.LOGPIXELSX) or 0
        dpi_y = api.get_device_caps(hdc, probe.LOGPIXELSY) or 0
        phys_w = api.get_device_caps(hdc, probe.PHYSICALWIDTH) or 0
        phys_h = api.get_device_caps(hdc, probe.PHYSICALHEIGHT) or 0
    finally:
        api.delete_dc(hdc)

    if not dpi_x or not dpi_y or not phys_w or not phys_h:
        return None
    return PaperForm(code=int(code), name=name,
                     w_mm=phys_w / dpi_x * 25.4, h_mm=phys_h / dpi_y * 25.4)


def measure(api, printer, codes=None) -> list:
    """逐表单码实测尺寸。codes 给定时只测这些码。

    单条失败（建 DC 抛错、驱动不认码、能力值缺失）只是跳过该条，绝不因此
    让整次探测失败——打印路径会把它当成"没有表单信息"退回旧行为。
    """
    try:
        names = list(api.device_caps(printer, probe.DC_PAPERNAMES) or [])
        table = list(api.device_caps(printer, probe.DC_PAPERS) or [])
    except Exception:
        return []
    name_by_code = {}
    for code, name in zip(table, names):
        try:
            name_by_code[int(code)] = _clean(name)
        except (TypeError, ValueError):
            continue

    wanted = list(name_by_code) if codes is None else [
        int(c) for c in codes if int(c) in name_by_code]

    out = []
    for code in wanted:
        try:
            form = _measure_one(api, printer, code, name_by_code[code])
        except Exception:
            continue
        if form is not None:
            out.append(form)
    return out


def find(forms_list, w_mm, h_mm, tol_mm=MATCH_TOL_MM):
    """按尺寸找绑定表单；无命中返回 None（调用方退回静态码/自定义尺寸）。

    仲裁必须确定：先比逐边偏差之和，再优先名字含 "mm" 的（命名更精确，
    如 "2L 127x178mm" 优于 '13x18cm 5"x7"'），最后按码升序。不按名字猜。
    """
    if not forms_list:
        return None
    hits = [f for f in forms_list if f.fits(w_mm, h_mm, tol_mm)]
    if not hits:
        return None

    def key(form):
        dw, dh = _delta(form.w_mm, form.h_mm, w_mm, h_mm)
        # round 消除浮点求和噪声，避免"并列"被 1e-16 打破
        return (round(dw + dh, 6), "mm" not in form.name.lower(), int(form.code))

    return min(hits, key=key)


def binding_note(form: PaperForm) -> str:
    """界面/日志文案：说清用了哪个表单、实测多大。"""
    return (f"已用驱动表单 {form.name}"
            f"（实测 {form.w_mm:.2f}×{form.h_mm:.2f}mm）")


def custom_rejected(paper_code, dm_paper_size) -> bool:
    """自定义尺寸是否被驱动重置。

    请求 DMPAPER_USER/None（= 自定义）但驱动回填的码变了，说明它不接受程序化
    自定义尺寸——此时必须点名原因，而不是笼统地说"驱动忽略了尺寸"。
    """
    requested = DMPAPER_USER if paper_code is None else int(paper_code)
    if requested != DMPAPER_USER:
        return False
    try:
        return int(dm_paper_size) != DMPAPER_USER
    except (TypeError, ValueError):
        return False
