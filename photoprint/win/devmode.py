"""DEVMODE 的读取与最小化改写。

四条不可变语义：
  1. buffer 按驱动回报的 size 分配（含私有扩展区），不得按 sizeof(DEVMODE) 截断
  2. 必须先向驱动取回当前默认设置再改，以继承无边距/介质类型等私有开关
  3. 不得改结构长度字段（PyDEVMODEW 里叫 Size，不是 cbSize）
  4. 只写纸张相关字段、Scale，以及显式请求的介质/质量

字段名是 pywin32 的真实契约（本机 PyDEVMODEW 实测）：Fields / PaperSize /
PaperWidth / PaperLength / DefaultSource / Scale / Size / MediaType /
PrintQuality；写 dmFields / dmPaperSize 只会 AttributeError（终审 C2）。
常量在此自持，避免测试期强绑 win32；真机调用由 api.RealWinApi 提供。
"""
from __future__ import annotations

from photoprint.win import media as media_mod
from photoprint.win.api import PromptCancelled

DMPAPER_USER = 259

# dmFields 位（与 win32con 同名常量逐一相等，tests/test_win32_contract.py 对拍）。
# 旧值（0x200/0x400/0x800/0x1000/0x1）整体错位一位，恰好都是相邻字段的位；
# 本机 G3800 驱动不看 dmFields，所以一直无症状，但别的驱动会看，新字段
# （DM_MEDIATYPE / DM_PRINTQUALITY）也必须在正确的位上。
DM_PAPERSIZE = 0x00000002
DM_PAPERLENGTH = 0x00000004
DM_PAPERWIDTH = 0x00000008
DM_DEFAULTSOURCE = 0x00000200
DM_SCALE = 0x00000010
DM_PRINTQUALITY = 0x00000400
DM_MEDIATYPE = 0x02000000

# 256 = DMBIN_USER（旧值 4 是 DMBIN_MANUAL 手动进纸，画错了纸盒语义）。
# 本驱动只有一个纸盒（7），写真值同样被驱动归一，行为不变。
DMBIN_USER = 256


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


def _submit_try(api, handle, printer, dm, **fields):
    """写一组字段并立刻交回驱动；失败只记账、不外抛。

    介质/质量是画质增强，不是打印前置条件（spec §4）：写不进、驱动拒收
    都要继续往下走，否则一张照片会因为驱动不认某个介质而彻底打不出来。
    """
    if not media_mod.apply(dm, **fields):
        return False
    try:
        api.document_properties(handle, printer, "update", dm)
    except Exception:
        return False
    return True


def build_with_prompt(api, printer, w_mm, h_mm, paper_code=None, prompt=False,
                      media=None, quality=None):
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

    介质/质量分两遍交回（不合并成一次）：介质一变，驱动会把质量重算回
    默认值，同一次 update 里写的质量会丢；实测只有“先介质、后质量”
    两遍写入能同时钉住两者（spec §0.3 第 1 条）。两者都不传时提交次数
    与旧行为逐次一致（向后兼容红线）。写入先于弹窗，让驱动设置页一打开
    就显示我们的选择；弹窗后只重钉几何，不重写介质/质量（用户可在页内改）。
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
        # 几何先交回（与旧行为同一调用），再写介质、再写质量：这个顺序正是
        # 真机探针验证过的形状——镜像 probe 里“先 build 再逐次写”的观察，
        # 不把“几何+介质”合并到第一次 update（那种组合未在硬件上验过）。
        # 只在真要写介质/质量时才预交：不传两者时提交次数与顺序与旧行为
        # 逐次一致（包括取消时一次 update 都不发生）。
        preset = media is not None or quality is not None
        if preset:
            api.document_properties(handle, printer, "update", dm)
        if media is not None:
            _submit_try(api, handle, printer, dm, media=media)
        if quality is not None:
            _submit_try(api, handle, printer, dm, quality=quality)
        if prompt:
            try:
                dm = api.prompt_devmode(handle, printer, dm)
            except PromptCancelled:
                raise                      # W-1：取消不是降级，直接向上传
            except Exception:
                degraded = True            # W-3：驱动无配置页→继承当前介质
            # 几何以请求为准（I-1）；但保留用户选的纸盒（W-2）
            modify(dm, size, w_mm, h_mm, paper_code, default_source=False)
            # 弹窗后必须重交一次，把盖回的几何交给驱动校验
            api.document_properties(handle, printer, "update", dm)
        elif not preset:
            # 不干预介质/质量时仍沿用旧形状：几何只在这里交回一次
            api.document_properties(handle, printer, "update", dm)
    finally:
        api.close_printer(handle)
    return dm, size, degraded


def build(api, printer, w_mm, h_mm, paper_code=None):
    """旧入口：等价 prompt=False。CLI / print_job 行为逐字不变。"""
    dm, size, _degraded = build_with_prompt(api, printer, w_mm, h_mm,
                                           paper_code, prompt=False)
    return dm, size
