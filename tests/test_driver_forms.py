"""驱动表单实测与匹配：全脱机（FakeApi 注入），本文件不 import win32。

实测口径来自真机采证：DC_PAPERSIZE 在该驱动上恒空，尺寸只能靠
"PaperSize=码 → 驱动回填 → CreateDC → PHYSICALWIDTH/HEIGHT" 回读。
"""
import pytest

from photoprint.win import forms, probe


class _DM:
    """最小 DEVMODE 替身：只保留本模块会写的字段。"""

    def __init__(self):
        self.Fields = 0
        self.PaperSize = 9
        self.PaperWidth = 2100
        self.PaperLength = 2970


class FakeApi:
    """按码回读实测尺寸；reject 模拟驱动不认该码，bad_dc 模拟建 DC 失败。"""

    def __init__(self, names, codes, sizes, dpi=600, reject=(), bad_dc=()):
        self.names = list(names)
        self.codes = list(codes)
        self.sizes = dict(sizes)          # code -> (w_mm, h_mm)
        self.dpi = dpi
        self.reject = set(reject)
        self.bad_dc = set(bad_dc)
        self.calls = []

    # --- 纸张清单 ---
    def device_caps(self, printer, field):
        self.calls.append(("device_caps", field))
        if field == probe.DC_PAPERNAMES:
            return tuple(self.names)
        if field == probe.DC_PAPERS:
            return tuple(self.codes)
        return 0

    # --- DEVMODE ---
    def open_printer(self, name):
        self.calls.append(("open_printer", name))
        return "H"

    def close_printer(self, handle):
        self.calls.append(("close_printer", handle))

    def get_devmode(self, handle):
        return _DM()

    def document_properties(self, handle, printer, mode="size", dm=None):
        self.calls.append(("document_properties", mode))
        if mode == "size":
            return 520
        if dm.PaperSize in self.reject:
            dm.PaperSize = 9              # 驱动把不认的码重置成默认表单
        return 1

    # --- 设备上下文 ---
    def create_dc(self, printer, devmode=None):
        code = devmode.PaperSize
        self.calls.append(("create_dc", code))
        if code in self.bad_dc:
            raise RuntimeError("create_dc failed")
        return f"hdc:{code}"

    def delete_dc(self, hdc):
        self.calls.append(("delete_dc", hdc))

    def get_device_caps(self, hdc, field):
        code = int(str(hdc).split(":", 1)[1])
        if code not in self.sizes:
            return 0
        w_mm, h_mm = self.sizes[code]
        if field in (probe.LOGPIXELSX, probe.LOGPIXELSY):
            return self.dpi
        if field == probe.PHYSICALWIDTH:
            return round(w_mm / 25.4 * self.dpi)
        if field == probe.PHYSICALHEIGHT:
            return round(h_mm / 25.4 * self.dpi)
        return 0


def test_measure_reads_physical_size_per_form_code():
    api = FakeApi(names=["L 89x127mm"], codes=[126], sizes={126: (88.98, 127.0)})
    got = forms.measure(api, "P")
    assert len(got) == 1
    form = got[0]
    assert (form.code, form.name) == (126, "L 89x127mm")
    assert form.w_mm == pytest.approx(88.98, abs=0.05)
    assert form.h_mm == pytest.approx(127.0, abs=0.05)
    # 只读纪律：自己建的 DC 必须删掉
    assert ("delete_dc", "hdc:126") in api.calls


def test_measure_skips_code_driver_rejects():
    """驱动不认的码回读会变：不得编造尺寸。"""
    api = FakeApi(names=["L 89x127mm"], codes=[126], sizes={126: (88.98, 127.0)},
                  reject={126})
    assert forms.measure(api, "P") == []
    assert not any(k == "create_dc" for k, _ in api.calls)


def test_measure_one_bad_code_does_not_abort_rest():
    api = FakeApi(names=["L 89x127mm", "2L 127x178mm"], codes=[126, 121],
                  sizes={121: (127.0, 177.97)}, bad_dc={126})
    got = forms.measure(api, "P")
    assert [f.code for f in got] == [121]


def test_measure_honours_codes_subset_and_cleans_names():
    api = FakeApi(names=["A4", "L 89x127mm\x00trailing"], codes=[9, 126],
                  sizes={9: (209.97, 296.97), 126: (88.98, 127.0)})
    got = forms.measure(api, "P", codes=[126])
    assert [f.code for f in got] == [126]
    assert got[0].name == "L 89x127mm"


def test_measure_empty_table_returns_empty():
    api = FakeApi(names=[], codes=[], sizes={})
    assert forms.measure(api, "P") == []


def test_find_matches_swapped_axes():
    card = forms.PaperForm(125, "Card 55x91mm", 54.99, 90.97)
    assert forms.find([card], 91.0, 55.0) is card


def test_find_prefers_smallest_delta():
    l2 = forms.PaperForm(121, "2L 127x178mm", 127.0, 177.97)
    other = forms.PaperForm(123, '13x18cm 5"x7"', 127.0, 177.8)
    assert forms.find([other, l2], 127.0, 178.0) is l2


def test_find_tie_prefers_mm_name():
    """完全并列时按名字确定性仲裁：含 mm 的更精确。

    故意让 mm 命名的那条码更大——“按码升序”会选另一条，故这条用例能真正
    钉住仲裁键而不是被码序偶然蒙对。
    """
    cm_named = forms.PaperForm(7, '13x18cm 5"x7"', 127.0, 178.0)
    mm_named = forms.PaperForm(9, "2L 127x178mm", 127.0, 178.0)
    assert forms.find([cm_named, mm_named], 127.0, 178.0) is mm_named
    # 顺序反过来结论不变（不得依赖传入顺序）
    assert forms.find([mm_named, cm_named], 127.0, 178.0) is mm_named


def test_find_returns_none_outside_tolerance():
    ten_by_fifteen = forms.PaperForm(122, '10x15cm 4"x6"', 101.6, 152.4)
    assert forms.find([ten_by_fifteen], 152.0, 203.0) is None      # 6R 无表单
    b5_jis = forms.PaperForm(13, "B5", 181.99, 256.96)
    # 驱动 B5 是 JIS 182×257（specs 已按实测校准）；拿 ISO 176×250 去匹配
    # 必须落空——容差 0.6 不允许跨纸种
    assert forms.find([b5_jis], 176.0, 250.0) is None


def test_find_with_empty_forms_is_none():
    assert forms.find([], 89.0, 127.0) is None
    assert forms.find(None, 89.0, 127.0) is None


def test_binding_note_mentions_form_name_and_measured_size():
    note = forms.binding_note(forms.PaperForm(126, "L 89x127mm", 88.98, 127.0))
    assert "L 89x127mm" in note
    assert "88.98" in note and "127.0" in note
