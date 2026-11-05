"""DEVMODE 的读取与最小化改写。

四条不可变语义：
  1. buffer 按驱动回报的 size 分配（含私有扩展区），不得按 sizeof(DEVMODE) 截断
  2. 必须先向驱动取回当前默认设置再改，以继承无边距/介质类型等私有开关
  3. 不得改结构长度字段（PyDEVMODEW 里叫 Size，不是 cbSize）
  4. 只写纸张相关字段与 Scale

字段名是 pywin32 的真实契约（本机 PyDEVMODEW 实测）：Fields / PaperSize /
PaperWidth / PaperLength / DefaultSource / Scale / Size；写 dmFields /
dmPaperSize 只会 AttributeError（终审 C2）。
常量在此自持，避免测试期强绑 win32；真机调用由 api.RealWinApi 提供。
"""
from __future__ import annotations

from photoprint.win.api import PromptCancelled

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

    dm.Fields = getattr(dm, "Fields", 0) | DM_PAPERSIZE | DM_PAPERLENGTH | DM_PAPERWIDTH | DM_SCALE
    if paper_code and paper_code != DMPAPER_USER:
        dm.PaperSize = int(paper_code)
    else:
        dm.PaperSize = DMPAPER_USER
    # 0.1mm 单位；preset 路径同样写入，避免驱动沿用旧的表单尺寸
    dm.PaperWidth = units.win_mm(w_mm)
    dm.PaperLength = units.win_mm(h_mm)
    if default_source:
        dm.Fields |= DM_DEFAULTSOURCE
        dm.DefaultSource = DMBIN_USER
    dm.Scale = 100
    return size


def build_with_prompt(api, printer, w_mm, h_mm, paper_code=None, prompt=False):
    """取驱动默认 DEVMODE → 写纸张几何 →（可选）弹驱动页选介质 → 再盖一次
    几何 → 交回驱动校验回填。返回 (dm, size, degraded)。

    I-1：弹窗返回的 dm 可能被用户/驱动改成别的表单尺寸，故 prompt 之后再
    `modify` 一次把几何钉回请求值；`modify` 只动纸张字段、从不碰私有区，
    所以用户选的介质（活在私有扩展区）原样保留。

    W-2：弹窗后的二次 `modify` 只盖回几何（default_source=False）——DefaultSource
    不在 I-1 授权的几何集（PaperSize/Width/Length/Scale）内，用户在驱动页选的
    纸盒必须保留，不得被夺回 DMBIN_USER。

    W-1：用户在驱动页取消（prompt_devmode 抛 PromptCancelled）向上传播，中止
    本次打印，不交回驱动、不建作业。

    W-3：驱动无配置页（prompt_devmode 抛非取消异常）→ 降级为继承当前介质，
    不外抛，回报 degraded=True 供上层状态栏提示。

    三步不可合并（真实契约）：
      1. DocumentProperties(fMode=0, None, None) 问出含私有区的总长；
      2. GetPrinter(2)["pDevMode"] 取回驱动当前设置；
      3. 改完再用 DM_IN_BUFFER|DM_OUT_BUFFER 交回驱动校验/回填。
    """
    handle = api.open_printer(printer)
    degraded = False
    try:
        size = api.document_properties(handle, printer, "size")
        if not size:
            raise RuntimeError("DocumentProperties 返回 0，无法取得 DEVMODE")
        dm = api.get_devmode(handle)
        # 先就地改再返回 dm 本体：写成 `return modify(...), size` 会把
        # modify 的返回值（size）当成 dm，下游拿到的第一元素是 int
        modify(dm, size, w_mm, h_mm, paper_code)
        if prompt:
            try:
                dm = api.prompt_devmode(handle, printer, dm)
            except PromptCancelled:
                raise                      # W-1：取消不是降级，直接向上传
            except Exception:
                degraded = True            # W-3：驱动无配置页→继承当前介质
            # 几何以请求为准（I-1）；但保留用户选的纸盒（W-2）
            modify(dm, size, w_mm, h_mm, paper_code, default_source=False)
        api.document_properties(handle, printer, "update", dm)
    finally:
        api.close_printer(handle)
    return dm, size, degraded


def build(api, printer, w_mm, h_mm, paper_code=None):
    """旧入口：等价 prompt=False。CLI / print_job 行为逐字不变。"""
    dm, size, _degraded = build_with_prompt(api, printer, w_mm, h_mm,
                                           paper_code, prompt=False)
    return dm, size
