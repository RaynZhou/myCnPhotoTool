"""papers.json 只存差异，升级预设不得冲掉用户标定。"""
import json
from pathlib import Path

import pytest

from photoprint.core import specs, store


@pytest.fixture
def tmp_store(tmp_path):
    return store.Store(tmp_path / "papers.json")


def test_resolve_without_override_returns_preset(tmp_store):
    tmp_store.load()
    s = tmp_store.resolve("3R")
    assert s.margins.top == 3.0
    assert s.margin_source == "spec"


def test_override_margins_upgrades_source_and_persists(tmp_store):
    tmp_store.load()
    tmp_store.override_margins("3R", specs.Margins(2.8, 5.2, 3.5, 3.5), "calibrated")
    assert tmp_store.save() is True
    disk = json.loads(Path(tmp_store.path).read_text(encoding="utf-8"))
    assert disk["overrides"]["3R"]["margin_source"] == "calibrated"
    assert disk["overrides"]["3R"]["margins_mm"]["bottom"] == 5.2

    again = store.Store(tmp_store.path)
    again.load()
    s = again.resolve("3R")
    assert s.margin_source == "calibrated"
    assert s.margins.left == 3.5


def test_file_only_stores_difference_not_whole_preset(tmp_store):
    tmp_store.load()
    tmp_store.override_margins("3R", specs.Margins(3.0, 5.0, 3.4, 3.4), "probed")
    tmp_store.save()
    disk = json.loads(Path(tmp_store.path).read_text(encoding="utf-8"))
    assert set(disk["overrides"]["3R"]) == {"margins_mm", "margin_source", "updated_at"}
    assert "w_mm" not in disk["overrides"]["3R"]


def test_user_size_rejects_illegal(tmp_store):
    tmp_store.load()
    bad = specs.SizeSpec("user-12", "12寸", 254.0, 305.0, "paper", "user",
                         False, specs.Margins(), "spec")
    with pytest.raises(ValueError, match="215.9"):
        tmp_store.add_user_size(bad)


def test_user_size_forces_borderless_false(tmp_store):
    tmp_store.load()
    s = specs.SizeSpec("user-4d", "4D 自建", 100.0, 148.0, "paper", "user",
                       True, specs.Margins(), "spec")
    tmp_store.add_user_size(s)
    got = tmp_store.resolve("user-4d")
    assert got.origin == "user"
    assert got.borderless is False  # 自定义尺寸不可能无边距，用户意愿不予采纳
    assert s.borderless is True     # 不得就地改调用方交进来的对象

    # 自建尺寸必须走完 save → load → resolve 的往返。只测内存里那条断言，
    # 磁盘少写一个字段也照样是绿的。
    assert tmp_store.save() is True
    again = store.Store(tmp_store.path)
    again.load()
    back = again.resolve("user-4d")
    assert (back.key, back.label) == ("user-4d", "4D 自建")
    assert (back.w_mm, back.h_mm) == (100.0, 148.0)
    assert back.origin == "user"
    assert back.role == "paper"
    assert back.borderless is False
    assert back.margins.bottom == 5.0

    # 磁盘上谎称无边距 / 当格子用也不采信：这条边界由代码守，不由文件守
    disk = json.loads(Path(tmp_store.path).read_text(encoding="utf-8"))
    disk["user_sizes"][0]["borderless"] = True
    disk["user_sizes"][0]["role"] = "cell"
    Path(tmp_store.path).write_text(json.dumps(disk, ensure_ascii=False),
                                    encoding="utf-8")
    liar = store.Store(tmp_store.path)
    liar.load()
    assert liar.resolve("user-4d").borderless is False
    assert liar.resolve("user-4d").role == "paper"


def test_save_failure_keeps_memory_effect(tmp_path):
    blocked = tmp_path / "dir.json"
    blocked.mkdir()  # 目录占位，写文件必然失败
    st = store.Store(blocked)
    st.load()
    st.override_margins("3R", specs.Margins(1, 2, 3, 4), "calibrated")
    assert st.save() is False
    assert st.resolve("3R").margin_source == "calibrated"


