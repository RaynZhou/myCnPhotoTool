"""驱动介质类型（dmMediaType）与打印质量（dmPrintQuality）的编排。

驱动给什么就写什么：名字与数值都来自 DeviceCapabilities 的两张配对表
（DC_MEDIATYPENAMES=34 / DC_MEDIATYPES=35），两者按相同顺序逐位对应。
本机 15 个介质实测全部可精确回读（见 spec 2026-11-07 §0.1/§0.2），因此不
硬编码任何厂商值——换驱动/换机器自动跟随。

本模块只改 DEVMODE 字段与 dmFields 位，**不做 update**：交回驱动校验由
devmode.build_with_prompt 负责，那里还必须遵守"介质先写、质量后写"的两遍
顺序（介质一变，驱动会把质量重算回默认值，spec §0.3 第 1 条）。

常量为避免测试期强绑 win32 而在此自持，与 win32con 同名值一致。
"""
from __future__ import annotations

from dataclasses import dataclass

DC_MEDIATYPENAMES = 34
DC_MEDIATYPES = 35

DM_PRINTQUALITY = 0x00000400
DM_MEDIATYPE = 0x02000000

QUALITY_DEFAULT = None      # 不写字段（继承驱动默认）
QUALITY_HIGH = -4           # DMRES_HIGH：本机唯一可用的更高档（§0.2）

QUALITY_LABELS = {QUALITY_HIGH: "高"}


@dataclass(frozen=True)
class MediaOption:
    """驱动提供的一个介质项：数值用于写 DEVMODE，名字用于 UI 与命令行。"""

    value: int
    name: str


def enumerate_media(api, printer):
    """枚举驱动的介质项。任何异常/空表都退 `[]`——枚举只是增强，不是打印前置。"""
    try:
        values = api.device_caps(printer, DC_MEDIATYPES) or ()
        names = api.device_caps(printer, DC_MEDIATYPENAMES) or ()
    except Exception:
        return []
    # 两表长度不等时按短表截断：错位配对会给出"名字对不上值"的错误选项，
    # 宁可少给几项也不能给错的。
    count = min(len(values), len(names))
    return [MediaOption(int(values[i]), str(names[i])) for i in range(count)]


def find_media(options, query):
    """按数值或名字查找：int 按值；str 先全等再包含（大小写不敏感）。

    查不到返回 None，等价于"不干预介质"。
    """
    if query is None or isinstance(query, bool):
        return None
    if isinstance(query, int):
        for opt in options:
            if opt.value == query:
                return opt
        return None
    text = str(query).strip()
    if not text:
        return None
    for opt in options:                     # 先全等，避免"照片纸"抢走精确输入
        if opt.name.strip() == text:
            return opt
    needle = text.casefold()
    for opt in options:                     # 再包含：CLI 手输短名也能命中
        if needle in opt.name.casefold():
            return opt
    return None


def _value_of(option):
    return option.value if isinstance(option, MediaOption) else int(option)


def apply(dm, media=None, quality=None):
    """就地写介质/质量字段与对应 dmFields 位。

    `media` 收 `MediaOption` 或裸整数；为 None 表示不干预该字段（默认红线）。
    返回是否全部写成功：缺属性（别的驱动/老结构）时返回 False 且不抛，
    调用方照样打印——介质是画质增强，不是打印前置条件。
    """
    ok = True
    if media is not None:
        try:
            dm.MediaType = _value_of(media)
            dm.Fields = getattr(dm, "Fields", 0) | DM_MEDIATYPE
        except (AttributeError, TypeError, ValueError):
            ok = False
    if quality is not None:
        try:
            dm.PrintQuality = int(quality)
            dm.Fields = getattr(dm, "Fields", 0) | DM_PRINTQUALITY
        except (AttributeError, TypeError, ValueError):
            ok = False
    return ok


def note(media=None, quality=None):
    """状态栏/命令行文案：'介质 高级光面照片纸 II · 质量 高'。

    两者都不干预时返回空串——不干预就不该多出任何字。
    """
    parts = []
    if media is not None:
        name = media.name if isinstance(media, MediaOption) else str(media)
        parts.append(f"介质 {name}")
    if quality is not None:
        label = QUALITY_LABELS.get(int(quality), quality)
        parts.append(f"质量 {label}")
    return " · ".join(parts)
