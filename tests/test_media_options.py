"""介质类型枚举/查找 + 打印质量档（纯编排，经 api 注入，全脱机）。

真机证据见 docs/superpowers/specs/2026-11-07-photoprint-print-quality-design.md：
DC_MEDIATYPENAMES(34) 与 DC_MEDIATYPES(35) 是本驱动唯一可靠的名字↔数值来源，
逐位对应的顺序就是驱动回报顺序，不得自行排序或猜测。
"""
import pytest

from photoprint.win import media


class CapsApi:
    """只实现 device_caps 的假 api：按 field 返回预置表或抛异常。"""

    def __init__(self, names=("普通纸", "高级光面照片纸 II"), values=(1, 303),
                 boom=None):
        self.names = names
        self.values = values
        self.boom = boom or ()

    def device_caps(self, printer, field):
        if field in self.boom:
            raise RuntimeError(f"DC {field} 不可用")
        return {media.DC_MEDIATYPENAMES: self.names,
                media.DC_MEDIATYPES: self.values}[field]


class FakeDM:
    """PyDEVMODEW 的真实字段名；MediaType 用不可能撞上的默认值便于断言。"""

    def __init__(self):
        self.Size = 220
        self.Fields = 0
        self.MediaType = 1
        self.PrintQuality = -3


def test_enumerate_pairs_driver_names_with_driver_values():
    opts = media.enumerate_media(CapsApi(), "P")
    assert opts == [media.MediaOption(1, "普通纸"),
                    media.MediaOption(303, "高级光面照片纸 II")]


def test_enumerate_truncates_to_shorter_table():
    """两表长度不等时按短表截断：错位配对会给出“名字对不上值”的错误选项。"""
    api = CapsApi(names=("A", "B", "C"), values=(1, 2))
    assert [o.value for o in media.enumerate_media(api, "P")] == [1, 2]


@pytest.mark.parametrize("boom", [(media.DC_MEDIATYPENAMES,),
                                  (media.DC_MEDIATYPES,),
                                  (media.DC_MEDIATYPENAMES, media.DC_MEDIATYPES)])
def test_enumerate_returns_empty_on_any_error(boom):
    """枚举只是增强：任何失败都退空表，调用方据此只显示“驱动默认”。"""
    assert media.enumerate_media(CapsApi(boom=boom), "P") == []


def test_enumerate_returns_empty_when_driver_gives_nothing():
    assert media.enumerate_media(CapsApi(names=(), values=()), "P") == []


def test_find_media_by_value():
    opts = [media.MediaOption(1, "普通纸"), media.MediaOption(303, "高级光面照片纸 II")]
    assert media.find_media(opts, 303) == media.MediaOption(303, "高级光面照片纸 II")


def test_find_media_by_exact_name():
    opts = [media.MediaOption(1, "普通纸"), media.MediaOption(303, "高级光面照片纸 II")]
    assert media.find_media(opts, "普通纸").value == 1


def test_find_media_falls_back_to_substring():
    """CLI 手输“照片纸”也该命中；多个命中时取驱动顺序里的第一个。"""
    opts = [media.MediaOption(1, "普通纸"), media.MediaOption(303, "高级光面照片纸 II")]
    assert media.find_media(opts, "照片纸").value == 303


@pytest.mark.parametrize("query", [None, "", "  ", "不存在的纸", 999])
def test_find_media_returns_none_when_not_found(query):
    opts = [media.MediaOption(1, "普通纸")]
    assert media.find_media(opts, query) is None


def test_apply_writes_media_and_quality_and_their_bits():
    dm = FakeDM()
    assert media.apply(dm, media.MediaOption(303, "高级光面照片纸 II"),
                       media.QUALITY_HIGH) is True
    assert dm.MediaType == 303
    assert dm.PrintQuality == media.QUALITY_HIGH == -4
    assert dm.Fields & media.DM_MEDIATYPE
    assert dm.Fields & media.DM_PRINTQUALITY


def test_apply_leaves_unrequested_fields_alone():
    """media=None 不动介质、quality=None 不动质量：默认不干预是红线。"""
    dm = FakeDM()
    assert media.apply(dm, None, None) is True
    assert (dm.MediaType, dm.PrintQuality, dm.Fields) == (1, -3, 0)


def test_apply_only_media_does_not_touch_quality():
    dm = FakeDM()
    media.apply(dm, media.MediaOption(303, "高级光面照片纸 II"), None)
    assert (dm.MediaType, dm.PrintQuality) == (303, -3)
    assert not dm.Fields & media.DM_PRINTQUALITY


def test_apply_accepts_plain_int_value():
    """devmode 已经把值解好了（303 这类整数）时也要能直接写。"""
    dm = FakeDM()
    assert media.apply(dm, 303, None) is True
    assert dm.MediaType == 303


def test_apply_returns_false_when_field_missing_and_does_not_raise():
    # __slots__ 是模拟 PyDEVMODEW 的关键：C 对象没有的属性赋值会 AttributeError，
    # 普通 Python 对象却能凭空加属性，那样这条用例就验不出东西。
    class NoQuality:
        __slots__ = ("Fields", "MediaType")

        def __init__(self):
            self.Fields = 0
            self.MediaType = 1

    dm = NoQuality()
    assert media.apply(dm, 303, media.QUALITY_HIGH) is False
    assert dm.MediaType == 303, "介质仍应写入，缺质量属性只影响返回值"


def test_note_names_media_and_quality():
    txt = media.note(media.MediaOption(303, "高级光面照片纸 II"), media.QUALITY_HIGH)
    assert "高级光面照片纸 II" in txt and "质量 高" in txt


def test_note_of_defaults_is_empty():
    """都不干预时不得往状态栏塞任何字（文案形状与上一轮一致）。"""
    assert media.note(None, None) == ""
    assert media.note(None, media.QUALITY_DEFAULT) == ""