def test_corrupt_file_falls_back_to_empty(tmp_store):
    Path(tmp_store.path).write_text("{ not json", encoding="utf-8")
    tmp_store.load()
    assert tmp_store.resolve("3R").margin_source == "spec"


def test_override_margins_on_user_size_reaches_back(tmp_store):
    """自建尺寸的边距只能落在它自己的记录上。

    resolve() 里 `_users` 短路在前，`overrides[key]` 对自建 key 是死数据：
    标定值看着存下了，实际每次都被磁盘上的旧记录盖掉。
    """
    tmp_store.load()
    tmp_store.add_user_size(specs.SizeSpec(
        "user-4d", "4D 自建", 100.0, 148.0, "paper", "user",
        False, specs.Margins(), "spec"))
    tmp_store.override_margins("user-4d", specs.Margins(1.5, 2.5, 3.5, 4.5),
                               "calibrated")
    assert tmp_store.resolve("user-4d").margins.left == 3.5
    assert "user-4d" not in tmp_store.raw["overrides"]
    assert tmp_store.save() is True
    again = store.Store(tmp_store.path)
    again.load()
    back = again.resolve("user-4d")
    assert back.margin_source == "calibrated"
    assert (back.margins.top, back.margins.bottom, back.margins.right) == (
        1.5, 2.5, 4.5)


@pytest.mark.parametrize("text", [
    "null",
    "[1, 2]",
    '{"user_sizes": ["abc"]}',
    '{"user_sizes": [{"key": "u1"}]}',
    '{"overrides": 3, "user_sizes": {"key": "u1"}}',
])
def test_structured_json_corruption_is_contained(tmp_store, text):
    """语法能过但形状错：不能抛，也不能带出半条记录。

    这些是用户手工编辑 papers.json 或旧版本写坏文件后最常见的形状。load()
    抛异常会让程序卡在启动，比丢掉这份配置更糟。
    """
    Path(tmp_store.path).write_text(text, encoding="utf-8")
    tmp_store.load()  # 不得抛
    assert isinstance(tmp_store.raw["overrides"], dict)
    assert isinstance(tmp_store.raw["user_sizes"], list)
    with pytest.raises(KeyError):
        tmp_store.resolve("u1")
    assert tmp_store.resolve("3R").margin_source == "spec"


def test_good_user_sizes_survive_a_bad_sibling(tmp_store):
    Path(tmp_store.path).write_text(json.dumps({"user_sizes": [
        {"key": "u-ok", "label": "ok", "w_mm": 100.0, "h_mm": 148.0},
        {"key": "u-bad"},
    ]}), encoding="utf-8")
    tmp_store.load()
    assert tmp_store.resolve("u-ok").label == "ok"
    # 坏条目已被剔除，下次存盘就写不回磁盘了
    assert [d["key"] for d in tmp_store.raw["user_sizes"]] == ["u-ok"]


def test_user_size_rejects_bad_key(tmp_store):
    """空 key 或与预设重名：重名会让 `_users` 静默遮蔽预设。"""
    tmp_store.load()
    for bad_key in ("", "A4"):
        s = specs.SizeSpec(bad_key, "x", 100.0, 148.0, "paper", "user",
                           False, specs.Margins(), "spec")
        with pytest.raises(ValueError, match="key"):
            tmp_store.add_user_size(s)


def test_override_with_bad_margin_value_is_dropped(tmp_store):
    """终审 Minor：边距值不可转 float 的整条覆盖必须丢弃。

    docstring 承诺“任何损坏都降级成没有，结对不抛”：值留在内存里会在
    渲染时炸成 ValueError，比丢掉一条标定严重得多。
    """
    Path(tmp_store.path).write_text(json.dumps({"overrides": {
        "3R": {"margins_mm": {"top": "bad"}, "margin_source": "calibrated"},
    }}), encoding="utf-8")
    tmp_store.load()  # 不得抛
    assert "3R" not in tmp_store.raw["overrides"]
    s = tmp_store.resolve("3R")
    assert s.margin_source == "spec"
    assert s.margins.top == 3.0
